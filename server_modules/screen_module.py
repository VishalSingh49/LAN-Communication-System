"""
Server screen share module - enforces a single presenter at a time with notifications.

Task summary:
- Accept viewer and presenter connections while enforcing exclusive presenter ownership.
- Relay captured screen frames to all viewers and broadcast presenter change events.
- Clean up orphaned sockets quickly to free the slot for the next presenter.
"""

import socket
import threading
import pickle
import struct
from constants import HOST, PORTS, BUFFER_SIZE

class ScreenServer:
    def __init__(self, host=HOST):
        self.host = host
        self.port = PORTS['SCREEN_SHARE']
        self.server_socket = None
        self.clients = {}  # {username: socket}
        self.client_threads = {}
        self.running = False
        
        # Screen sharing control (ONLY ONE PRESENTER)
        self.current_presenter = None  # Username of current presenter
        self.presenter_lock = threading.Lock()
        
    def start(self):
        """Start the screen share server"""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(10)
            self.running = True
            
            print(f"[ScreenServer] Started on {self.host}:{self.port}")
            
            # Accept clients
            accept_thread = threading.Thread(target=self._accept_clients, daemon=True)
            accept_thread.start()
            
            return True
            
        except Exception as e:
            print(f"[ScreenServer] Failed to start: {e}")
            return False
            
    def _accept_clients(self):
        """Accept incoming client connections"""
        while self.running:
            try:
                client_socket, address = self.server_socket.accept()
                
                # Receive username
                username = client_socket.recv(1024).decode('utf-8')
                
                self.clients[username] = client_socket
                print(f"[ScreenServer] {username} connected from {address}")
                
                # Send current presenter info if someone is presenting
                with self.presenter_lock:
                    if self.current_presenter:
                        self._send_to_client(username, {
                            'type': 'presenter_started',
                            'username': self.current_presenter
                        })
                
                # Start handler thread for this client
                handler = threading.Thread(
                    target=self._handle_client,
                    args=(username, client_socket),
                    daemon=True
                )
                self.client_threads[username] = handler
                handler.start()
                
            except Exception as e:
                if self.running:
                    print(f"[ScreenServer] Accept error: {e}")
                break
                
    def _handle_client(self, username, client_socket):
        """Handle screen share from a client"""
        data = b""
        payload_size = struct.calcsize("L")
        
        while self.running:
            try:
                # Receive message size
                while len(data) < payload_size:
                    packet = client_socket.recv(BUFFER_SIZE)
                    if not packet:
                        break
                    data += packet
                    
                if len(data) < payload_size:
                    break
                    
                packed_msg_size = data[:payload_size]
                data = data[payload_size:]
                msg_size = struct.unpack("L", packed_msg_size)[0]
                
                # Receive frame data
                while len(data) < msg_size:
                    data += client_socket.recv(BUFFER_SIZE)
                    
                frame_data = data[:msg_size]
                data = data[msg_size:]
                
                # Unpack message
                message = pickle.loads(frame_data)
                
                # Handle different message types
                if message['type'] == 'start_presenting':
                    self._handle_start_presenting(username)
                elif message['type'] == 'stop_presenting':
                    self._handle_stop_presenting(username)
                elif message['type'] == 'screen_frame':
                    # Only broadcast if this user is the current presenter
                    with self.presenter_lock:
                        if self.current_presenter == username:
                            frame_info = {
                                'type': 'screen_frame',
                                'username': username,
                                'frame': message['frame']
                            }
                            self._broadcast_to_all_except(username, frame_info)
                
            except Exception as e:
                print(f"[ScreenServer] Error with {username}: {e}")
                break
                
        # Client disconnected
        self._handle_stop_presenting(username)
        self._remove_client(username)
        
    def _handle_start_presenting(self, username):
        """Handle request to start presenting"""
        with self.presenter_lock:
            if self.current_presenter is None:
                # No one is presenting, allow this user
                self.current_presenter = username
                print(f"[ScreenServer] {username} started presenting")
                
                # Notify all clients that someone started presenting
                notification = {
                    'type': 'presenter_started',
                    'username': username
                }
                self._broadcast_to_all(notification)
                
                # Send success to requester
                self._send_to_client(username, {
                    'type': 'presenting_allowed',
                    'allowed': True
                })
            else:
                # Someone else is presenting
                print(f"[ScreenServer] {username} denied - {self.current_presenter} is already presenting")
                
                # Send denial to requester
                self._send_to_client(username, {
                    'type': 'presenting_allowed',
                    'allowed': False,
                    'current_presenter': self.current_presenter
                })
    
    def _handle_stop_presenting(self, username):
        """Handle request to stop presenting"""
        with self.presenter_lock:
            if self.current_presenter == username:
                self.current_presenter = None
                print(f"[ScreenServer] {username} stopped presenting")
                
                # Notify all clients that presenter stopped
                notification = {
                    'type': 'presenter_stopped',
                    'username': username
                }
                self._broadcast_to_all(notification)
                
    def _broadcast_to_all(self, message):
        """Broadcast message to ALL clients"""
        data = pickle.dumps(message)
        message_size = struct.pack("L", len(data))
        full_message = message_size + data
        
        disconnected = []
        for username, client_socket in list(self.clients.items()):
            try:
                client_socket.sendall(full_message)
            except Exception as e:
                print(f"[ScreenServer] Failed to send to {username}: {e}")
                disconnected.append(username)
        
        for username in disconnected:
            self._remove_client(username)
    
    def _broadcast_to_all_except(self, sender_username, message):
        """Broadcast message to all clients except sender"""
        data = pickle.dumps(message)
        message_size = struct.pack("L", len(data))
        full_message = message_size + data
        
        disconnected = []
        for username, client_socket in list(self.clients.items()):
            if username != sender_username:
                try:
                    client_socket.sendall(full_message)
                except Exception as e:
                    print(f"[ScreenServer] Failed to send to {username}: {e}")
                    disconnected.append(username)
        
        for username in disconnected:
            self._remove_client(username)
    
    def _send_to_client(self, username, message):
        """Send message to specific client"""
        if username in self.clients:
            try:
                data = pickle.dumps(message)
                message_size = struct.pack("L", len(data))
                self.clients[username].sendall(message_size + data)
            except Exception as e:
                print(f"[ScreenServer] Failed to send to {username}: {e}")
                self._remove_client(username)
                
    def _remove_client(self, username):
        """Remove a disconnected client"""
        if username in self.clients:
            try:
                self.clients[username].close()
            except:
                pass
            del self.clients[username]
            print(f"[ScreenServer] {username} disconnected")
            
        if username in self.client_threads:
            del self.client_threads[username]
            
    def stop(self):
        """Stop the screen share server"""
        self.running = False
        
        # Close all client connections
        for username, client_socket in list(self.clients.items()):
            try:
                client_socket.close()
            except:
                pass
                
        self.clients.clear()
        self.client_threads.clear()
        
        # Close server socket
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
                
        print("[ScreenServer] Stopped")