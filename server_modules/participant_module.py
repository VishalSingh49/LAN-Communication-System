"""
Server participant module - manages the active attendance roster.

Task summary:
- Accept participant connections, track their status, and keep timestamps for the UI.
- Forward presence and video-status changes to every connected client as JSON messages.
- Drop inactive sockets gracefully so the roster stays accurate even after abrupt disconnects.
"""

import socket
import threading
import json
import time
from datetime import datetime
from constants import HOST, PORTS

class ParticipantServer:
    def __init__(self, host=HOST):
        self.host = host
        self.port = PORTS['PARTICIPANTS']
        self.server_socket = None
        self.clients = {}  # {socket: username}
        self.participants = {}  # {username: {'status': 'online', 'joined_at': timestamp, 'video_active': False}}
        self.running = False
        self.lock = threading.Lock()
        
    def start(self):
        """Start the participant server"""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(10)
            self.running = True
            
            print(f"[ParticipantServer] Started on {self.host}:{self.port}")
            
            # Accept clients
            accept_thread = threading.Thread(target=self._accept_clients, daemon=True)
            accept_thread.start()
            
            return True
            
        except Exception as e:
            print(f"[ParticipantServer] Failed to start: {e}")
            return False
            
    def _accept_clients(self):
        """Accept incoming client connections"""
        while self.running:
            try:
                client_socket, address = self.server_socket.accept()
                client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                client_socket.settimeout(30)  # 30 second timeout
                
                # Receive username
                username = client_socket.recv(1024).decode('utf-8')
                
                with self.lock:
                    self.clients[client_socket] = username
                    self.participants[username] = {
                        'status': 'online',
                        'joined_at': datetime.now().strftime('%H:%M:%S'),
                        'video_active': False
                    }
                
                print(f"[ParticipantServer] ✓ {username} joined from {address}")
                
                # Small delay to ensure socket is ready
                time.sleep(0.1)
                
                # Send current participant list to new client IMMEDIATELY
                self._send_participant_list(client_socket)
                
                # Small delay before broadcasting
                time.sleep(0.1)
                
                # Broadcast updated list to all clients (including new one)
                self._broadcast_participant_update()
                
                # Start handler thread for this client
                handler = threading.Thread(
                    target=self._handle_client,
                    args=(username, client_socket),
                    daemon=True
                )
                handler.start()
                
            except Exception as e:
                if self.running:
                    print(f"[ParticipantServer] Accept error: {e}")
                break
                
    def _handle_client(self, username, client_socket):
        """Handle client connection (mainly for keepalive and status updates)"""
        try:
            while self.running:
                try:
                    data = client_socket.recv(4096)
                    if not data:
                        print(f"[ParticipantServer] {username} disconnected (no data)")
                        break
                except socket.timeout:
                    print(f"[ParticipantServer] {username} timed out (no keepalive)")
                    break
                    
                # Handle status updates
                try:
                    message = json.loads(data.decode('utf-8'))
                    
                    if message.get('type') == 'status_update':
                        with self.lock:
                            if username in self.participants:
                                self.participants[username]['status'] = message.get('status', 'online')
                                self._broadcast_participant_update()
                    
                    elif message.get('type') == 'video_status':
                        # Update video active status
                        with self.lock:
                            if username in self.participants:
                                self.participants[username]['video_active'] = message.get('active', False)
                                print(f"[ParticipantServer] {username} video status: {message.get('active', False)}")
                        # Broadcast OUTSIDE the lock to avoid deadlock
                        self._broadcast_participant_update()
                    
                    elif message.get('type') == 'keepalive':
                        # Respond to keepalive
                        try:
                            response = json.dumps({'type': 'keepalive_ack'}).encode('utf-8') + b'\n'
                            client_socket.sendall(response)
                        except:
                            print(f"[ParticipantServer] Failed to send keepalive ack to {username}")
                            break
                                
                except json.JSONDecodeError:
                    pass
                except Exception as e:
                    print(f"[ParticipantServer] Error processing message from {username}: {e}")
                    
        except (ConnectionResetError, ConnectionAbortedError, OSError) as e:
            print(f"[ParticipantServer] {username} connection error: {e}")
        except Exception as e:
            print(f"[ParticipantServer] Unexpected error with {username}: {e}")
        finally:
            # CRITICAL: Always remove and broadcast
            print(f"[ParticipantServer] Cleaning up {username}...")
            self._remove_participant(username, client_socket)
            
    def _send_participant_list(self, client_socket):
        """Send current participant list to a specific client"""
        try:
            with self.lock:
                message = {
                    'type': 'participant_list',
                    'participants': self.participants.copy()
                }
            
            data = json.dumps(message).encode('utf-8')
            client_socket.sendall(data + b'\n')
            print(f"[ParticipantServer] Sent participant list to client: {len(self.participants)} participants")
            
        except Exception as e:
            print(f"[ParticipantServer] Error sending list: {e}")
            
    def _broadcast_participant_update(self):
        """Broadcast updated participant list to all clients"""
        # Get data while holding lock
        with self.lock:
            message = {
                'type': 'participant_list',
                'participants': self.participants.copy()
            }
            participant_names = list(self.participants.keys())
            clients_to_notify = list(self.clients.items())
            
        data = json.dumps(message).encode('utf-8') + b'\n'
        
        print(f"[ParticipantServer] 📢 Broadcasting to {len(clients_to_notify)} clients: {participant_names}")
        
        disconnected = []
        
        # Send to all clients (without holding lock)
        for client_socket, username in clients_to_notify:
            try:
                client_socket.sendall(data)
                print(f"[ParticipantServer]   ✓ Sent to {username}")
            except Exception as e:
                print(f"[ParticipantServer]   ✗ Failed to send to {username}: {e}")
                disconnected.append((client_socket, username))
        
        # Clean up failed sends
        if disconnected:
            print(f"[ParticipantServer] Cleaning {len(disconnected)} dead connections")
            with self.lock:
                for client_socket, username in disconnected:
                    if client_socket in self.clients:
                        del self.clients[client_socket]
                    if username in self.participants:
                        del self.participants[username]
                    try:
                        client_socket.close()
                    except:
                        pass
                
    def _remove_participant(self, username, client_socket):
        """Remove a disconnected participant"""
        removed = False
        
        # Remove from tracking
        with self.lock:
            if client_socket in self.clients:
                del self.clients[client_socket]
                removed = True
                
            if username in self.participants:
                del self.participants[username]
                remaining = list(self.participants.keys())
                print(f"[ParticipantServer] ❌ {username} removed (Remaining: {remaining})")
                removed = True
        
        # Close socket
        try:
            client_socket.close()
        except:
            pass
        
        # CRITICAL: Broadcast if someone was removed
        if removed:
            print(f"[ParticipantServer]  Broadcasting removal of {username}")
            time.sleep(0.1)  # Small delay to ensure cleanup
            self._broadcast_participant_update()
        
    def stop(self):
        """Stop the participant server"""
        self.running = False
        
        # Close all client connections
        for client_socket in list(self.clients.keys()):
            try:
                client_socket.close()
            except:
                pass
                
        self.clients.clear()
        self.participants.clear()
        
        # Close server socket
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
                
        print("[ParticipantServer] Stopped")