# client/audio_module.py
"""Client-side audio streaming module.

Task summary:
- Capture microphone audio, respect mute state, and push PCM chunks to the server.
- Register the client, maintain heartbeats, and rebuild downstream mixes streamed back from the server.
- Buffer and trim playback data so local output stays synchronized even as more speakers join.
"""

import socket
import threading
import time
from collections import deque

import pyaudio

from constants import PORTS, AUDIO_CONFIG, BUFFER_SIZE


REGISTER_PREFIX = "REGISTER"
RECV_BUFFER_SIZE = min(BUFFER_SIZE, 65535)
KEEPALIVE_INTERVAL = 4


class AudioClient:
    def __init__(self, server_ip, username):
        self.server_ip = server_ip
        self.username = username
        self.socket = None
        self.running = False
        self.connected = False
        self.streaming = False
        self.mic_muted = True
        self.audio = None
        self.stream_in = None
        self.stream_out = None
        self._keepalive_thread = None
        self.playback_queue = deque()
        self.playback_thread = None
        self.playback_running = False
        self.max_queue = 10  # Max chunks to buffer before trimming
        self.chunk_interval = AUDIO_CONFIG['CHUNK_SIZE'] / AUDIO_CONFIG['SAMPLE_RATE']

    def connect(self):
        """Connect to audio server"""
        try:
            # Clear any stale playback data from previous sessions
            self.playback_queue.clear()
            
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, BUFFER_SIZE)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, BUFFER_SIZE)
            self.socket.bind(("", 0))
            self.socket.settimeout(1.0)

            self.audio = pyaudio.PyAudio()

            self.connected = True
            self.running = True

            # Nudge the server a few times so it registers us even if the
            # first packet collides with other LAN traffic.
            self._send_registration(burst=True)

            self._keepalive_thread = threading.Thread(target=self._keepalive_loop, daemon=True)
            self._keepalive_thread.start()

            threading.Thread(target=self._receive_audio, daemon=True).start()

            print("[AUDIO] Connected to audio server")
            return True

        except Exception as exc:
            print(f"[AUDIO] Connection error: {exc}")
            self.connected = False
            self.running = False
            return False

    def start_streaming(self):
        """Start streaming audio from microphone"""
        if self.streaming:
            return True

        try:
            # Open input stream with error handling
            self.stream_in = self.audio.open(
                format=pyaudio.paInt16,
                channels=AUDIO_CONFIG['CHANNELS'],
                rate=AUDIO_CONFIG['SAMPLE_RATE'],
                input=True,
                frames_per_buffer=AUDIO_CONFIG['CHUNK_SIZE'],
                input_device_index=None  # Use default device
            )

            # Open output stream with error handling
            self.stream_out = self.audio.open(
                format=pyaudio.paInt16,
                channels=AUDIO_CONFIG['CHANNELS'],
                rate=AUDIO_CONFIG['SAMPLE_RATE'],
                output=True,
                frames_per_buffer=AUDIO_CONFIG['CHUNK_SIZE'],
                output_device_index=None  # Use default device
            )

            self.streaming = True
            threading.Thread(target=self._stream_audio, daemon=True).start()

            self.playback_running = True
            self.playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
            self.playback_thread.start()

            print("[AUDIO] Started audio streaming")
            return True

        except Exception as exc:
            print(f"[AUDIO] Error starting stream: {exc}")
            return False

    def stop_streaming(self):
        """Stop streaming audio"""
        self.streaming = False

        self.playback_running = False
        self.playback_queue.clear()

        if self.stream_in:
            self.stream_in.stop_stream()
            self.stream_in.close()
            self.stream_in = None

        if self.stream_out:
            self.stream_out.stop_stream()
            self.stream_out.close()
            self.stream_out = None

        print("[AUDIO] Stopped audio streaming")

    def _stream_audio(self):
        """Continuously read microphone frames and push them upstream."""
        while self.streaming and self.connected:
            try:
                audio_data = self.stream_in.read(
                    AUDIO_CONFIG['CHUNK_SIZE'],
                    exception_on_overflow=False
                )

                if not self.mic_muted:
                    self.socket.sendto(audio_data, (self.server_ip, PORTS['AUDIO']))

            except Exception as exc:
                print(f"[AUDIO] Error streaming: {exc}")
                break

    def set_mic_mute(self, muted):
        self.mic_muted = muted
        if muted:
            print("[AUDIO] Microphone muted")
        else:
            print("[AUDIO] Microphone unmuted")

    def _receive_audio(self):
        """Pull mixed audio packets from the server and queue them for playback."""
        while self.running:
            try:
                data, _ = self.socket.recvfrom(RECV_BUFFER_SIZE)
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception as exc:
                if self.running:
                    print(f"[AUDIO] Error receiving: {exc}")
                continue

            if data.startswith(REGISTER_PREFIX.encode('utf-8')):
                continue

            if self.streaming and self.stream_out:
                if len(self.playback_queue) >= self.max_queue:
                    self.playback_queue.popleft()
                self.playback_queue.append(data)

    def _send_registration(self, burst=False):
        """Register this endpoint with the server; optionally repeat to improve reliability."""
        message = f"{REGISTER_PREFIX}|{self.username}".encode('utf-8')
        attempts = 3 if burst else 1
        for _ in range(attempts):
            try:
                self.socket.sendto(message, (self.server_ip, PORTS['AUDIO']))
                if burst:
                    time.sleep(0.05)
            except Exception:
                pass

    def _keepalive_loop(self):
        """Send periodic registrations to keep NAT/firewall tables warm."""
        while self.running:
            self._send_registration()
            time.sleep(KEEPALIVE_INTERVAL)

    def _playback_loop(self):
        """Play queued audio at a stable cadence, trimming backlog when needed."""
        while self.playback_running:
            if self.playback_queue and self.stream_out:
                # Trim excessive backlog to prevent audio delay buildup
                while len(self.playback_queue) > self.max_queue:
                    self.playback_queue.popleft()
                
                chunk = self.playback_queue.popleft()
                try:
                    self.stream_out.write(chunk, exception_on_underflow=False)
                except Exception as e:
                    if self.playback_running:
                        print(f"[AUDIO] Playback error: {e}")
                
                # Precise timing to maintain smooth playback
                time.sleep(self.chunk_interval * 0.95)  # Slight overlap prevents gaps
            else:
                # Wait when queue is empty to avoid busy loop
                time.sleep(self.chunk_interval / 4)

    def disconnect(self):
        """Disconnect from audio server"""
        self.running = False
        self.connected = False
        self.stop_streaming()

        if self.audio:
            self.audio.terminate()
            self.audio = None

        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass

        print("[AUDIO] Disconnected from audio server")