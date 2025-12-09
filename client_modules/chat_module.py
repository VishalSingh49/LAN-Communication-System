# client/chat_module.py
"""
Client-side chat module - Handles text messaging independently.

Task summary:
- Establish a TCP connection to the chat service and register the current username.
- Provide a send API that respects encoding limits defined in ``CHAT_CONFIG``.
- Listen for broadcast messages and surface them through the GUI callback without blocking the UI thread.
"""

import socket
import threading
import json
from constants import PORTS, CHAT_CONFIG

class ChatClient:
    def __init__(self, server_ip, username, message_callback):
        self.server_ip = server_ip
        self.username = username
        self.message_callback = message_callback  # Callback to display messages in GUI
        self.socket = None
        self.running = False
        self.connected = False
        
    def connect(self):
        """Connect to chat server"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.server_ip, PORTS['CHAT']))
            
            # Send username
            self.socket.send(self.username.encode(CHAT_CONFIG['MESSAGE_ENCODING']))
            
            self.connected = True
            self.running = True
            
            # Start receiving messages
            receive_thread = threading.Thread(target=self._receive_messages, daemon=True)
            receive_thread.start()
            
            print("[CHAT] Connected to chat server")
            return True
            
        except Exception as e:
            print(f"[CHAT] Connection error: {e}")
            return False
            

    def _receive_messages(self):
        """Receive messages from server"""
        while self.running:
            try:
                data = self.socket.recv(CHAT_CONFIG['MAX_MESSAGE_LENGTH'])
                if not data:
                    break
                    
                message_data = json.loads(data.decode(CHAT_CONFIG['MESSAGE_ENCODING']))
                
                # Call GUI callback to display message
                if self.message_callback:
                    # Received messages are NOT sent messages, set is_sent=False
                    self.message_callback(message_data, is_sent=False) 
                    
            except Exception as e:
                if self.running:
                    print(f"[CHAT] Error receiving message: {e}")
                break
                
        self.connected = False
        
    def send_message(self, message):
        """Send a message to the server, and display it locally (Local Echo)"""
        if not self.connected:
            return False
            
        try:
            message_data = {
                'type': 'message',
                'username': self.username,
                'message': message
            }
            
            # 1. LOCAL ECHO: Call the GUI callback IMMEDIATELY with a flag
            if self.message_callback:
                self.message_callback(message_data, is_sent=True) # <-- PASS THE FLAG

            # 2. Send the message to the server
            self.socket.send(json.dumps(message_data).encode(CHAT_CONFIG['MESSAGE_ENCODING']))
            return True
            
        except Exception as e:
            print(f"[CHAT] Error sending message: {e}")
            return False
            
    def disconnect(self):
        """Disconnect from chat server"""
        self.running = False
        self.connected = False
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
        print("[CHAT] Disconnected from chat server")