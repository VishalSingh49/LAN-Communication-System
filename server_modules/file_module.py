# server/file_module.py
"""
Server-side file transfer module - handles file sharing independently.

Task summary:
- Accept upload/download requests and stream file chunks between clients.
- Maintain the canonical catalogue of shared files, including metadata for the UI.
- Persist uploads to disk and reload them on startup so history survives restarts.
"""

import socket
import threading
import json
import os
from constants import PORTS, HOST, FILE_TRANSFER_CONFIG

class FileServer:
    def __init__(self):
        self.clients = []  # List of connected client sockets
        self.running = False
        self.server_socket = None
        self.available_files = {}  # {filename: {'size': size, 'uploader': username}}
        self.storage_path = FILE_TRANSFER_CONFIG['STORAGE_PATH']
        
        # Create storage directory if it doesn't exist
        os.makedirs(self.storage_path, exist_ok=True)
        
        # Load existing files from storage directory
        self._load_existing_files()
        
    def _load_existing_files(self):
        """Load existing files from storage directory on startup"""
        try:
            for filename in os.listdir(self.storage_path):
                filepath = os.path.join(self.storage_path, filename)
                if os.path.isfile(filepath):
                    filesize = os.path.getsize(filepath)
                    self.available_files[filename] = {
                        'size': filesize,
                        'uploader': 'Server'  # Mark as uploaded by server (existing file)
                    }
            
            if self.available_files:
                print(f"[FILE] Loaded {len(self.available_files)} existing files from storage")
                print(f"[FILE] Files: {list(self.available_files.keys())}")
            else:
                print(f"[FILE] No existing files found in {self.storage_path}")
                
        except Exception as e:
            print(f"[FILE] Error loading existing files: {e}")
        
    def start(self):
        """Start the file transfer server"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((HOST, PORTS['FILE_TRANSFER']))
        self.server_socket.listen(5)
        self.running = True
        
        print(f"[FILE] Server started on {HOST}:{PORTS['FILE_TRANSFER']}")
        
        # Start accepting clients
        accept_thread = threading.Thread(target=self._accept_clients, daemon=True)
        accept_thread.start()
        
    def _accept_clients(self):
        """Accept incoming file transfer connections"""
        while self.running:
            try:
                client_socket, address = self.server_socket.accept()
                print(f"[FILE] New connection from {address}")
                self.clients.append(client_socket)
                
                # Handle client in separate thread
                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_socket,),
                    daemon=True
                )
                client_thread.start()
            except Exception as e:
                if self.running:
                    print(f"[FILE] Error accepting client: {e}")
                    
    def _handle_client(self, client_socket):
        """Handle file transfer requests from a client"""
        try:
            while self.running:
                data = client_socket.recv(1024).decode('utf-8')
                if not data:
                    break
                    
                request = json.loads(data)
                command = request.get('command')
                
                if command == 'UPLOAD':
                    self._handle_upload(client_socket, request)
                elif command == 'DOWNLOAD':
                    self._handle_download(client_socket, request)
                elif command == 'LIST':
                    self._send_file_list(client_socket)
                    
        except Exception as e:
            print(f"[FILE] Error handling client: {e}")
        finally:
            if client_socket in self.clients:
                self.clients.remove(client_socket)
            client_socket.close()
            
    def _handle_upload(self, client_socket, request):
        """Receive file from client and store it"""
        try:
            filename = request['filename']
            filesize = request['filesize']
            username = request['username']
            
            print(f"[FILE] Upload request: {filename} ({filesize} bytes) from {username}")
            
            # Check file size limit
            if filesize > FILE_TRANSFER_CONFIG['MAX_FILE_SIZE']:
                response = {'status': 'error', 'message': 'File too large'}
                client_socket.send(json.dumps(response).encode('utf-8'))
                return
                
            # Send ready signal
            response = {'status': 'ready'}
            client_socket.send(json.dumps(response).encode('utf-8'))
            
            # Receive file data
            filepath = os.path.join(self.storage_path, filename)
            received = 0
            
            with open(filepath, 'wb') as f:
                while received < filesize:
                    chunk = client_socket.recv(
                        min(FILE_TRANSFER_CONFIG['CHUNK_SIZE'], filesize - received)
                    )
                    if not chunk:
                        break
                    f.write(chunk)
                    received += len(chunk)
                    
            print(f"[FILE] Received {filename} ({received} bytes) from {username}")
            
            # Add to available files
            self.available_files[filename] = {
                'size': filesize,
                'uploader': username
            }
            
            # Send success response
            response = {'status': 'success', 'message': 'File uploaded successfully'}
            client_socket.send(json.dumps(response).encode('utf-8'))
            
            # Broadcast file list update to all connected clients
            print(f"[FILE] Broadcasting file list update to {len(self.clients)} clients")
            self._broadcast_file_list()
            
        except Exception as e:
            print(f"[FILE] Error in upload: {e}")
            response = {'status': 'error', 'message': str(e)}
            try:
                client_socket.send(json.dumps(response).encode('utf-8'))
            except:
                pass
                
    def _handle_download(self, client_socket, request):
        """Send file to client"""
        try:
            filename = request['filename']
            filepath = os.path.join(self.storage_path, filename)
            
            if not os.path.exists(filepath):
                response = {'status': 'error', 'message': 'File not found'}
                client_socket.send(json.dumps(response).encode('utf-8'))
                return
                
            filesize = os.path.getsize(filepath)
            
            # Send file metadata
            response = {
                'status': 'ready',
                'filesize': filesize
            }
            client_socket.send(json.dumps(response).encode('utf-8'))
            
            # Wait for client ready signal
            client_socket.recv(1024)
            
            # Send file data
            with open(filepath, 'rb') as f:
                sent = 0
                while sent < filesize:
                    chunk = f.read(FILE_TRANSFER_CONFIG['CHUNK_SIZE'])
                    if not chunk:
                        break
                    client_socket.send(chunk)
                    sent += len(chunk)
                    
            print(f"[FILE] Sent {filename} ({sent} bytes)")
            
        except Exception as e:
            print(f"[FILE] Error in download: {e}")
            
    def _send_file_list(self, client_socket):
        """Send list of available files to client"""
        try:
            response = {
                'status': 'success',
                'files': self.available_files
            }
            data = json.dumps(response).encode('utf-8')
            # Add length header
            data_with_length = len(data).to_bytes(4, 'big') + data
            client_socket.send(data_with_length)
            print(f"[FILE] Sent file list to client: {list(self.available_files.keys())}")
        except Exception as e:
            print(f"[FILE] Error sending file list: {e}")
            
    def _broadcast_file_list(self):
        """Broadcast updated file list to all clients"""
        message = {
            'type': 'file_list_update',
            'files': self.available_files
        }
        data = json.dumps(message).encode('utf-8')
        
        print(f"[FILE] Broadcasting file list: {list(self.available_files.keys())}")
        
        disconnected = []
        for client_socket in self.clients:
            try:
                # Add length header to help with parsing
                data_with_length = len(data).to_bytes(4, 'big') + data
                client_socket.send(data_with_length)
            except Exception as e:
                print(f"[FILE] Error broadcasting to client: {e}")
                disconnected.append(client_socket)
                
        # Clean up disconnected clients
        for client_socket in disconnected:
            if client_socket in self.clients:
                self.clients.remove(client_socket)
                
    def stop(self):
        """Stop the file transfer server"""
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        for client_socket in self.clients:
            client_socket.close()
        print("[FILE] Server stopped")