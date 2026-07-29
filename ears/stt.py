"""
EMO — Ears / Speech-to-Text  (instant-flush, on-demand VAD)
===========================================================
A simple, high-reliability listening pipeline. There is NO always-hot mic and
NO background producer thread: `capture_utterance()` records short finalized
clips on demand, watches their energy for a silence tail, and stops the instant
you go quiet, then hands the joined audio to whisper.

Why chunks instead of one growing file (Termux hard limits, learned on-device)
------------------------------------------------------------------------------
`termux-microphone-record` wraps Android MediaRecorder: it writes an ENCODED
container to a FILE and cannot pipe raw PCM to /dev/stdout. And Python 3.13+
REMOVED `audioop`, so there is no `audioop.rms()`. We first tried decoding a
single GROWING file for energy, but many ROMs (this one included) write an MP4
container for `.aac`, whose "moov" atom is only written on stop — so a growing
clip cannot be decoded mid-record. The robust, ROM-agnostic fix: record a series
of SHORT clips, each fully finalized before we read it, decode each in one clean
ffmpeg pass to PCM, and compute RMS in pure stdlib (`array`). That energy drives
the endpointer; the utterance's PCM is joined and written to a WAV for whisper.

Public API:
    capture_utterance(on_captured, on_speech, preroll)  -> transcript ("" = nothing)
    stop()                                              -> cancel the live capture
    next_window(seconds, cfg)                           -> fixed chunk (wake spotting)
    start_stream()/stop_stream()/stream_active()/reset_wake_cursor()  -> compat shims

Standalone test (records, endpoints on silence, prints what it heard):
    python ears/stt.py

Requires (see INSTALL.md Slice 5): Termux:API app (mic), ffmpeg, whisper.cpp.
"""

import os
import sys
import math
import time
import wave
import array
import shutil
import threading
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import section   # noqa: E402

TMP = os.environ.get("TMPDIR", str(Path.home()))
SR = 16000                                     # whisper wants 16kHz mono
SEG_AAC = os.path.join(TMP, "emo_seg.aac")     # one finalized VAD chunk
REC_WAV = os.path.join(TMP, "emo_rec.wav")     # joined clip handed to whisper
WAKE_AAC = os.path.join(TMP, "emo_wake.aac")   # short wake-spotting chunk

# whisper prints these for silence/non-speech — treat them as "heard nothing".
_NOISE_TOKENS = {"[blank_audio]", "[silence]", "(silence)", "[ inaudible ]",
                 "[music]", "[ music ]", "you", ""}

# Handle to the in-flight whisper process so stop() (the UI's second tap) can
# KILL it mid-decode instead of waiting the transcription out.
_proc_lock = threading.Lock()
_active_proc = None

# Tripped by stop() to cancel the current capture (recording or decode).
_abort = threading.Event()

# --- Native MediaRecorder lifecycle guard ------------------------------------
# Android's MediaRecorder throws `java.lang.RuntimeException: stop failed` if
# stop() lands before the hardware encoder has finished spinning up — and on some
# ROMs (e.g. vivo/MediaTek) that crash takes the whole Termux:API service down.
# We stamp the spawn time and refuse to release the mic until MIC_INIT_GUARD has
# elapsed. Config-overridable via ears.stt.mic_init_guard for slow-mic devices.
try:
    MIC_INIT_GUARD = float(section("ears", {}).get("stt", {}).get("mic_init_guard", 0.8))
except Exception:
    MIC_INIT_GUARD = 0.8
_spawn_lock = threading.Lock()
_spawn_ts = 0.0


def _run(cmd, timeout=None):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _stt_cfg():
    return section("ears", {}).get("stt", {})


def _mark_spawn():
    global _spawn_ts
    with _spawn_lock:
        _spawn_ts = time.monotonic()


def _await_hw_ready():
    with _spawn_lock:
        spawned = _spawn_ts
    if not spawned:
        return
    remaining = MIC_INIT_GUARD - (time.monotonic() - spawned)
    while remaining > 0:
        time.sleep(min(0.02, remaining))
        remaining = MIC_INIT_GUARD - (time.monotonic() - spawned)


def _stop_mic():
    """Stop the active recording / release the mic, after the init guard clears."""
    if shutil.which("termux-microphone-record") is None:
        return
    _await_hw_ready()
    _run(["termux-microphone-record", "-q"])
    global _spawn_ts
    with _spawn_lock:
        _spawn_ts = 0.0


def _start_recorder(path):
    """Spawn ONE clean recording into `path`. Returns True on start."""
    try:
        os.remove(path)
    except OSError:
        pass
    _stop_mic()                                # free the mic from any prior session
    st = _run(["termux-microphone-record", "-f", path, "-r", str(SR), "-c", "1"])
    if st.returncode != 0:
        print(f"[stt] mic failed to start: {st.stdout} {st.stderr}")
        return False
    _mark_spawn()
    return True


def _record_chunk(path, seconds):
    """Record ONE finalized clip of ~`seconds` into `path`. False on abort/failure.

    We start the recorder, sleep for the chunk length (bailing early if stop() is
    called), then stop the mic so the container is fully finalized on disk — ready
    for a clean decode. Returns True only if a complete chunk was captured.
    """
    if not _start_recorder(path):
        return False
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if _abort.is_set():
            _stop_mic()
            return False
        time.sleep(0.02)
    _stop_mic()
    return True


# --- energy (pure stdlib; audioop is gone in py3.13+) -------------------------
def _rms(pcm):
    """RMS amplitude of signed 16-bit little-endian mono PCM."""
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    samples = array.array("h")
    samples.frombytes(pcm[: n * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    return math.sqrt(sum(v * v for v in samples) / n)


def _decode_pcm(path):
    """One clean ffmpeg pass: a FINALIZED clip -> raw s16le mono 16kHz PCM bytes.

    Works regardless of container (ADTS .aac or MP4-in-.aac) because the file is
    always complete before we read it. Returns b"" on any failure.
    """
    if not (os.path.exists(path) and os.path.getsize(path) > 0):
        return b""
    if shutil.which("ffmpeg") is None:
        print("[stt] ffmpeg not found. Install: pkg install ffmpeg")
        return b""
    try:
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "quiet", "-i", path,
             "-ac", "1", "-ar", str(SR), "-f", "s16le", "pipe:1"],
            capture_output=True, timeout=30,
        )
        return p.stdout or b""
    except Exception:
        return b""


def _write_wav(pcm, path=REC_WAV):
    """Write 16kHz mono s16le PCM to a WAV file for whisper."""
    if not pcm:
        return False
    try:
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm)
    except Exception:
        return False
    return True


# ==========================================================================
# Capture — instant-flush, VAD-endpointed utterance (finalized-chunk VAD)
# ==========================================================================
def _capture_single(cfg, on_captured=None, on_speech=None):
    """Gap-free capture: record ONE continuous clip, then transcribe it whole.

    Why: `termux-microphone-record` can only hand us audio once it STOPS, so the
    chunked VAD path restarts the mic between chunks — and each restart is a
    ~0.5s dead zone that clips words (the cause of the inconsistent, half-dropped
    transcripts on this ROM). Recording the whole utterance in ONE session has
    NO internal gaps, so nothing is lost. whisper handles any trailing silence.

    Trade-off: no dynamic silence endpoint — the turn runs the full `single_seconds`
    window (a second tap / stop() ends it early). Returns the transcript, or "".
    """
    dur = float(cfg.get("single_seconds", 6.0))
    _abort.clear()
    if not _start_recorder(SEG_AAC):
        return ""
    if on_speech:
        on_speech()                       # onset unknown in single mode; flag now
    end = time.monotonic() + dur
    while time.monotonic() < end:
        if _abort.is_set():
            break                         # tap / stop() -> end early, keep audio
        time.sleep(0.05)
    _stop_mic()                           # finalize the container for a clean decode
    if _abort.is_set():
        return ""                         # tap during capture = cancel (as before)
    if on_captured:
        on_captured()
    pcm = _decode_pcm(SEG_AAC)
    if not pcm:
        print("[stt] single-clip won't decode — check ffmpeg / Termux:API mic.")
        return ""
    if not _write_wav(pcm):
        return ""
    return _transcribe_wav(cfg, REC_WAV)


def capture_utterance(on_captured=None, on_speech=None, preroll=None):
    """Record one utterance, ending on `silence_tail` seconds of quiet.

    Records short finalized clips back-to-back, decoding each for RMS energy. It
    starts collecting at speech onset (keeping one chunk of pre-roll so the onset
    isn't clipped) and stops the instant a trailing silence is detected OR stop()
    is called. Then it joins the captured PCM and runs whisper. `on_speech` fires
    at detected onset; `on_captured` fires the moment we stop recording (before
    the whisper decode) so the UI can flip to 'thinking'. `preroll` is accepted
    for call-site compatibility. Returns the transcript, or "" for silence /
    nothing / an aborted capture.
    """
    cfg = _stt_cfg()
    if shutil.which("termux-microphone-record") is None:
        print("[stt] mic not available.")
        return ""

    # capture_mode: "single" = one gap-free clip (no dropped words on ROMs whose
    # mic restart clips audio — the reliable default); "chunk" = the older VAD-
    # endpointed finalized-chunk path (dynamic silence stop, but gap-prone).
    if (cfg.get("capture_mode") or "single").lower() == "single":
        return _capture_single(cfg, on_captured=on_captured, on_speech=on_speech)

    seg = float(cfg.get("segment_seconds", 0.7))          # per-chunk length (VAD granularity)
    silence_tail = float(cfg.get("silence_tail", 1.5))
    max_utt = float(cfg.get("max_utterance", 30))
    onset_timeout = float(cfg.get("onset_timeout", 10))
    factor = float(cfg.get("vad_factor", 2.5))
    min_rms = float(cfg.get("vad_min_rms", 350))

    _abort.clear()
    floor = None
    started = False
    collected = []
    preroll_pcm = b""
    silence = 0.0
    waited = 0.0
    total = 0.0
    dead = 0

    while not _abort.is_set():
        if not _record_chunk(SEG_AAC, seg):
            break                                          # aborted or mic failed
        pcm = _decode_pcm(SEG_AAC)
        if not pcm:
            dead += 1
            if dead >= 3:
                print("[stt] ERROR: mic clips won't decode — check ffmpeg / Termux:API mic.")
                break
            continue
        dead = 0

        rms = _rms(pcm)
        dur = (len(pcm) // 2) / SR or seg
        if not started:
            floor = rms if floor is None else 0.9 * floor + 0.1 * rms
            if rms > max(min_rms, floor * factor):
                started = True
                collected = [preroll_pcm, pcm]             # seed with 1 chunk of pre-roll
                if on_speech:
                    on_speech()
            else:
                preroll_pcm = pcm                          # rolling 1-chunk lookback
                waited += dur
                if waited > onset_timeout:
                    break                                  # nobody spoke
        else:
            collected.append(pcm)
            if rms > max(min_rms, (floor or 0.0) * factor):
                silence = 0.0
            else:
                silence += dur
                if silence >= silence_tail:
                    break                                  # trailing silence -> done
            total += dur
            if total > max_utt:
                break                                      # hard safety ceiling

    if _abort.is_set() or not started:
        return ""                                          # cancelled, or nobody spoke
    if on_captured:
        on_captured()
    if not _write_wav(b"".join(collected)):
        return ""
    return _transcribe_wav(cfg, REC_WAV)


def stop():
    """Explicit stop signal (the UI's second tap): cancel the live capture.

    Trips the abort flag (breaks the recording loop), releases the mic, and kills
    an in-flight whisper decode so the turn ends immediately.
    """
    _abort.set()
    _stop_mic()
    with _proc_lock:
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


# ==========================================================================
# Wake spotting — a fixed-length on-demand chunk (shared with ears/wake.py)
# ==========================================================================
def next_window(seconds, cfg=None):
    """Record a fixed ~`seconds` chunk and transcribe it (for wake keyword spotting).

    Named `next_window` for compatibility with the wake loop, which polls this
    back-to-back while EMO sleeps. Returns the transcript ("").
    """
    cfg = cfg or _stt_cfg()
    if shutil.which("termux-microphone-record") is None:
        return ""
    _abort.clear()
    if not _record_chunk(WAKE_AAC, max(1.0, float(seconds))):
        return ""
    pcm = _decode_pcm(WAKE_AAC)
    if not _write_wav(pcm):
        return ""
    # Wake spotting can use a LIGHTER model (e.g. tiny.en) for snappier checks
    # while command capture keeps the accurate model. Set ears.stt.wake_model.
    wcfg = cfg
    wake_model = cfg.get("wake_model")
    if wake_model and os.path.exists(wake_model):
        wcfg = dict(cfg)
        wcfg["model"] = wake_model
    return _transcribe_wav(wcfg, REC_WAV)


# --- Compatibility shims ------------------------------------------------------
# The old design ran an always-hot background stream. Capture is now on-demand,
# so these are thin stubs that keep existing callers (ears/wake.py, orchestrator)
# working unchanged.
def start_stream():
    """No persistent stream anymore; just report whether the mic exists."""
    return shutil.which("termux-microphone-record") is not None


def stop_stream():
    """Release the mic (there is no background thread to join)."""
    _stop_mic()


def stream_active():
    return shutil.which("termux-microphone-record") is not None


def reset_wake_cursor():
    """No-op: on-demand capture buffers no audio between turns."""
    return


# ==========================================================================
# whisper
# ==========================================================================
def _transcribe_wav(cfg, wav_path=REC_WAV):
    binary = cfg.get("binary", "")
    model = cfg.get("model", "")
    if not (binary and os.path.exists(binary)):
        print(f"[stt] whisper binary not found: {binary}")
        return ""
    if not (model and os.path.exists(model)):
        print(f"[stt] whisper model not found: {model}")
        return ""
    if not os.path.exists(wav_path):
        return ""

    # Popen (not run) so stop() can .terminate()/.kill() this immediately.
    # Command is tuned from config: -t threads (speed), -bs beam size (accuracy),
    # --prompt to bias whisper toward EMO's vocabulary (fewer mis-hearings).
    cmd = [binary, "-m", model, "-f", wav_path, "-nt", "-l", "en"]
    threads = cfg.get("threads")
    if threads:
        cmd += ["-t", str(int(threads))]
    beam = cfg.get("beam_size")
    if beam:
        cmd += ["-bs", str(int(beam))]
    prompt = (cfg.get("prompt") or "").strip()
    if prompt:
        cmd += ["--prompt", prompt]
    # Hardware/accel levers. `-fa` (flash attention) speeds up the decode on
    # builds that support it; `extra_args` is an escape hatch for any other
    # whisper-cli flag (e.g. a GPU/vulkan toggle on a custom build). Both are
    # config-gated so an older whisper-cli that rejects them stays untouched.
    if cfg.get("flash_attn"):
        cmd += ["-fa"]
    extra = cfg.get("extra_args")
    if extra:
        cmd += extra.split() if isinstance(extra, str) else [str(a) for a in extra]

    global _active_proc
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    with _proc_lock:
        _active_proc = proc
    try:
        out, _ = proc.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
    finally:
        with _proc_lock:
            _active_proc = None

    if proc.returncode != 0:                # killed by stop(), or whisper errored
        return ""
    text = " ".join(line.strip() for line in (out or "").splitlines()).strip()
    if text.lower() in _NOISE_TOKENS:
        return ""
    return text


def transcribe(cfg=None, on_captured=None):
    """Capture one utterance (for standalone use / the INSTALL test)."""
    cfg = cfg if cfg is not None else _stt_cfg()
    return capture_utterance(on_captured=on_captured) or ""


if __name__ == "__main__":
    _mode = (_stt_cfg().get("capture_mode") or "single").lower()
    if _mode == "single":
        _win = _stt_cfg().get("single_seconds", 6)
        print(f"[stt] single-clip mode — speak NOW; recording for ~{_win}s "
              "(one continuous take, no gaps)...")
    else:
        print("[stt] chunk mode — speak when ready (endpoints on trailing silence)...")
    heard = transcribe()
    if heard:
        print(f"[stt] heard: {heard!r}")
    else:
        print("[stt] heard nothing (silence, or a setup issue above).")
