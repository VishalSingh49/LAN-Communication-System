# server/chat_module.py
"""
Server-side chat module - handles text messaging independently.

Task summary:
- Accept incoming chat connections and register usernames for broadcast routing.
- Fan out each message to every connected client while cleaning up broken sockets.
- Generate join/leave system notices so the UI can keep the room informed.
"""

import socket
import threading
import json
from datetime import datetime
from constants import PORTS, HOST, CHAT_CONFIG

class ChatServer:
    def __init__(self):
        self.clients = {}  # {socket: username}
        self.running = False
        self.server_socket = None
        
    def start(self):
        """Start the chat server"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((HOST, PORTS['CHAT']))
        self.server_socket.listen(5)
        self.running = True
        
        print(f"[CHAT] Server started on {HOST}:{PORTS['CHAT']}")
        
        # Start accepting clients
        accept_thread = threading.Thread(target=self._accept_clients, daemon=True)
        accept_thread.start()
        
    def _accept_clients(self):
        """Accept incoming chat connections"""
        while self.running:
            try:
                client_socket, address = self.server_socket.accept()
                print(f"[CHAT] New connection from {address}")
                
                # Handle client in separate thread
                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_socket,),
                    daemon=True
                )
                client_thread.start()
            except Exception as e:
                if self.running:
                    print(f"[CHAT] Error accepting client: {e}")
                    
    def _handle_client(self, client_socket):
        """Handle messages from a single client"""
        username = None
        
        try:
            # Receive username first
            data = client_socket.recv(1024).decode(CHAT_CONFIG['MESSAGE_ENCODING'])
            username = data
            self.clients[client_socket] = username
            
            # Broadcast join message
            join_msg = {
                'type': 'system',
                'username': 'System',
                'message': f'{username} joined the chat',
                'timestamp': datetime.now().strftime('%H:%M:%S')
            }
            self._broadcast(json.dumps(join_msg), None)
            
            # Handle messages
            while self.running:
                data = client_socket.recv(CHAT_CONFIG['MAX_MESSAGE_LENGTH'])
                if not data:
                    break
                    
                message_data = json.loads(data.decode(CHAT_CONFIG['MESSAGE_ENCODING']))
                message_data['timestamp'] = datetime.now().strftime('%H:%M:%S')
                
                # Broadcast to all clients
                self._broadcast(json.dumps(message_data), client_socket)
                
        except Exception as e:
            print(f"[CHAT] Error handling client {username}: {e}")
        finally:
            # Client disconnected
            if client_socket in self.clients:
                username = self.clients[client_socket]
                del self.clients[client_socket]
                
                # Broadcast leave message
                leave_msg = {
                    'type': 'system',
                    'username': 'System',
                    'message': f'{username} left the chat',
                    'timestamp': datetime.now().strftime('%H:%M:%S')
                }
                self._broadcast(json.dumps(leave_msg), None)
                
            client_socket.close()
            
    def _broadcast(self, message, exclude_socket=None):
        """Broadcast message to all connected clients"""
        disconnected = []
        
        for client_socket in self.clients:
            if client_socket != exclude_socket:
                try:
                    client_socket.send(message.encode(CHAT_CONFIG['MESSAGE_ENCODING']))
                except:
                    disconnected.append(client_socket)
                    
        # Clean up disconnected clients
        for client_socket in disconnected:
            if client_socket in self.clients:
                del self.clients[client_socket]
                client_socket.close()
                
    def stop(self):
        """Stop the chat server"""
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        for client_socket in list(self.clients.keys()):
            client_socket.close()
        print("[CHAT] Server stopped")