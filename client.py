"""
Client GUI for the conferencing suite.

Task summary:
- Build and orchestrate the user interface for video, audio, chat, files, and participants.
- Coordinate client modules so each subsystem (audio, video, screen share, chat, files) remains responsive.
- Maintain user state (tiles, participants, notifications) and react to network callbacks.
"""

import tkinter as tk
import datetime
import time 
from tkinter import ttk, scrolledtext, filedialog, messagebox
import cv2
from PIL import Image, ImageTk
import threading
from datetime import datetime, time
from client_modules.chat_module import ChatClient
from client_modules.file_module import FileClient
from client_modules.video_module import VideoClient
from client_modules.audio_module import AudioClient
from client_modules.screen_module import ScreenClient
from client_modules.participant_module import ParticipantClient
from constants import UI_CONFIG

class ConferenceGUI:
    def __init__(self, root, server_ip, username):
        self.root = root
        self.server_ip = server_ip
        self.username = username
        
        # Initialize modules
        self.chat_client = None
        self.file_client = None
        self.video_client = None
        self.audio_client = None
        self.screen_client = None
        self.participant_client = None
        
        # State variables
        self.video_enabled = False
        self.audio_enabled = False
        self.mic_muted = True
        self.screen_sharing = False
        
        # Dynamic video tiles
        self.video_tiles = {}
        self.self_video_thread = None
        self.updating_self_video = False
        self.video_theme = {
            'tile_bg': '#2A2A2A',
            'tile_border': '#404040',
            'placeholder_bg': '#1A1A1A',
            'placeholder_fg': '#E0E0E0',
            'waiting_fg': '#CCCCCC',
            'name_self': '#FFFFFF',
            'name_peer': '#B0B0B0'
        }
        # Keep every tile at a predictable footprint so camera-off placeholders
        # line up with live feeds and the grid never jitters between layouts.
        self.video_dimensions = (400, 300)
        self.tile_padding = (16, 76)
        
        # Participant list
        self.participants = {}
        
        # Screen share state
        self.current_presenter = None
        self.screen_viewer_window = None
        self.screen_viewer_label = None
        self.latest_screen_frame = None
        
        self.setup_ui()
        self.connect_to_server()
        
    def setup_ui(self):
        """Setup the main user interface """
        self.root.title(f"Chai pe Charcha - {self.username}")
        self.root.geometry("1800x950")
        self.root.configure(bg='#000000')
        
        # Top bar for screen share notification
        self.setup_screen_notification_bar()
        
        # Main container with gradient effect
        main_frame = tk.Frame(self.root, bg='#000000')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        # Left panel - Video grid
        left_panel = tk.Frame(main_frame, bg='#000000')
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        # Video section (dynamic)
        self.setup_video_section(left_panel)
        
        # Control buttons (bottom)
        self.setup_control_buttons(left_panel)
        
        # Right panel - Chat, Files, and Participants
        right_panel = tk.Frame(main_frame, bg='#1A1A1A', width=450)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(10, 0))
        right_panel.pack_propagate(False)
        
        self.setup_tabbed_section(right_panel)
        
    def setup_screen_notification_bar(self):
        """Setup top bar for screen share notifications"""
        self.screen_notification_bar = tk.Frame(self.root, bg='#2A2A2A', height=60)
        self.screen_notification_bar.pack(fill=tk.X, side=tk.TOP)
        self.screen_notification_bar.pack_propagate(False)
        self.screen_notification_bar.pack_forget()
        
        # Content container
        content_frame = tk.Frame(self.screen_notification_bar, bg='#2A2A2A')
        content_frame.pack(expand=True)
        
        # Presenter info
        self.presenter_label = tk.Label(
            content_frame,
            text="",
            font=('Segoe UI', 12, 'bold'),
            bg='#2A2A2A',
            fg='#FFFFFF'
        )
        self.presenter_label.pack(side=tk.LEFT, padx=15)
        
        # View button
        self.view_screen_btn = tk.Button(
            content_frame,
            text="🖥️ View Screen",
            command=self.open_screen_viewer,
            bg='#FFFFFF',
            fg='#000000',
            font=('Segoe UI', 10, 'bold'),
            cursor='hand2',
            padx=25,
            pady=8,
            relief=tk.FLAT,
            borderwidth=0
        )
        self.view_screen_btn.pack(side=tk.LEFT, padx=10)
        
        # Hover effects
        self.view_screen_btn.bind('<Enter>', lambda e: self.view_screen_btn.config(bg='#E0E0E0'))
        self.view_screen_btn.bind('<Leave>', lambda e: self.view_screen_btn.config(bg='#FFFFFF'))
        
    def setup_video_section(self, parent):
        """Setup dynamic video grid area """
        video_frame = tk.Frame(parent, bg='#0A0A0A', relief=tk.FLAT, borderwidth=0)
        video_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Title
        title_frame = tk.Frame(video_frame, bg='#1A1A1A', height=50)
        title_frame.pack(fill=tk.X)
        title_frame.pack_propagate(False)

        title_label = tk.Label(
            title_frame,
            text="📹 Live Conference",
            font=('Segoe UI', 14, 'bold'),
            bg='#1A1A1A',
            fg='#FFFFFF'
        )
        title_label.pack(pady=12)

        # Scrollable video container
        canvas_frame = tk.Frame(video_frame, bg='#0A0A0A')
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Canvas for scrolling
        self.video_canvas = tk.Canvas(canvas_frame, bg='#0A0A0A', highlightthickness=0)
        video_scrollbar = tk.Scrollbar(
            canvas_frame,
            orient="vertical",
            command=self.video_canvas.yview,
            bg='#2A2A2A',
            troughcolor='#0A0A0A',
            width=12
        )

        self.video_container = tk.Frame(self.video_canvas, bg='#0A0A0A')

        self.video_canvas.create_window((0, 0), window=self.video_container, anchor="nw")
        self.video_canvas.configure(yscrollcommand=video_scrollbar.set)

        self.video_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        video_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.video_container.bind(
            "<Configure>",
            lambda e: self.video_canvas.configure(scrollregion=self.video_canvas.bbox("all"))
        )

        self.no_video_label = tk.Label(
            self.video_container,
            text="Participants will appear here\n\n🎥 Camera tiles update automatically",
            font=('Segoe UI', 13),
            bg='#0A0A0A',
            fg='#999999'
        )
        self.no_video_label.grid(row=0, column=0, columnspan=1, sticky='nsew', padx=50, pady=50)
        
    def setup_control_buttons(self, parent):
        """Setup control buttons """
        control_frame = tk.Frame(parent, bg='#1A1A1A', height=85)
        control_frame.pack(fill=tk.X)
        control_frame.pack_propagate(False)
        
        button_container = tk.Frame(control_frame, bg='#1A1A1A')
        button_container.pack(expand=True, pady=10)
        
        button_style = {
            'font': ('Segoe UI', 10, 'bold'),
            'width': 13,
            'height': 2,
            'relief': tk.FLAT,
            'cursor': 'hand2',
            'borderwidth': 0
        }
        
        # Microphone button
        self.mic_btn = tk.Button(
            button_container,
            text="🎤 Unmute",
            command=self.toggle_microphone,
            bg='#4A4A4A',
            fg='#FFFFFF',
            activebackground='#3A3A3A',
            **button_style
        )
        self.mic_btn.pack(side=tk.LEFT, padx=5)
        
        # Video button
        self.video_btn = tk.Button(
            button_container,
            text="🎥 Start Camera",
            command=self.toggle_video,
            bg='#6A6A6A',
            fg='#FFFFFF',
            activebackground='#5A5A5A',
            **button_style
        )
        self.video_btn.pack(side=tk.LEFT, padx=5)
        
        # Screen Share button
        self.screen_btn = tk.Button(
            button_container,
            text="🖥️ Share Screen",
            command=self.toggle_screen_share,
            bg='#8A8A8A',
            fg='#FFFFFF',
            activebackground='#7A7A7A',
            **button_style
        )
        self.screen_btn.pack(side=tk.LEFT, padx=5)
        
        # Speaker button
        self.speaker_btn = tk.Button(
            button_container,
            text="🔊 Speaker",
            command=self.toggle_speaker,
            bg='#6A6A6A',
            fg='#FFFFFF',
            activebackground='#5A5A5A',
            **button_style
        )
        self.speaker_btn.pack(side=tk.LEFT, padx=5)
        
        # Leave button
        leave_btn = tk.Button(
            button_container,
            text="❌ Leave",
            command=self.leave_conference,
            bg='#2A2A2A',
            fg='#FFFFFF',
            activebackground='#1A1A1A',
            **button_style
        )
        leave_btn.pack(side=tk.LEFT, padx=5)
        
        # Add hover effects
        for btn in [self.mic_btn, self.video_btn, self.screen_btn, self.speaker_btn, leave_btn]:
            self._add_button_hover(btn)
    
    def _add_button_hover(self, button):
        """Add hover effect to buttons"""
        original_bg = button['bg']
        hover_bg = button['activebackground']
        
        button.bind('<Enter>', lambda e: button.config(bg=hover_bg))
        button.bind('<Leave>', lambda e: button.config(bg=original_bg))
        
    def setup_tabbed_section(self, parent):
        """Setup tabbed interface """
        notebook = ttk.Notebook(parent)
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Style for notebook
        style = ttk.Style()
        style.theme_use('default')
        style.configure('TNotebook', background='#1A1A1A', borderwidth=0)
        style.configure('TNotebook.Tab', 
                       padding=[20, 12], 
                       font=('Segoe UI', 11, 'bold'),
                       background='#2A2A2A',
                       foreground='#FFFFFF')
        style.map('TNotebook.Tab',
                 background=[('selected', '#4A4A4A')],
                 foreground=[('selected', '#FFFFFF')])
        
        # Chat tab
        chat_frame = tk.Frame(notebook, bg='#2A2A2A')
        notebook.add(chat_frame, text='💬 Chat')
        self.setup_chat_tab(chat_frame)
        
        # Files tab
        files_frame = tk.Frame(notebook, bg='#2A2A2A')
        notebook.add(files_frame, text='📁 Files')
        self.setup_files_tab(files_frame)
        
        # Participants tab
        participants_frame = tk.Frame(notebook, bg='#2A2A2A')
        notebook.add(participants_frame, text='👥 Participants')
        self.setup_participants_tab(participants_frame)
        
    def setup_chat_tab(self, parent):
        """Setup chat interface"""
        self.chat_display = scrolledtext.ScrolledText(
            parent,
            wrap=tk.WORD,
            font=('Segoe UI', 10),
            bg='#0A0A0A',
            fg='#FFFFFF',
            state=tk.DISABLED,
            height=20,
            relief=tk.FLAT,
            borderwidth=0,
            insertbackground='#FFFFFF'
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        
            # Tag configurations for styling
        self.chat_display.tag_config('system', foreground='#888888', font=('Segoe UI', 9, 'italic'))
        self.chat_display.tag_config('username', foreground='#CCCCCC', font=('Segoe UI', 10, 'bold'))
        self.chat_display.tag_config('message', foreground='#E0E0E0', font=('Segoe UI', 10))
        self.chat_display.tag_config('time', foreground='#666666', font=('Segoe UI', 8))
        self.chat_display.tag_config('self', foreground='#FFFFFF', font=('Segoe UI', 10, 'bold'))
        self.chat_display.tag_config('self_message', justify='right', foreground='#AAAAAA')
        
        # Input area
        input_frame = tk.Frame(parent, bg='#2A2A2A')
        input_frame.pack(fill=tk.X, padx=12, pady=(0, 12))
        
        self.message_entry = tk.Entry(
            input_frame, 
            font=('Segoe UI', 11), 
            relief=tk.FLAT, 
            borderwidth=0,
            bg='#1A1A1A',
            fg='#FFFFFF',
            insertbackground='#FFFFFF'
        )
        self.message_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8), ipady=8)
        self.message_entry.bind('<Return>', lambda e: self.send_message())
        
        send_btn = tk.Button(
            input_frame,
            text="Send ➤",
            command=self.send_message,
            bg='#6A6A6A',
            fg='#FFFFFF',
            font=('Segoe UI', 10, 'bold'),
            width=10,
            cursor='hand2',
            relief=tk.FLAT,
            borderwidth=0,
            pady=8
        )
        send_btn.pack(side=tk.RIGHT)
        self._add_button_hover(send_btn)
        
    def setup_files_tab(self, parent):
        """Setup file sharing interface"""
        upload_frame = tk.Frame(parent, bg='#2A2A2A')
        upload_frame.pack(fill=tk.X, padx=12, pady=12)
        
        upload_btn = tk.Button(
            upload_frame,
            text="📤 Upload File",
            command=self.upload_file,
            bg='#6A6A6A',
            fg='#FFFFFF',
            font=('Segoe UI', 10, 'bold'),
            cursor='hand2',
            relief=tk.FLAT,
            borderwidth=0,
            padx=15,
            pady=8
        )
        upload_btn.pack(side=tk.LEFT, padx=5)
        self._add_button_hover(upload_btn)
        
        self.upload_status = tk.Label(
            upload_frame, 
            text="", 
            bg='#2A2A2A', 
            font=('Segoe UI', 9), 
            fg='#AAAAAA'
        )
        self.upload_status.pack(side=tk.LEFT, padx=10)
        
        separator = tk.Frame(parent, height=2, bg='#1A1A1A')
        separator.pack(fill=tk.X, padx=12, pady=8)
        
        list_label = tk.Label(
            parent, 
            text="Available Files:", 
            bg='#2A2A2A', 
            font=('Segoe UI', 12, 'bold'), 
            fg='#FFFFFF',
            anchor='w'
        )
        list_label.pack(fill=tk.X, padx=12, pady=(10, 5))
        
        list_frame = tk.Frame(parent, bg='#2A2A2A')
        list_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        
        scrollbar = tk.Scrollbar(list_frame, bg='#1A1A1A', troughcolor='#2A2A2A')
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.files_listbox = tk.Listbox(
            list_frame,
            font=('Segoe UI', 10),
            yscrollcommand=scrollbar.set,
            selectmode=tk.SINGLE,
            relief=tk.FLAT,
            borderwidth=0,
            bg='#0A0A0A',
            fg='#E0E0E0',
            selectbackground='#4A4A4A',
            selectforeground='#FFFFFF'
        )
        self.files_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.files_listbox.yview)
        
        download_btn = tk.Button(
            parent,
            text="⬇️ Download Selected",
            command=self.download_file,
            bg='#0984E3',
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            cursor='hand2',
            relief=tk.FLAT,
            borderwidth=0,
            pady=10
        )
        download_btn.pack(fill=tk.X, padx=12, pady=(0, 12))
        self._add_button_hover(download_btn)
    
    def setup_participants_tab(self, parent):
        """Setup participants list interface"""
        # Header
        header_frame = tk.Frame(parent, bg='#4A4A4A')
        header_frame.pack(fill=tk.X)
        
        header_label = tk.Label(
            header_frame,
            text="👥 Active Participants",
            font=('Segoe UI', 13, 'bold'),
            bg='#4A4A4A',
            fg='#FFFFFF',
            pady=15
        )
        header_label.pack()
        
        # Participant count
        self.participant_count_label = tk.Label(
            parent,
            text="0 participants",
            font=('Segoe UI', 10),
            bg='#2A2A2A',
            fg='#AAAAAA',
            pady=8
        )
        self.participant_count_label.pack(fill=tk.X, padx=12)
        
        # Separator
        separator = tk.Frame(parent, height=2, bg='#1A1A1A')
        separator.pack(fill=tk.X, padx=12, pady=8)
        
        # Scrollable participant list
        list_frame = tk.Frame(parent, bg='#2A2A2A')
        list_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        
        scrollbar = tk.Scrollbar(list_frame, bg='#1A1A1A', troughcolor='#2A2A2A')
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.participants_canvas = tk.Canvas(
            list_frame,
            bg='#2A2A2A',
            highlightthickness=0,
            yscrollcommand=scrollbar.set
        )
        self.participants_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.participants_canvas.yview)
        
        self.participants_container = tk.Frame(self.participants_canvas, bg='#2A2A2A')
        self.participants_canvas.create_window((0, 0), window=self.participants_container, anchor="nw")
        
        self.participants_container.bind(
            "<Configure>",
            lambda e: self.participants_canvas.configure(scrollregion=self.participants_canvas.bbox("all"))
        )
        
    def connect_to_server(self):
        """Connect all modules to server"""
        connection_errors = []
        
        connecting_window = tk.Toplevel(self.root)
        connecting_window.title("Connecting...")
        connecting_window.geometry("350x200")
        connecting_window.configure(bg='#1A1A1A')
        connecting_window.transient(self.root)
        connecting_window.grab_set()
        
        
        title_label = tk.Label(
            connecting_window,
            text="🔗 Connecting to Server",
            font=('Segoe UI', 14, 'bold'),
            bg='#1A1A1A',
            fg='#FFFFFF'
        )
        title_label.pack(pady=(30, 20))
        
        status_label = tk.Label(
            connecting_window,
            text="Please wait...",
            font=('Segoe UI', 11),
            bg='#1A1A1A',
            fg='#AAAAAA'
        )
        status_label.pack(expand=True)
        
        def connect_modules():
            try:
                # Connect chat
                status_label.config(text="📬 Connecting to chat...")
                connecting_window.update()
                self.chat_client = ChatClient(
                    self.server_ip,
                    self.username,
                    self.on_chat_message
                )
                if not self.chat_client.connect():
                    connection_errors.append("Chat")
                
                # Connect participants
                status_label.config(text="👥 Connecting to participants...")
                connecting_window.update()
                self.participant_client = ParticipantClient(
                    self.server_ip,
                    self.username,
                    self.on_participant_update
                )
                if not self.participant_client.connect():
                    connection_errors.append("Participants")
                
                # Connect file transfer
                status_label.config(text="📁 Connecting to file transfer...")
                connecting_window.update()
                self.file_client = FileClient(
                    self.server_ip,
                    self.username,
                    self.on_file_list_update,
                    self.on_file_progress
                )
                if not self.file_client.connect():
                    connection_errors.append("File Transfer")
                
                # Connect video
                status_label.config(text="🎥 Connecting to video...")
                connecting_window.update()
                self.video_client = VideoClient(
                    self.server_ip,
                    self.username,
                    self.on_video_frame
                )
                if not self.video_client.connect():
                    connection_errors.append("Video")
                
                # Connect audio
                status_label.config(text="🎤 Connecting to audio...")
                connecting_window.update()
                self.audio_client = AudioClient(
                    self.server_ip,
                    self.username
                )
                if not self.audio_client.connect():
                    connection_errors.append("Audio")
                
                # Connect screen share
                status_label.config(text="🖥️ Connecting to screen share...")
                connecting_window.update()
                self.screen_client = ScreenClient(
                    self.server_ip,
                    self.username,
                    self.on_screen_frame,
                    self.on_screen_notification
                )
                if not self.screen_client.connect():
                    connection_errors.append("Screen Share")
                
                connecting_window.destroy()
                
                if connection_errors:
                    error_msg = f"Failed to connect to: {', '.join(connection_errors)}\n\n"
                    error_msg += "Please check if the server is running."
                    messagebox.showwarning("Connection Issues", error_msg)
                    if len(connection_errors) >= 4:
                        self.root.quit()
                        return
                
                self.add_chat_message({
                    'type': 'system', 
                    'message': f'✨ Connected to server as {self.username}', 
                    'timestamp': datetime.now().strftime('%H:%M:%S')
                })
                
            except Exception as e:
                connecting_window.destroy()
                messagebox.showerror("Connection Error", f"Failed to connect: {e}\n\nPlease ensure the server is running.")
                self.root.quit()
        
        threading.Thread(target=connect_modules, daemon=True).start()
    
    def on_participant_update(self, participants):
        """Callback for participant updates from the server"""
        self.participants = participants

        def handle_updates():
            for username, info in participants.items():
                video_active = info.get('video_active', False)
                self.add_video_participant(username, video_active)

            for username in list(self.video_tiles.keys()):
                if username not in participants:
                    self.remove_video_participant(username)

            self.update_participant_list(participants)

        self.root.after(0, handle_updates)

    def update_participant_list(self, participants):
        """Update the participant list display"""
        self.participants = participants
        
        count = len(participants)
        self.participant_count_label.config(text=f"{count} participant{'s' if count != 1 else ''}")
        
        for widget in self.participants_container.winfo_children():
            widget.destroy()
        
        for username, info in sorted(participants.items()):
            self._create_participant_item(username, info)
    
    def _create_participant_item(self, username, info):
        """Create a participant list item"""
        is_self = (username == self.username)
        
        item_frame = tk.Frame(
            self.participants_container,
            bg='#4A4A4A' if is_self else '#1A1A1A',
            relief=tk.FLAT,
            borderwidth=0
        )
        item_frame.pack(fill=tk.X, padx=8, pady=5, ipady=8, ipadx=8)
        
        # Status indicator
        status_color = '#CCCCCC' if info['status'] == 'online' else '#666666'
        status_dot = tk.Label(
            item_frame,
            text="●",
            font=('Segoe UI', 14),
            fg=status_color,
            bg=item_frame['bg']
        )
        status_dot.pack(side=tk.LEFT, padx=(8, 10))
        
        # Username
        display_name = f"{username} (You)" if is_self else username
        name_label = tk.Label(
            item_frame,
            text=display_name,
            font=('Segoe UI', 11, 'bold' if is_self else 'normal'),
            bg=item_frame['bg'],
            fg='#FFFFFF',
            anchor='w'
        )
        name_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=8)
        
        # Joined time
        time_label = tk.Label(
            item_frame,
            text=f"🕐 {info['joined_at']}",
            font=('Segoe UI', 8),
            bg=item_frame['bg'],
            fg='#AAAAAA'
        )
        time_label.pack(side=tk.RIGHT, padx=10)
    
    def add_video_participant(self, username, video_active=False):
        """Ensure a participant has a tile and update its state."""
        tile = self.video_tiles.get(username)
        is_self = (username == self.username)

        if tile is None:
            # First-time attendees need a tile immediately even if their camera is off.
            # That way everyone can see who joined before the first frame arrives.
            if self.no_video_label.winfo_ismapped():
                self.no_video_label.grid_forget()

            tile_width = self.video_dimensions[0] + self.tile_padding[0]
            tile_height = self.video_dimensions[1] + self.tile_padding[1]

            container = tk.Frame(
                self.video_container,
                bg=self.video_theme['tile_bg'],
                relief=tk.FLAT,
                borderwidth=0,
                highlightbackground=self.video_theme['tile_border'],
                highlightthickness=1,
                width=tile_width,
                height=tile_height
            )
            container.grid_propagate(False)

            video_frame = tk.Frame(
                container,
                bg=self.video_theme['placeholder_bg'],
                width=self.video_dimensions[0],
                height=self.video_dimensions[1]
            )
            video_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 4))
            video_frame.pack_propagate(False)

            video_label = tk.Label(
                video_frame,
                bg=self.video_theme['placeholder_bg'],
                fg=self.video_theme['placeholder_fg'],
                font=('Segoe UI', 15, 'bold'),
                justify=tk.CENTER,
                anchor='center',
                wraplength=self.video_dimensions[0] - 40
            )
            video_label.pack(fill=tk.BOTH, expand=True)

            display_name = f"You ({username})" if is_self else username
            name_bg = self.video_theme['name_self'] if is_self else self.video_theme['name_peer']
            
            name_fg = '#000000' if name_bg == '#FFFFFF' else '#FFFFFF'
            name_label = tk.Label(
                container,
                text=display_name,
                bg=name_bg,
                fg=name_fg,
                font=('Segoe UI', 10, 'bold'),
                pady=10
            )
            name_label.pack(fill=tk.X, side=tk.BOTTOM)

            tile = {
                'container': container,
                'frame': video_frame,
                'video': video_label,
                'name': name_label,
                'video_active': video_active,
                'has_frame': False
            }
            self.video_tiles[username] = tile
            self._rearrange_video_grid()

        tile['video_active'] = video_active
        if not video_active and tile['has_frame']:
            tile['has_frame'] = False
            self._show_camera_off(username)
        elif not tile['has_frame']:
            if video_active:
                self._show_waiting_for_video(username)
            else:
                self._show_camera_off(username)

        return tile

    def _show_camera_off(self, username):
        tile = self.video_tiles.get(username)
        if not tile:
            return
        video_frame = tile['frame']
        video_label = tile['video']
        video_frame.config(bg=self.video_theme['placeholder_bg'])
        video_label.config(
            image='',
            text="👤\nCamera off",
            font=('Segoe UI', 15, 'bold'),
            fg=self.video_theme['placeholder_fg'],
            bg=self.video_theme['placeholder_bg'],
            wraplength=self.video_dimensions[0] - 40
        )
        video_label.image = None
        tile['has_frame'] = False

    def _show_waiting_for_video(self, username):
        tile = self.video_tiles.get(username)
        if not tile:
            return
        video_frame = tile['frame']
        video_label = tile['video']
        video_frame.config(bg=self.video_theme['placeholder_bg'])
        video_label.config(
            image='',
            text='Waiting for video…',
            font=('Segoe UI', 12, 'bold'),
            fg=self.video_theme['waiting_fg'],
            bg=self.video_theme['placeholder_bg'],
            wraplength=self.video_dimensions[0] - 40
        )
        video_label.image = None
        tile['has_frame'] = False

    def remove_video_participant(self, username):
        """Remove a video participant from the grid"""
        if username in self.video_tiles:
            tile = self.video_tiles.pop(username)

            if tile.get('video'):
                tile['video'].config(image='', text='')
                tile['video'].image = None

            if tile.get('container'):
                tile['container'].destroy()

            print(f"[GUI] Removed video participant: {username}")

            if not self.video_tiles:
                self.no_video_label.grid(row=0, column=0, columnspan=1, sticky='nsew', padx=50, pady=50)

            self._rearrange_video_grid()
            
    def toggle_microphone(self):
        """Toggle microphone on/off"""
        # Check if microphone is currently muted
        if self.mic_muted:
            # If audio streaming is not enabled, start it first
            if not self.audio_enabled:
                if self.audio_client.start_streaming():
                    self.audio_enabled = True
            
            # Unmute the microphone
            self.mic_muted = False
            self.audio_client.set_mic_mute(False)
            
            # Update button to show "Mute" option with green color
            self.mic_btn.config(text="🎤 Mic ON", bg='#27AE60')
            
            # Add system message to chat indicating microphone is unmuted
            self.add_chat_message({
                'type': 'system',
                'message': 'Microphone unmuted',
                'timestamp': datetime.now().strftime('%H:%M:%S')
            })
        else:
            # Mute the microphone
            self.mic_muted = True
            self.audio_client.set_mic_mute(True)
            
            # Update button to show "Unmute" option with red color
            self.mic_btn.config(text="🎤 MIC OFF", bg='#E74C3C')
            
            # Add system message to chat indicating microphone is muted
            self.add_chat_message({
                'type': 'system',
                'message': 'Microphone muted',
                'timestamp': datetime.now().strftime('%H:%M:%S')
            })
    
    def toggle_speaker(self):
        """Toggle speaker on/off"""
        # Check if audio is currently enabled
        if self.audio_enabled:
            # Stop audio streaming to turn off speaker
            self.audio_client.stop_streaming()
            self.audio_enabled = False
            
            # Also mute microphone when speaker is turned off
            self.mic_muted = True
            
            # Update speaker button to show "Off" state with red color
            self.speaker_btn.config(text="🔊 Off", bg='#E74C3C')
            
            # Update microphone button to disabled state with grey color
            self.mic_btn.config(text="🎤 Unmute", bg='#95A5A6')
        else:
            # Attempt to start audio streaming for speaker
            if self.audio_client.start_streaming():
                # Successfully started audio streaming
                self.audio_enabled = True
                
                # Update speaker button to show "On" state with green color
                self.speaker_btn.config(text="🔊 On", bg='#27AE60')

#---------------------video functions -----------------------------
#
#-----------------------------------------------------------------

    def toggle_video(self):
        """Toggle video streaming"""
        if not self.video_enabled:
            if self.video_client.start_streaming():
                self.video_enabled = True
                self.video_btn.config(text="🎥 Stop Camera", bg='#D63031')
                self.add_video_participant(self.username, video_active=True)
                # Broadcast that our video feed is now live so everyone swaps out placeholders.
                if self.participant_client:
                    self.participant_client.send_video_status(True)
                self.start_self_video_display()
        else:
            self.video_client.stop_streaming()
            self.video_enabled = False
            self.video_btn.config(text="🎥 Start Camera", bg='#00B894')
            self.stop_self_video_display()
            if self.participant_client:
                self.participant_client.send_video_status(False)
            tile = self.video_tiles.get(self.username)
            if tile:
                tile['has_frame'] = False
            self.add_video_participant(self.username, video_active=False)

    def display_video_frame(self, username, frame):
        """Display video frame in dynamic grid"""
        tile = self.add_video_participant(username, video_active=True)
        
        try:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb)
            img = img.resize(self.video_dimensions, Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image=img)
            
            tile['frame'].config(bg='black')
            tile['video'].config(image=photo, text='', bg='black')
            tile['video'].image = photo
            tile['has_frame'] = True
            tile['video_active'] = True
        except Exception as e:
            print(f"[GUI] Error displaying video: {e}")

    def on_video_frame(self, username, frame):

        """Callback for received video frames"""
        self.root.after(0, self.display_video_frame, username, frame)

    def start_self_video_display(self):
        """Start displaying self video feed"""
        self.updating_self_video = True
        
        def update_self_video():
            while self.updating_self_video and self.video_enabled:
                try:
                    if self.video_client.camera and self.video_client.camera.isOpened():
                        ret, frame = self.video_client.camera.read()
                        if ret:
                            frame = cv2.flip(frame, 1)
                            self.root.after(0, self.display_video_frame, self.username, frame)
                    threading.Event().wait(0.033)
                except Exception as e:
                    print(f"[GUI] Error in self video: {e}")
                    break
        
        self.self_video_thread = threading.Thread(target=update_self_video, daemon=True)
        self.self_video_thread.start()

    def stop_self_video_display(self):
        """Stop displaying self video feed"""
        self.updating_self_video = False

    def _complete_video_start(self):
        """Complete video startup after server notification"""
        # Now add self to video display
        self.add_video_participant(self.username)
        
        # Start displaying own video
        self.start_self_video_display()
        
        self.add_chat_message({
            'type': 'system',
            'message': '📹 Your video is now on',
            'timestamp': datetime.now().strftime('%H:%M:%S')
        })

    def toggle_screen_share(self):
        """Toggle screen sharing"""
        if not self.screen_sharing:
            self.screen_client.start_streaming()
            self.screen_sharing = True
            self.screen_btn.config(text="🖥️ Stop Share", bg='#D63031')
        else:
            self.screen_client.stop_streaming()
            self.screen_sharing = False
            self.screen_btn.config(text="🖥️ Share Screen", bg='#6C5CE7')
    
    def on_screen_notification(self, notification_type, presenter):
        """Handle screen share notifications"""
        if notification_type == 'denied':
            self.screen_sharing = False
            self.screen_btn.config(text="🖥️ Share Screen", bg='#6C5CE7')
            messagebox.showinfo(
                "Screen Share Unavailable",
                f"{presenter} is currently presenting.\nOnly one person can share at a time."
            )
        elif notification_type == 'started':
            self.current_presenter = presenter
            self.presenter_label.config(text=f"🖥️ {presenter} is presenting")
            self.screen_notification_bar.pack(fill=tk.X, side=tk.TOP, before=self.root.winfo_children()[1])
            
            self.add_chat_message({
                'type': 'system',
                'message': f'🖥️ {presenter} started screen sharing',
                'timestamp': datetime.now().strftime('%H:%M:%S')
            })
        elif notification_type == 'stopped':
            if self.current_presenter == presenter:
                self.current_presenter = None
                self.screen_notification_bar.pack_forget()
                self.latest_screen_frame = None
                
                if self.screen_viewer_window and self.screen_viewer_window.winfo_exists():
                    self.screen_viewer_window.destroy()
                
                self.add_chat_message({
                    'type': 'system',
                    'message': f'🖥️ {presenter} stopped screen sharing',
                    'timestamp': datetime.now().strftime('%H:%M:%S')
                })
    
    def on_screen_frame(self, username, frame):
        """Callback for received screen frames"""
        self.latest_screen_frame = frame
        
        if self.screen_viewer_window and self.screen_viewer_window.winfo_exists():
            self.root.after(0, self.update_screen_viewer, frame)
    
    def open_screen_viewer(self):
        """Open screen viewer window"""
        if self.screen_viewer_window and self.screen_viewer_window.winfo_exists():
            self.screen_viewer_window.lift()
            return
        
        if not self.current_presenter:
            return
        
        self.screen_viewer_window = tk.Toplevel(self.root)
        self.screen_viewer_window.title(f"Screen Share - {self.current_presenter}")
        self.screen_viewer_window.geometry("1280x720")
        self.screen_viewer_window.configure(bg='#000000')
        
        control_bar = tk.Frame(self.screen_viewer_window, bg='#1A1A1A', height=50)
        control_bar.pack(fill=tk.X, side=tk.TOP)
        control_bar.pack_propagate(False)
        
        username_label = tk.Label(
            control_bar,
            text=f"🖥️ {self.current_presenter}'s Screen",
            font=('Segoe UI', 13, 'bold'),
            bg='#1A1A1A',
            fg='#FFFFFF'
        )
        username_label.pack(side=tk.LEFT, padx=15)
        
        fullscreen_btn = tk.Button(
            control_bar,
            text="⛶ Fullscreen",
            command=self.toggle_viewer_fullscreen,
            bg='#6A6A6A',
            fg='#FFFFFF',
            font=('Segoe UI', 10, 'bold'),
            cursor='hand2',
            relief=tk.FLAT,
            borderwidth=0,
            padx=15,
            pady=8
        )
        fullscreen_btn.pack(side=tk.RIGHT, padx=8)
        
        close_btn = tk.Button(
            control_bar,
            text="✕ Close",
            command=lambda: self.screen_viewer_window.destroy(),
            bg='#2A2A2A',
            fg='#FFFFFF',
            font=('Segoe UI', 10, 'bold'),
            cursor='hand2',
            relief=tk.FLAT,
            borderwidth=0,
            padx=15,
            pady=8
        )
        close_btn.pack(side=tk.RIGHT, padx=8)
        
        screen_frame = tk.Frame(self.screen_viewer_window, bg='#000000')
        screen_frame.pack(fill=tk.BOTH, expand=True)
        
        self.screen_viewer_label = tk.Label(screen_frame, bg='#000000')
        self.screen_viewer_label.pack(fill=tk.BOTH, expand=True)
        
        if self.latest_screen_frame is not None:
            self.update_screen_viewer(self.latest_screen_frame)
        
        self.screen_viewer_window.bind('<Escape>', lambda e: self.screen_viewer_window.destroy())
    
    def update_screen_viewer(self, frame):
        """Update screen viewer with new frame"""
        if not self.screen_viewer_window or not self.screen_viewer_window.winfo_exists():
            return
        
        try:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb)
            
            if self.screen_viewer_window.winfo_width() > 1:
                window_width = self.screen_viewer_window.winfo_width()
                window_height = self.screen_viewer_window.winfo_height() - 50
            else:
                window_width = 1280
                window_height = 670
            
            img_width, img_height = img.size
            scale = min(window_width / img_width, window_height / img_height)
            new_width = int(img_width * scale)
            new_height = int(img_height * scale)
            
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image=img)
            
            self.screen_viewer_label.config(image=photo)
            self.screen_viewer_label.image = photo
        except Exception as e:
            print(f"[GUI] Error updating screen viewer: {e}")
    
    def toggle_viewer_fullscreen(self):
        """Toggle fullscreen mode for viewer"""
        if self.screen_viewer_window:
            current = self.screen_viewer_window.attributes('-fullscreen')
            self.screen_viewer_window.attributes('-fullscreen', not current)
    

    def send_message(self):
        """Get message from entry, send via client, and clear entry."""
        message = self.message_entry.get().strip()
        
        if message and self.chat_client and self.chat_client.connected:
            success = self.chat_client.send_message(message) 

            if success:
                self.message_entry.delete(0, tk.END)
                
            return True
        return False
            
    def upload_file(self):
        """Upload a file"""
        filepath = filedialog.askopenfilename(
            title="Select file to upload",
            filetypes=[
                ("All Files", "*.*"),
                ("PDF Files", "*.pdf"),
                ("Images", "*.png *.jpg *.jpeg *.gif *.bmp"),
                ("Documents", "*.doc *.docx *.txt *.ppt *.pptx *.xls *.xlsx"),
                ("Videos", "*.mp4 *.avi *.mkv *.mov"),
                ("Audio", "*.mp3 *.wav *.flac *.aac"),
                ("Archives", "*.zip *.rar *.7z *.tar *.gz")
            ]
        )
        if filepath and self.file_client:
            self.upload_status.config(text=" Starting upload...")
            threading.Thread(
                target=self.file_client.upload_file,
                args=(filepath,),
                daemon=True
            ).start()
            
    def download_file(self):
        """Download selected file"""
        selection = self.files_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a file to download")
            return
        
        # Extract filename (before " - ")
        selected_text = self.files_listbox.get(selection[0])
        filename = selected_text.split(' - ')[0].strip()
        
        print(f"[GUI] Downloading file: '{filename}'")
        
        save_path = filedialog.askdirectory(title="Select download location")
        
        if save_path and self.file_client:
            threading.Thread(
                target=self.file_client.download_file,
                args=(filename, save_path),
                daemon=True
            ).start()
            
        filename = self.files_listbox.get(selection[0]).split(' - ')[0]
        save_path = filedialog.askdirectory(title="Select download location")
        
        if save_path and self.file_client:
            threading.Thread(
                target=self.file_client.download_file,
                args=(filename, save_path),
                daemon=True
            ).start()

    def on_chat_message(self, message_data, is_sent=False):
        """Callback for received chat messages"""
        self.root.after(0, self.add_chat_message, message_data, is_sent)
        
    def add_chat_message(self, message_data, is_sent=False):
        """Append a message to the chat display with formatting."""
        
        timestamp = message_data.get('timestamp', datetime.now().strftime('%H:%M:%S'))
        
        self.chat_display.config(state=tk.NORMAL)
        
        if message_data['type'] == 'system':
            text = f"[{timestamp}] {message_data['message']}\n"
            self.chat_display.insert(tk.END, text, ('system',))
            
        else:
            username = message_data['username']
            message = message_data['message']
            
            if is_sent:
                text = f"[{timestamp}] (You): {message}\n"
                self.chat_display.insert(tk.END, text, ('self_message', 'time'))
            else:
                username_tag = 'self' if username == self.username else 'username'
                
                self.chat_display.insert(tk.END, f"[{timestamp}] ", 'time')
                self.chat_display.insert(tk.END, f"{username}: ", (username_tag,))
                self.chat_display.insert(tk.END, f"{message}\n", ('message',))
        
        self.chat_display.config(state=tk.DISABLED)
        self.chat_display.see(tk.END)
        
    def on_file_list_update(self, files):
        """Callback for file list updates"""
        self.root.after(0, self.update_file_list, files)
        
    def update_file_list(self, files):
        """Update files listbox"""
        self.files_listbox.delete(0, tk.END)
        
        if not files:
            self.files_listbox.insert(tk.END, "No files available")
            return
        
        for filename, info in files.items():
            size_mb = info['size'] / (1024 * 1024)
            if size_mb < 1:
                size_kb = info['size'] / 1024
                size_str = f"{size_kb:.2f} KB"
            else:
                size_str = f"{size_mb:.2f} MB"
            
            display = f"{filename} - {size_str} (by {info['uploader']})"
            self.files_listbox.insert(tk.END, display)
            
    def on_file_progress(self, status, message):
        """Callback for file transfer progress"""
        self.root.after(0, self.upload_status.config, {'text': message})
        
            
    def leave_conference(self):
        """Leave conference and cleanup"""
        if messagebox.askyesno("Leave Conference", "Are you sure you want to leave?"):
            self.cleanup()
            self.root.quit()
            
    def cleanup(self):
        """Cleanup all connections"""
        self.updating_self_video = False
        
        if self.video_enabled:
            if self.video_client:
                self.video_client.stop_streaming()
            self.video_enabled = False
            if self.participant_client:
                self.participant_client.send_video_status(False)
        
        for username in list(self.video_tiles.keys()):
            self.remove_video_participant(username)
        
        if self.video_client:
            self.video_client.disconnect()
        if self.audio_client:
            self.audio_client.disconnect()
        if self.chat_client:
            self.chat_client.disconnect()
        if self.file_client:
            self.file_client.disconnect()
        if self.screen_client:
            self.screen_client.disconnect()
        if self.participant_client:
            self.participant_client.disconnect()
        
        if self.screen_viewer_window:
            try:
                self.screen_viewer_window.destroy()
            except:
                pass
        
        print("[GUI] Cleanup completed")

    def _calculate_grid_dimensions(self):
        """Calculates the optimal number of rows and columns for a square-like grid."""
        count = len(self.video_tiles)
        if count == 0:
            return 0, 0
            
        cols = int(count**0.5)
        rows = (count + cols - 1) // cols
        
        if count == 3:
            return 2, 2
        
        if cols * rows < count:
             rows += 1
        
        if cols < rows:
            cols, rows = rows, cols
            
        return rows, cols
    
    def _rearrange_video_grid(self):
        """Clears the grid and rearranges all video participants based on new dimensions."""
        
        for widget in self.video_container.winfo_children():
            widget.grid_forget()
            
        rows, cols = self._calculate_grid_dimensions()
        
        for i in range(rows):
            self.video_container.grid_rowconfigure(i, weight=1)
        for j in range(cols):
            self.video_container.grid_columnconfigure(j, weight=1)

        if rows == 0:
            self.no_video_label.grid(row=0, column=0, columnspan=1, sticky='nsew', padx=50, pady=50)
            return

        participants_list = list(self.video_tiles.keys())
        
        for index, username in enumerate(participants_list):
            container = self.video_tiles[username]['container']
            container.grid_propagate(False)
            
            row = index // cols
            col = index % cols
            
            container.grid(row=row, column=col, sticky='nsew', padx=5, pady=5)

        if not self.video_tiles:
            self.no_video_label.grid(row=0, column=0, columnspan=1, sticky='nsew', padx=50, pady=50)

        self.root.after(100, lambda: self.video_canvas.configure(scrollregion=self.video_canvas.bbox("all")))

def main():
    """Main entry point"""
    from constants import DEFAULT_SERVER_IP
    
    login_root = tk.Tk()
    login_root.title("Chai pe Charcha - Login")
    login_root.geometry("450x550")
    login_root.configure(bg='#000000')
    
    frame = tk.Frame(login_root, bg='#1A1A1A')
    frame.place(relx=0.5, rely=0.5, anchor='center', width=380, height=480)
    
    # Logo/Title
    tk.Label(
        frame, 
        text="☕", 
        font=('Segoe UI', 60), 
        bg='#1A1A1A', 
        fg='#FFFFFF'
    ).pack(pady=(40, 10))
    
    tk.Label(
        frame, 
        text="Chai pe Charcha", 
        font=('Segoe UI', 24, 'bold'), 
        bg='#1A1A1A', 
        fg='#FFFFFF'
    ).pack(pady=(0, 5))
    
    tk.Label(
        frame, 
        text="Connect, Collaborate, Communicate", 
        font=('Segoe UI', 10), 
        bg='#1A1A1A', 
        fg='#AAAAAA'
    ).pack(pady=(0, 40))
    
    # Server IP
    tk.Label(
        frame, 
        text="Server IP Address", 
        font=('Segoe UI', 11, 'bold'), 
        bg='#1A1A1A', 
        fg='#FFFFFF',
        anchor='w'
    ).pack(fill=tk.X, padx=30, pady=(0, 5))
    
    server_entry = tk.Entry(
        frame, 
        font=('Segoe UI', 12), 
        width=30,
        relief=tk.FLAT,
        bg='#2A2A2A',
        fg='#FFFFFF',
        insertbackground='#FFFFFF',
        borderwidth=0
    )
    server_entry.insert(0, DEFAULT_SERVER_IP)
    server_entry.pack(padx=30, pady=(0, 20), ipady=10)
    
    # Username
    tk.Label(
        frame, 
        text="Your Name", 
        font=('Segoe UI', 11, 'bold'), 
        bg='#1A1A1A', 
        fg='#FFFFFF',
        anchor='w'
    ).pack(fill=tk.X, padx=30, pady=(0, 5))
    
    username_entry = tk.Entry(
        frame, 
        font=('Segoe UI', 12), 
        width=30,
        relief=tk.FLAT,
        bg='#2A2A2A',
        fg='#FFFFFF',
        insertbackground='#FFFFFF',
        borderwidth=0
    )
    username_entry.pack(padx=30, pady=(0, 30), ipady=10)
    
    def start_conference(event=None):
        server_ip = server_entry.get().strip()
        username = username_entry.get().strip()
        
        if not server_ip or not username:
            messagebox.showerror("Error", "Please fill all fields")
            return
            
        login_root.destroy()
        
        main_root = tk.Tk()
        app = ConferenceGUI(main_root, server_ip, username)
        main_root.protocol("WM_DELETE_WINDOW", app.leave_conference)
        main_root.mainloop()
    
    server_entry.bind('<Return>', start_conference)
    username_entry.bind('<Return>', start_conference)
    username_entry.focus()
        
    join_btn = tk.Button(
        frame,
        text="🚀 Join Conference",
        command=start_conference,
        bg='#6A6A6A',
        fg='#FFFFFF',
        font=('Segoe UI', 13, 'bold'),
        width=25,
        cursor='hand2',
        relief=tk.FLAT,
        borderwidth=0,
        pady=12
    )
    join_btn.pack(pady=(0, 20))
    
    # Hover effect for join button
    join_btn.bind('<Enter>', lambda e: join_btn.config(bg='#5A5A5A'))
    join_btn.bind('<Leave>', lambda e: join_btn.config(bg='#6A6A6A'))
    
    login_root.mainloop()

if __name__ == "__main__":
    main()