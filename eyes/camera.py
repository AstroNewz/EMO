"""
EMO — Eyes / Camera (snapshot capture)
======================================
A tiny, high-reliability wrapper around Termux:API's `termux-camera-photo`.
Pure standard library — no opencv / PIL / numpy (none of which pip-install on
Termux's Python 3.14). We just shell out to the camera bridge and hand back a
JPEG path; every heavier step (motion, vision) reads that file with ffmpeg.

Snapshots are written OUTSIDE the synced EMO folder (default `~/.emo_eyes/`) so
the delete-and-paste code sync never wipes them — the same rule the model files
and STT temp clips follow.

Public API:
    snapshot(cfg=None, camera_id=None, name="last") -> path | None
    available()                                     -> bool

Standalone test (writes a photo, prints the path; first run pops the Android
camera-permission prompt — tap Allow, then run it again):
    python eyes/camera.py
"""

import os
import sys
import shutil
import threading
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import section   # noqa: E402

# Default capture dir lives in Termux HOME (re-sync safe). Overridable via
# config `eyes.snapshot_dir`. Expanded with ~ at call time.
_DEFAULT_DIR = "~/.emo_eyes"

_lock = threading.Lock()
_warned = set()          # soft-fail: each problem is reported only once

# The phone can only open ONE camera at a time. This lock serialises every
# capture so the always-on ambient watcher and an on-request "what do you see"
# command never grab the camera simultaneously (which fails with camera-busy).
_capture_lock = threading.Lock()


def _warn_once(key, msg):
    with _lock:
        if key in _warned:
            return
        _warned.add(key)
    print(msg)


def available():
    """True if the Termux camera bridge is installed."""
    return shutil.which("termux-camera-photo") is not None


def _eyes_cfg(cfg):
    return cfg if isinstance(cfg, dict) else section("eyes", {})


def _snapshot_dir(cfg):
    d = _eyes_cfg(cfg).get("snapshot_dir", _DEFAULT_DIR)
    path = Path(os.path.expanduser(d))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _downscale(path, max_edge=512):
    """Shrink the JPEG in place so its LONGEST side is <= max_edge (aspect ratio
    kept, never upscaled). Camera frames are multi-MB; this strips ~90% of the
    bytes so the cloud POST doesn't time out and the local VLM decodes fast.
    Soft-fail: if ffmpeg is missing or errors, the original file is left as-is."""
    if not (max_edge and shutil.which("ffmpeg")):
        return
    src = Path(path)
    tmp = src.with_name(src.stem + ".small.jpg")
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "quiet", "-i", str(src),
             "-vf", f"scale='min({max_edge},iw)':'min({max_edge},ih)':"
                    "force_original_aspect_ratio=decrease",
             "-q:v", "5", str(tmp)],
            capture_output=True, timeout=15,
        )
        if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            os.replace(tmp, src)          # atomic overwrite of the raw capture
        else:
            tmp.unlink(missing_ok=True)
    except Exception:
        tmp.unlink(missing_ok=True)


def snapshot(cfg=None, camera_id=None, name="last"):
    """Capture one JPEG and return its path, or None on any failure.

    `camera_id` overrides `eyes.camera_id` (0 = back, 1 = front/selfie). `name`
    lets callers keep separate frames (e.g. presence uses its own slot so a
    command snapshot can't clobber the motion baseline). Never raises.
    """
    cfg = _eyes_cfg(cfg)
    if not available():
        _warn_once("_bridge", "[eyes] termux-camera-photo not found "
                             "(pkg install termux-api); camera disabled.")
        return None

    cam = str(camera_id if camera_id is not None else cfg.get("camera_id", 0))
    out = _snapshot_dir(cfg) / f"{name}.jpg"
    try:
        # termux-camera-photo is blocking; it opens the camera, captures, closes.
        # A generous timeout covers slow shutters without hanging the caller.
        # Held under _capture_lock so concurrent callers queue instead of
        # colliding on the single camera device.
        with _capture_lock:
            r = subprocess.run(
                ["termux-camera-photo", "-c", cam, str(out)],
                capture_output=True, text=True, timeout=30,
            )
    except subprocess.TimeoutExpired:
        _warn_once("_timeout", "[eyes] camera capture timed out.")
        return None
    except Exception as e:
        _warn_once("_spawn", f"[eyes] camera failed: {e}")
        return None

    # The bridge sometimes returns 0 but writes nothing if permission was just
    # granted, or prints an error to stdout. Trust the file, not the code.
    if not (out.exists() and out.stat().st_size > 0):
        detail = (r.stdout or r.stderr or "").strip()
        _warn_once("_empty", f"[eyes] no image written{': ' + detail if detail else ''} "
                            "(grant the Termux:API camera permission and retry).")
        return None
    _downscale(out, cfg.get("max_edge", 512))   # shrink before any VLM upload
    return str(out)


if __name__ == "__main__":
    print("[eyes] capturing... (first run pops the camera-permission prompt)")
    p = snapshot()
    print(f"[eyes] saved: {p}" if p else "[eyes] no photo (see message above).")
