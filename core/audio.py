"""
EMO — Audio / SFX reflex engine
===============================
Fire-and-forget 8-bit chiptune blips tied to state changes. Pure stdlib: each
cue is a DETACHED `play-audio sound/<name>.wav` via subprocess.Popen, so the
conversational loop never blocks on playback and never crashes when a clip or
the audio package is missing (it soft-fails and warns exactly once).

Drop your WAVs in  ~/storage/shared/EMO/sound/  (e.g. wake.wav, thinking.wav,
happy.wav, dizzy.wav). `play-audio` ships with Termux:API (pkg install
termux-api); termux-media-player / ffplay are used automatically if it's absent.
"""

import shutil
import threading
import subprocess
from pathlib import Path

# Sounds live INSIDE the synced EMO folder so they travel with the code. This
# resolves to ~/storage/shared/EMO/sound on the phone and Desktop\EMO\sound here.
SOUND_DIR = Path(__file__).resolve().parent.parent / "sound"

# Preferred player first; each is only used if it's actually on PATH.
_PLAYERS = (
    ["play-audio"],                                             # Termux:API (preferred)
    ["termux-media-player", "play"],                            # Termux:API fallback
    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],   # ffmpeg fallback
)

_lock = threading.Lock()
_warned = set()          # soft-fail: each missing piece is reported only once
_player = None           # resolved argv prefix, cached after first lookup


def _warn_once(key, msg):
    with _lock:
        if key in _warned:
            return
        _warned.add(key)
    print(msg)


def _resolve_player():
    global _player
    if _player is None:
        for argv in _PLAYERS:
            if shutil.which(argv[0]):
                _player = argv
                break
    return _player


def play_sfx(name):
    """Play sound/<name>.wav without blocking. Never raises."""
    argv = _resolve_player()
    if argv is None:
        _warn_once("_player", "[sfx] no audio player found "
                              "(pkg install termux-api for play-audio); sound muted.")
        return
    path = SOUND_DIR / f"{name}.wav"
    if not path.exists():
        _warn_once(name, f"[sfx] missing clip: {path} (skipped).")
        return
    try:
        subprocess.Popen(argv + [str(path)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        _warn_once("_spawn", f"[sfx] play failed: {e}")


def start_loop(name, period=0.9):
    """Fire <name>.wav every `period`s on a daemon thread until stopped.

    Returns a zero-arg stop() — call it to end the loop (e.g. when thinking is
    done). Plays the first blip immediately so the rhythm starts at once.
    """
    stop = threading.Event()

    def _run():
        while not stop.is_set():
            play_sfx(name)
            if stop.wait(period):        # sleeps `period`, returns True if stopped
                break

    threading.Thread(target=_run, daemon=True).start()
    return stop.set
