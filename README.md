# RcloneMaster

A lightweight Windows toolkit for managing an rclone cloud mount — with a system tray monitor, auto game detection, and a GUI uploader.

---

## What it does

- Mounts a union cloud remote (`Cloud Volume:`) as drive `Z:` at Windows login
- Shows a system tray icon (green = running, red = stopped, orange = working)
- Automatically **stops** rclone when a game is detected (to free memory/bandwidth)
- Automatically **restarts** rclone when the game closes
- Provides a GUI uploader for sending video files to the cloud with live progress

---

## Files

### `RcloneMaster.vbs`
Silent launcher — called by Task Scheduler at login. Waits 10 seconds for the network to initialize, then starts `rclone mount` with the web GUI on `127.0.0.1:5573`. Exits immediately after launching rclone.

### `RcloneTray.py`
System tray monitor. Shows a colour-coded icon, handles start/stop/toggle via left-click or right-click menu, and runs a background loop every 5 seconds to detect games and auto-manage rclone. Replaces the old `RcloneMaster.ps1`.

### `RcloneUploader.py`
GUI upload tool. Opens a file picker, asks for a destination folder on `Cloud Volume:`, lets you choose copy or move, then uploads all selected files via rclone with a live per-file progress table and a system tray icon while running.

---

## Requirements

### rclone
Download from [rclone.org](https://rclone.org/downloads/) and add to your system `PATH`.

Your `Cloud Volume:` remote must already be configured in rclone as a union remote. The mount command in `RcloneMaster.vbs` assumes this remote exists.

### WinFsp
Required for `rclone mount` to work on Windows. Download from [winfsp.dev](https://winfsp.dev).

### Python 3.x
Download from [python.org](https://python.org). Make sure to check **"Add Python to PATH"** during install.

### Python dependencies
```
pip install pystray pillow psutil
```

---

## Setup

### 1. Configure paths
In `RcloneTray.py`, update the path to your VBS file:
```python
VBS_PATH = r"C:\Users\YOUR_USERNAME\RcloneMaster.vbs"
```

In `RcloneMaster.vbs`, confirm the mount letter and remote name match your rclone config:
```vbs
WshShell.Run "rclone mount ""Cloud Volume:"" Z: ..."
```

### 2. Task Scheduler — two tasks

#### Task 1: RcloneMount
Starts the rclone mount silently at login.

| Setting | Value |
|---|---|
| Trigger | At log on (your user) |
| Delay | 10 seconds |
| Program | `wscript.exe` |
| Arguments | `"C:\Users\YOUR_USERNAME\RcloneMaster.vbs"` |
| Run with highest privileges | Yes |
| Stop task if runs longer than | Disabled |
| AC power only | Disabled |

#### Task 2: RcloneTray
Starts the tray monitor after rclone has had time to initialize.

| Setting | Value |
|---|---|
| Trigger | At log on (your user) |
| Delay | 30 seconds |
| Program | `C:\Path\to\pythonw.exe` |
| Arguments | `"C:\Users\YOUR_USERNAME\RcloneTray.py"` |
| Run with highest privileges | Yes |
| Stop task if runs longer than | Disabled |
| If already running | Do not start a new instance |
| AC power only | Disabled |

To find your exact `pythonw.exe` path:
```
where pythonw
```

### 3. RcloneUploader
No Task Scheduler setup needed. Run it manually whenever you want to upload:
```
pythonw RcloneUploader.py
```
Or create a desktop shortcut pointing to `pythonw.exe` with `RcloneUploader.py` as the argument.

---

## Boot sequence

```
0s  — Log in
10s — RcloneMount task fires → RcloneMaster.vbs launches
20s — VBS wakes (10s internal sleep) → rclone mount + web GUI starts on port 5573
30s — RcloneTray task fires → tray icon appears (red)
35s — Auto-detect loop runs → detects rclone running → icon turns green
```

---

## Tray icon

| Colour | Meaning |
|---|---|
| 🟢 Green | Rclone is running, drive Z: is mounted |
| 🔴 Red | Rclone is stopped, drive Z: is unmounted |
| 🟠 Orange | Start/stop in progress |

**Left-click** — toggle rclone on/off  
**Right-click menu:**
- `Toggle Rclone` — start or stop
- `Start Rclone` — force start
- `Stop Rclone` — force stop
- `Exit` — quit the tray app (does not stop rclone)

---

## Game detection

Games that trigger rclone to stop when running , added by default:

- ZenlessZoneZero
- GenshinImpact
- PGR
- Endfield

To add or remove games, edit the `GAME_LIST` in `RcloneTray.py`:
```python
GAME_LIST = [
    "ZenlessZoneZero",
    "GenshinImpact",
    "PGR",
    "Endfield",
]
```
Use the process name as it appears in Task Manager (without `.exe`).

---

## Web GUI

The rclone web GUI is available at `http://127.0.0.1:5573` while rclone is running. It is started automatically by the VBS alongside the mount — no separate setup needed.

---

## Troubleshooting

**Icon stays red after boot**
The network wasn't ready in time. RcloneTray's auto-detect will retry every 5 seconds automatically. If it keeps happening, increase the internal sleep in `RcloneMaster.vbs` from `10000` to `15000`.

**Drive Z: not appearing**
Make sure WinFsp is installed. Run the rclone mount command manually in a terminal to see the exact error.

**Port 5573 already in use error**
A previous rclone instance didn't fully exit. RcloneTray waits for the port to free before restarting. If it persists, run `taskkill /f /im rclone.exe` in a terminal and toggle the tray icon.

**Uploader file dialog doesn't appear**
Run with `python` instead of `pythonw` temporarily to see any error output in the console.
