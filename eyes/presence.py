"""
EMO — Eyes / Presence (proactive greeter)
=========================================
A daemon that notices when you sit down or leave and reacts — the "Jarvis"
proactive behaviour. Runs on its own thread (like the orchestrator's dizzy
watcher) so it never blocks the conversation loop.

Battery discipline ("heavy inference triggered, not continuous"): a CHEAP MOTION
GATE decides when anything interesting happened, and only THEN do we (optionally)
spend a VLM call. The gate reuses the exact idiom from `ears/stt.py`'s VAD —
decode a frame with ffmpeg, compute energy in pure stdlib — but on pixels:

    termux-camera-photo -> 64x64 grayscale via ffmpeg -> stdlib per-pixel RMS diff
    vs the previous frame. Diff over threshold = motion.

Arrival  (quiet -> motion) : greet. Online -> identify (personalise "Welcome
                             back, Boss" if it's you, neutral otherwise).
                             Offline -> generic "Someone's here."
Departure (present, then a run of still polls): online we CONFIRM the frame is
                             empty before saying goodbye (so we don't farewell
                             someone sitting still); offline it's best-effort.

Public API:
    watch(config, speak, is_online=None, busy=None, stop_event=None)
        -> runs forever (start it on a daemon thread). Guards everything; if the
           camera or ffmpeg is missing it logs once and returns.
"""

import os
import sys
import math
import time
import array
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eyes import camera, vision, faces   # noqa: E402

_GRID = 64                                # downscale frame to 64x64 gray for the gate


def _gray_frame(path):
    """Decode a JPEG to raw 64x64 grayscale bytes via ffmpeg. b'' on failure."""
    if not (path and os.path.exists(path) and shutil.which("ffmpeg")):
        return b""
    try:
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "quiet", "-i", path,
             "-vf", f"scale={_GRID}:{_GRID},format=gray", "-f", "rawvideo", "pipe:1"],
            capture_output=True, timeout=15,
        )
        return p.stdout or b""
    except Exception:
        return b""


def _diff_rms(a, b):
    """RMS of per-pixel differences between two equal-length gray frames."""
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    xa, xb = array.array("B"), array.array("B")
    xa.frombytes(a[:n])
    xb.frombytes(b[:n])
    return math.sqrt(sum((xa[i] - xb[i]) ** 2 for i in range(n)) / n)


def _mean(frame):
    """Average brightness 0-255 (used to spot a dark/covered lens)."""
    if not frame:
        return 0.0
    x = array.array("B")
    x.frombytes(frame)
    return sum(x) / len(x)


def watch(config, speak, is_online=None, busy=None, stop_event=None):
    """Motion-gated presence loop. `speak(text)` MUST be the orchestrator's
    serialised speaker so we never talk over the main loop. `is_online()` -> bool
    gates personalised greetings. `busy()` -> bool (optional) suppresses proactive
    speech while EMO is mid-conversation. `stop_event` (optional) ends the loop."""
    eyes = (config or {}).get("eyes", {})
    pc = eyes.get("presence", {})
    if not pc.get("enabled", True):
        return
    if not camera.available():
        print("[presence] camera bridge not found; presence disabled.")
        return
    if shutil.which("ffmpeg") is None:
        print("[presence] ffmpeg not found; presence disabled.")
        return

    cam_id = pc.get("camera_id", eyes.get("camera_id", 1))     # front cam by default
    poll = float(pc.get("poll_seconds", 25))
    threshold = float(pc.get("motion_threshold", 12))
    absent_after = int(pc.get("absent_after", 3))
    cooldown = float(pc.get("greet_cooldown", 120))
    say_goodbye = bool(pc.get("goodbye", True))
    is_online = is_online or (lambda: False)
    busy = busy or (lambda: False)

    def _stopped():
        return bool(stop_event and stop_event.is_set())

    prev = b""
    present = False
    quiet = 0
    last_greet = 0.0                       # monotonic clock is stamped below

    print(f"[presence] watching (camera {cam_id}, every {poll:.0f}s, "
          f"threshold {threshold:.0f}).")

    # Prime the baseline frame so the first real poll has something to diff.
    prev = _gray_frame(camera.snapshot(eyes, camera_id=cam_id, name="presence"))

    while not _stopped():
        # Sleep first (baseline already taken); bail promptly if asked to stop.
        for _ in range(int(max(1, poll / 0.5))):
            if _stopped():
                return
            time.sleep(0.5)

        shot = camera.snapshot(eyes, camera_id=cam_id, name="presence")
        frame = _gray_frame(shot)
        if not frame:
            continue                       # transient capture/decode miss — skip
        motion = _diff_rms(prev, frame) if prev else 0.0
        dark = _mean(frame) < 8            # lens covered / lights off -> treat as empty
        prev = frame

        now = time.monotonic()
        moved = motion > threshold and not dark

        if not present:
            # ---- ARRIVAL: a quiet scene just came alive -------------------------
            if moved and (now - last_greet) >= cooldown and not busy():
                present = True
                quiet = 0
                last_greet = now
                _greet_arrival(shot, eyes, speak, is_online)
        else:
            # ---- already present: track stillness, confirm departures ----------
            if moved:
                quiet = 0
            else:
                quiet += 1
                if quiet >= absent_after:
                    if _confirm_left(shot, eyes, is_online, dark):
                        present = False
                        quiet = 0
                        if say_goodbye and not busy():
                            speak("Catch you later.")
                    else:
                        quiet = 0            # still here, just sitting still — stay present


def _greet_arrival(shot, eyes, speak, is_online):
    """Speak the right hello for who just showed up."""
    if is_online():
        res = vision.identify(shot, faces.ref_paths(), eyes)
        if res.get("person") and res.get("known"):
            speak("Welcome back, Boss.")
            return
        if res.get("person"):
            speak("Hello there. I don't think we've met.")
            return
        # person=None (cloud hiccup) or no person detected -> fall through generic
    speak("Oh — someone's here.")


def _confirm_left(shot, eyes, is_online, dark):
    """True if we're confident the space is now empty. Online we ASK before
    farewelling (avoid saying bye to someone sitting still); offline / dark we
    accept the motion evidence as best-effort."""
    if dark:
        return True
    if is_online():
        present = vision.person_present(shot, eyes)
        if present is True:
            return False                    # they're still there, just still
        if present is False:
            return True
    # offline or inconclusive: trust the stillness (best-effort departure)
    return True
