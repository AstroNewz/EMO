"""
brain/computer_control.py — EMO Computer Control Module (Windows)

Gives EMO full control over the Windows laptop:
- Open any installed app by name
- List, focus, and close windows
- Click, type, scroll, press keyboard shortcuts
- Take screenshots (returned as base64 PNG)
- WhatsApp Desktop / WhatsApp Web automation

Dependencies: pyautogui, pygetwindow, psutil, pillow (PIL)
Install: pip install pyautogui pygetwindow
"""

import os
import re
import sys
import time
import glob
import base64
import subprocess
import webbrowser
from pathlib import Path
from io import BytesIO

# ── Lazy imports (installed separately) ────────────────────────────────────
def _get_pyautogui():
    try:
        import pyautogui
        pyautogui.FAILSAFE = False  # Safe: EMO is the controller, not a user accident
        pyautogui.PAUSE = 0.03
        return pyautogui
    except ImportError:
        raise RuntimeError("pyautogui not installed. Run: pip install pyautogui")

def _get_gw():
    try:
        import pygetwindow as gw
        return gw
    except ImportError:
        raise RuntimeError("pygetwindow not installed. Run: pip install pygetwindow")

# ── Known app aliases ────────────────────────────────────────────────────────
_APP_ALIASES = {
    # Browsers
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "firefox": "firefox.exe",
    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",
    "brave": "brave.exe",
    "opera": "opera.exe",

    # Communication
    "whatsapp": "WhatsApp.exe",
    "telegram": "Telegram.exe",
    "discord": "Discord.exe",
    "slack": "slack.exe",
    "teams": "Teams.exe",
    "microsoft teams": "Teams.exe",
    "zoom": "Zoom.exe",
    "skype": "Skype.exe",

    # Productivity
    "notepad": "notepad.exe",
    "notepad++": "notepad++.exe",
    "word": "WINWORD.EXE",
    "excel": "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE",
    "outlook": "OUTLOOK.EXE",
    "onenote": "ONENOTE.EXE",
    "calculator": "calc.exe",
    "paint": "mspaint.exe",

    # Dev tools
    "vscode": "Code.exe",
    "vs code": "Code.exe",
    "visual studio code": "Code.exe",
    "pycharm": "pycharm64.exe",
    "android studio": "studio64.exe",
    "terminal": "wt.exe",
    "windows terminal": "wt.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "git bash": "git-bash.exe",

    # Media & Entertainment
    "spotify": "Spotify.exe",
    "vlc": "vlc.exe",
    "media player": "wmplayer.exe",
    "photos": "ms-photos:",
    "movies": "mswindowsvideo:",

    # System
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "task manager": "taskmgr.exe",
    "control panel": "control.exe",
    "settings": "ms-settings:",
    "snipping tool": "SnippingTool.exe",
    "snip": "SnippingTool.exe",

    # Games & Social
    "steam": "Steam.exe",
    "epic games": "EpicGamesLauncher.exe",
    "instagram": "instagram:",
    "twitter": "twitter:",
    "x": "twitter:",
}

# Start Menu shortcut search paths
_START_MENU_PATHS = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path("C:/ProgramData/Microsoft/Windows/Start Menu/Programs"),
]

# Common install directories
_COMMON_DIRS = [
    Path("C:/Program Files"),
    Path("C:/Program Files (x86)"),
    Path(os.environ.get("LOCALAPPDATA", "")),
    Path(os.environ.get("APPDATA", "")),
]


# ══════════════════════════════════════════════════════════════════════════════
# APP LAUNCHER
# ══════════════════════════════════════════════════════════════════════════════

def _find_exe_in_registry(name: str) -> str | None:
    """Look up exe path in Windows registry App Paths."""
    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key = winreg.OpenKey(
                    root,
                    rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}",
                )
                path, _ = winreg.QueryValueEx(key, "")
                if path and Path(path).exists():
                    return str(path)
            except OSError:
                pass
    except ImportError:
        pass
    return None


def _find_exe_in_start_menu(app_name: str) -> str | None:
    """Search Start Menu .lnk files for a matching app."""
    low = app_name.lower().replace(" ", "*")
    for base in _START_MENU_PATHS:
        if not base.exists():
            continue
        matches = list(base.rglob(f"*{low}*.lnk"))
        if not matches:
            matches = list(base.rglob(f"*{app_name.lower()}*.lnk"))
        if matches:
            return str(matches[0])
    return None


def _find_exe_in_common_dirs(exe_name: str) -> str | None:
    """Recursively search common install dirs for the exe."""
    for base in _COMMON_DIRS:
        if not base.exists():
            continue
        found = list(base.rglob(exe_name))
        if found:
            return str(found[0])
    return None


def open_app(name: str) -> dict:
    """
    Open any application by name on Windows.
    Returns {"ok": True, "launched": name} or {"ok": False, "error": "..."}
    """
    low = name.strip().lower()

    # 1. Check aliases first
    exe = _APP_ALIASES.get(low)
    if not exe:
        # Try partial alias match
        for alias, path in _APP_ALIASES.items():
            if low in alias or alias in low:
                exe = path
                break

    # 2. If alias is a URI protocol (ms-settings:, ms-photos:, etc.)
    if exe and exe.endswith(":"):
        try:
            os.startfile(exe)
            return {"ok": True, "launched": name, "method": "uri"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # 3. Try running the exe directly (it may be on PATH)
    target = exe or (name if name.endswith(".exe") else f"{name}.exe")
    try:
        subprocess.Popen(
            target,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            if sys.platform == "win32" else 0,
        )
        time.sleep(0.5)
        return {"ok": True, "launched": name, "method": "shell"}
    except Exception:
        pass

    # 4. Registry lookup
    reg_path = _find_exe_in_registry(target)
    if reg_path:
        try:
            subprocess.Popen([reg_path], shell=False)
            return {"ok": True, "launched": name, "method": "registry"}
        except Exception:
            pass

    # 5. Start Menu shortcut
    lnk = _find_exe_in_start_menu(low)
    if lnk:
        try:
            os.startfile(lnk)
            return {"ok": True, "launched": name, "method": "start_menu"}
        except Exception:
            pass

    # 6. Scan common directories
    exe_in_dirs = _find_exe_in_common_dirs(target)
    if exe_in_dirs:
        try:
            subprocess.Popen([exe_in_dirs])
            return {"ok": True, "launched": name, "method": "filesystem"}
        except Exception:
            pass

    # 7. Last resort: os.startfile with name
    try:
        os.startfile(name)
        return {"ok": True, "launched": name, "method": "startfile"}
    except Exception as e:
        return {"ok": False, "error": f"Could not find or open '{name}': {e}"}


# ══════════════════════════════════════════════════════════════════════════════
# WINDOW MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

def list_open_windows() -> list[str]:
    """Return titles of all visible, non-empty windows."""
    try:
        gw = _get_gw()
        return [w.title for w in gw.getAllWindows() if w.title.strip()]
    except Exception:
        return []


def focus_window(title_fragment: str) -> dict:
    """Bring a window to front by partial title match."""
    try:
        gw = _get_gw()
        matches = gw.getWindowsWithTitle(title_fragment)
        if not matches:
            # Fuzzy: search all windows
            low = title_fragment.lower()
            matches = [w for w in gw.getAllWindows() if low in w.title.lower()]
        if not matches:
            return {"ok": False, "error": f"No window matching '{title_fragment}'"}
        win = matches[0]
        win.activate()
        time.sleep(0.3)
        return {"ok": True, "focused": win.title}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def close_window(title_fragment: str) -> dict:
    """Close a window by partial title match."""
    try:
        gw = _get_gw()
        low = title_fragment.lower()
        matches = [w for w in gw.getAllWindows() if low in w.title.lower()]
        if not matches:
            return {"ok": False, "error": f"No window matching '{title_fragment}'"}
        win = matches[0]
        win.close()
        return {"ok": True, "closed": win.title}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def minimize_window(title_fragment: str) -> dict:
    """Minimise a window."""
    try:
        gw = _get_gw()
        low = title_fragment.lower()
        matches = [w for w in gw.getAllWindows() if low in w.title.lower()]
        if not matches:
            return {"ok": False, "error": f"No window matching '{title_fragment}'"}
        matches[0].minimize()
        return {"ok": True, "minimized": matches[0].title}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# MOUSE & KEYBOARD CONTROL
# ══════════════════════════════════════════════════════════════════════════════

def click(x: int, y: int, button: str = "left") -> dict:
    """Click at screen coordinates."""
    try:
        pag = _get_pyautogui()
        pag.click(x, y, button=button)
        return {"ok": True, "clicked": [x, y]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def double_click(x: int, y: int) -> dict:
    """Double-click at screen coordinates."""
    try:
        pag = _get_pyautogui()
        pag.doubleClick(x, y)
        return {"ok": True, "double_clicked": [x, y]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def right_click(x: int, y: int) -> dict:
    """Right-click at screen coordinates."""
    try:
        pag = _get_pyautogui()
        pag.rightClick(x, y)
        return {"ok": True, "right_clicked": [x, y]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def type_text(text: str, interval: float = 0.03) -> dict:
    """Type text into the currently focused window."""
    try:
        pag = _get_pyautogui()
        time.sleep(0.2)
        pag.typewrite(text, interval=interval)
        return {"ok": True, "typed": text}
    except Exception as e:
        # Fallback: pyperclip paste
        try:
            import pyperclip
            pyperclip.copy(text)
            pag.hotkey("ctrl", "v")
            return {"ok": True, "typed": text, "method": "clipboard"}
        except Exception:
            return {"ok": False, "error": str(e)}


def press_key(key: str) -> dict:
    """
    Press a key or key combination.
    Examples: 'enter', 'escape', 'ctrl+s', 'ctrl+alt+del', 'win+d'
    """
    try:
        pag = _get_pyautogui()
        # Normalise
        key = key.strip().lower().replace(" ", "").replace("windows", "win")
        if "+" in key:
            keys = key.split("+")
            pag.hotkey(*keys)
        else:
            pag.press(key)
        return {"ok": True, "pressed": key}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def scroll(direction: str = "down", amount: int = 3) -> dict:
    """Scroll in the given direction. direction: up/down/left/right."""
    try:
        pag = _get_pyautogui()
        low = direction.lower()
        if low in ("up", "down"):
            clicks = amount if low == "up" else -amount
            pag.scroll(clicks)
        elif low in ("left", "right"):
            clicks = amount if low == "right" else -amount
            pag.hscroll(clicks)
        return {"ok": True, "scrolled": direction, "amount": amount}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def move_mouse(x: int, y: int) -> dict:
    """Move the mouse cursor to given coordinates."""
    try:
        pag = _get_pyautogui()
        pag.moveTo(x, y, duration=0.2)
        return {"ok": True, "moved_to": [x, y]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# SCREENSHOT
# ══════════════════════════════════════════════════════════════════════════════

def take_screenshot() -> dict:
    """
    Take a full-screen screenshot.
    Returns {"ok": True, "image_b64": "<base64 PNG>", "width": ..., "height": ...}
    Tries mss → pyautogui → PowerShell .NET CopyFromScreen.
    """
    import tempfile

    # Method 1: mss
    try:
        import mss
        from PIL import Image
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            raw = sct.grab(monitor)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            buf = BytesIO()
            img.save(buf, format="PNG", optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            return {"ok": True, "image_b64": b64, "width": img.width, "height": img.height}
    except Exception:
        pass

    # Method 2: pyautogui
    try:
        pag = _get_pyautogui()
        img = pag.screenshot()
        buf = BytesIO()
        img.save(buf, format="PNG", optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return {"ok": True, "image_b64": b64, "width": img.width, "height": img.height}
    except Exception:
        pass

    # Method 3: PowerShell CopyFromScreen (.NET) — works in non-interactive sessions
    try:
        tmp = Path(tempfile.gettempdir()) / "emo_screenshot.png"
        ps_script = (
            r"Add-Type -AssemblyName System.Windows.Forms; "
            r"Add-Type -AssemblyName System.Drawing; "
            r"$s = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
            r"$bmp = New-Object System.Drawing.Bitmap $s.Width, $s.Height; "
            r"$g = [System.Drawing.Graphics]::FromImage($bmp); "
            r"$g.CopyFromScreen($s.Location, [System.Drawing.Point]::Empty, $s.Size); "
            rf"$bmp.Save('{str(tmp).replace(chr(92), '/')}', [System.Drawing.Imaging.ImageFormat]::Png);"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, timeout=10
        )
        if tmp.exists():
            from PIL import Image
            img = Image.open(tmp)
            buf = BytesIO()
            img.save(buf, format="PNG", optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            tmp.unlink(missing_ok=True)
            return {"ok": True, "image_b64": b64, "width": img.width, "height": img.height,
                    "method": "powershell"}
    except Exception as e3:
        return {"ok": False, "error": f"All screenshot methods failed. Last: {e3}"}

    return {"ok": False, "error": "All screenshot methods failed."}


def get_screen_size() -> dict:
    """Return the current screen resolution."""
    try:
        pag = _get_pyautogui()
        w, h = pag.size()
        return {"ok": True, "width": w, "height": h}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# WHATSAPP ON LAPTOP
# ══════════════════════════════════════════════════════════════════════════════

def _whatsapp_desktop_path() -> str | None:
    """Find WhatsApp Desktop exe on this machine."""
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "WhatsApp" / "WhatsApp.exe",
        Path(os.environ.get("APPDATA", "")) / "WhatsApp" / "WhatsApp.exe",
        Path("C:/Program Files/WindowsApps").glob("*WhatsApp*"),
    ]
    for c in candidates:
        if isinstance(c, Path) and c.exists():
            return str(c)
    return None


def whatsapp_send_laptop(contact: str, message: str) -> dict:
    """
    Send a WhatsApp message on the laptop.
    Strategy:
      1. WhatsApp Desktop — if installed, open it, search contact, send.
      2. WhatsApp Web — open in browser, instruct user to scan QR if needed.
    Returns {"ok": True, "method": "desktop"|"web", ...}
    """
    pag = _get_pyautogui()
    wa_path = _whatsapp_desktop_path()

    if wa_path:
        # ── WhatsApp Desktop ──
        try:
            # Launch or focus WhatsApp
            subprocess.Popen([wa_path])
            time.sleep(3)  # wait for app to load

            # Focus WhatsApp window
            result = focus_window("WhatsApp")
            if not result["ok"]:
                return {"ok": False, "error": "Could not focus WhatsApp Desktop"}

            time.sleep(1)

            # Press Ctrl+F to open search / new chat search
            pag.hotkey("ctrl", "f")
            time.sleep(0.5)

            # Type the contact name
            pag.typewrite(contact, interval=0.05)
            time.sleep(1.5)

            # Press Enter to open the first result
            pag.press("enter")
            time.sleep(0.8)

            # Type the message
            pag.typewrite(message, interval=0.04)
            time.sleep(0.3)

            # Press Enter to send
            pag.press("enter")
            time.sleep(0.5)

            return {"ok": True, "method": "desktop", "contact": contact, "message": message}
        except Exception as e:
            return {"ok": False, "method": "desktop", "error": str(e)}

    else:
        # ── WhatsApp Web fallback ──
        from brain.whatsapp import lookup_phone, build_whatsapp_url
        phone = lookup_phone(contact)
        if phone:
            url = build_whatsapp_url(phone, message)
            webbrowser.open(url)
            return {
                "ok": True,
                "method": "web",
                "contact": contact,
                "message": message,
                "url": url,
                "note": "WhatsApp Web opened in browser. Scan QR code if not already logged in.",
            }
        else:
            return {
                "ok": False,
                "method": "web",
                "error": f"No phone number saved for '{contact}'. Add it via EMO: 'save {contact} as +91...'",
            }


# ══════════════════════════════════════════════════════════════════════════════
# NLU — INTENT DETECTION
# ══════════════════════════════════════════════════════════════════════════════

# Open / launch patterns
_OPEN_RE = re.compile(
    r"^(?:open|launch|start|run|fire up|pull up|bring up|load)\s+(?P<app>.+)$",
    re.IGNORECASE,
)

# Focus / switch patterns
_FOCUS_RE = re.compile(
    r"^(?:switch to|go to|focus|show|bring up|activate)\s+(?P<window>.+)$",
    re.IGNORECASE,
)

# Close patterns
_CLOSE_RE = re.compile(
    r"^(?:close|quit|exit|kill|shut down)\s+(?P<window>.+)$",
    re.IGNORECASE,
)

# Type patterns
_TYPE_RE = re.compile(
    r"^(?:type|write|input|enter)\s+(?:the text\s+|this\s+|in\s+notepad[:\s]+)?(?P<text>.+)$",
    re.IGNORECASE,
)

# Press key patterns
_KEY_RE = re.compile(
    r"^(?:press|hit|tap|hold)\s+(?P<key>(?:ctrl|alt|shift|win|windows|cmd)[\+\w]*|\w+)$",
    re.IGNORECASE,
)

# Screenshot
_SCREENSHOT_RE = re.compile(
    r"(?:take a screenshot|screenshot|screen grab|what(?:'s| is) on (?:my |the )?screen|capture screen)",
    re.IGNORECASE,
)

# Scroll
_SCROLL_RE = re.compile(
    r"^(?:scroll)\s+(?P<direction>up|down|left|right)(?:\s+(?P<amount>\d+))?$",
    re.IGNORECASE,
)

# Minimise
_MIN_RE = re.compile(
    r"^(?:minimise|minimize|hide)\s+(?P<window>.+)$",
    re.IGNORECASE,
)

# List windows
_LIST_WIN_RE = re.compile(
    r"^(?:what(?:'s| is) open|list (?:open )?(?:apps|windows)|show (?:open )?windows)$",
    re.IGNORECASE,
)


def is_control_command(text: str) -> bool:
    """Return True if text is a computer control command."""
    t = text.strip()
    return bool(
        _OPEN_RE.match(t)
        or _FOCUS_RE.match(t)
        or _CLOSE_RE.match(t)
        or _TYPE_RE.match(t)
        or _KEY_RE.match(t)
        or _SCREENSHOT_RE.search(t)
        or _SCROLL_RE.match(t)
        or _MIN_RE.match(t)
        or _LIST_WIN_RE.match(t)
    )


def parse_and_execute(text: str) -> dict:
    """
    Parse a control command from natural language and execute it.
    Returns a result dict with at least {"ok": bool, "reply": str, ...}
    """
    t = text.strip()

    # Screenshot
    if _SCREENSHOT_RE.search(t):
        result = take_screenshot()
        if result["ok"]:
            return {**result, "reply": "Screenshot taken, Boss!", "action_type": "screenshot"}
        return {**result, "reply": f"Screenshot failed: {result.get('error')}"}

    # List open windows
    if _LIST_WIN_RE.match(t):
        wins = list_open_windows()
        reply = "Open windows: " + ", ".join(wins[:10]) if wins else "No windows open."
        return {"ok": True, "windows": wins, "reply": reply, "action_type": "list_windows"}

    # Open app
    m = _OPEN_RE.match(t)
    if m:
        app = m.group("app").strip()
        result = open_app(app)
        if result["ok"]:
            return {**result, "reply": f"Opening {app} now, Boss!", "action_type": "open_app"}
        return {**result, "reply": f"Couldn't find '{app}', Boss. Is it installed?"}

    # Focus window
    m = _FOCUS_RE.match(t)
    if m:
        win = m.group("window").strip()
        result = focus_window(win)
        if result["ok"]:
            return {**result, "reply": f"Switched to {result['focused']}, Boss!", "action_type": "focus_window"}
        return {**result, "reply": f"No window named '{win}' found, Boss."}

    # Close window
    m = _CLOSE_RE.match(t)
    if m:
        win = m.group("window").strip()
        result = close_window(win)
        if result["ok"]:
            return {**result, "reply": f"Closed {result['closed']}, Boss!", "action_type": "close_window"}
        return {**result, "reply": f"Couldn't find '{win}' to close, Boss."}

    # Minimise
    m = _MIN_RE.match(t)
    if m:
        win = m.group("window").strip()
        result = minimize_window(win)
        if result["ok"]:
            return {**result, "reply": f"Minimised {result['minimized']}, Boss!", "action_type": "minimize_window"}
        return {**result, "reply": f"Couldn't find '{win}', Boss."}

    # Type text
    m = _TYPE_RE.match(t)
    if m:
        text_to_type = m.group("text").strip()
        result = type_text(text_to_type)
        if result["ok"]:
            return {**result, "reply": f"Typed it, Boss!", "action_type": "type_text"}
        return {**result, "reply": f"Couldn't type: {result.get('error')}"}

    # Press key
    m = _KEY_RE.match(t)
    if m:
        key = m.group("key").strip()
        result = press_key(key)
        if result["ok"]:
            return {**result, "reply": f"Pressed {key}, Boss!", "action_type": "press_key"}
        return {**result, "reply": f"Couldn't press {key}: {result.get('error')}"}

    # Scroll
    m = _SCROLL_RE.match(t)
    if m:
        direction = m.group("direction")
        amount = int(m.group("amount") or 3)
        result = scroll(direction, amount)
        if result["ok"]:
            return {**result, "reply": f"Scrolled {direction}, Boss!", "action_type": "scroll"}
        return {**result, "reply": f"Scroll failed: {result.get('error')}"}

    return {"ok": False, "reply": "Didn't catch that command, Boss.", "action_type": "unknown"}
