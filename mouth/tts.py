"""
EMO — Mouth / Text-to-Speech
============================
Speaks text out loud. Backend is swappable via config.yaml (mouth.engine):

  sherpa  -> sherpa-onnx offline neural TTS (VITS/piper voice). Built from source
             in Termux so it runs on bionic libc natively (no glibc shim). This is
             the recommended natural voice. Synthesizes a WAV, then plays it.
  piper   -> piper-tts. REALISTIC male neural voice, fully offline. Needs a
             one-time model download (see config.yaml). The native piper binary is
             glibc-linked, so under Termux's bionic libc it usually WON'T launch —
             which is why sherpa is now the default. Kept as a fallback rung.
  termux  -> termux-tts-speak (phone's built-in system TTS via Termux:API).
             Zero setup, but usually Google TTS (the robotic voice).
  espeak  -> espeak-ng (robotic but tiny/offline).  pkg install espeak-ng

Fallback ladder: sherpa -> piper -> termux, so EMO always talks even if the
neural voice isn't set up yet.

The orchestrator calls speak(text). Every backend BLOCKS until the phone
finishes speaking, which is exactly the sequencing we want (the face shows
"speaking" for the whole duration).

Test standalone:
    python mouth/tts.py "Hello, I am EMO."
"""

import os
import sys
import shutil
import threading
import subprocess
from pathlib import Path

# Make 'core' importable when this file is run directly from the project root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import section  # noqa: E402

# Scratch space for synthesized audio. Termux has no /tmp — honor $TMPDIR.
TMP = os.environ.get("TMPDIR", str(Path.home()))


# --- Interruptible playback ---------------------------------------------------
# The dizzy / face-down reflexes must be able to CUT OFF speech mid-sentence, so
# every backend runs its blocking player through a tracked subprocess that stop()
# can terminate. `_stopped` distinguishes a deliberate interrupt from a real
# failure, so we never noisily "fall back" to another engine after a stop.
_active_lock = threading.Lock()
_active_proc = None
_stopped = threading.Event()


def _run_tracked(cmd, timeout=None, input_bytes=None, env=None):
    """Run `cmd` to completion, registered so stop() can kill it mid-playback.

    Returns the process return code. Re-raises TimeoutExpired / FileNotFoundError
    exactly like subprocess would, so callers keep their existing handling.
    `env` (if given) is passed straight to Popen — used to inject LD_LIBRARY_PATH
    for the glibc/shared-lib sherpa-onnx binary.
    """
    global _active_proc
    proc = subprocess.Popen(
        cmd,
        stdin=(subprocess.PIPE if input_bytes is not None else None),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=env,
    )
    with _active_lock:
        _active_proc = proc
    try:
        proc.communicate(input=input_bytes, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise
    finally:
        with _active_lock:
            if _active_proc is proc:
                _active_proc = None
    return proc.returncode


def stop():
    """Cut off any in-progress speech immediately (used by the dizzy/asleep
    reflexes). Safe to call when nothing is speaking."""
    _stopped.set()
    with _active_lock:
        proc = _active_proc
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception:
            pass


def _speak_termux(text, cfg, on_audio_start=None):
    """
    Speak via the phone's built-in system TTS. Blocks until playback finishes.

    Reads optional flags straight from the mouth config so you can push the OS
    engine toward a deeper / male timbre or a different installed voice:
        rate     -> -r   speech rate multiplier
        pitch    -> -p   lower = deeper (the main "male" lever for Google TTS)
        language -> -l   locale, e.g. en-US
        voice    -> -n   system voice / region variant name (if your engine has one)
        stream   -> -s   audio stream (True == "MUSIC", or a name like "NOTIFICATION")
    Anything left blank/false is simply omitted, so old configs still work.
    """
    if shutil.which("termux-tts-speak") is None:
        print("[tts] termux-tts-speak not found. Install: pkg install termux-api "
              "(and the Termux:API app from F-Droid).")
        return False

    rate = cfg.get("rate", 1.0)
    pitch = cfg.get("pitch", 1.0)
    language = (cfg.get("language") or "").strip()
    voice = (cfg.get("voice") or "").strip()
    stream = cfg.get("stream", False)

    cmd = ["termux-tts-speak", "-r", str(rate), "-p", str(pitch)]
    if language:
        cmd += ["-l", language]
    if voice:
        cmd += ["-n", voice]
    if stream:
        cmd += ["-s", stream if isinstance(stream, str) else "MUSIC"]
    cmd.append(text)

    # Timeout scales with text length so long replies aren't cut off, but a
    # dead bridge can't hang EMO forever.
    timeout = max(20, len(text) // 8)
    if on_audio_start:                       # termux speaks immediately, no synth gap
        on_audio_start()
    try:
        rc = _run_tracked(cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"[tts] termux-tts-speak hung for {timeout}s and was killed. "
              "The Termux:API app or the phone's TTS engine isn't responding.")
        return False
    if _stopped.is_set():
        return False                     # deliberately interrupted by a reflex
    if rc != 0:
        print(f"[tts] termux-tts-speak failed: exit {rc}")
        return False
    return True


def _speak_espeak(text, rate, on_audio_start=None):
    """Lightweight offline fallback. pkg install espeak-ng"""
    if shutil.which("espeak-ng") is None:
        print("[tts] espeak-ng not found. Install: pkg install espeak-ng")
        return False
    # espeak-ng speed is words-per-minute; map our ~1.0 multiplier to ~175 wpm.
    wpm = int(175 * float(rate))
    if on_audio_start:
        on_audio_start()
    try:
        rc = _run_tracked(["espeak-ng", "-s", str(wpm), text])
    except Exception as e:
        print(f"[tts] espeak-ng failed: {e}")
        return False
    if _stopped.is_set():
        return False
    if rc != 0:
        print(f"[tts] espeak-ng failed: exit {rc}")
        return False
    return True


def _play_wav(path):
    """Play a WAV and BLOCK until it finishes (keeps the 'speaking' face honest)."""
    if not os.path.exists(path):
        return False
    if shutil.which("ffplay"):                       # exact duration, clean exit
        cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path]
    elif shutil.which("termux-media-player"):        # Termux:API fallback
        cmd = ["termux-media-player", "play", path]
    else:
        print("[tts] no audio player found (install ffmpeg for ffplay, "
              "or termux-api for termux-media-player).")
        return False
    try:
        rc = _run_tracked(cmd, timeout=180)
    except Exception as e:
        if _stopped.is_set():
            return False                 # killed by a reflex, not a real failure
        print(f"[tts] playback failed: {e}")
        return False
    if _stopped.is_set():
        return False
    return rc == 0


def _speak_sherpa(text, cfg, on_audio_start=None):
    """
    Natural neural TTS via sherpa-onnx (built from source in Termux — bionic-safe,
    unlike the glibc piper binary). Synthesizes a WAV with the offline-tts CLI,
    then plays it through the shared killable player.

    `on_audio_start` (if given) fires the instant real playback begins — AFTER the
    silent synthesis step — so the caller can flip the face to 'speaking' in sync
    with actual sound instead of during the synth gap (fixes the speech/visual lag).

    Falls back to piper (which itself falls back to termux) if the binary or the
    voice model isn't set up yet, so EMO always talks. Reads `mouth.sherpa`:
        binary   -> absolute path to sherpa-onnx-offline-tts
        lib_dir  -> dir of the shared .so's (added to LD_LIBRARY_PATH at launch)
        model    -> the VITS .onnx voice model
        tokens   -> its tokens.txt
        data_dir -> the shared espeak-ng-data/ directory
        speed    -> optional speaking-rate multiplier (>1 faster, <1 slower)
        sid      -> optional speaker id for MULTI-speaker models (e.g. a child
                    voice in libritts_r); omitted for single-speaker voices
    """
    sh = cfg.get("sherpa", {}) or {}
    binary = sh.get("binary") or "sherpa-onnx-offline-tts"
    model = sh.get("model") or ""
    tokens = sh.get("tokens") or ""
    data_dir = sh.get("data_dir") or ""

    resolved = binary if os.path.isabs(binary) else shutil.which(binary)
    if not (resolved and os.path.exists(resolved)) or not (model and os.path.exists(model)):
        print("[tts] sherpa-onnx or its voice model isn't set up yet; using piper. "
              "(See INSTALL.md for the one-time build + voice download.)")
        return _speak_piper(text, cfg, on_audio_start)

    wav = os.path.join(TMP, "emo_tts.wav")
    cmd = [resolved, f"--vits-model={model}"]
    if tokens:
        cmd.append(f"--vits-tokens={tokens}")
    if data_dir:
        cmd.append(f"--vits-data-dir={data_dir}")
    # Parallelise the neural synthesis across the phone's big cores — the single
    # biggest speed lever (sherpa defaults to ~1-2 threads, wasting an 8-core CPU).
    threads = sh.get("num_threads")
    if threads:
        cmd.append(f"--num-threads={int(threads)}")
    if sh.get("speed") is not None:
        cmd.append(f"--vits-length-scale={1.0 / float(sh['speed']):g}")  # speed>1 => shorter
    if sh.get("sid") is not None:                    # multi-speaker models: pick a voice
        cmd.append(f"--sid={int(sh['sid'])}")        # e.g. a child speaker in libritts_r
    cmd.append(f"--output-filename={wav}")
    cmd.append(text)

    # Inject LD_LIBRARY_PATH for the shared-lib build (same gotcha as llama-server).
    env = None
    lib_dir = sh.get("lib_dir")
    if lib_dir:
        env = dict(os.environ)
        lib_dir = os.path.expanduser(lib_dir)
        env["LD_LIBRARY_PATH"] = (lib_dir + os.pathsep + env["LD_LIBRARY_PATH"]
                                  if env.get("LD_LIBRARY_PATH") else lib_dir)

    try:
        rc = _run_tracked(cmd, timeout=max(30, len(text) // 3), env=env)
    except Exception as e:
        if _stopped.is_set():
            return False                 # interrupted mid-synthesis, not a failure
        print(f"[tts] sherpa synthesis failed ({e}); falling back to piper.")
        return _speak_piper(text, cfg, on_audio_start)
    if _stopped.is_set():
        return False
    if rc != 0:
        print(f"[tts] sherpa synthesis failed (exit {rc}); falling back to piper.")
        return _speak_piper(text, cfg, on_audio_start)

    if on_audio_start:
        on_audio_start()                 # synth done — audio starts NOW; sync the face
    if not _play_wav(wav):
        if _stopped.is_set():
            return False
        return _speak_piper(text, cfg, on_audio_start)
    return True


def _speak_piper(text, cfg, on_audio_start=None):
    """
    Realistic offline neural TTS via piper. Synthesizes to a WAV, then plays it.
    Falls back to the termux engine if piper or its voice model isn't set up yet,
    so EMO always talks. `on_audio_start` fires when real playback begins.
    """
    piper = cfg.get("piper", {}) or {}
    binary = piper.get("binary") or "piper"
    model = piper.get("model") or ""

    if shutil.which(binary) is None or not (model and os.path.exists(model)):
        print("[tts] piper or its voice model isn't set up yet; using termux. "
              "(See config.yaml mouth.piper for the one-time download.)")
        return _speak_termux(text, cfg, on_audio_start)

    wav = os.path.join(TMP, "emo_tts.wav")
    pcmd = [binary, "--model", model, "--output_file", wav]
    if piper.get("length_scale") is not None:        # >1 slower/deeper, <1 faster
        pcmd += ["--length_scale", str(piper["length_scale"])]
    if piper.get("speaker") is not None:             # multi-speaker models only
        pcmd += ["--speaker", str(piper["speaker"])]

    try:
        rc = _run_tracked(pcmd, timeout=max(30, len(text) // 4),
                          input_bytes=text.encode("utf-8"))
    except Exception as e:
        if _stopped.is_set():
            return False                 # interrupted mid-synthesis, not a failure
        print(f"[tts] piper synthesis failed ({e}); falling back to termux.")
        return _speak_termux(text, cfg, on_audio_start)
    if _stopped.is_set():
        return False
    if rc != 0:
        print(f"[tts] piper synthesis failed (exit {rc}); falling back to termux.")
        return _speak_termux(text, cfg, on_audio_start)

    if on_audio_start:
        on_audio_start()
    if not _play_wav(wav):
        if _stopped.is_set():
            return False
        return _speak_termux(text, cfg, on_audio_start)
    return True


def speak(text, cfg=None, on_audio_start=None):
    """
    Speak `text` out loud using the configured backend.
    Returns True on success, False if the backend was unavailable.
    """
    if not text or not text.strip():
        return False

    _stopped.clear()                     # fresh utterance; arm interrupt tracking
    cfg = cfg if cfg is not None else section("mouth", {})
    engine = (cfg.get("engine") or "termux").lower()

    if engine == "termux":
        ok = _speak_termux(text, cfg, on_audio_start)
    elif engine == "espeak":
        ok = _speak_espeak(text, cfg.get("rate", 1.0), on_audio_start)
    elif engine == "sherpa":
        ok = _speak_sherpa(text, cfg, on_audio_start)
    elif engine == "piper":
        ok = _speak_piper(text, cfg, on_audio_start)
    else:
        print(f"[tts] unknown engine '{engine}', using termux.")
        ok = _speak_termux(text, cfg, on_audio_start)

    if _stopped.is_set():                # a reflex cut this utterance off — that's
        return True                      # intentional, so don't retry another engine
    # Last-ditch fallback: if the chosen engine wasn't available, try termux.
    if not ok and engine != "termux":
        print("[tts] falling back to termux engine.")
        ok = _speak_termux(text, cfg, on_audio_start)
    return ok


if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]) or "Hello, I am EMO. Your phone can talk now."
    print(f"[tts] speaking: {msg!r}")
    success = speak(msg)
    print("[tts] done." if success else "[tts] FAILED — see messages above.")
    sys.exit(0 if success else 1)
