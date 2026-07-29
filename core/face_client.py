"""
EMO — Face client
=================
Tiny helper to change EMO's on-screen expression by POSTing to the face server.
Used by the orchestrator. Fails quietly if the face server isn't running, so a
missing face never crashes the main loop.
"""

import json
import urllib.request

from core.config import section

_FACE = section("face", {})
_BASE = f"http://{_FACE.get('host', '127.0.0.1')}:{_FACE.get('port', 8008)}"

VALID = {
    "idle", "listening", "thinking", "speaking",
    "happy", "excited", "confused", "curious",
    "surprised", "sad", "angry", "error"
}


def set_state(state):
    """Set EMO's face expression. Returns True on success, False otherwise."""
    if state not in VALID:
        return False
    try:
        data = json.dumps({"state": state}).encode()
        req = urllib.request.Request(
            _BASE + "/state", data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=2):
            return True
    except Exception:
        return False   # face server not up yet — that's fine


def get_wish():
    """
    Read the user's on-screen button intent: "listen" (tapped) or "sleep".
    This is the browser -> orchestrator channel. Returns "sleep" if the face
    server is unreachable, so a missing face never traps EMO in listening.
    """
    try:
        with urllib.request.urlopen(_BASE + "/wish", timeout=2) as r:
            return (json.loads(r.read().decode()) or {}).get("wish", "sleep")
    except Exception:
        return "sleep"


def get_event():
    """
    Read (and consume) a pending one-shot browser reflex, e.g. "dizzy" when the
    screen is rotated. The server clears the event on read, so each event is
    returned exactly once. Returns "" if nothing is pending or the face is down.
    """
    try:
        with urllib.request.urlopen(_BASE + "/event", timeout=2) as r:
            return (json.loads(r.read().decode()) or {}).get("event", "") or ""
    except Exception:
        return ""


def set_wish(wish):
    """Set the control wish ("listen"/"sleep"). Orchestrator uses this to reset
    the flag once a mic session is consumed. Fails quietly if the face is down."""
    if wish not in ("listen", "sleep"):
        return False
    try:
        data = json.dumps({"wish": wish}).encode()
        req = urllib.request.Request(
            _BASE + "/wish", data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=2):
            return True
    except Exception:
        return False
