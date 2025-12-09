"""
Client screen share module - single presenter mode with notifications.

Task summary:
- Capture desktop frames and stream them to the server when the user is granted presenter rights.
- Listen for presentation notifications and push them to the GUI so attendees can react.
- Rebuild inbound screen frames and forward them to the viewer window without blocking the UI.
"""

import socket
import threading
import pickle
import struct
import cv2
import numpy as np
from mss import mss
from constants import PORTS, SCREEN_SHARE_CONFIG, BUFFER_SIZE

class ScreenClient:
    def __init__(self, server_ip, username, on_screen_frame_callback, on_notification_callback):
        self.server_ip = server_ip
        self.username = username
        self.on_screen_frame = on_screen_frame_callback
        self.on_notification = on_notification_callback
        
        self.socket = None
        self.streaming = False
        self.receiving = False
        self.presenting_allowed = False
        
        self.send_thread = None
        self.receive_thread = None
        
    def connect(self):
        """Connect to screen share server"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.server_ip, PORTS['SCREEN_SHARE']))
            
            # Send username
            self.socket.send(self.username.encode('utf-8'))
            
            # Start receiving thread
            self.receiving = True
            self.receive_thread = threading.Thread(target=self._receive_messages, daemon=True)
            self.receive_thread.start()
            
            print(f"[Screen] Connected to server at {self.server_ip}:{PORTS['SCREEN_SHARE']}")
            return True
            
        except Exception as e:
            print(f"[Screen] Connection error: {e}")
            return False
            
    def start_streaming(self):
        """Request to start screen sharing"""
        if self.streaming:
            return True
        
        # Send request to server
        self._send_message({
            'type': 'start_presenting',
            'username': self.username
        })
        
        # Wait for response (handled in receive thread)
        # The actual streaming will start when server approves
        return True
    
    def _actually_start_streaming(self):
        """Actually start streaming after server approval"""
        self.streaming = True
        self.presenting_allowed = True
        self.send_thread = threading.Thread(target=self._stream_screen, daemon=True)
        self.send_thread.start()
        print("[Screen] Started screen sharing")
            
    def stop_streaming(self):
        """Stop screen streaming"""
        if not self.streaming:
            return
            
        self.streaming = False
        self.presenting_allowed = False
        
        # Notify server
        self._send_message({
            'type': 'stop_presenting',
            'username': self.username
        })
        
        print("[Screen] Stopped screen sharing")
        
    def _stream_screen(self):
        """Capture and stream screen continuously"""
        # Create mss instance inside the thread
        sct = mss()
        monitor = sct.monitors[1]  # Primary monitor
        frame_delay = 1.0 / SCREEN_SHARE_CONFIG['FPS']
        
        try:
            while self.streaming and self.presenting_allowed:
                try:
                    # Capture screen
                    screenshot = sct.grab(monitor)
                    frame = np.array(screenshot)
                    
                    # Convert BGRA to BGR
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                    
                    # Resize to reduce bandwidth
                    height, width = frame.shape[:2]
                    max_width = SCREEN_SHARE_CONFIG['MAX_WIDTH']
                    max_height = SCREEN_SHARE_CONFIG['MAX_HEIGHT']
                    
                    # Calculate scaling factor
                    scale = min(max_width / width, max_height / height, 1.0)
                    new_width = int(width * scale)
                    new_height = int(height * scale)
                    
                    frame = cv2.resize(frame, (new_width, new_height))
                    
                    # Compress frame
                    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), SCREEN_SHARE_CONFIG['QUALITY']]
                    _, buffer = cv2.imencode('.jpg', frame, encode_param)
                    
                    # Send frame
                    self._send_message({
                        'type': 'screen_frame',
                        'frame': buffer
                    })
                    
                    # Control frame rate
                    threading.Event().wait(frame_delay)
                    
                except Exception as e:
                    print(f"[Screen] Frame capture error: {e}")
                    
        except Exception as e:
            print(f"[Screen] Streaming error: {e}")
            self.streaming = False
        finally:
            # Close mss instance when done
            sct.close()
    
    def _send_message(self, message):
        """Send message to server"""
        try:
            data = pickle.dumps(message)
            message_size = struct.pack("L", len(data))
            self.socket.sendall(message_size + data)
        except Exception as e:
            print(f"[Screen] Send error: {e}")
                
    def _receive_messages(self):
        """Receive messages from server"""
        data = b""
        payload_size = struct.calcsize("L")
        
        while self.receiving:
            try:
                # Receive message size
                while len(data) < payload_size:
                    packet = self.socket.recv(BUFFER_SIZE)
                    if not packet:
                        break
                    data += packet
                    
                if len(data) < payload_size:
                    break
                    
                packed_msg_size = data[:payload_size]
                data = data[payload_size:]
                msg_size = struct.unpack("L", packed_msg_size)[0]
                
                # Receive message data
                while len(data) < msg_size:
                    data += self.socket.recv(BUFFER_SIZE)
                    
                message_data = data[:msg_size]
                data = data[msg_size:]
                
                # Unpack message
                message = pickle.loads(message_data)
                
                # Handle different message types
                if message['type'] == 'presenting_allowed':
                    if message['allowed']:
                        # Server approved, start streaming
                        self._actually_start_streaming()
                        # Notify GUI
                        self.on_notification('approved', self.username)
                    else:
                        # Someone else is presenting
                        current = message.get('current_presenter', 'Unknown')
                        self.on_notification('denied', current)
                        
                elif message['type'] == 'presenter_started':
                    # Someone started presenting
                    presenter = message['username']
                    if presenter != self.username:
                        self.on_notification('started', presenter)
                    
                elif message['type'] == 'presenter_stopped':
                    # Someone stopped presenting
                    presenter = message['username']
                    self.on_notification('stopped', presenter)
                    
                elif message['type'] == 'screen_frame':
                    # Received screen frame
                    username = message['username']
                    frame_buffer = message['frame']
                    
                    # Decode frame
                    frame = cv2.imdecode(frame_buffer, cv2.IMREAD_COLOR)
                    
                    if frame is not None:
                        self.on_screen_frame(username, frame)
                    
            except Exception as e:
                print(f"[Screen] Receive error: {e}")
                break
                
        self.receiving = False
        
    def disconnect(self):
        """Disconnect from server"""
        self.streaming = False
        self.receiving = False
        self.presenting_allowed = False
        
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
                
        print("[Screen] Disconnected")