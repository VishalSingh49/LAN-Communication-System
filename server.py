"""Main server application with GUI console and logging.

Task summary:
- Bootstrap each standalone server module (chat, files, audio, video, screen share, participants).
- Present an operator GUI that exposes module status, real-time logs, and the active LAN IP.
- Handle safe startup, shutdown, and rollback so dependent modules never remain in a half-started state.
"""

import socket
import sys
import threading
import time
from queue import Queue

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

from server_modules.chat_module import ChatServer
from server_modules.file_module import FileServer
from server_modules.video_module import VideoServer
from server_modules.audio_module import AudioServer
from server_modules.screen_module import ScreenServer
from server_modules.participant_module import ParticipantServer


class MainServer:
    """Coordinates startup and shutdown of all server modules."""

    def __init__(self):
        self.chat_server = ChatServer()
        self.file_server = FileServer()
        self.video_server = VideoServer()
        self.audio_server = AudioServer()
        self.screen_server = ScreenServer()
        self.participant_server = ParticipantServer()

        self.modules = [
            ("Chat Service", self.chat_server),
            ("File Transfer Service", self.file_server),
            ("Video Service", self.video_server),
            ("Audio Service", self.audio_server),
            ("Screen Share Service", self.screen_server),
            ("Participant Service", self.participant_server),
        ]

        self.module_states = {name: "stopped" for name, _ in self.modules}
        self.active_modules = []
        self.running = False
        self._log_callback = None
        self._status_callback = None
        self._lock = threading.Lock()

    def set_log_callback(self, callback):
        """Register a callback that receives log output."""
        self._log_callback = callback

    def set_status_callback(self, callback):
        """Register a callback that mirrors module status changes."""
        self._status_callback = callback

    def _log(self, message):
        """Emit a log message via the registered callback or stdout."""
        callback = self._log_callback or print
        callback(message)

    def _update_status(self, name, status):
        """Update internal status tracking and notify the GUI."""
        self.module_states[name] = status
        if self._status_callback:
            self._status_callback(name, status)

    def _stop_modules_list(self, modules):
        """Stop the provided modules in reverse order, updating status along the way."""
        for name, module in reversed(modules):
            self._update_status(name, "stopping")
            self._log(f"- Stopping {name}...")
            try:
                module.stop()
            except Exception as exc:  # pragma: no cover - defensive
                self._log(f"    Error stopping {name}: {exc}")
            finally:
                self._update_status(name, "stopped")

    def start_modules(self):
        """Spin up every server module and roll back safely if a failure occurs."""
        with self._lock:
            if self.running:
                self._log("  Server is already running.")
                return

            self._log("=" * 60)
            self._log("Chai pe Charcha - Server Console")
            self._log("=" * 60)

            started = []

            try:
                total = len(self.modules)
                for index, (name, module) in enumerate(self.modules, start=1):
                    self._update_status(name, "starting")
                    self._log(f"[{index}/{total}] Starting {name}...")
                    result = module.start()
                    if result is False:
                        raise RuntimeError(f"{name} reported startup failure")
                    self._update_status(name, "running")
                    self._log(f"   ✓ {name} online")
                    started.append((name, module))

                self.active_modules = started
                self.running = True

                self._log("-" * 60)
                self._log(" All services are up and listening")
                self._log("Services: Chat, Files, Video, Audio, Screen Share, Participants")
                self._log("Press Stop to shut the server down safely.")
                self._log("=" * 60)

            except Exception as exc:  # pragma: no cover - defensive
                self._log(f" Startup error: {exc}")
                self._update_status(name, "error")
                if started:
                    self._log("Rolling back previously started services...")
                    self._stop_modules_list(started)
                self.active_modules = []
                self.running = False
                raise

    def stop_modules(self):
        """Shut down all active modules and clear tracking state."""
        with self._lock:
            if not self.running and not self.active_modules:
                return

            self._log("\nStopping server services...")
            self._stop_modules_list(self.active_modules)
            self.active_modules.clear()
            self.running = False
            self._log(" Server shutdown complete.")

    def start(self):
        """Run the server in CLI mode until interrupted."""
        try:
            self.start_modules()
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self._log("\nKeyboard interrupt received. Shutting down...")
            self.stop_modules()
        except Exception as exc:
            self._log(f"\nFatal server error: {exc}")
            self.stop_modules()
            sys.exit(1)

    def stop(self):
        """Public helper that shuts down every module."""
        self.stop_modules()


def get_local_ips():
    """Return the primary IPv4 address for the current host."""
    primary_ip = "127.0.0.1"

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            primary_ip = probe.getsockname()[0]
    except Exception:
        pass

    if primary_ip.startswith("127.") or primary_ip.startswith("169.254"):
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                candidate = info[4][0]
                if not candidate.startswith(("127.", "169.254")):
                    primary_ip = candidate
                    break
        except Exception:
            pass

    return [primary_ip]


class StreamRedirect:
    """Redirect stdout/stderr into a callback while preserving console output."""

    def __init__(self, callback, original_stream):
        self.callback = callback
        self.original_stream = original_stream

    def write(self, message):
        if self.original_stream:
            self.original_stream.write(message)
        if message:
            self.callback(message)

    def flush(self):
        if self.original_stream:
            self.original_stream.flush()


class ServerGUI:
    """Interactive Tkinter console for supervising the modular server."""

    def __init__(self, root):
        """Set up widgets, stream redirects, and periodic polling."""
        self.root = root
        self.root.title("Chai pe Charcha - Server Console")
        self.root.geometry("960x640")
        self.root.configure(bg="#000000")

        self.server = MainServer()
        self.server.set_log_callback(self.enqueue_log)
        self.server.set_status_callback(self.handle_status_update)

        self.log_queue = Queue()
        self.status_labels = {}
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self.stdout_redirect = None
        self.stderr_redirect = None

        self._build_ui()
        self._redirect_streams()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.poll_log_queue)

    def _build_ui(self):
        """Create the header, control buttons, status list, and log console."""
        header = tk.Frame(self.root, bg="#1A1A1A", height=80)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        title = tk.Label(
            header,
            text="Chai pe Charcha",
            font=("Segoe UI", 22, "bold"),
            bg="#1A1A1A",
            fg="#FFFFFF",
        )
        title.pack(side=tk.LEFT, padx=25)

        subtitle = tk.Label(
            header,
            text="Server Control Center",
            font=("Segoe UI", 12),
            bg="#1A1A1A",
            fg="#AAAAAA",
        )
        subtitle.pack(side=tk.LEFT, padx=10, pady=12)

        ip_frame = tk.Frame(self.root, bg="#000000")
        ip_frame.pack(fill=tk.X, padx=20, pady=(15, 5))

        tk.Label(
            ip_frame,
            text="Local IPs",
            font=("Segoe UI", 12, "bold"),
            bg="#000000",
            fg="#CCCCCC",
        ).pack(anchor="w")

        ips = get_local_ips()
        ip_text = f"Current IP: {ips[0]}"
        self.ip_label = tk.Label(
            ip_frame,
            text=ip_text,
            font=("Consolas", 11),
            bg="#000000",
            fg="#FFFFFF",
            justify=tk.LEFT,
        )
        self.ip_label.pack(anchor="w", pady=(4, 0))

        control_frame = tk.Frame(self.root, bg="#000000")
        control_frame.pack(fill=tk.X, padx=20, pady=(5, 15))

        self.start_btn = tk.Button(
            control_frame,
            text="▶ Start Server",
            command=self.start_server,
            font=("Segoe UI", 11, "bold"),
            bg="#6A6A6A",
            fg="#FFFFFF",
            activebackground="#5A5A5A",
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            padx=18,
            pady=10,
            cursor="hand2",
        )
        self.start_btn.pack(side=tk.LEFT)

        self.stop_btn = tk.Button(
            control_frame,
            text="■ Stop Server",
            command=self.stop_server,
            font=("Segoe UI", 11, "bold"),
            bg="#2A2A2A",
            fg="#FFFFFF",
            activebackground="#1A1A1A",
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            padx=18,
            pady=10,
            cursor="hand2",
            state=tk.DISABLED,
        )
        self.stop_btn.pack(side=tk.LEFT, padx=(12, 0))

        status_card = tk.LabelFrame(
            self.root,
            text="Service Status",
            font=("Segoe UI", 11, "bold"),
            bg="#000000",
            fg="#CCCCCC",
            bd=0,
            labelanchor="nw",
        )
        status_card.pack(fill=tk.X, padx=20, pady=10)

        for name, _ in self.server.modules:
            row = tk.Frame(status_card, bg="#000000")
            row.pack(fill=tk.X, pady=3)

            label = tk.Label(
                row,
                text=name,
                font=("Segoe UI", 10, "bold"),
                bg="#000000",
                fg="#FFFFFF",
            )
            label.pack(side=tk.LEFT)

            status = tk.Label(
                row,
                text="Stopped",
                font=("Segoe UI", 10, "bold"),
                bg="#2A2A2A",
                fg="#888888",
                padx=10,
                pady=4,
            )
            status.pack(side=tk.RIGHT)
            self.status_labels[name] = status

        log_frame = tk.Frame(self.root, bg="#000000")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(5, 20))

        tk.Label(
            log_frame,
            text="Server Logs",
            font=("Segoe UI", 12, "bold"),
            bg="#000000",
            fg="#CCCCCC",
        ).pack(anchor="w", pady=(0, 6))

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            bg="#0A0A0A",
            fg="#E0E0E0",
            insertbackground="#E0E0E0",
            font=("Consolas", 10),
            wrap=tk.WORD,
            relief=tk.FLAT,
            height=15,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.config(state=tk.DISABLED)

    def _redirect_streams(self):
        """Pipe stdout/stderr into the GUI while preserving terminal output."""
        self.stdout_redirect = StreamRedirect(self.enqueue_log, self.original_stdout)
        self.stderr_redirect = StreamRedirect(self.enqueue_log, self.original_stderr)
        sys.stdout = self.stdout_redirect
        sys.stderr = self.stderr_redirect

    def enqueue_log(self, message):
        """Queue a log message for the text widget."""
        self.log_queue.put(message)

    def poll_log_queue(self):
        """Drain the log queue and append entries into the scrolled text."""
        while not self.log_queue.empty():
            message = self.log_queue.get()
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, message)
            self.log_text.config(state=tk.DISABLED)
            self.log_text.see(tk.END)
        self.root.after(100, self.poll_log_queue)

    def handle_status_update(self, name, status):
        """Schedule a thread-safe status update for the UI."""
        self.root.after(0, self._apply_status_update, name, status)

    def _apply_status_update(self, name, status):
        """Update the status badge for a specific module."""
        label = self.status_labels.get(name)
        if not label:
            return

        palette = {
            "stopped": ("Stopped", "#2A2A2A", "#888888"),
            "starting": ("Starting", "#4A4A4A", "#CCCCCC"),
            "running": ("Running", "#6A6A6A", "#FFFFFF"),
            "stopping": ("Stopping", "#3A3A3A", "#AAAAAA"),
            "error": ("Error", "#2A2A2A", "#999999"),
        }

        text, bg, fg = palette.get(status, (status.title(), "#2A2A2A", "#E0E0E0"))
        label.config(text=text, bg=bg, fg=fg)

    def start_server(self):
        """Launch the server startup routine asynchronously."""
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.DISABLED)

        def worker():
            try:
                self.server.start_modules()
                self.root.after(0, lambda: self.stop_btn.config(state=tk.NORMAL))
            except Exception as exc:  # pragma: no cover - defensive
                self.root.after(0, lambda: self._handle_start_error(exc))
            finally:
                if not self.server.running:
                    self.root.after(0, lambda: self.start_btn.config(state=tk.NORMAL))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_start_error(self, exc):
        """Inform the operator when a module fails to start."""
        messagebox.showerror("Server Error", f"Failed to start server: {exc}")
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)

    def stop_server(self):
        """Shut down running services on a background thread."""
        self.stop_btn.config(state=tk.DISABLED)

        def worker():
            try:
                self.server.stop_modules()
            finally:
                self.root.after(0, lambda: self.start_btn.config(state=tk.NORMAL))

        threading.Thread(target=worker, daemon=True).start()

    def on_close(self):
        """Prompt for confirmation and restore streams before exit."""
        if self.server.running:
            if not messagebox.askyesno("Confirm Exit", "Server is running. Stop it and exit?"):
                return
            self.server.stop_modules()

        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr
        self.root.destroy()


if __name__ == "__main__":
    if "--no-gui" in sys.argv or "--cli" in sys.argv:
        server = MainServer()
        server.start()
    else:
        tk_root = tk.Tk()
        gui = ServerGUI(tk_root)
        tk_root.mainloop()