# server/audio_module.py
"""Server-side audio relay with registration keepalives.

Task summary:
- Accept and track audio clients, enforcing heartbeats so stale sockets disappear automatically.
- Collect the most recent PCM chunk from every speaker and mix a custom stream for each listener.
- Broadcast the blended audio downstream while guarding against LAN packet loss.
"""

import socket
import threading
import time

import numpy as np

from constants import PORTS, HOST, BUFFER_SIZE

REGISTER_PREFIX = b"REGISTER|"
RECV_BUFFER_SIZE = min(BUFFER_SIZE, 65535)
CLIENT_TIMEOUT = 12


class AudioServer:
    def __init__(self):
        self.clients = {}  # {address: username}
        self.last_seen = {}
        self.latest_chunks = {}
        self.running = False
        self.server_socket = None

    def start(self):
        """Start the audio streaming server"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((HOST, PORTS['AUDIO']))
        self.server_socket.settimeout(1.0)
        self.running = True

        print(f"[AUDIO] Server started on {HOST}:{PORTS['AUDIO']}")

        threading.Thread(target=self._receive_and_broadcast, daemon=True).start()
        threading.Thread(target=self._cleanup_loop, daemon=True).start()

    def _receive_and_broadcast(self):
        """Accept incoming audio chunks, register clients, and fan out mixed audio."""
        while self.running:
            try:
                data, address = self.server_socket.recvfrom(RECV_BUFFER_SIZE)
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception as exc:
                if self.running:
                    print(f"[AUDIO] Error receiving: {exc}")
                continue

            if not data:
                continue

            if data.startswith(REGISTER_PREFIX):
                username = data[len(REGISTER_PREFIX):].decode('utf-8', errors='ignore')
                previous = self.clients.get(address)
                if previous != username:
                    print(f"[AUDIO] Registered audio client: {username} from {address}")
                self.clients[address] = username
                self.last_seen[address] = time.time()
                self.latest_chunks.setdefault(address, b"")
                continue

            if address not in self.clients:
                continue

            self.last_seen[address] = time.time()
            self.latest_chunks[address] = data

            disconnected = []
            for client_address in list(self.clients.keys()):
                if client_address == address:
                    continue
                try:
                    mix_bytes = self._build_mix_for_target(client_address)
                    if mix_bytes:
                        self.server_socket.sendto(mix_bytes, client_address)
                except Exception as exc:
                    print(f"[AUDIO] Error sending to {client_address}: {exc}")
                    disconnected.append(client_address)

            for dead in disconnected:
                self.clients.pop(dead, None)
                self.last_seen.pop(dead, None)
                self.latest_chunks.pop(dead, None)

    def _cleanup_loop(self):
        """Periodically expire clients that stopped sending keepalives."""
        while self.running:
            time.sleep(3)
            now = time.time()
            stale = [addr for addr, last in self.last_seen.items() if now - last > CLIENT_TIMEOUT]
            for addr in stale:
                username = self.clients.pop(addr, None)
                self.last_seen.pop(addr, None)
                self.latest_chunks.pop(addr, None)
                if username:
                    print(f"[AUDIO] Removed stale audio client: {username} {addr}")

    def _build_mix_for_target(self, target_address):
        """Blend the freshest PCM chunks from everyone except the target client."""
        contributors = [
            chunk for addr, chunk in self.latest_chunks.items()
            if addr != target_address and chunk
        ]

        if not contributors:
            return None

        arrays = []
        min_length = None

        for chunk in contributors:
            if len(chunk) < 2:
                continue
            try:
                pcm = np.frombuffer(chunk, dtype=np.int16)
                if min_length is None or pcm.size < min_length:
                    min_length = pcm.size
                arrays.append(pcm)
            except Exception:
                continue

        if not arrays or min_length is None or min_length == 0:
            return None

        # Trim all arrays to same length
        arrays = [pcm[:min_length] for pcm in arrays]
        
        # Mix with proper normalization to prevent clipping
        mixed = np.sum(arrays, axis=0, dtype=np.float32)
        
        # Normalize by number of contributors with headroom
        mixed = mixed / max(len(arrays), 1)
        
        # Soft limiting to prevent harsh clipping
        mixed = np.tanh(mixed / 32768.0) * 32767.0
        
        # Convert back to int16
        np.clip(mixed, -32768, 32767, out=mixed)
        return mixed.astype(np.int16).tobytes()

    def stop(self):
        """Stop the audio server"""
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        print("[AUDIO] Server stopped")