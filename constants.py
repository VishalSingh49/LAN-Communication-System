# constants.py
"""
Centralized configuration for the LAN communication application.

Task summary:
- Expose network constants (hosts and ports) consumed by every module.
- Collect streaming, file-transfer, and UI configuration values in one place for easy tuning.
- Provide sane defaults so both server and client boot without additional setup.
"""

# Network Configuration
HOST = '0.0.0.0'  # Server binds to all interfaces
DEFAULT_SERVER_IP = '172.16.201.188'  # Change this to your server IP
BUFFER_SIZE = 131072  # 128KB

# Port Assignments (Each module gets its own port)
PORTS = {
    'CHAT': 5001,           # TCP - Text chat messaging
    'FILE_TRANSFER': 5002,  # TCP - File sharing
    'VIDEO': 5003,          # UDP - Video streaming
    'AUDIO': 5004,          # UDP - Audio streaming
    'SCREEN_SHARE': 5005,
    'CONTROL': 5000,
    'PARTICIPANTS': 5006    # TCP - Main control & user management
}

SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
SCREEN_QUALITY = 60 


AUDIO_CONFIG = {
    'SAMPLE_RATE': 44100,   
    'CHANNELS': 1,          # Mono
    'CHUNK_SIZE': 2048,     # Larger chunks = less crackling, smoother playback
    'FORMAT': 'int16',
}


VIDEO_CONFIG = {
    'FPS': 15,             
    'QUALITY': 45,          
    'WIDTH': 320,
    'HEIGHT': 240,
    'MAX_STREAMS': 9,
}

# Network Configuration
BUFFER_SIZE = 131072  # 128KB

# Screen Share Configuration
SCREEN_SHARE_CONFIG = {
    'FPS': 5,
    'QUALITY': 70,
    'MAX_WIDTH': 1280,
    'MAX_HEIGHT': 720,
}

# File Transfer Configuration
FILE_TRANSFER_CONFIG = {
    'CHUNK_SIZE': 8192,
    'MAX_FILE_SIZE': 500 * 1024 * 1024,  # 500 MB
    'STORAGE_PATH': './shared_files/',
}

# Chat Configuration
CHAT_CONFIG = {
    'MAX_MESSAGE_LENGTH': 4096,
    'MESSAGE_ENCODING': 'utf-8',
}

# UI Configuration
UI_CONFIG = {
    'WINDOW_WIDTH': 1400,
    'WINDOW_HEIGHT': 800,
    'VIDEO_GRID_COLS': 3,
    'THEME_COLOR': '#2C3E50',
    'ACCENT_COLOR': '#3498DB',
}

# Connection Settings
CONNECTION_CONFIG = {
    'TIMEOUT': 30,
    'RECONNECT_ATTEMPTS': 3,
    'HEARTBEAT_INTERVAL': 5,
}