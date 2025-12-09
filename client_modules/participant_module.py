"""
Client participant module - maintains the live roster for the conference.

Task summary:
- Connect to the participant service, register the local username, and send keepalives.
- Stream participant presence, status, and video-state updates to the GUI layer.
- Resiliently parse JSON messages so the UI can react without blocking on socket I/O.
"""

import socket
import threading
import json
import time
from constants import PORTS

class ParticipantClient:
    def __init__(self, server_ip, username, update_callback):
        self.server_ip = server_ip
        self.username = username
        self.update_callback = update_callback  # Callback to update GUI
        self.socket = None
        self.running = False
        self.connected = False
        self.buffer = ""  # Buffer for incomplete JSON messages
        
    def connect(self):
        """Connect to participant server"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.socket.settimeout(10)  # Set timeout for connection
            self.socket.connect((self.server_ip, PORTS['PARTICIPANTS']))
            
            # Send username
            self.socket.send(self.username.encode('utf-8'))
            
            self.connected = True
            self.running = True
            
            # Start receiving updates BEFORE waiting for initial list
            receive_thread = threading.Thread(target=self._receive_updates, daemon=True)
            receive_thread.start()
            
            # Start keepalive thread
            keepalive_thread = threading.Thread(target=self._send_keepalive, daemon=True)
            keepalive_thread.start()
            
            print("[Participant] Connected to participant server")
            
            # Give time for initial participant list to arrive
            time.sleep(0.2)
            
            return True
            
        except Exception as e:
            print(f"[Participant] Connection error: {e}")
            return False
    
    def _send_keepalive(self):
        """Send periodic keepalive messages"""
        while self.running and self.connected:
            try:
                time.sleep(5)  # Send keepalive every 5 seconds
                if self.connected and self.running:
                    message = {'type': 'keepalive'}
                    self.socket.sendall(json.dumps(message).encode('utf-8') + b'\n')
            except Exception as e:
                if self.running:
                    print(f"[Participant] Keepalive error: {e}")
                self.connected = False
                break
                
    def _receive_updates(self):
        """Receive participant list updates from server"""
        self.socket.settimeout(1.0)  # Set socket timeout for recv
        
        while self.running:
            try:
                data = self.socket.recv(8192)
                if not data:
                    print("[Participant] Connection closed by server")
                    self.connected = False
                    break
                
                # Add received data to buffer
                self.buffer += data.decode('utf-8')
                
                # Process complete messages (delimited by newline)
                while '\n' in self.buffer:
                    message_str, self.buffer = self.buffer.split('\n', 1)
                    
                    if not message_str.strip():
                        continue
                    
                    try:
                        message = json.loads(message_str)
                        
                        if message['type'] == 'participant_list':
                            participants = message['participants']
                            print(f"[Participant] Received participant list: {list(participants.keys())}")
                            
                            # Call GUI callback to update participant list
                            if self.update_callback:
                                try:
                                    self.update_callback(participants)
                                except Exception as e:
                                    print(f"[Participant] Error in update callback: {e}")
                        
                        elif message['type'] == 'keepalive_ack':
                            # Keepalive acknowledged
                            pass
                                
                    except json.JSONDecodeError as e:
                        print(f"[Participant] JSON decode error: {e}")
                    except Exception as e:
                        print(f"[Participant] Error processing message: {e}")
                        
            except socket.timeout:
                # Timeout is normal, just continue
                continue
            except Exception as e:
                if self.running:
                    print(f"[Participant] Error receiving update: {e}")
                self.connected = False
                break
                
        self.connected = False
        print("[Participant] Receive loop ended")
        
    def send_status_update(self, status):
        """Send status update to server"""
        if not self.connected:
            return False
            
        try:
            message = {
                'type': 'status_update',
                'status': status
            }
            
            self.socket.sendall(json.dumps(message).encode('utf-8') + b'\n')
            return True
            
        except Exception as e:
            print(f"[Participant] Error sending status: {e}")
            self.connected = False
            return False
    
    def send_video_status(self, active):
        """Send video status update to server"""
        if not self.connected:
            return False
            
        try:
            message = {
                'type': 'video_status',
                'active': active
            }
            
            self.socket.sendall(json.dumps(message).encode('utf-8') + b'\n')
            print(f"[Participant] Sent video status: {active}")
            return True
            
        except Exception as e:
            print(f"[Participant] Error sending video status: {e}")
            self.connected = False
            return False
            
    def disconnect(self):
        """Disconnect from participant server"""
        print("[Participant] Disconnecting...")
        self.running = False
        self.connected = False
        
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
        
        print("[Participant] Disconnected")