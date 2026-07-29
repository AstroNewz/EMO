"""
EMO — Eyes / Ambient (always-on dual-camera awareness)
======================================================
The "keep your eyes open" daemon. Unlike `presence.py` (a battery-thrifty motion
gate on ONE camera), this one runs the vision model CONTINUOUSLY across BOTH
cameras and narrates the world as it changes — the "EMO is always watching" mode.

Hardware truth: the phone can only open one camera at a time, so we ALTERNATE —
snap the back camera, understand it, snap the front camera, understand it, repeat
as fast as inference allows. That's as close to "both at once" as Termux permits.

Battery/shutter truth: this is deliberately heavy (a VLM call per frame, a real
shutter each shot). It exists because the user asked for full-continuous eyes;
`eyes.ambient.enabled: false` turns it back off.

How "speak on change" works: each camera's fresh description is compared to its
previous one with stdlib `difflib`. Similar enough -> stay quiet (nothing new).
Different enough -> announce it (rate-limited per camera). The first thing each
camera ever sees is announced once, so EMO tells you what's around on startup.

Public API:
    watch(config, speak, is_online=None, busy=None, stop_event=None)
        -> runs forever (start it on a daemon thread). Fully guarded.
    current_scene() -> {cam_id: {"text": str, "ts": float}}
        -> latest per-camera understanding (handy if you later want to feed it
           to the brain as context).
"""

import sys
import time
import difflib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eyes import camera, vision            # noqa: E402
from eyes.presence import _gray_frame, _mean   # noqa: E402  (reuse frame helpers)

# Latest understanding per camera, exposed via current_scene(). Written by the
# watch loop; read-only for callers.
_scene = {}


def current_scene():
    """Return a shallow copy of the latest per-camera descriptions."""
    return dict(_scene)


def _label(labels, cam_id, default):
    """Config may key `labels` by int (YAML `0:`) or str; accept either."""
    if isinstance(labels, dict):
        if cam_id in labels:
            return labels[cam_id]
        if str(cam_id) in labels:
            return labels[str(cam_id)]
    return default


_DEFAULT_LABELS = {0: "Behind me, I can see", 1: "In front of me, I can see"}


def _changed(new, old, ratio):
    """True if `new` is different enough from `old` to be worth announcing.
    Uses difflib similarity: below `ratio` similar = changed. Empty `old`
    (first observation) counts as changed so the initial scene is announced."""
    new = (new or "").strip()
    if not new:
        return False
    if not (old or "").strip():
        return True
    return difflib.SequenceMatcher(None, new.lower(), old.lower()).ratio() < ratio


def watch(config, speak, is_online=None, busy=None, stop_event=None):
    """Continuous dual-camera narration loop. `speak(text)` MUST be the
    orchestrator's serialised speaker. `busy()` -> bool suppresses the whole
    cycle (capture + inference + speech) while EMO is mid-conversation, so the
    eyes never fight the ears for the camera/CPU or talk over a reply.
    `is_online()` lets us skip the wasted cloud round-trip when we're offline and
    have no local vision server to fall back to. `stop_event` ends the loop."""
    eyes = (config or {}).get("eyes", {})
    ac = eyes.get("ambient", {})
    if not ac.get("enabled", False):
        return
    if not camera.available():
        print("[ambient] camera bridge not found; ambient eyes disabled.")
        return

    cameras = ac.get("cameras", [0, 1]) or [0, 1]
    interval = float(ac.get("interval_seconds", 2))
    change_ratio = float(ac.get("change_ratio", 0.6))
    cooldown = float(ac.get("announce_cooldown", 20))
    labels = ac.get("labels", _DEFAULT_LABELS)
    prompt = ac.get("prompt", "Describe what is visible in one short spoken sentence.")

    is_online = is_online or (lambda: True)
    busy = busy or (lambda: False)
    local_on = eyes.get("vision", {}).get("local", {}).get("enabled", False)

    def _stopped():
        return bool(stop_event and stop_event.is_set())

    last_desc = {}          # cam_id -> last description we compared against
    last_spoke = {}         # cam_id -> monotonic time we last announced
    warned_offline = False

    print(f"[ambient] watching cameras {cameras} continuously "
          f"(interval {interval:.0f}s, change<{change_ratio}).")

    while not _stopped():
        # Hush entirely during a conversation — free the camera and stay quiet.
        if busy():
            time.sleep(0.5)
            continue

        # No internet AND no local vision server => nothing can answer; idle
        # cheaply instead of burning a full cloud timeout on every frame.
        if not is_online() and not local_on:
            if not warned_offline:
                print("[ambient] offline and no local vision server — idling.")
                warned_offline = True
            time.sleep(max(interval, 2))
            continue
        warned_offline = False

        for cam_id in cameras:
            if _stopped() or busy():
                break

            shot = camera.snapshot(eyes, camera_id=cam_id, name=f"ambient_{cam_id}")
            if not shot:
                continue                       # transient capture miss — skip

            # Cheap covered/dark-lens check (optional; needs ffmpeg). If ffmpeg
            # is absent _gray_frame returns b'' and we just skip the check.
            frame = _gray_frame(shot)
            if frame and _mean(frame) < 8:
                continue                       # lens covered / lights off — nothing to see

            desc = vision.describe(shot, prompt, eyes)
            if not desc:
                continue                       # both vision backends failed this frame

            _scene[cam_id] = {"text": desc, "ts": time.time()}

            now = time.monotonic()
            fresh = _changed(desc, last_desc.get(cam_id, ""), change_ratio)
            last_desc[cam_id] = desc
            if fresh and (now - last_spoke.get(cam_id, 0.0)) >= cooldown and not busy():
                last_spoke[cam_id] = now
                label = _label(labels, cam_id, f"Camera {cam_id} sees")
                speak(f"{label} {desc}")

        # Pace the loop. interval=0 means back-to-back (inference latency paces it).
        if interval > 0:
            for _ in range(int(max(1, interval / 0.5))):
                if _stopped():
                    return
                time.sleep(0.5)


if __name__ == "__main__":
    # Standalone check: narrate both cameras for a short while, printing instead
    # of speaking. First run pops the Android camera-permission prompt.
    import threading
    from core.config import load_config

    cfg = load_config()
    # Force-enable ambient for the manual test even if config has it off.
    cfg.setdefault("eyes", {}).setdefault("ambient", {})["enabled"] = True
    stop = threading.Event()
    t = threading.Thread(
        target=watch,
        args=(cfg, lambda s: print(f"[ambient/say] {s}")),
        kwargs={"stop_event": stop},
        daemon=True,
    )
    t.start()
    print("[ambient] running ~60s — move things / cover a lens to see changes. Ctrl-C to stop.")
    try:
        time.sleep(60)
    except KeyboardInterrupt:
        pass
    stop.set()
    t.join(timeout=3)
    print("[ambient] done.")
