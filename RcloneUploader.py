import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox
import subprocess
import threading
import queue
import sys
import os
import re

try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_tray_image(color):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, 60, 60], fill=color)
    return img


def pick_files():
    root = tk.Tk()
    root.withdraw()
    files = filedialog.askopenfilenames(
        title="Select files to upload",
        filetypes=[("Video Files", "*.mp4 *.mkv *.avi *.mov"), ("All Files", "*.*")]
    )
    root.destroy()
    return list(files)


def ask_destination():
    root = tk.Tk()
    root.withdraw()
    folder = simpledialog.askstring(
        "Destination",
        "Folder on Cloud Volume (e.g. Pictures, Movies)\nLeave blank to upload to root:",
        parent=root
    )
    root.destroy()
    if folder is None:
        return None
    folder = folder.strip()
    return f"Cloud Volume:{folder}" if folder else "Cloud Volume:"


def ask_mode(destination):
    result = {"choice": None}
    win = tk.Tk()
    win.title("Choose Action")
    win.resizable(False, False)
    win.attributes("-topmost", True)

    tk.Label(win, text=f"Upload to:  {destination}",
             font=("Segoe UI", 10, "bold"), pady=6).pack(padx=20)
    tk.Label(win, text="Choose an action:", font=("Segoe UI", 9)).pack()

    btn_frame = tk.Frame(win)
    btn_frame.pack(pady=12, padx=20)

    def choose(val):
        result["choice"] = val
        win.destroy()

    tk.Button(btn_frame, text="COPY  (keep originals)", width=22,
              command=lambda: choose("copy")).grid(row=0, column=0, padx=5)
    tk.Button(btn_frame, text="MOVE  (delete after)", width=22,
              command=lambda: choose("move")).grid(row=0, column=1, padx=5)
    tk.Button(btn_frame, text="Cancel", width=10,
              command=lambda: choose(None)).grid(row=1, column=0, columnspan=2, pady=(6, 0))

    win.eval("tk::PlaceWindow . center")
    win.mainloop()
    return result["choice"]


def parse_rclone_progress(line):
    """
    Parse rclone --progress lines like:
      * filename.mp4: 45% /4.005Mi, 2.1Mi/s, 1s
    Returns dict or None.
    """
    m = re.search(r'(\d+)%\s*/\s*([\d.]+\s*\S+),\s*([\d.]+\s*\S+/s),?\s*([\w-]+)?', line)
    if m:
        return {
            "pct":   m.group(1) + "%",
            "size":  m.group(2).strip(),
            "speed": m.group(3).strip(),
            "eta":   (m.group(4) or "-").strip(),
        }
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  Main App
# ─────────────────────────────────────────────────────────────────────────────

class UploaderApp:
    def __init__(self, files, destination, mode):
        self.files          = files
        self.destination    = destination
        self.mode           = mode
        self.msg            = "Copied" if mode == "copy" else "Moved"
        self.q              = queue.Queue()
        self.upload_done    = False
        self.cancel_current = False
        self.current_proc   = None
        self.tray           = None

        # Maps file index → line number in the output Text widget (1-based)
        self.output_line_index = {}

        self.root = tk.Tk()
        self.root.title("Rclone Uploader")
        self.root.geometry("760x540")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self.root.after(200, self._start_upload)
        self.root.after(100, self._poll_queue)

        if TRAY_AVAILABLE:
            self._setup_tray()

        self.root.mainloop()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        pad = {"padx": 10, "pady": 3}

        tk.Label(self.root,
                 text=f"Files ({len(self.files)} total)  →  {self.destination}",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", **pad)

        # ── Per-file progress table ────────────────────────────────────────
        cols   = ("file", "pct", "speed", "size", "eta", "status")
        hdrs   = ("File",  "%",   "Speed", "Size", "ETA", "Status")
        widths = (260,      55,    90,      80,     70,    110)

        tbl_frame = tk.Frame(self.root)
        tbl_frame.pack(fill="x", padx=10)

        self.tree = ttk.Treeview(tbl_frame, columns=cols, show="headings", height=8)
        for col, hdr, w in zip(cols, hdrs, widths):
            self.tree.heading(col, text=hdr)
            self.tree.column(col, width=w,
                             anchor="center" if col != "file" else "w")

        sb = ttk.Scrollbar(tbl_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="x", expand=True)
        sb.pack(side="right", fill="y")

        self.tree.tag_configure("pending",   foreground="#888888")
        self.tree.tag_configure("uploading", foreground="#e07b00")
        self.tree.tag_configure("done",      foreground="#007700")
        self.tree.tag_configure("cancelled", foreground="#cc0000")

        self.tree_ids = []
        for f in self.files:
            iid = self.tree.insert("", "end",
                                   values=(os.path.basename(f), "", "", "", "", "Pending"),
                                   tags=("pending",))
            self.tree_ids.append(iid)

        # ── Overall progress ───────────────────────────────────────────────
        self.overall_var = tk.StringVar(value=f"Overall: 0 / {len(self.files)}")
        tk.Label(self.root, textvariable=self.overall_var,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=10, pady=(6, 0))

        self.progress = ttk.Progressbar(self.root, maximum=len(self.files),
                                        length=740, mode="determinate")
        self.progress.pack(padx=10, pady=2)

        # ── Status bar ─────────────────────────────────────────────────────
        self.status_var = tk.StringVar(value="Status: Waiting to start…")
        tk.Label(self.root, textvariable=self.status_var,
                 font=("Segoe UI", 9), fg="navy").pack(anchor="w", padx=10)

        # ── Live output box (one line per file, updates in place) ──────────
        toggle_frame = tk.Frame(self.root)
        toggle_frame.pack(fill="x", padx=10, pady=(6, 0))

        self.log_visible = tk.BooleanVar(value=True)
        tk.Checkbutton(toggle_frame, text="Show live output",
                       variable=self.log_visible,
                       command=self._toggle_log,
                       font=("Segoe UI", 9, "bold")).pack(side="left")

        self.log_frame = tk.Frame(self.root)
        self.log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        self.output = tk.Text(self.log_frame, bg="#0c0c0c", fg="#00ff00",
                              font=("Consolas", 9), state="disabled",
                              wrap="none", height=8,
                              insertbackground="#00ff00")
        ys = ttk.Scrollbar(self.log_frame, orient="vertical",   command=self.output.yview)
        xs = ttk.Scrollbar(self.log_frame, orient="horizontal", command=self.output.xview)
        self.output.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.output.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        self.log_frame.rowconfigure(0, weight=1)
        self.log_frame.columnconfigure(0, weight=1)

        # colour tags for the Text widget
        self.output.tag_configure("label",     foreground="#888888")
        self.output.tag_configure("progress",  foreground="#00ff00")
        self.output.tag_configure("done_line", foreground="#32cd32")
        self.output.tag_configure("cancel_ln", foreground="#ff4444")

    def _toggle_log(self):
        if self.log_visible.get():
            self.log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        else:
            self.log_frame.pack_forget()

    # ── Output helpers ────────────────────────────────────────────────────────

    def _output_init_line(self, file_index):
        """Write the initial placeholder line for a file and record its line number."""
        filename = os.path.basename(self.files[file_index])
        label    = f"File {file_index + 1:>2}  {filename:<40}"

        self.output.configure(state="normal")
        # Record which line this file occupies (line numbers are 1-based in tk)
        line_no = int(self.output.index("end-1c").split(".")[0])
        if self.output.get("1.0", "end") == "\n":
            # Widget is empty — use line 1
            line_no = 1
        else:
            line_no += 1

        self.output_line_index[file_index] = line_no
        self.output.insert("end", f"{label}  waiting…\n", ("label",))
        self.output.see("end")
        self.output.configure(state="disabled")

    def _output_update_line(self, file_index, text, tag="progress"):
        """Overwrite the progress portion of a file's line in place."""
        filename = os.path.basename(self.files[file_index])
        label    = f"File {file_index + 1:>2}  {filename:<40}  "
        full     = label + text

        line_no  = self.output_line_index.get(file_index)
        if line_no is None:
            return

        self.output.configure(state="normal")
        start = f"{line_no}.0"
        end   = f"{line_no}.end"
        self.output.delete(start, end)
        self.output.insert(start, full, (tag,))
        self.output.configure(state="disabled")

    # ── Tray ──────────────────────────────────────────────────────────────────

    def _setup_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Open Progress Window",  self._restore_window, default=True),
            pystray.MenuItem("Cancel Current File",   self._tray_cancel_current),
            pystray.MenuItem("Exit",                  self._tray_exit),
        )
        self.tray = pystray.Icon(
            "rclone_uploader",
            make_tray_image("#1e90ff"),
            "Rclone Uploader - Running",
            menu
        )
        threading.Thread(target=self.tray.run, daemon=True).start()

    def _restore_window(self, icon=None, item=None):
        self.root.after(0, self._do_restore)

    def _do_restore(self):
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()

    def _tray_cancel_current(self, icon=None, item=None):
        if self.upload_done:
            return
        self.cancel_current = True
        if self.current_proc:
            try:
                self.current_proc.kill()
            except Exception:
                pass

    def _tray_exit(self, icon=None, item=None):
        self.root.after(0, self._prompt_exit)

    def _prompt_exit(self):
        if not self.upload_done:
            if not messagebox.askyesno("Confirm Exit",
                                       "Upload still in progress. Cancel everything and exit?",
                                       parent=self.root):
                return
        self._force_quit()

    def _force_quit(self):
        self.cancel_current = True
        if self.current_proc:
            try:
                self.current_proc.kill()
            except Exception:
                pass
        if self.tray:
            self.tray.stop()
        self.root.destroy()

    def _on_close(self):
        if not self.upload_done:
            if not messagebox.askyesno("Confirm Exit",
                                       "Upload still in progress. Cancel and exit?",
                                       parent=self.root):
                return
        self._force_quit()

    def _on_minimize(self, event=None):
        if self.root.state() == "iconic":
            self.root.withdraw()
            if self.tray:
                self.tray.notify(
                    "Upload running in background. Double-click to restore.",
                    "Rclone Uploader"
                )

    # ── Upload worker ─────────────────────────────────────────────────────────

    def _start_upload(self):
        self.root.bind("<Unmap>", self._on_minimize)
        threading.Thread(target=self._upload_worker, daemon=True).start()

    def _upload_worker(self):
        completed = 0
        for i, filepath in enumerate(self.files):
            filename   = os.path.basename(filepath)
            self.q.put(("file_start", i, filename))

            cmd = [
                "rclone", self.mode,
                filepath, self.destination,
                "--progress", "--buffer-size", "1G", "--stats", "1s"
            ]

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            self.current_proc = proc

            last_speed = ""
            last_size  = ""

            for line in proc.stdout:
                parsed = parse_rclone_progress(line)
                if parsed:
                    last_speed = parsed["speed"]
                    last_size  = parsed["size"]
                    self.q.put(("file_progress", i, parsed))
                if self.cancel_current:
                    proc.kill()
                    break

            proc.wait()
            self.current_proc = None

            if self.cancel_current:
                self.cancel_current = False
                self.q.put(("file_cancelled", i))
                if i == len(self.files) - 1:
                    self.q.put(("all_done", completed))
                continue

            completed += 1
            self.q.put(("file_done", i, last_speed, last_size))

        self.q.put(("all_done", completed))

    # ── Queue polling ─────────────────────────────────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                msg  = self.q.get_nowait()
                kind = msg[0]

                if kind == "file_start":
                    _, i, filename = msg
                    # Table row
                    self.tree.item(self.tree_ids[i],
                                   values=(filename, "—", "—", "—", "—", "Uploading…"),
                                   tags=("uploading",))
                    self.tree.see(self.tree_ids[i])
                    self.status_var.set(
                        f"Status: Uploading {i+1} of {len(self.files)}…")
                    # Output box — create the line for this file
                    self._output_init_line(i)

                elif kind == "file_progress":
                    _, i, p = msg
                    filename = os.path.basename(self.files[i])
                    # Update table
                    self.tree.item(self.tree_ids[i],
                                   values=(filename,
                                           p["pct"], p["speed"],
                                           p["size"], p["eta"],
                                           "Uploading…"),
                                   tags=("uploading",))
                    # Update single line in output box
                    progress_str = (
                        f"{p['pct']:>5}   {p['speed']:>12}   "
                        f"{p['size']:>10}   ETA {p['eta']}"
                    )
                    self._output_update_line(i, progress_str, "progress")

                elif kind == "file_done":
                    _, i, speed, size = msg
                    filename = os.path.basename(self.files[i])
                    done_val = f"✓ Done  {size}  @ {speed}" if speed else "✓ Done"
                    # Table
                    self.tree.item(self.tree_ids[i],
                                   values=(filename, "100%", speed, size, "—", done_val),
                                   tags=("done",))
                    self.progress["value"] = i + 1
                    self.overall_var.set(
                        f"Overall: {i+1} / {len(self.files)}")
                    # Output line — stamp as done
                    self._output_update_line(
                        i, f"✓  Done   {size}  @ {speed}", "done_line")

                elif kind == "file_cancelled":
                    _, i = msg
                    filename = os.path.basename(self.files[i])
                    self.tree.item(self.tree_ids[i],
                                   values=(filename, "—", "—", "—", "—", "✗ Cancelled"),
                                   tags=("cancelled",))
                    self._output_update_line(i, "✗  Cancelled", "cancel_ln")

                elif kind == "all_done":
                    _, completed = msg
                    self.upload_done = True
                    self.status_var.set(
                        f"Status: Finished — {self.msg} {completed} of "
                        f"{len(self.files)} file(s) to {self.destination}"
                    )
                    if self.tray:
                        self.tray.icon  = make_tray_image("#32cd32")
                        self.tray.title = "Rclone Uploader - Done"
                    self._do_restore()

        except queue.Empty:
            pass

        self.root.after(50, self._poll_queue)


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    files = pick_files()
    if not files:
        sys.exit(0)

    destination = ask_destination()
    if destination is None:
        sys.exit(0)

    mode = ask_mode(destination)
    if mode is None:
        sys.exit(0)

    if not TRAY_AVAILABLE:
        messagebox.showwarning(
            "Optional dependency missing",
            "pystray and/or Pillow not installed — tray icon unavailable.\n\n"
            "Install with:\n  pip install pystray pillow"
        )

    UploaderApp(files, destination, mode)