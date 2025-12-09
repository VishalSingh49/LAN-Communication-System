# client/video_module.py
"""Client-side video streaming with resilient UDP chunking.

Task summary:
- Capture camera frames, compress them, and ship them to the server in MTU-friendly datagrams.
- Maintain registration keepalives so the server always routes frames back to active viewers.
- Reassemble incoming video fragments and surface completed frames to the GUI renderer.
"""

import socket
import threading
import time
from collections import defaultdict

import cv2
import numpy as np

from constants import PORTS, VIDEO_CONFIG, BUFFER_SIZE


FRAME_HEADER = "FRAME"
REGISTER_HEADER = "REGISTER"
MAX_DATAGRAM_SIZE = 8192
RECV_BUFFER_SIZE = min(BUFFER_SIZE, 16384)
KEEPALIVE_INTERVAL = 4
FRAME_EXPIRY_SECONDS = 1.0


class VideoClient:
    def __init__(self, server_ip, username, video_callback):
        self.server_ip = server_ip
        self.username = username
        self.video_callback = video_callback

        self.socket = None
        self.running = False
        self.connected = False
        self.streaming = False
        self.camera = None

        self._frame_counter = 0
        self._incoming_frames = defaultdict(dict)
        self._frame_meta = {}
        self._frame_lock = threading.Lock()
        self._keepalive_thread = None

    def connect(self):
        """Connect to video server"""
        try:
            # Clear any stale data from previous sessions
            self._incoming_frames.clear()
            self._frame_meta.clear()
            self._frame_counter = 0

            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, BUFFER_SIZE)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, BUFFER_SIZE)
            self.socket.bind(("", 0))

            self.connected = True
            self.running = True

            # Send initial registration bursts so the server learns our address quickly
            # even if the first frame does not arrive intact.
            self._send_registration(burst=True)

            self._keepalive_thread = threading.Thread(target=self._keepalive_loop, daemon=True)
            self._keepalive_thread.start()

            receive_thread = threading.Thread(target=self._receive_video, daemon=True)
            receive_thread.start()

            print("[VIDEO] Connected to video server")
            return True

        except Exception as exc:
            print(f"[VIDEO] Connection error: {exc}")
            self.connected = False
            self.running = False
            return False

    def start_streaming(self):
        """Start streaming video from camera"""
        if self.streaming:
            return True

        # Start camera initialization in background for faster UI response
        def init_camera():
            try:
                print("[VIDEO] Initializing camera...")
                self.camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)  # Use DirectShow backend on Windows
                
                if not self.camera.isOpened():
                    print("[VIDEO] Failed to open camera")
                    return False

                # Set properties in optimal order for faster startup
                self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, VIDEO_CONFIG['WIDTH'])
                self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, VIDEO_CONFIG['HEIGHT'])
                self.camera.set(cv2.CAP_PROP_FPS, VIDEO_CONFIG['FPS'])
                self.camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimize buffering for lower latency

                # Warm up the camera by reading first frame
                for _ in range(3):
                    self.camera.read()

                self.streaming = True
                stream_thread = threading.Thread(target=self._stream_video, daemon=True)
                stream_thread.start()

                print("[VIDEO] Started video streaming")
                return True

            except Exception as exc:
                print(f"[VIDEO] Error starting stream: {exc}")
                return False

        # Run camera init in background thread
        threading.Thread(target=init_camera, daemon=True).start()
        return True

    def stop_streaming(self):
        """Stop streaming video"""
        self.streaming = False
        if self.camera:
            self.camera.release()
            self.camera = None
        print("[VIDEO] Stopped video streaming")

    def _stream_video(self):
        """Capture, encode, and send video frames in UDP chunks."""
        while self.streaming and self.connected:
            try:
                ret, frame = self.camera.read()
                if not ret:
                    continue

                frame = cv2.resize(frame, (VIDEO_CONFIG['WIDTH'], VIDEO_CONFIG['HEIGHT']))
                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), VIDEO_CONFIG['QUALITY']]
                success, encoded = cv2.imencode('.jpg', frame, encode_param)

                if success:
                    self._send_frame(encoded.tobytes())

                time.sleep(max(1.0 / max(VIDEO_CONFIG['FPS'], 1), 0.001))

            except Exception as exc:
                print(f"[VIDEO] Error streaming: {exc}")
                break

    def _send_frame(self, frame_bytes):
        """Break a JPEG frame into ordered datagrams and transmit each one."""
        frame_id = self._frame_counter
        self._frame_counter = (self._frame_counter + 1) % 1_000_000

        total_chunks = max(1, (len(frame_bytes) + MAX_DATAGRAM_SIZE - 1) // MAX_DATAGRAM_SIZE)

        for chunk_index in range(total_chunks):
            start = chunk_index * MAX_DATAGRAM_SIZE
            end = start + MAX_DATAGRAM_SIZE
            chunk = frame_bytes[start:end]

            header = f"{FRAME_HEADER}|{self.username}|{frame_id}|{chunk_index}|{total_chunks}|".encode('utf-8')
            packet = header + chunk

            try:
                self.socket.sendto(packet, (self.server_ip, PORTS['VIDEO']))
            except Exception as exc:
                print(f"[VIDEO] Error sending frame chunk: {exc}")
                break

    def _keepalive_loop(self):
        """Maintain the registration heartbeat while the client is active."""
        while self.running:
            try:
                self._send_registration()
            except Exception:
                pass
            time.sleep(KEEPALIVE_INTERVAL)

    def _send_registration(self, burst=False):
        """Send an identification packet; optional burst improves initial discovery."""
        message = f"{REGISTER_HEADER}|{self.username}".encode('utf-8')
        attempts = 3 if burst else 1
        for _ in range(attempts):
            self.socket.sendto(message, (self.server_ip, PORTS['VIDEO']))
            if burst:
                time.sleep(0.05)

    def _receive_video(self):
        """Collect incoming datagrams and assemble them into complete frames."""
        self.socket.settimeout(1.0)

        while self.running:
            try:
                data, _ = self.socket.recvfrom(RECV_BUFFER_SIZE)
            except socket.timeout:
                self._cleanup_stale_frames()
                continue
            except OSError:
                break
            except Exception as exc:
                if self.running:
                    print(f"[VIDEO] Error receiving: {exc}")
                continue

            if not data or data.startswith(REGISTER_HEADER.encode('utf-8')):
                continue

            if data.startswith(FRAME_HEADER.encode('utf-8')):
                self._handle_frame_chunk(data)

    def _handle_frame_chunk(self, packet):
        """Store a frame chunk and, when complete, forward the decoded frame upstream."""
        parts = packet.split(b'|', 5)
        if len(parts) != 6:
            return

        _, sender_bytes, frame_id_bytes, chunk_index_bytes, total_chunks_bytes, payload = parts

        try:
            sender = sender_bytes.decode('utf-8')
            frame_id = int(frame_id_bytes)
            chunk_index = int(chunk_index_bytes)
            total_chunks = int(total_chunks_bytes)
        except ValueError:
            return

        if sender == self.username:
            return

        key = (sender, frame_id)
        frame_bytes = None

        with self._frame_lock:
            frame_buffer = self._incoming_frames[key]
            frame_buffer[chunk_index] = payload
            self._frame_meta[key] = {
                'total': total_chunks,
                'created': time.time(),
            }

            if len(frame_buffer) == total_chunks:
                ordered_chunks = [frame_buffer.get(i) for i in range(total_chunks)]
                if any(chunk is None for chunk in ordered_chunks):
                    return

                frame_bytes = b''.join(ordered_chunks)
                del self._incoming_frames[key]
                self._frame_meta.pop(key, None)

        if frame_bytes is None:
            return

        frame = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_COLOR)
        if frame is not None and self.video_callback:
            self.video_callback(sender, frame)

    def _cleanup_stale_frames(self):
        """Drop incomplete frames that have lingered beyond the expiry window."""
        now = time.time()
        with self._frame_lock:
            stale_keys = [
                key for key, meta in self._frame_meta.items()
                if now - meta['created'] > FRAME_EXPIRY_SECONDS
            ]
            for key in stale_keys:
                self._incoming_frames.pop(key, None)
                self._frame_meta.pop(key, None)

    def disconnect(self):
        """Disconnect from video server"""
        self.running = False
        self.connected = False
        self.stop_streaming()

        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass

        print("[VIDEO] Disconnected from video server")