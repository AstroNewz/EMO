"""
EMO — Ears / Wake word (whisper.cpp keyword spotting)
=====================================================
Lets EMO sit quietly until it hears its wake word (default: "emo" / "hey emo"),
turning the assistant hands-free instead of recording on a rigid loop.

Why not Porcupine?  Picovoice ships only glibc `.so` files; they don't load
under Termux's bionic libc on Python 3.14 (the same native-wheel wall this
project keeps hitting). So instead of a new native dependency, we REUSE the
Slice-5 STT pipeline that already works on the phone:

    termux-microphone-record -> ffmpeg -> whisper-cli  (see ears/stt.py)

We record short chunks, transcribe them, and check whether the wake word
(or a phonetic look-alike) shows up. When it does, we return control to the
orchestrator, which then captures the actual command.

Trade-off: running whisper on every chunk is heavier than a tiny DSP wake
engine, so expect ~1-2s latency per check and some battery cost. Use a short
`record_seconds` and consider tiny.en to keep it snappy.

Standalone test (sleeps until it hears the wake word, then exits):
    python ears/wake.py
"""

import os
import re
import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import load_config   # noqa: E402
from ears import stt                  # noqa: E402  (shared continuous stream + whisper)


# Whisper hallucinates these on pure silence in quiet rooms, causing false
# wakes. Anything bracketed (e.g. "[MUSIC PLAYING]", "[wind]") or matching one
# of these stock phrases is treated as noise, not speech.
_BRACKETED = re.compile(r"\[.*?\]|\(.*?\)")
_HALLUCINATIONS = (
    "thanks for watching", "thank you for watching", "thanks for watching!",
    "thank you", "music playing", "music", "you", "subscribe",
    "please subscribe", "the end", "applause", "silence",
)


def is_hallucination(text):
    """True if `text` is empty or a known Whisper silence/non-speech artifact."""
    stripped = _BRACKETED.sub("", (text or "")).strip()
    if not stripped:                       # was ONLY brackets, or empty
        return True
    low = stripped.lower().strip(" .!?,")
    return low in _HALLUCINATIONS


def _keywords(wcfg):
    """The set of spoken strings that count as the wake word."""
    keyword = (wcfg.get("keyword") or "emo").strip().lower()
    aliases = [a.strip().lower() for a in (wcfg.get("aliases") or []) if a.strip()]
    # De-dup while preserving the primary keyword first.
    out = [keyword]
    for a in aliases:
        if a not in out:
            out.append(a)
    return out


# Fuzzy phonetic guard. In room noise whisper warps the short wake word "emo"
# into look-alikes ("imo", "eemo", "heymo", "amoe", "emu", "immo", "emo."). Any
# TOKEN that BEGINS with one of these stems counts as a wake, so those mis-hearings
# no longer drop the command. Case-insensitive; punctuation is already stripped by
# the tokenizer below. This matcher is shared by wake.py AND the orchestrator.
_WAKE_RE = re.compile(r"^(emo|imo|eemo|heymo|amoe|emu|immo)", re.IGNORECASE)


def _matches(text, keywords):
    """True if `text` contains the wake word, a configured alias, or a phonetic
    look-alike (fuzzy guard)."""
    low = text.lower()
    words = re.findall(r"[a-z']+", low)
    wordset = set(words)
    # 1) Fuzzy phonetic stems — primary guard against noisy mis-hearings.
    for w in words:
        if _WAKE_RE.match(w):
            return True
    # 2) Configured keyword/aliases (handles multi-word phrases like "hey emo").
    for kw in keywords:
        if " " in kw:               # multi-word phrase: substring match
            if kw in low:
                return True
        elif kw in wordset:         # single word: must be a standalone token
            return True
    return False


def wait_for_wake_word(config=None):
    """
    Block until the wake word is heard, then return True.

    Returns:
        True  — a genuine wake word was heard (caller may play a chirp, etc.).
        None  — the wake gate is disabled or unavailable; proceed WITHOUT a
                chirp (EMO still captures a command, as in the old loop).
        False — interrupted (Ctrl-C); the caller should shut down.
    """
    config = config if config is not None else load_config()
    wcfg = config.get("ears", {}).get("wake_word", {})
    stt_cfg = config.get("ears", {}).get("stt", {})

    # Wake gating turned off in config → behave like the old always-listen loop.
    if not wcfg.get("enabled", True):
        return None

    keywords = _keywords(wcfg)
    seconds = int(wcfg.get("record_seconds", 2))

    # Preflight: if the mic or whisper aren't there, DON'T spin forever printing
    # errors — degrade to "no wake gate" so EMO still works.
    if shutil.which("termux-microphone-record") is None:
        print("[wake] mic not available; skipping wake gate.")
        return None
    binary = stt_cfg.get("binary", "")
    model = stt_cfg.get("model", "")
    if not (binary and os.path.exists(binary) and model and os.path.exists(model)):
        print("[wake] whisper binary/model not found; skipping wake gate.")
        return None

    # Reuse the always-hot STT stream: pull fresh ~`seconds` windows and match.
    if not stt.start_stream():
        print("[wake] could not start mic stream; skipping wake gate.")
        return None

    print(f"[wake] sleeping — say '{keywords[0]}' to wake me...")
    try:
        while True:
            text = stt.next_window(seconds, stt_cfg)
            if not text or is_hallucination(text):
                continue                        # silence/noise — keep sleeping
            # Show what whisper heard so you can tune `keyword`/`aliases`.
            print(f"[wake] heard: {text!r}")
            if _matches(text, keywords):
                print("[wake] wake word matched!")
                return True
            # Heard speech but not the wake word — stay asleep.
    except KeyboardInterrupt:
        return False


if __name__ == "__main__":
    woke = wait_for_wake_word()
    if woke is True:
        print("[wake] awake!")
    elif woke is False:
        print("[wake] interrupted.")
    else:
        print("[wake] gate disabled/unavailable — nothing to wait for.")
