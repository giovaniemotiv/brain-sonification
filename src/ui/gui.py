"""Tkinter GUI for the Brain Sonification tool.

Provides a graphical launcher with two tabs:
  - Music mode:  pick a preset and start an immersive session.
  - Study mode:  pick a config + subject ID, calibrate, log a session.

A shared log panel shows live status output from the running mode and
LSL stream discovery results. A Start/Stop button manages the session
lifecycle on a background thread so the UI stays responsive.
"""

from __future__ import annotations

import os
import sys
import glob
import queue
import threading
import traceback
from typing import Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox


CONFIGS_DIR = "configs"
MUSIC_DIR = os.path.join(CONFIGS_DIR, "music")
STUDY_DIR = os.path.join(CONFIGS_DIR, "study")


class _StdoutRedirector:
    """File-like object that pushes writes onto a thread-safe queue."""

    def __init__(self, q: "queue.Queue[str]"):
        self._q = q

    def write(self, data: str) -> int:
        if data:
            self._q.put(data)
        return len(data)

    def flush(self) -> None:
        pass


class BrainSonificationGUI:
    """Main Tk application window."""

    POLL_MS = 80

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Brain Sonification")
        self.root.geometry("900x640")
        self.root.minsize(720, 520)

        self._log_queue: "queue.Queue[str]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._runner = None  # MusicMode or StudyMode instance
        self._running = False

        self._build_styles()
        self._build_layout()
        self._populate_presets()
        self._populate_study_configs()
        self._update_controls()
        self.root.after(self.POLL_MS, self._drain_log_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- layout ----------

    def _build_styles(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Header.TLabel", font=("TkDefaultFont", 16, "bold"))
        style.configure("Sub.TLabel", foreground="#555")
        style.configure("Status.TLabel", font=("TkDefaultFont", 10, "bold"))
        style.configure("Start.TButton", foreground="white", background="#2e7d32")
        style.configure("Stop.TButton", foreground="white", background="#c62828")

    def _build_layout(self) -> None:
        # Header
        header = ttk.Frame(self.root, padding=(16, 12))
        header.pack(fill="x")
        ttk.Label(header, text="Brain Sonification",
                  style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Convert Emotiv EEG data into real-time audio.",
            style="Sub.TLabel",
        ).pack(anchor="w")

        # Mode tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="x", padx=16, pady=(0, 8))
        self.music_frame = ttk.Frame(self.notebook, padding=12)
        self.study_frame = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.music_frame, text="Music mode")
        self.notebook.add(self.study_frame, text="Study mode")
        self.notebook.bind("<<NotebookTabChanged>>", lambda _e: self._update_controls())

        self._build_music_tab()
        self._build_study_tab()

        # Action bar
        action = ttk.Frame(self.root, padding=(16, 4))
        action.pack(fill="x")

        self.status_var = tk.StringVar(value="Idle")
        self.status_dot = tk.Canvas(action, width=14, height=14,
                                    highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 6))
        self._draw_status_dot("#888")
        ttk.Label(action, textvariable=self.status_var,
                  style="Status.TLabel").pack(side="left")

        self.stop_btn = ttk.Button(action, text="Stop", command=self._on_stop,
                                   style="Stop.TButton", state="disabled")
        self.stop_btn.pack(side="right")
        self.start_btn = ttk.Button(action, text="Start session",
                                    command=self._on_start,
                                    style="Start.TButton")
        self.start_btn.pack(side="right", padx=(0, 8))
        self.streams_btn = ttk.Button(action, text="List LSL streams",
                                      command=self._on_list_streams)
        self.streams_btn.pack(side="right", padx=(0, 8))

        # Log panel
        log_wrap = ttk.LabelFrame(self.root, text="Session log",
                                  padding=(8, 6))
        log_wrap.pack(fill="both", expand=True, padx=16, pady=(4, 12))

        self.log_text = tk.Text(log_wrap, wrap="word", height=12,
                                background="#111", foreground="#e6e6e6",
                                insertbackground="#e6e6e6",
                                font=("TkFixedFont", 10))
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll = ttk.Scrollbar(log_wrap, orient="vertical",
                                   command=self.log_text.yview)
        log_scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=log_scroll.set, state="disabled")

        btn_row = ttk.Frame(self.root, padding=(16, 0))
        btn_row.pack(fill="x", pady=(0, 12))
        ttk.Button(btn_row, text="Clear log",
                   command=self._clear_log).pack(side="right")

    def _build_music_tab(self) -> None:
        frame = self.music_frame
        ttk.Label(
            frame,
            text="Choose a preset and start. Mapping is fully automatic.",
            style="Sub.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        ttk.Label(frame, text="Preset:").grid(row=1, column=0,
                                              sticky="w", padx=(0, 8), pady=4)
        self.music_preset = tk.StringVar(value="ambient")
        self.music_preset_combo = ttk.Combobox(
            frame, textvariable=self.music_preset, state="readonly", width=28,
        )
        self.music_preset_combo.grid(row=1, column=1, sticky="w", pady=4)

        ttk.Label(frame, text="Description:").grid(row=2, column=0,
                                                   sticky="nw", padx=(0, 8), pady=4)
        self.music_desc = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.music_desc, wraplength=620,
                  foreground="#444").grid(row=2, column=1, sticky="w", pady=4)
        self.music_preset_combo.bind("<<ComboboxSelected>>",
                                     lambda _e: self._update_music_desc())

        frame.columnconfigure(1, weight=1)

    def _build_study_tab(self) -> None:
        frame = self.study_frame
        ttk.Label(
            frame,
            text="Calibrates a baseline, then records a fully-mapped session.",
            style="Sub.TLabel",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        ttk.Label(frame, text="Config:").grid(row=1, column=0,
                                              sticky="w", padx=(0, 8), pady=4)
        self.study_config = tk.StringVar(value="")
        self.study_config_combo = ttk.Combobox(
            frame, textvariable=self.study_config, width=44,
        )
        self.study_config_combo.grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(frame, text="Browse…",
                   command=self._browse_study_config).grid(
            row=1, column=2, padx=(8, 0), pady=4)

        ttk.Label(frame, text="Subject ID:").grid(row=2, column=0,
                                                  sticky="w", padx=(0, 8), pady=4)
        self.study_subject = tk.StringVar(value="S01")
        ttk.Entry(frame, textvariable=self.study_subject, width=20).grid(
            row=2, column=1, sticky="w", pady=4)

        ttk.Label(
            frame,
            text="Sessions are saved to ./sessions/ as JSONL or HDF5 plus a "
                 "snapshot of the config used.",
            foreground="#666", wraplength=620,
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))

        frame.columnconfigure(1, weight=1)

    # ---------- population ----------

    def _populate_presets(self) -> None:
        presets = sorted(
            os.path.splitext(os.path.basename(p))[0]
            for p in glob.glob(os.path.join(MUSIC_DIR, "*.yaml"))
        )
        if not presets:
            presets = ["ambient"]
        self.music_preset_combo["values"] = presets
        if self.music_preset.get() not in presets:
            self.music_preset.set(presets[0])
        self._update_music_desc()

    def _populate_study_configs(self) -> None:
        configs = sorted(glob.glob(os.path.join(STUDY_DIR, "*.yaml")))
        self.study_config_combo["values"] = configs
        if configs and not self.study_config.get():
            self.study_config.set(configs[0])

    def _update_music_desc(self) -> None:
        name = self.music_preset.get()
        path = os.path.join(MUSIC_DIR, f"{name}.yaml")
        desc = ""
        try:
            import yaml
            with open(path, "r") as f:
                data = yaml.safe_load(f) or {}
            desc = data.get("description", "") or ""
        except Exception:
            pass
        if not desc:
            desc = f"Preset file: {path}"
        self.music_desc.set(desc)

    def _browse_study_config(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose study config",
            initialdir=STUDY_DIR if os.path.isdir(STUDY_DIR) else ".",
            filetypes=[("YAML config", "*.yaml *.yml"), ("All files", "*.*")],
        )
        if path:
            self.study_config.set(path)

    # ---------- status / log ----------

    def _draw_status_dot(self, color: str) -> None:
        self.status_dot.delete("all")
        self.status_dot.create_oval(2, 2, 12, 12, fill=color, outline="")

    def _set_status(self, text: str, color: str) -> None:
        self.status_var.set(text)
        self._draw_status_dot(color)

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        # Treat \r as line refresh for in-place status updates.
        if "\r" in text and "\n" not in text:
            last_line_start = self.log_text.index("end-1l linestart")
            self.log_text.delete(last_line_start, "end-1c")
            text = text.replace("\r", "")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _drain_log_queue(self) -> None:
        try:
            while True:
                chunk = self._log_queue.get_nowait()
                self._append_log(chunk)
        except queue.Empty:
            pass
        # If a worker finished, refresh the controls.
        if self._worker is not None and not self._worker.is_alive() and self._running:
            self._running = False
            self._runner = None
            self._worker = None
            self._set_status("Idle", "#888")
            self._update_controls()
        self.root.after(self.POLL_MS, self._drain_log_queue)

    def _update_controls(self) -> None:
        running = self._running
        state = "disabled" if running else "normal"
        self.notebook.configure()
        # Disable tab switching while running by disabling combos/entries
        for child in self.music_frame.winfo_children():
            try:
                child.configure(state=state if not isinstance(
                    child, ttk.Combobox) else ("disabled" if running else "readonly"))
            except tk.TclError:
                pass
        for child in self.study_frame.winfo_children():
            try:
                child.configure(state=state)
            except tk.TclError:
                pass
        self.start_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")
        self.streams_btn.configure(state="disabled" if running else "normal")

    # ---------- actions ----------

    def _on_list_streams(self) -> None:
        self._append_log("\n[GUI] Scanning for LSL streams (5s)…\n")
        self._set_status("Scanning streams…", "#1565c0")
        self.streams_btn.configure(state="disabled")

        def work():
            redirect = _StdoutRedirector(self._log_queue)
            old = sys.stdout
            sys.stdout = redirect
            try:
                from .cli import print_streams
                print_streams()
            except Exception:
                self._log_queue.put(traceback.format_exc())
            finally:
                sys.stdout = old
                self._log_queue.put("\n")
                self.root.after(0, lambda: (
                    self.streams_btn.configure(state="normal"),
                    self._set_status("Idle", "#888"),
                ))

        threading.Thread(target=work, daemon=True).start()

    def _on_start(self) -> None:
        tab = self.notebook.index(self.notebook.select())
        try:
            if tab == 0:
                runner = self._build_music_runner()
                label = f"Music · {self.music_preset.get()}"
            else:
                runner = self._build_study_runner()
                label = f"Study · {os.path.basename(self.study_config.get() or 'config')}"
        except Exception as exc:
            messagebox.showerror("Cannot start", str(exc))
            return

        self._runner = runner
        self._running = True
        self._set_status(f"Running — {label}", "#2e7d32")
        self._update_controls()
        self._append_log(f"\n[GUI] Starting {label}\n")

        def work():
            redirect = _StdoutRedirector(self._log_queue)
            old_out, old_err = sys.stdout, sys.stderr
            sys.stdout = redirect
            sys.stderr = redirect
            try:
                runner.start()
            except Exception:
                self._log_queue.put(traceback.format_exc())
            finally:
                sys.stdout = old_out
                sys.stderr = old_err
                self._log_queue.put("\n[GUI] Session ended.\n")

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _on_stop(self) -> None:
        if self._runner is None:
            return
        self._append_log("\n[GUI] Stopping session…\n")
        self._set_status("Stopping…", "#ef6c00")
        try:
            # Both MusicMode and StudyMode honor _running and have stop().
            self._runner._running = False
        except Exception:
            pass

    def _build_music_runner(self):
        from .cli import load_music_preset
        from ..modes.music_mode import MusicMode
        preset = self.music_preset.get().strip()
        if not preset:
            raise ValueError("Choose a preset first.")
        config = load_music_preset(preset)
        return MusicMode(config)

    def _build_study_runner(self):
        from .cli import load_config
        from ..modes.study_mode import StudyMode
        path = self.study_config.get().strip()
        if not path:
            raise ValueError("Choose a study config file first.")
        if not os.path.isfile(path):
            raise ValueError(f"Config file not found:\n{path}")
        config = load_config(path)
        subject = self.study_subject.get().strip()
        return StudyMode(config, subject_id=subject)

    def _on_close(self) -> None:
        if self._running and self._runner is not None:
            if not messagebox.askyesno(
                "Quit?",
                "A session is still running. Stop it and quit?",
            ):
                return
            try:
                self._runner._running = False
            except Exception:
                pass
        self.root.after(150, self.root.destroy)


def launch() -> None:
    """Entry point used by ``python main.py --gui``."""
    root = tk.Tk()
    BrainSonificationGUI(root)
    root.mainloop()


if __name__ == "__main__":
    launch()
