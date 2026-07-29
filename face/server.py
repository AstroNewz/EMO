"""
EMO — Face server  (standard-library only; no pip installs needed)
==================================================================
Serves the animated face UI and exposes a tiny API the orchestrator uses to
switch expressions in real time.

Why stdlib only? Termux runs bleeding-edge Python and many web frameworks
(FastAPI/pydantic) need a Rust/C compile that fails on aarch64-linux-android.
http.server is always present and needs nothing installed.

Endpoints:
  GET  /            -> the face page (static/index.html)
  GET  /static/*    -> static assets (the face is self-contained in index.html)
  GET  /state       -> {"state", "time", "battery_pct", "battery_charging",
                        "weather_temp", "weather_code"}   (the browser polls this)
  POST /state       -> body {"state": "thinking"}  set the current expression
  GET  /wish        -> {"wish": "sleep|listen"}  (the orchestrator polls this)
  POST /wish        -> body {"wish": "listen"}   button toggles mic on/off
  GET  /event       -> {"event": "dizzy|"}  one-shot; consumed (cleared) on read
  POST /event       -> body {"event": "dizzy"}   browser reflex flags the backend
  GET  /gestures    -> the gestures: config block (MediaPipe reads this on load)

The browser polls /state a few times a second. For an expression change that's
imperceptible, and it removes every moving part that breaks on Termux.

Run standalone (for testing):
    python face/server.py
"""

import os
import sys as _sys
import json
import threading
import subprocess
import time as _time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# --- Resolve paths relative to the project root, wherever we're launched from ---
HERE = Path(__file__).resolve().parent          # .../EMO/face
ROOT = HERE.parent                              # .../EMO
STATIC_DIR = HERE / "static"

# Chiptune SFX reflex (optional): lets /event play a clip in sync with the UI.
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    from core.audio import play_sfx
except Exception:
    def play_sfx(_name):                        # audio module optional — never crash
        return

# The expressions the orchestrator is allowed to request.
VALID_STATES = {
    "idle", "listening", "thinking", "speaking",
    "happy", "excited", "confused", "curious",
    "surprised", "sad", "angry", "error",
}

# --- Load host/port from config.yaml WITHOUT requiring PyYAML ---------------
# We only need two scalar values, so we do a tiny tolerant parse and fall back
# to defaults if PyYAML isn't installed or the file is missing.
def load_face_config():
    host, port = "127.0.0.1", 8008
    cfg_path = ROOT / "config.yaml"
    try:
        text = cfg_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return host, port
    # Try PyYAML if available (most correct); otherwise scrape the two keys.
    try:
        import yaml  # optional
        cfg = yaml.safe_load(text) or {}
        face = cfg.get("face", {})
        return face.get("host", host), int(face.get("port", port))
    except Exception:
        in_face = False
        for line in text.splitlines():
            if line.startswith("face:"):
                in_face = True
                continue
            if in_face:
                if line and not line[0].isspace():
                    break  # left the face: block
                s = line.strip()
                if s.startswith("host:"):
                    host = s.split(":", 1)[1].strip().strip('"').strip("'")
                elif s.startswith("port:"):
                    try:
                        port = int(s.split(":", 1)[1].strip())
                    except ValueError:
                        pass
        return host, port


def load_dashboard_config():
    """(weather_city, temperature_unit) from config.yaml's dashboard: block."""
    city, unit = "", "C"
    cfg_path = ROOT / "config.yaml"
    try:
        text = cfg_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return city, unit
    try:
        import yaml  # optional
        cfg = yaml.safe_load(text) or {}
        dash = cfg.get("dashboard", {}) or {}
        return (dash.get("weather_city") or ""), (str(dash.get("temperature_unit") or "C"))
    except Exception:
        in_dash = False
        for line in text.splitlines():
            if line.startswith("dashboard:"):
                in_dash = True
                continue
            if in_dash:
                if line and not line[0].isspace():
                    break  # left the dashboard: block
                s = line.strip()
                if s.startswith("weather_city:"):
                    city = s.split(":", 1)[1].strip().strip('"').strip("'")
                elif s.startswith("temperature_unit:"):
                    unit = s.split(":", 1)[1].strip().strip('"').strip("'") or "C"
        return city, unit


def load_gestures_config():
    """Return the `gestures:` config block as a plain dict for the browser.

    The face page fetches this from GET /gestures so MediaPipe knows whether it's
    enabled and how sensitive/how often to fire. Tolerant of a missing PyYAML
    (returns sensible defaults) — same discipline as load_dashboard_config."""
    defaults = {
        "enabled": True,
        "min_confidence": 0.6,
        "cooldown_seconds": 6,
        "presence_cooldown_seconds": 30,
        "camera": "user",          # getUserMedia facingMode: user(front) | environment(back)
    }
    cfg_path = ROOT / "config.yaml"
    try:
        text = cfg_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return defaults
    try:
        import yaml  # optional
        cfg = yaml.safe_load(text) or {}
        g = cfg.get("gestures", {}) or {}
        return {**defaults, **{k: g[k] for k in defaults if k in g}}
    except Exception:
        return defaults        # bare-Termux fallback: MediaPipe uses the defaults


HOST, PORT = load_face_config()
# Default port override: config says 8008 for backward compat, but the
# Android launcher expects 3000. The serve() function reads --port CLI.
_DEFAULT_LAUNCHER_PORT = 3000

# Track server start time for uptime reporting
_server_start_time = _time.monotonic()

# --- Shared expression state (thread-safe enough for our needs) ---
_state_lock = threading.Lock()
_current_state = {"value": "idle"}

# --- Shared control "wish": what the USER wants via the on-screen button ------
# This is the browser -> orchestrator channel. The button POSTs /wish; the
# orchestrator polls GET /wish to decide when to open/close the mic.
#   "sleep"  = passive (wake-word scanning / idle)
#   "listen" = user tapped the face; go active and capture a command
_VALID_WISHES = {"sleep", "listen"}
_current_wish = {"value": "sleep"}

# --- One-shot "event" channel: browser reflex -> orchestrator ------------------
# The face posts transient reflexes here (currently just "dizzy" on a
# portrait/landscape flip). Unlike state/wish this is CONSUMED on read: GET
# returns the pending event exactly once and clears it, so the orchestrator's
# poller reacts to each event once and never re-fires a stale flag.
_VALID_EVENTS = {
    "dizzy",
    # Real-time hand gestures recognised in the browser face by MediaPipe
    # (front camera). The orchestrator's event watcher speaks a canned reaction.
    "gesture_thumbs_up", "gesture_thumbs_down", "gesture_victory",
    "gesture_open_palm", "gesture_point", "gesture_fist", "gesture_love",
    # Someone appeared / sat down in front of the camera (MediaPipe pose).
    "presence_arrived",
}
_current_event = {"value": ""}


def get_state():
    with _state_lock:
        return _current_state["value"]


def set_state(value):
    with _state_lock:
        _current_state["value"] = value


def get_wish():
    with _state_lock:
        return _current_wish["value"]


def set_wish(value):
    with _state_lock:
        _current_wish["value"] = value


def set_event(value):
    with _state_lock:
        _current_event["value"] = value


def take_event():
    """Return the pending event and clear it (consume-once)."""
    with _state_lock:
        value = _current_event["value"]
        _current_event["value"] = ""
        return value


# ============================================================================
# AMBIENT TELEMETRY — clock / battery / weather for the idle desk dashboard
# ----------------------------------------------------------------------------
# One daemon thread keeps a tiny cached snapshot that GET /state folds into its
# JSON. Battery is a local termux-battery-status call (cheap, every tick);
# weather is a wttr.in fetch throttled to ~15 min so we never spam the network.
# Both fail soft: on any error the cached value is simply left unchanged, and
# request handling only ever READS the cache — it never blocks on I/O.
# ============================================================================
_telemetry_lock = threading.Lock()
_telemetry = {
    "battery_pct": None,        # int 0..100
    "battery_charging": False,  # bool
    "weather_temp": None,       # int, in the configured unit
    "weather_code": None,       # WWO weather code (drives the UI climate glyph)
    "weather_unit": "C",        # "C" | "F" (so the UI can print the letter)
}
_BATTERY_PERIOD = 60          # seconds between battery polls (also the loop tick)
_WEATHER_PERIOD = 15 * 60     # seconds between weather fetches (be kind to wttr.in)


def get_telemetry():
    with _telemetry_lock:
        return dict(_telemetry)


def _fetch_battery():
    """(percentage:int, charging:bool) via termux-battery-status, or (None, None)."""
    try:
        out = subprocess.run(
            ["termux-battery-status"],
            capture_output=True, text=True, timeout=8,
        )
        data = json.loads(out.stdout or "{}")
        pct = int(round(float(data.get("percentage"))))
        status = str(data.get("status", "")).strip().upper()
        return pct, status in ("CHARGING", "FULL")
    except Exception:
        return None, None


def _fetch_weather(city, unit):
    """(temp:int, code:int|None) from wttr.in's j1 JSON, or (None, None). Never raises."""
    try:
        loc = urllib.parse.quote(city.strip()) if city and city.strip() else ""
        url = f"https://wttr.in/{loc}?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        cur = data["current_condition"][0]
        temp = int(cur["temp_F" if str(unit).upper() == "F" else "temp_C"])
        try:
            code = int(cur.get("weatherCode"))
        except (TypeError, ValueError):
            code = None
        return temp, code
    except Exception:
        return None, None


def _telemetry_loop(city, unit):
    """Refresh the cached snapshot forever (daemon). Battery each tick, weather
    every _WEATHER_PERIOD — retrying weather every tick until the first success."""
    unit_letter = "F" if str(unit).upper() == "F" else "C"
    with _telemetry_lock:
        _telemetry["weather_unit"] = unit_letter
    last_weather = 0.0
    first = True
    while True:
        update = {}
        pct, charging = _fetch_battery()
        if pct is not None:
            update["battery_pct"] = pct
            update["battery_charging"] = bool(charging)
        now = _time.monotonic()
        if first or (now - last_weather) >= _WEATHER_PERIOD:
            temp, code = _fetch_weather(city, unit)
            if temp is not None:
                update["weather_temp"] = temp
                update["weather_code"] = code
                last_weather = now
        first = False
        if update:
            with _telemetry_lock:
                _telemetry.update(update)
        _time.sleep(_BATTERY_PERIOD)


def start_telemetry():
    city, unit = load_dashboard_config()
    threading.Thread(
        target=_telemetry_loop, args=(city, unit),
        name="emo-telemetry", daemon=True,
    ).start()


_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",     # ES module (MediaPipe bundle)
    ".wasm": "application/wasm",                    # MediaPipe WASM runtime
    ".task": "application/octet-stream",           # MediaPipe model bundle
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
}


class Handler(BaseHTTPRequestHandler):
    # Silence the default per-request logging (keeps the terminal clean).
    def log_message(self, *args):
        pass

    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path):
        if not path.is_file():
            self.send_error(404, "Not found")
            return
        ctype = _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path == "/" or path == "/index.html" or path == "/hud/" or path == "/hud":
            hud_file = STATIC_DIR / "hud" / "index.html"
            if hud_file.is_file():
                self._send_file(hud_file)
            else:
                self._send_file(STATIC_DIR / "index.html")
            return

        if path.startswith("/hud/"):
            rel = path[len("/hud/"):]
            target = (STATIC_DIR / "hud" / rel).resolve()
            hud_dir = (STATIC_DIR / "hud").resolve()
            if hud_dir in target.parents or target == hud_dir:
                self._send_file(target)
            else:
                self.send_error(403, "Forbidden")
            return

        # ---- API endpoints (Android launcher watchdog + HUD) ----
        if path.startswith("/api/tts"):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            text = params.get("text", ["Hello"])[0]
            voice = params.get("voice", ["en-US-AnaNeural"])[0] # Genuine Neural Child Voice

            try:
                import asyncio
                import edge_tts

                temp_mp3 = ROOT / "face" / "static" / "temp_speech.mp3"
                communicate = edge_tts.Communicate(text, voice, rate="+6%", pitch="+15Hz")
                asyncio.run(communicate.save(str(temp_mp3)))

                with open(temp_mp3, "rb") as f:
                    data = f.read()

                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)
                return
            except Exception as ex:
                self.send_error(500, f"TTS error: {ex}")
                return

        if path == "/api/health":
            uptime = int(_time.monotonic() - _server_start_time)
            self._send_json({
                "status": "alive",
                "uptime": uptime,
                "pid": os.getpid(),
            })
            return

        if path == "/api/telemetry":
            tele = get_telemetry()
            self._send_json({
                "state": get_state(),
                "time": datetime.now().strftime("%H:%M"),
                "date": datetime.now().strftime("%Y-%m-%d"),
                "battery_pct": tele.get("battery_pct"),
                "battery_charging": tele.get("battery_charging", False),
                "weather_temp": tele.get("weather_temp"),
                "weather_code": tele.get("weather_code"),
                "weather_unit": tele.get("weather_unit", "C"),
                "uptime": int(_time.monotonic() - _server_start_time),
            })
            return

        if path == "/api/ai/status":
            # Read brain config to report which tier is active
            brain_info = {"tier": "unknown", "model": "unknown"}
            try:
                cfg_path = ROOT / "config.yaml"
                text = cfg_path.read_text(encoding="utf-8")
                try:
                    import yaml
                    cfg = yaml.safe_load(text) or {}
                    brain = cfg.get("brain", {})
                    brain_info["mode"] = brain.get("mode", "local")
                    if brain.get("openrouter", {}).get("enabled"):
                        brain_info["tier"] = "openrouter"
                        brain_info["model"] = brain.get("openrouter", {}).get("model", "")
                    elif brain.get("cloudflare", {}).get("enabled"):
                        brain_info["tier"] = "cloudflare"
                        brain_info["model"] = brain.get("cloudflare", {}).get("model", "")
                    else:
                        brain_info["tier"] = "local"
                        brain_info["model"] = brain.get("local", {}).get("model_path", "").split("/")[-1]
                except Exception:
                    pass
            except Exception:
                pass
            self._send_json(brain_info)
            return

        # Face Recognition Status API
        if path == "/api/vision/status":
            try:
                from brain import face_lock
                self._send_json({"ok": True, "enrolled": face_lock.is_enrolled()})
            except Exception as e:
                self._send_json({"ok": False, "enrolled": False})
            return

        # ---- Original endpoints (preserved for backward compat) ----
        if path == "/state":
            tele = get_telemetry()
            self._send_json({
                "state": get_state(),
                "time": datetime.now().strftime("%H:%M"),
                "battery_pct": tele.get("battery_pct"),
                "battery_charging": tele.get("battery_charging", False),
                "weather_temp": tele.get("weather_temp"),
                "weather_code": tele.get("weather_code"),
                "weather_unit": tele.get("weather_unit", "C"),
            })
            return

        if path == "/wish":
            self._send_json({"wish": get_wish()})
            return

        if path == "/event":
            # Consume-once: hand the orchestrator the event, then clear it.
            self._send_json({"event": take_event()})
            return

        if path == "/gestures":
            # The face page reads its MediaPipe settings from here on load.
            self._send_json(load_gestures_config())
            return

        if path.startswith("/static/"):
            # Prevent directory traversal: resolve and ensure it stays inside STATIC_DIR
            rel = path[len("/static/"):]
            target = (STATIC_DIR / rel).resolve()
            if STATIC_DIR.resolve() in target.parents or target == STATIC_DIR.resolve():
                self._send_file(target)
            else:
                self.send_error(403, "Forbidden")
            return

        self.send_error(404, "Not found")

    def _read_json(self):
        """Parse the request body as JSON, or None on failure."""
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode() or "{}")
        except Exception:
            return None

    def do_POST(self):
        path = self.path.split("?", 1)[0]

        # Browser button -> backend control channel.
        if path == "/wish":
            body = self._read_json()
            if body is None:
                self._send_json({"error": "invalid JSON"}, code=400)
                return
            wish = (body or {}).get("wish")
            if wish not in _VALID_WISHES:
                self._send_json(
                    {"error": f"unknown wish '{wish}'", "valid": sorted(_VALID_WISHES)},
                    code=400,
                )
                return
            set_wish(wish)
            self._send_json({"ok": True, "wish": wish})
            return

        # Browser reflex (e.g. orientation flip) -> backend event flag.
        if path == "/event":
            body = self._read_json()
            if body is None:
                self._send_json({"error": "invalid JSON"}, code=400)
                return
            event = (body or {}).get("event")
            if event not in _VALID_EVENTS:
                self._send_json(
                    {"error": f"unknown event '{event}'", "valid": sorted(_VALID_EVENTS)},
                    code=400,
                )
                return
            set_event(event)
            play_sfx(event)          # audio reflex in lock-step with the visual (e.g. dizzy)
            self._send_json({"ok": True, "event": event})
            return

        # Direct Ultra-Fast NVIDIA AI Chat Endpoint with Memory, Web Search & Google Workspace
        if path == "/api/ai/chat":
            body = self._read_json()
            if not body or "message" not in body:
                self._send_json({"error": "missing message"}, code=400)
                return

            user_msg = body.get("message", "").strip()
            if not user_msg:
                self._send_json({"reply": "I'm listening, Boss!"})
                return

            try:
                from brain import api_llm, memory, web_search, google_workspace

                context_addons = ""
                
                # Real-Time Google & Web Search Trigger
                if web_search.is_search_needed(user_msg):
                    print(f"[chat.api] Fetching live web search for: '{user_msg}'")
                    search_res = web_search.search_web(user_msg)
                    if search_res:
                        context_addons += f"\n\n[LIVE SEARCH RESULTS]:\n{search_res}"

                # Google Workspace Integration Trigger (Calendar, Gmail, Drive)
                if google_workspace.is_workspace_query(user_msg):
                    low = user_msg.lower()
                    if any(k in low for k in ["email", "gmail", "inbox"]):
                        ws_res = google_workspace.list_unread_emails()
                    elif any(k in low for k in ["calendar", "schedule", "meeting", "event"]):
                        ws_res = google_workspace.list_calendar_events()
                    else:
                        ws_res = google_workspace.search_drive_docs(user_msg)
                    context_addons += f"\n\n[GOOGLE WORKSPACE DATA]:\n{ws_res}"

                system = (
                    "You are EMO, a warm, cheerful, excitable AI companion. "
                    "You have live Google/web search access and Google Workspace integration. "
                    "Always answer in ONE short, friendly spoken sentence. "
                    "Use light enthusiasm like 'Ooh!', 'Got it, Boss!', 'Yay!'."
                )

                # Fetch full conversation history from JSON memory
                history = memory.get_history_for_llm()
                prompt_msg = user_msg + context_addons if context_addons else user_msg
                history.append({"role": "user", "content": prompt_msg})

                reply = api_llm.generate(system, history)

                # Save turn to JSON memory
                memory.add_exchange(user_msg, reply)

                self._send_json({"ok": True, "reply": reply})
            except Exception as e:
                print(f"[chat.api] Error: {e}")
                self._send_json({"ok": False, "reply": "I'm right here with you, Boss!"})
            return

        # Google Workspace Status API
        if path == "/api/workspace/status":
            try:
                from brain import google_workspace
                self._send_json({"ok": True, "connected": google_workspace.is_connected()})
            except Exception:
                self._send_json({"ok": False, "connected": False})
            return

        # Google Workspace Connect API (Save Access Token or API Key)
        if path == "/api/workspace/connect":
            body = self._read_json()
            if not body:
                self._send_json({"error": "missing token or credentials"}, code=400)
                return
            try:
                from brain import google_workspace
                ok = google_workspace.save_credentials(body)
                self._send_json({"ok": ok, "connected": ok})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, code=500)
            return

        # Face Recognition Status API
        if path == "/api/vision/status":
            try:
                from brain import face_lock
                self._send_json({"ok": True, "enrolled": face_lock.is_enrolled()})
            except Exception as e:
                self._send_json({"ok": False, "enrolled": False})
            return

        # Face Lock Enrollment API (Snapshot webcam frame as Boss)
        if path == "/api/vision/enroll":
            body = self._read_json()
            b64_image = (body or {}).get("image", "")
            if not b64_image:
                self._send_json({"ok": False, "error": "missing image data"}, code=400)
                return
            try:
                from brain import face_lock
                ok, msg = face_lock.enroll_image_b64(b64_image, label="Boss")
                self._send_json({"ok": ok, "message": msg})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, code=500)
            return

        # Face Lock Recognition API (Identify face in camera frame)
        if path == "/api/vision/recognize":
            body = self._read_json()
            b64_image = (body or {}).get("image", "")
            if not b64_image:
                self._send_json({"ok": False, "error": "missing image data"}, code=400)
                return
            try:
                from brain import face_lock
                res = face_lock.recognize_image_b64(b64_image)
                self._send_json({"ok": True, **res})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, code=500)
            return

        # Full Vision Analysis API (Boss Recognition, Gestures & Environment)
        if path == "/api/vision/analyze":
            body = self._read_json()
            b64_image = (body or {}).get("image", "")
            if not b64_image:
                self._send_json({"ok": False, "error": "missing image data"}, code=400)
                return
            try:
                from brain import face_lock
                res = face_lock.analyze_frame_b64(b64_image)
                self._send_json({"ok": True, **res})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, code=500)
            return
            self.send_error(404, "Not found")
            return

        body = self._read_json()
        if body is None:
            self._send_json({"error": "invalid JSON"}, code=400)
            return

        state = (body or {}).get("state")
        if state not in VALID_STATES:
            self._send_json(
                {"error": f"unknown state '{state}'", "valid": sorted(VALID_STATES)},
                code=400,
            )
            return

        set_state(state)
        self._send_json({"ok": True, "state": state})


def serve(port=None):
    global _server_start_time
    _server_start_time = _time.monotonic()
    use_port = port if port is not None else PORT
    start_telemetry()          # background clock/battery/weather refresh
    httpd = ThreadingHTTPServer((HOST, use_port), Handler)
    print(f"[EMO face] serving on http://{HOST}:{use_port}  (open this in the phone browser)")
    print(f"[EMO face] API health: http://{HOST}:{use_port}/api/health")
    print(f"[EMO face] HUD:        http://{HOST}:{use_port}/hud/")
    print("[EMO face] Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[EMO face] shutting down.")
        httpd.shutdown()


if __name__ == "__main__":
    # CLI: python face/server.py --port 3000
    _port = None
    if "--port" in _sys.argv:
        try:
            _port = int(_sys.argv[_sys.argv.index("--port") + 1])
        except (IndexError, ValueError):
            pass
    serve(port=_port)
