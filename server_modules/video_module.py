# server/video_module.py
"""Server-side video streaming with client keepalive tracking.

Task summary:
- Register video endpoints, monitor their keepalives, and drop them when they go silent.
- Relay chunked frame packets from each sender to every other active subscriber.
- Periodically clean up stale metadata so the broadcaster loop stays lightweight.
"""

import socket
import threading
import time

from constants import PORTS, HOST, BUFFER_SIZE

REGISTER_PREFIX = b"REGISTER|"
RECV_BUFFER_SIZE = min(BUFFER_SIZE, 16384)
CLIENT_TIMEOUT = 12


class VideoServer:
    def __init__(self):
        self.clients = {}  # {address: username}
        self.last_seen = {}
        self.running = False
        self.server_socket = None

    def start(self):
        """Start the video streaming server"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((HOST, PORTS['VIDEO']))
        self.server_socket.settimeout(1.0)
        self.running = True

        print(f"[VIDEO] Server started on {HOST}:{PORTS['VIDEO']}")

        threading.Thread(target=self._receive_and_broadcast, daemon=True).start()
        threading.Thread(target=self._cleanup_loop, daemon=True).start()

    def _receive_and_broadcast(self):
        """Process registration packets and relay frame chunks to active clients."""
        while self.running:
            try:
                data, address = self.server_socket.recvfrom(RECV_BUFFER_SIZE)
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception as exc:
                if self.running:
                    print(f"[VIDEO] Error receiving: {exc}")
                continue

            if not data:
                continue

            if data.startswith(REGISTER_PREFIX):
                username = data[len(REGISTER_PREFIX):].decode('utf-8', errors='ignore')
                previous = self.clients.get(address)
                if previous != username:
                    print(f"[VIDEO] Registered video client: {username} from {address}")
                elif previous == username:
                    # Re-registration from same client - they may have reconnected
                    # Send acknowledgment by echoing registration back
                    try:
                        self.server_socket.sendto(data, address)
                    except Exception:
                        pass
                self.clients[address] = username
                self.last_seen[address] = time.time()
                continue

            if address not in self.clients:
                continue

            self.last_seen[address] = time.time()

            disconnected = []
            for client_address in list(self.clients.keys()):
                if client_address == address:
                    continue
                try:
                    self.server_socket.sendto(data, client_address)
                except Exception as exc:
                    print(f"[VIDEO] Error sending to {client_address}: {exc}")
                    disconnected.append(client_address)

            for dead in disconnected:
                self.clients.pop(dead, None)
                self.last_seen.pop(dead, None)

    def _cleanup_loop(self):
        """Remove clients that stop sending keepalives to keep routing tables clean."""
        while self.running:
            time.sleep(3)
            now = time.time()
            stale = [addr for addr, last in self.last_seen.items() if now - last > CLIENT_TIMEOUT]
            for addr in stale:
                username = self.clients.pop(addr, None)
                self.last_seen.pop(addr, None)
                if username:
                    print(f"[VIDEO] Removed stale video client: {username} {addr}")

    def stop(self):
        """Stop the video server"""
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        print("[VIDEO] Server stopped")