# client/file_module.py
"""
Client-side file transfer module - Handles file sharing independently.

Task summary:
- Maintain a TCP connection used for metadata, file listing, and chunked transfers.
- Provide asynchronous upload/download helpers that integrate with GUI progress callbacks.
- Keep the local file list synchronized with updates broadcast by the server.
"""

import socket
import threading
import json
import os
from constants import PORTS, FILE_TRANSFER_CONFIG

class FileClient:
    def __init__(self, server_ip, username, file_list_callback, progress_callback):
        self.server_ip = server_ip
        self.username = username
        self.file_list_callback = file_list_callback
        self.progress_callback = progress_callback
        self.socket = None
        self.running = False
        self.connected = False
        self.socket_lock = threading.Lock()  # Prevent concurrent socket access
        
    def connect(self):
        """Connect to file transfer server"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(30)  # 30 second timeout
            self.socket.connect((self.server_ip, PORTS['FILE_TRANSFER']))
            
            self.connected = True
            self.running = True
            
            print("[FILE] Connected to file server")
            
            # Start listening for updates
            listen_thread = threading.Thread(target=self._listen_updates, daemon=True)
            listen_thread.start()
            
            # Request initial file list
            def request_list():
                import time
                time.sleep(0.5)
                self.request_file_list()
            
            threading.Thread(target=request_list, daemon=True).start()
            
            return True
            
        except Exception as e:
            print(f"[FILE] Connection error: {e}")
            return False
            
    def _listen_updates(self):
        """Listen for file list updates from server"""
        while self.running and self.connected:
            try:
                # Set a timeout for receiving
                self.socket.settimeout(1.0)
                
                # First receive the length header (4 bytes)
                length_data = b''
                while len(length_data) < 4:
                    chunk = self.socket.recv(4 - len(length_data))
                    if not chunk:
                        print("[FILE] Connection closed by server")
                        return
                    length_data += chunk
                
                msg_length = int.from_bytes(length_data, 'big')
                
                # Receive the actual message
                data = b''
                while len(data) < msg_length:
                    chunk = self.socket.recv(min(8192, msg_length - len(data)))
                    if not chunk:
                        break
                    data += chunk
                
                if not data or len(data) < msg_length:
                    break
                    
                update = json.loads(data.decode('utf-8'))
                
                if update.get('type') == 'file_list_update':
                    print(f"[FILE] Received file list update: {list(update['files'].keys())}")
                    if self.file_list_callback:
                        self.file_list_callback(update['files'])
                        
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[FILE] Error receiving update: {e}")
                break
                
        self.connected = False
        print("[FILE] Listen thread ended")
        
    def upload_file(self, filepath):
        """Upload a file to the server"""
        if not self.connected:
            if self.progress_callback:
                self.progress_callback("error", "Not connected to server")
            return False
            
        try:
            filename = os.path.basename(filepath)
            filesize = os.path.getsize(filepath)
            
            # Check file size
            if filesize > FILE_TRANSFER_CONFIG['MAX_FILE_SIZE']:
                if self.progress_callback:
                    self.progress_callback("error", "File too large (max 500MB)")
                return False
            
            if self.progress_callback:
                self.progress_callback("upload", "Preparing upload...")
                
            # Create new socket for upload
            upload_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            upload_socket.settimeout(60)  # 60 second timeout
            upload_socket.connect((self.server_ip, PORTS['FILE_TRANSFER']))
                
            # Send upload request
            request = {
                'command': 'UPLOAD',
                'filename': filename,
                'filesize': filesize,
                'username': self.username
            }
            upload_socket.send(json.dumps(request).encode('utf-8'))
            
            # Wait for ready signal
            response = json.loads(upload_socket.recv(1024).decode('utf-8'))
            if response['status'] != 'ready':
                if self.progress_callback:
                    self.progress_callback("error", response.get('message', 'Upload failed'))
                upload_socket.close()
                return False
                
            # Send file data
            sent = 0
            with open(filepath, 'rb') as f:
                while sent < filesize:
                    chunk = f.read(FILE_TRANSFER_CONFIG['CHUNK_SIZE'])
                    if not chunk:
                        break
                    upload_socket.sendall(chunk) 
                    sent += len(chunk)
                    
                    # Update progress
                    if self.progress_callback:
                        progress = int((sent / filesize) * 100)
                        self.progress_callback("upload", f"Uploading: {progress}%")
                        
            # Wait for completion response
            response = json.loads(upload_socket.recv(1024).decode('utf-8'))
            upload_socket.close()
            
            if response['status'] == 'success':
                if self.progress_callback:
                    self.progress_callback("success", f"Uploaded: {filename}")
                print(f"[FILE] Uploaded {filename}")
                return True
            else:
                if self.progress_callback:
                    self.progress_callback("error", response.get('message', 'Upload failed'))
                return False
                
        except Exception as e:
            print(f"[FILE] Upload error: {e}")
            if self.progress_callback:
                self.progress_callback("error", f"Upload failed: {str(e)}")
            return False
            
    def download_file(self, filename, save_path):
        """Download a file from the server"""
        if not self.connected:
            if self.progress_callback:
                self.progress_callback("error", "Not connected to server")
            return False
            
        try:
            if self.progress_callback:
                self.progress_callback("download", f"Starting download of {filename}...")
            
            print(f"[FILE] Starting download: {filename}")
            
            # Create new socket for download
            download_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            download_socket.settimeout(60)  # 60 second timeout
            download_socket.connect((self.server_ip, PORTS['FILE_TRANSFER']))
            
            # Send download request
            request = {
                'command': 'DOWNLOAD',
                'filename': filename
            }
            download_socket.send(json.dumps(request).encode('utf-8'))
            print(f"[FILE] Sent download request for {filename}")
            
            # Receive file metadata
            response_data = download_socket.recv(1024).decode('utf-8')
            print(f"[FILE] Received response: {response_data}")
            response = json.loads(response_data)
            
            if response['status'] != 'ready':
                if self.progress_callback:
                    self.progress_callback("error", response.get('message', 'Download failed'))
                download_socket.close()
                return False
                
            filesize = response['filesize']
            print(f"[FILE] File size: {filesize} bytes")
            
            # Send ready signal
            download_socket.send(b'READY')
            print(f"[FILE] Sent READY signal")
            
            # Receive file data
            received = 0
            filepath = os.path.join(save_path, filename)
            
            print(f"[FILE] Saving to: {filepath}")
            
            with open(filepath, 'wb') as f:
                while received < filesize:
                    remaining = filesize - received
                    chunk_size = min(FILE_TRANSFER_CONFIG['CHUNK_SIZE'], remaining)
                    chunk = download_socket.recv(chunk_size)
                    
                    if not chunk:
                        print(f"[FILE] Connection closed, received {received}/{filesize} bytes")
                        break
                        
                    f.write(chunk)
                    received += len(chunk)
                    
                    # Update progress
                    if self.progress_callback:
                        progress = int((received / filesize) * 100)
                        self.progress_callback("download", f"Downloading: {progress}%")
                        
                    # Log progress every 10%
                    if received % (filesize // 10 + 1) == 0:
                        print(f"[FILE] Progress: {received}/{filesize} bytes ({progress}%)")
            
            download_socket.close()
            
            if received == filesize:
                if self.progress_callback:
                    self.progress_callback("success", f"Downloaded: {filename}")
                print(f"[FILE] Successfully downloaded {filename} ({received} bytes)")
                return True
            else:
                if self.progress_callback:
                    self.progress_callback("error", f"Incomplete download: {received}/{filesize} bytes")
                print(f"[FILE] Incomplete download: {received}/{filesize} bytes")
                return False
            
        except Exception as e:
            print(f"[FILE] Download error: {e}")
            import traceback
            traceback.print_exc()
            if self.progress_callback:
                self.progress_callback("error", f"Download failed: {str(e)}")
            return False
            
    def request_file_list(self):
        """Request list of available files"""
        if not self.connected:
            return
            
        try:
            # Create temporary socket for LIST request
            list_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            list_socket.settimeout(10)
            list_socket.connect((self.server_ip, PORTS['FILE_TRANSFER']))
            
            request = {'command': 'LIST'}
            list_socket.send(json.dumps(request).encode('utf-8'))
            
            # Receive length header
            length_data = b''
            while len(length_data) < 4:
                chunk = list_socket.recv(4 - len(length_data))
                if not chunk:
                    break
                length_data += chunk
            
            if len(length_data) == 4:
                msg_length = int.from_bytes(length_data, 'big')
                
                # Receive the actual data
                data = b''
                while len(data) < msg_length:
                    chunk = list_socket.recv(min(8192, msg_length - len(data)))
                    if not chunk:
                        break
                    data += chunk
                
                if len(data) == msg_length:
                    response = json.loads(data.decode('utf-8'))
                    if response['status'] == 'success' and self.file_list_callback:
                        print(f"[FILE] Received file list: {list(response['files'].keys())}")
                        self.file_list_callback(response['files'])
            
            list_socket.close()
                
        except Exception as e:
            print(f"[FILE] Error requesting file list: {e}")
            
    def disconnect(self):
        """Disconnect from file server"""
        self.running = False
        self.connected = False
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
        print("[FILE] Disconnected from file server")