"""
brain/computer_control.py — EMO Computer Control Module (Windows)

Gives EMO full control over the Windows laptop:
- Open any installed app by name (URI, PATH, Registry, Start Menu, Shell)
- List, focus, close, and minimize windows with Win32 + psutil + PowerShell fallbacks
- Click, type, scroll, press keyboard shortcuts
- Take screenshots (returned as base64 PNG) via mss / pyautogui / PowerShell
- WhatsApp Desktop / WhatsApp Web automation

Dependencies: pyautogui, pygetwindow, psutil, pillow (PIL), mss
"""

import os
import re
import sys
import time
import base64
import shutil
import winreg
import tempfile
import subprocess
import webbrowser
from pathlib import Path
from io import BytesIO

# ── Lazy imports ────────────────────────────────────────────────────────────
def _get_pyautogui():
    try:
        import pyautogui
        pyautogui.FAILSAFE = False  # EMO controls mouse programmatically
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

# ── App Aliases & URI Mappings ──────────────────────────────────────────────
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

    # Productivity & Built-ins
    "notepad": "notepad.exe",
    "notepad++": "notepad++.exe",
    "word": "WINWORD.EXE",
    "excel": "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE",
    "outlook": "OUTLOOK.EXE",
    "onenote": "ONENOTE.EXE",
    "calc": "calculator:",
    "calculator": "calculator:",
    "paint": "ms-paint:",
    "mspaint": "mspaint.exe",
    "settings": "ms-settings:",
    "photos": "ms-photos:",
    "snipping tool": "SnippingTool.exe",
    "snip": "SnippingTool.exe",

    # Dev tools
    "vscode": "Code.exe",
    "vs code": "Code.exe",
    "visual studio code": "Code.exe",
    "code": "Code.exe",
    "pycharm": "pycharm64.exe",
    "android studio": "studio64.exe",
    "terminal": "wt.exe",
    "windows terminal": "wt.exe",
    "cmd": "cmd.exe",
    "command prompt": "cmd.exe",
    "powershell": "powershell.exe",
    "git bash": "git-bash.exe",

    # Media & Games
    "spotify": "spotify:",
    "vlc": "vlc.exe",
    "steam": "Steam.exe",
    "epic games": "EpicGamesLauncher.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "task manager": "taskmgr.exe",
    "control panel": "control.exe",
}

_START_MENU_PATHS = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path("C:/ProgramData/Microsoft/Windows/Start Menu/Programs"),
]

# Common Windows system GUI apps to include in window listings
_COMMON_GUI_EXES = {
    "chrome.exe", "firefox.exe", "msedge.exe", "brave.exe", "opera.exe",
    "notepad.exe", "notepad++.exe", "code.exe", "spotify.exe", "whatsapp.exe",
    "telegram.exe", "discord.exe", "slack.exe", "teams.exe", "zoom.exe",
    "calculatorApp.exe", "calc.exe", "winword.exe", "excel.exe", "powerpnt.exe",
    "explorer.exe", "taskmgr.exe", "cmd.exe", "powershell.exe", "wt.exe",
    "vlc.exe", "steam.exe", "mspaint.exe"
}


# ══════════════════════════════════════════════════════════════════════════════
# APP LAUNCHER — Multi-strategy execution
# ══════════════════════════════════════════════════════════════════════════════

def _find_exe_in_registry(name: str) -> str | None:
    """Look up exe path in Windows registry App Paths."""
    target = name if name.endswith(".exe") else f"{name}.exe"
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            key = winreg.OpenKey(
                root,
                rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{target}",
            )
            path, _ = winreg.QueryValueEx(key, "")
            if path and Path(path).exists():
                return str(path)
        except OSError:
            pass
    return None


def _find_exe_in_start_menu(app_name: str) -> str | None:
    """Search Start Menu .lnk files for a matching app."""
    low = app_name.lower().strip()
    for base in _START_MENU_PATHS:
        if not base.exists():
            continue
        for lnk in base.rglob("*.lnk"):
            if low in lnk.stem.lower():
                return str(lnk)
    return None


def open_app(name: str) -> dict:
    """
    Open any application by name on Windows.
    Returns {"ok": True, "launched": name, "method": ...} or {"ok": False, "error": "..."}
    """
    raw_name = name.strip()
    low = raw_name.lower()
    # Strip filler words ("the", "app", "application")
    low = re.sub(r"^(?:the\s+)?", "", low).strip()
    low = re.sub(r"\s+(?:app|application)$", "", low).strip()

    # 1. Check known aliases
    target = _APP_ALIASES.get(low, low)

    # 2. URI Protocol launch (ms-settings:, spotify:, calculator:, etc.)
    if target.endswith(":"):
        try:
            os.startfile(target)
            return {"ok": True, "launched": raw_name, "method": "uri"}
        except Exception:
            pass

    # 3. Check PATH via shutil.which
    exe_path = shutil.which(target) or shutil.which(target + ".exe")
    if exe_path:
        try:
            os.startfile(exe_path)
            return {"ok": True, "launched": raw_name, "method": "path"}
        except Exception:
            pass

    # 4. Registry App Paths lookup
    reg_path = _find_exe_in_registry(target)
    if reg_path:
        try:
            os.startfile(reg_path)
            return {"ok": True, "launched": raw_name, "method": "registry"}
        except Exception:
            pass

    # 5. Start Menu shortcut (.lnk)
    lnk = _find_exe_in_start_menu(low)
    if lnk:
        try:
            os.startfile(lnk)
            return {"ok": True, "launched": raw_name, "method": "start_menu"}
        except Exception:
            pass

    # 6. Shell start fallback via cmd.exe /c start "" "target"
    try:
        proc = subprocess.run(
            ["cmd.exe", "/c", "start", "", target],
            capture_output=True, timeout=5
        )
        if proc.returncode == 0:
            return {"ok": True, "launched": raw_name, "method": "shell"}
    except Exception:
        pass

    # 7. os.startfile fallback
    try:
        os.startfile(target)
        return {"ok": True, "launched": raw_name, "method": "startfile"}
    except Exception:
        pass

    return {"ok": False, "error": f"Could not find or open '{raw_name}' on your laptop."}


# ══════════════════════════════════════════════════════════════════════════════
# WINDOW MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

def list_open_windows() -> list[str]:
    """Return titles of all open user applications."""
    windows = []
    # Method A: pygetwindow
    try:
        gw = _get_gw()
        for w in gw.getAllWindows():
            t = w.title.strip()
            if t and t not in ("Program Manager", "Settings", "Windows Input Experience"):
                windows.append(t)
    except Exception:
        pass

    # Method B: psutil process fallback if pygetwindow returned empty
    if not windows:
        try:
            import psutil
            seen = set()
            for p in psutil.process_iter(['name']):
                name = (p.info['name'] or '').strip()
                if name.lower() in _COMMON_GUI_EXES and name not in seen:
                    seen.add(name)
                    windows.append(name.replace('.exe', '').title())
        except Exception:
            pass

    return windows


def focus_window(title_fragment: str) -> dict:
    """Bring a window to front by title or app name."""
    target = title_fragment.strip().lower()

    # Method A: pygetwindow + Win32 Alt key un-lock
    try:
        gw = _get_gw()
        matches = [w for w in gw.getAllWindows() if target in w.title.lower()]
        if matches:
            win = matches[0]
            try:
                import ctypes
                # Press Alt key to bypass Windows SetForegroundWindow restriction
                ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
                win.activate()
                ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)
            except Exception:
                win.activate()
            time.sleep(0.2)
            return {"ok": True, "focused": win.title}
    except Exception:
        pass

    # Method B: PowerShell AppActivate fallback
    try:
        ps_code = (
            f"$w = Get-Process | Where-Object {{$_.MainWindowTitle -like '*{target}*' -or $_.ProcessName -like '*{target}*'}} | Select-Object -First 1; "
            f"if ($w) {{ (New-Object -ComObject WScript.Shell).AppActivate($w.Id) }}"
        )
        proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps_code], capture_output=True, timeout=5)
        if proc.returncode == 0:
            return {"ok": True, "focused": title_fragment}
    except Exception:
        pass

    return {"ok": False, "error": f"No open window matching '{title_fragment}' found."}


def close_window(title_fragment: str) -> dict:
    """Close a window by title match or process name."""
    target = title_fragment.strip().lower()

    # Method A: pygetwindow
    try:
        gw = _get_gw()
        matches = [w for w in gw.getAllWindows() if target in w.title.lower()]
        if matches:
            matches[0].close()
            return {"ok": True, "closed": matches[0].title}
    except Exception:
        pass

    # Method B: psutil process kill
    try:
        import psutil
        for p in psutil.process_iter(['name', 'pid']):
            name = (p.info['name'] or '').lower()
            if target in name or target in name.replace('.exe', ''):
                p.kill()
                return {"ok": True, "closed": p.info['name']}
    except Exception:
        pass

    return {"ok": False, "error": f"Could not find window or process matching '{title_fragment}'."}


def minimize_window(title_fragment: str) -> dict:
    """Minimize a window by title."""
    target = title_fragment.strip().lower()
    try:
        gw = _get_gw()
        matches = [w for w in gw.getAllWindows() if target in w.title.lower()]
        if matches:
            matches[0].minimize()
            return {"ok": True, "minimized": matches[0].title}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": False, "error": f"No window matching '{title_fragment}' found."}


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
        time.sleep(0.1)
        pag.typewrite(text, interval=interval)
        return {"ok": True, "typed": text}
    except Exception:
        # Fallback: pyperclip paste
        try:
            import pyperclip
            pyperclip.copy(text)
            pag = _get_pyautogui()
            pag.hotkey("ctrl", "v")
            return {"ok": True, "typed": text, "method": "clipboard"}
        except Exception as e:
            return {"ok": False, "error": str(e)}


def press_key(key: str) -> dict:
    """Press a key or shortcut (enter, escape, ctrl+s, win+d, etc.)."""
    try:
        pag = _get_pyautogui()
        clean_key = key.strip().lower().replace(" ", "").replace("windows", "win")
        if "+" in clean_key:
            keys = clean_key.split("+")
            pag.hotkey(*keys)
        else:
            pag.press(clean_key)
        return {"ok": True, "pressed": key}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def scroll(direction: str = "down", amount: int = 3) -> dict:
    """Scroll mouse wheel in given direction."""
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


# ══════════════════════════════════════════════════════════════════════════════
# SCREENSHOT
# ══════════════════════════════════════════════════════════════════════════════

def take_screenshot() -> dict:
    """
    Take a full-screen screenshot.
    Tries mss → pyautogui → PowerShell .NET CopyFromScreen.
    """
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

    # Method 3: PowerShell CopyFromScreen (.NET)
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
        subprocess.run(
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
            return {"ok": True, "image_b64": b64, "width": img.width, "height": img.height, "method": "powershell"}
    except Exception as e3:
        return {"ok": False, "error": f"Screenshot failed: {e3}"}

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
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def whatsapp_send_laptop(contact: str, message: str) -> dict:
    """Send WhatsApp message via WhatsApp Desktop or WhatsApp Web."""
    pag = _get_pyautogui()
    wa_path = _whatsapp_desktop_path()

    if wa_path:
        try:
            os.startfile(wa_path)
            time.sleep(2.5)
            focus_window("WhatsApp")
            time.sleep(0.5)

            pag.hotkey("ctrl", "f")
            time.sleep(0.5)

            pag.typewrite(contact, interval=0.04)
            time.sleep(1.2)

            pag.press("enter")
            time.sleep(0.6)

            pag.typewrite(message, interval=0.03)
            time.sleep(0.3)

            pag.press("enter")
            return {"ok": True, "method": "desktop", "contact": contact, "message": message}
        except Exception:
            pass

    # WhatsApp Web fallback
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
            "note": "Opened WhatsApp Web in browser.",
        }
    else:
        return {
            "ok": False,
            "method": "web",
            "error": f"No phone number saved for '{contact}'. Add it in EMO contacts.",
        }


# ══════════════════════════════════════════════════════════════════════════════
# NLU — INTENT DETECTION & PARSER
# ══════════════════════════════════════════════════════════════════════════════

_OPEN_RE = re.compile(
    r"^(?:open|launch|start|run|fire up|pull up|bring up|load)\s+(?P<app>.+)$",
    re.IGNORECASE,
)

_FOCUS_RE = re.compile(
    r"^(?:switch to|go to|focus|show|bring up|activate)\s+(?P<window>.+)$",
    re.IGNORECASE,
)

_CLOSE_RE = re.compile(
    r"^(?:close|quit|exit|kill|shut down)\s+(?P<window>.+)$",
    re.IGNORECASE,
)

_TYPE_RE = re.compile(
    r"^(?:type|write|input|enter)\s+(?:the text\s+|this\s+|in\s+\w+[:\s]+)?(?P<text>.+)$",
    re.IGNORECASE,
)

_KEY_RE = re.compile(
    r"^(?:press|hit|tap|hold)\s+(?P<key>(?:ctrl|alt|shift|win|windows|cmd)[\+\w]*|\w+)$",
    re.IGNORECASE,
)

_SCREENSHOT_RE = re.compile(
    r"(?:take a screenshot|screenshot|screen grab|what(?:'s| is) on (?:my |the )?screen|capture screen)",
    re.IGNORECASE,
)

_SCROLL_RE = re.compile(
    r"^(?:scroll)\s+(?P<direction>up|down|left|right)(?:\s+(?P<amount>\d+))?$",
    re.IGNORECASE,
)

_MIN_RE = re.compile(
    r"^(?:minimise|minimize|hide)\s+(?P<window>.+)$",
    re.IGNORECASE,
)

_LIST_WIN_RE = re.compile(
    r"(?:what(?:'s| is) open|list (?:open )?(?:apps|windows)|show (?:open )?windows|open windows)",
    re.IGNORECASE,
)

# In-App Actions (e.g. "in calculator do 200+300", "do 200+300 in calculator", "in notepad write hello")
_IN_APP_RE = re.compile(
    r"^(?:in|on|using|with)\s+(?:the\s+)?(?P<app>calculator|calc|notepad|chrome|browser|vscode|code|word|excel|terminal|cmd)\s+(?:do|type|write|calculate|compute|search|open|input)?\s*[:\s]+(?P<action>.+)$",
    re.IGNORECASE,
)

_DO_IN_APP_RE = re.compile(
    r"^(?:do|type|write|calculate|compute|search|input)\s+(?P<action>.+?)\s+(?:in|on|using|with)\s+(?:the\s+)?(?P<app>calculator|calc|notepad|chrome|browser|vscode|code|word|excel|terminal|cmd)$",
    re.IGNORECASE,
)


def interact_app(app_name: str, action: str) -> dict:
    """
    Perform an action directly inside an open application.
    Supports Calculator math typing, Notepad text typing, Chrome web searching, etc.
    """
    low_app = app_name.strip().lower()
    low_action = action.strip()

    # 1. Calculator Interaction
    if low_app in ("calculator", "calc"):
        open_app("calculator")
        focus_window("calculator")
        time.sleep(0.4)

        clean_expr = (
            low_action.replace("plus", "+")
            .replace("minus", "-")
            .replace("times", "*")
            .replace("x", "*")
            .replace("divided by", "/")
            .replace("over", "/")
            .replace(" ", "")
        )
        if not clean_expr.endswith("="):
            clean_expr += "="

        try:
            pag = _get_pyautogui()
            pag.typewrite(clean_expr, interval=0.04)
            time.sleep(0.3)
        except Exception:
            pass

        calc_result = None
        try:
            expr_eval = clean_expr.rstrip("=")
            if re.match(r"^[\d\+\-\*\/\.\(\)\s]+$", expr_eval):
                calc_result = eval(expr_eval)
        except Exception:
            pass

        ss = take_screenshot()
        reply_val = f" {calc_result}" if calc_result is not None else ""
        reply = f"I entered '{clean_expr}' into Calculator for you, Boss! Result is{reply_val}."
        res = {"ok": True, "reply": reply, "action_type": "app_interaction", "app": "calculator"}
        if ss.get("ok"):
            res["screenshot_b64"] = ss["image_b64"]
        return res

    # 2. Notepad Interaction
    elif low_app in ("notepad", "word"):
        open_app(low_app)
        focus_window(low_app)
        time.sleep(0.3)
        type_text(low_action)
        return {"ok": True, "reply": f"Typed '{low_action}' into {app_name.title()}, Boss!", "action_type": "app_interaction", "app": low_app}

    # 3. Chrome / Browser Search Interaction
    elif low_app in ("chrome", "browser"):
        open_app("chrome")
        focus_window("chrome")
        time.sleep(0.3)
        try:
            pag = _get_pyautogui()
            pag.hotkey("ctrl", "l")
            time.sleep(0.2)
            pag.typewrite(low_action, interval=0.03)
            pag.press("enter")
        except Exception:
            pass
        return {"ok": True, "reply": f"Searched '{low_action}' in Chrome, Boss!", "action_type": "app_interaction", "app": "chrome"}

    # 4. Generic App Action Fallback
    else:
        open_app(low_app)
        focus_window(low_app)
        time.sleep(0.3)
        type_text(low_action)
        return {"ok": True, "reply": f"Entered '{low_action}' into {app_name.title()}, Boss!", "action_type": "app_interaction", "app": low_app}


def clean_command(text: str) -> str:
    """Strip leading EMO trigger words and trailing filler words."""
    t = text.strip()
    t = re.sub(
        r"^(?:hey|hi|hello|ok|okay)?\s*(?:emo)?\s*(?:please|can you|could you|would you|i want you to|help me|kindly)?\s*",
        "", t, flags=re.IGNORECASE
    ).strip()
    t = re.sub(
        r"\s*(?:please|emo|boss|thanks|thank you)?$",
        "", t, flags=re.IGNORECASE
    ).strip()
    return t


def is_control_command(text: str) -> bool:
    """Return True if text is a computer control command."""
    t = clean_command(text)
    return bool(
        _IN_APP_RE.match(t)
        or _DO_IN_APP_RE.match(t)
        or _OPEN_RE.match(t)
        or _FOCUS_RE.match(t)
        or _CLOSE_RE.match(t)
        or _TYPE_RE.match(t)
        or _KEY_RE.match(t)
        or _SCREENSHOT_RE.search(t)
        or _SCROLL_RE.match(t)
        or _MIN_RE.match(t)
        or _LIST_WIN_RE.search(t)
    )



def parse_and_execute(text: str) -> dict:
    """
    Parse a control command from natural language and execute it natively on Windows.
    Returns a result dict with at least {"ok": bool, "reply": str, ...}
    """
    t = clean_command(text)

    # 0. In-App Actions (e.g. "in calculator do 200+300", "do 200+300 in calculator")
    m_in = _IN_APP_RE.match(t) or _DO_IN_APP_RE.match(t)
    if m_in:
        app_target = m_in.group("app")
        action_target = m_in.group("action")
        return interact_app(app_target, action_target)

    # 1. Screenshot
    if _SCREENSHOT_RE.search(t):

        result = take_screenshot()
        if result["ok"]:
            return {**result, "reply": "Screenshot taken, Boss!", "action_type": "screenshot"}
        return {**result, "reply": f"Screenshot failed: {result.get('error')}"}

    # 2. List open windows
    if _LIST_WIN_RE.search(t):
        wins = list_open_windows()
        reply = "Open apps: " + ", ".join(wins[:10]) if wins else "No open apps found."
        return {"ok": True, "windows": wins, "reply": reply, "action_type": "list_windows"}

    # 3. Open app
    m = _OPEN_RE.match(t)
    if m:
        app = m.group("app").strip()
        result = open_app(app)
        if result["ok"]:
            return {**result, "reply": f"Opening {app} now, Boss!", "action_type": "open_app"}
        return {**result, "reply": f"Couldn't find or open '{app}' on your laptop, Boss."}

    # 4. Focus window
    m = _FOCUS_RE.match(t)
    if m:
        win = m.group("window").strip()
        result = focus_window(win)
        if result["ok"]:
            return {**result, "reply": f"Switched to {result.get('focused', win)}, Boss!", "action_type": "focus_window"}
        return {**result, "reply": f"No open window matching '{win}' found, Boss."}

    # 5. Close window / app
    m = _CLOSE_RE.match(t)
    if m:
        win = m.group("window").strip()
        result = close_window(win)
        if result["ok"]:
            return {**result, "reply": f"Closed {result.get('closed', win)}, Boss!", "action_type": "close_window"}
        return {**result, "reply": f"Couldn't find '{win}' to close, Boss."}

    # 6. Minimize window
    m = _MIN_RE.match(t)
    if m:
        win = m.group("window").strip()
        result = minimize_window(win)
        if result["ok"]:
            return {**result, "reply": f"Minimised {result.get('minimized', win)}, Boss!", "action_type": "minimize_window"}
        return {**result, "reply": f"Couldn't find '{win}', Boss."}

    # 7. Type text
    m = _TYPE_RE.match(t)
    if m:
        text_to_type = m.group("text").strip()
        result = type_text(text_to_type)
        if result["ok"]:
            return {**result, "reply": f"Typed it, Boss!", "action_type": "type_text"}
        return {**result, "reply": f"Couldn't type: {result.get('error')}"}

    # 8. Press key
    m = _KEY_RE.match(t)
    if m:
        key = m.group("key").strip()
        result = press_key(key)
        if result["ok"]:
            return {**result, "reply": f"Pressed {key}, Boss!", "action_type": "press_key"}
        return {**result, "reply": f"Couldn't press {key}: {result.get('error')}"}

    # 9. Scroll
    m = _SCROLL_RE.match(t)
    if m:
        direction = m.group("direction")
        amount = int(m.group("amount") or 3)
        result = scroll(direction, amount)
        if result["ok"]:
            return {**result, "reply": f"Scrolled {direction}, Boss!", "action_type": "scroll"}
        return {**result, "reply": f"Scroll failed: {result.get('error')}"}

    return {"ok": False, "reply": "Didn't catch that command, Boss.", "action_type": "unknown"}

