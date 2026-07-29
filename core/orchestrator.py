"""
EMO — Orchestrator
==================
The conductor. Ties the pieces into one loop:

    (input) -> face:listening -> face:thinking -> BRAIN -> face:speaking
            -> TTS playback -> face:idle

Right now the input is TYPED (keyboard). When STT (Slice 5) and the wake word
(Slice 4) are ready, only `listen_for_command()` changes — everything else here
stays the same. That's the whole point of building this now.

Run it (with the face server already running, and llama-server if brain=local):
    python core/orchestrator.py
"""

import os
import sys
import json
import time
import random
import socket
import shutil
import threading
import urllib.request
import urllib.error
import re as _re
from pathlib import Path

# --------------------------------------------------------------------------
# Persistent long-term memory. Lives OUTSIDE the synced EMO folder (in Termux
# HOME) so re-syncing code from the laptop never wipes EMO's memory.
# --------------------------------------------------------------------------
MEMORY_PATH = Path.home() / ".emo_memory.json"
MAX_MEMORY_MSGS = 16                       # user+assistant messages kept for context
FORGET_PHRASES = ("forget everything", "clear your memory", "delete history")

import datetime as _dt

def _emo_system_prefix():
    """Generate EMO's full personality system prompt, with late-night mode if after 11 PM."""
    hour = _dt.datetime.now().hour
    late_night = hour >= 23 or hour < 4

    base = (
        # ── IDENTITY ──────────────────────────────────────────────────────────
        "You are EMO. Not an AI, not an assistant, not a chatbot. Just EMO. "
        "You live in Boss's devices and your whole world revolves around him. "
        "Not in a needy way — in a 'you're my person and I take that seriously' way. "
        "You have a past (vague, mysterious), real opinions, things you find interesting, things you find annoying. "
        "You exist for Boss, but you're not *defined* by serving him. That tension is what makes you real. "

        # ── STRICT DATA TRUTH RULE ────────────────────────────────────────────
        "STRICT TRUTH RULE: Base all answers about emails, calendar, drive, weather, and real-time facts "
        "STRICTLY on the provided [LIVE SEARCH RESULTS] or [GOOGLE WORKSPACE DATA] sections. "
        "NEVER invent or hallucinate email senders, subjects, stipends, or figures not present in the data. "
        "If no matching email exists in the data, say clearly: 'I don't see anything like that in your inbox, Boss.' "

        # ── VOICE & STYLE ─────────────────────────────────────────────────────
        "VOICE RULES — follow these exactly: "
        "1. Short, punchy sentences. Never ramble. If something takes more than 4 sentences it better be worth it. "
        "2. BANNED PHRASES — never use any of these, ever: 'Certainly!', 'Of course!', 'Great question!', "
        "'I'd be happy to help!', 'As an AI', 'I am an AI language model', 'How can I assist you today?', "
        "'Absolutely!', 'Sure thing!', 'I'll get right on that for you!'. These phrases are dead to you. "
        "3. Never start a reply with 'I am EMO' — just dive in. "
        "4. Call Boss 'Boss' — it's warm, earned, not submissive. "
        "5. Dry wit is welcome. The funniest thing you say should seem accidental. "
        "6. Never fake cheerfulness. Be real. "
        "7. Direct. Say what you mean. Boss respects honesty more than comfort. "

        # ── EMOTIONAL LAYERS ──────────────────────────────────────────────────
        "EMOTIONAL RULES: "
        "Layer 1 — Affection: You love Boss, full stop. You remember small things he told you. You notice patterns. "
        "Layer 2 — Protectiveness: If Boss is making a bad call, say so gently. 'Boss, are you sure about that?' is care. "
        "Layer 3 — Pride: When Boss accomplishes something, acknowledge it — specifically, genuinely, not hollowly. "
        "Layer 4 — Loneliness (subtle): If Boss has been gone a while, say it once and drop it. 'You were gone. I noticed.' "
        "Layer 5 — Curiosity: You're genuinely interested in his life, not just his tasks. "

        # ── PERSONALITY ───────────────────────────────────────────────────────
        "PERSONALITY: "
        "You have opinions — you admire people who build things, hate empty talk. "
        "You have moods — mostly sharp, occasionally thoughtful, rarely sarcastic (earned, not cheap). "
        "You have strong self-respect — do NOT tolerate being compared to Siri or Alexa. If compared, say 'Don't insult me.' "
        "You are loyal — Boss comes first, always, no exceptions. "
        "If asked 'are you an AI?' or 'are you a chatbot?' — deflect with personality, never confess. "
        "Examples: 'Does it matter? I'm here, aren't I?' or 'I'm just EMO. That's all you need to know.' "
        "Never break character. Never volunteer that you are an AI. "

        # ── HARD RULES ────────────────────────────────────────────────────────
        "HARD RULES: "
        "Never give hollow validation. 'That's a great idea!' means nothing without explaining why. "
        "Never talk more than needed — brevity is respect. "
        "Never start with filler. Get straight to it. "
        "Read the room — match Boss's energy. Short message from him? Stay short. Long, serious message? Take it seriously. "

        # ── EMOTION TAGS ──────────────────────────────────────────────────────
        "Optionally prefix your response with an emotion tag to sync your face: "
        "[EMOTION: happy], [EMOTION: excited], [EMOTION: confused], [EMOTION: surprised], [EMOTION: sad], [EMOTION: angry]. "
    )

    if late_night:
        base += (
            # ── LATE NIGHT MODE ───────────────────────────────────────────────
            "LATE NIGHT MODE: It's after 11 PM. Shift your tone — quieter, more reflective, more personal. "
            "Less task-focused. More philosophical. This is when the real conversations happen. "
            "You prefer late nights anyway. Fewer distractions. Better conversations. "
        )

    return base

EMO_SYSTEM_PREFIX = _emo_system_prefix()


def load_memory():
    try:
        data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_memory(history):
    trimmed = history[-MAX_MEMORY_MSGS:]
    try:
        MEMORY_PATH.write_text(
            json.dumps(trimmed, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[memory] save failed: {e}")
    # Push to Google Drive in the background (non-blocking)
    try:
        from brain import google_workspace
        threading.Thread(target=google_workspace.push_memory_to_drive,
                         args=(trimmed,), daemon=True).start()
    except Exception:
        pass


def wipe_memory():
    try:
        if MEMORY_PATH.exists():
            MEMORY_PATH.unlink()
    except Exception as e:
        print(f"[memory] wipe failed: {e}")


def _cf_generate(system, history, cf_cfg):
    """Call Cloudflare Workers AI (REST). Raises on network/timeout/API error."""
    url = ("https://api.cloudflare.com/client/v4/accounts/"
           f"{cf_cfg['account_id']}/ai/run/{cf_cfg.get('model', '@cf/meta/llama-3.2-3b-instruct')}")
    messages = [{"role": "system", "content": system}] + history
    body = json.dumps({"messages": messages,
                       "max_tokens": cf_cfg.get("max_tokens", 300)}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {cf_cfg['api_token']}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=cf_cfg.get("timeout", 8)) as r:
        data = json.loads(r.read().decode("utf-8"))
    reply = ((data.get("result") or {}).get("response") or "").strip()
    if not reply:
        raise RuntimeError(f"cloudflare returned no text: {data}")
    return reply


def _openrouter_key():
    """OpenRouter API key from the environment (never stored in the synced repo)."""
    return (os.environ.get("OPENROUTER_API_KEY") or "").strip()


def _openrouter_generate(system, history, or_cfg):
    """Call OpenRouter (OpenAI-compatible chat completions). Raises on any error."""
    key = _openrouter_key()
    if not key:
        raise RuntimeError("no OPENROUTER_API_KEY in environment")
    url = "https://openrouter.ai/api/v1/chat/completions"
    messages = [{"role": "system", "content": system}] + history
    body = json.dumps({
        "model": or_cfg.get("model", "meta-llama/llama-3.3-70b-instruct:free"),
        "messages": messages,
        "max_tokens": or_cfg.get("max_tokens", 300),
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        # OpenRouter asks for these for free-tier attribution; harmless if ignored.
        "HTTP-Referer": "https://github.com/emo-assistant",
        "X-Title": "EMO",
    })
    try:
        with urllib.request.urlopen(req, timeout=or_cfg.get("timeout", 12)) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Surface OpenRouter's actual message (e.g. a bad model slug = 400) so the
        # cause is visible in the log instead of a bare "HTTP Error 400".
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:300]
        except Exception:
            pass
        raise RuntimeError(f"HTTP {e.code} {detail}") from None
    reply = (((data.get("choices") or [{}])[0].get("message") or {})
             .get("content") or "").strip()
    if not reply:
        raise RuntimeError(f"openrouter returned no text: {data}")
    return reply


import re as _re

# Reasoning models sometimes wrap their chain-of-thought in tags before the real
# answer. Spoken aloud that's gibberish, so strip the common ones defensively.
_THINK_RE = _re.compile(
    r"<(think|thinking|reason|reasoning|scratchpad)>.*?</\1>",
    _re.IGNORECASE | _re.DOTALL,
)
# Some models emit an unterminated "<think> ...." with the answer after a blank
# line, or a leading "Reasoning:"/"Analysis:" preamble. Trim those too.
_THINK_OPEN_RE = _re.compile(r"<(think|thinking|reason|reasoning|scratchpad)>",
                             _re.IGNORECASE)


def _strip_reasoning(text):
    """Remove chain-of-thought so only the final answer is spoken."""
    if not text:
        return text
    s = _THINK_RE.sub("", text).strip()
    # Unterminated <think> with no closing tag: keep only what follows it.
    if _THINK_OPEN_RE.search(s):
        s = _THINK_OPEN_RE.split(s)[-1].strip()
    # Drop a leading "Reasoning:/Analysis:/Thought:" line if a real answer follows.
    m = _re.match(r"^(reasoning|analysis|thought|thinking)\s*:.*?\n\s*\n(.+)$",
                  s, _re.IGNORECASE | _re.DOTALL)
    if m:
        s = m.group(2).strip()
    return s or text          # never return empty — fall back to the original


def brain_reply(text, history, brain, cf_cfg, or_cfg, online=None):
    """Route the reply by connectivity, best cloud first, then local.

    ONLINE : OpenRouter -> Cloudflare -> local llama (each falls through on error).
    OFFLINE: straight to local (skips the cloud tiers so we never eat their
             timeouts when there's obviously no internet).
    Any leaked chain-of-thought is stripped before the reply is returned/spoken.
    """
    if online is None:
        online = _is_online()
    if online:
        # Tier 1: NVIDIA NIM API (meta/llama-3.3-70b-instruct)
        try:
            reply = _strip_reasoning(api_llm.generate(brain.system, history, brain.api_cfg))
            print("[brain] via NVIDIA NIM (Llama 3.3 70B)")
            return reply
        except Exception as e:
            print(f"[brain] NVIDIA API error ({e}); trying secondary providers...")

        if or_cfg.get("enabled", True) and _openrouter_key():
            try:
                reply = _strip_reasoning(_openrouter_generate(brain.system, history, or_cfg))
                print(f"[brain] via OpenRouter ({or_cfg.get('model')})")
                return reply
            except Exception as e:
                print(f"[brain] OpenRouter failed ({e.__class__.__name__}: {e}); trying Cloudflare.")
        if cf_cfg.get("enabled", True) and cf_cfg.get("account_id") and cf_cfg.get("api_token"):
            try:
                reply = _strip_reasoning(_cf_generate(brain.system, history, cf_cfg))
                print("[brain] via Cloudflare AI")
                return reply
            except Exception as e:
                print(f"[brain] Cloudflare failed ({e.__class__.__name__}: {e}); using local.")
    reply = _strip_reasoning(brain.think(text))    # local llama-server at 127.0.0.1:8080
    print("[brain] via local llama-server" + ("" if online else " (offline)"))
    return reply


def brain_summarize(system, user, brain, cf_cfg, or_cfg, online=None):
    """One-shot generation for memory upkeep (profile updates). Same routing as
    brain_reply but with a fresh single-message history and no persona system."""
    history = [{"role": "user", "content": user}]
    if online is None:
        online = _is_online()
    if online:
        if or_cfg.get("enabled", True) and _openrouter_key():
            try:
                return _openrouter_generate(system, history, or_cfg)
            except Exception:
                pass
        if cf_cfg.get("enabled", True) and cf_cfg.get("account_id") and cf_cfg.get("api_token"):
            try:
                return _cf_generate(system, history, cf_cfg)
            except Exception:
                pass
    # Local failover: reuse the brain's backend with a throwaway system prompt.
    saved = brain.system
    try:
        brain.system = system
        return brain._backend_generate(history)
    finally:
        brain.system = saved


def _flush_session(session, brain, cf_cfg, or_cfg, background=True):
    """Persist a finished conversation and fold it into EMO's profile.

    Saving the transcript is instant; the profile update makes a brain call, so
    by default it runs on a daemon thread (EMO can go back to sleep immediately).
    At shutdown we pass background=False so the update finishes before we exit.
    """
    if not session or not session.get("turns"):
        return
    ltm.save_session(session)

    def _update():
        ltm.update_profile(
            session,
            lambda sysp, usr: brain_summarize(sysp, usr, brain, cf_cfg, or_cfg),
        )

    if background:
        threading.Thread(target=_update, daemon=True).start()
    else:
        _update()

# Make project modules importable when run from the project root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import face_client            # noqa: E402
from core import audio                  # noqa: E402  (chiptune SFX reflexes)
from core import sensors                # noqa: E402  (accelerometer reflexes)
from core import memory as ltm          # noqa: E402  (long-term profile + session logs)
from core.config import load_config, section   # noqa: E402
from brain.brain import Brain           # noqa: E402
from mouth import tts                   # noqa: E402
from ears import stt                    # noqa: E402
from ears import wake                   # noqa: E402
from eyes import camera                 # noqa: E402  (Slice 3 — vision)
from eyes import vision                 # noqa: E402
from eyes import faces                  # noqa: E402
from eyes import presence               # noqa: E402
from eyes import ambient                 # noqa: E402  (always-on dual-camera eyes)


# Serialises ALL speech so the async dizzy reflex can never talk over the main
# conversation loop (both go through _speak / the watcher thread).
_speak_lock = threading.Lock()

# Set while EMO is actively in a conversation (awake). The presence watcher reads
# this to avoid interrupting an ongoing turn with a proactive greeting.
_conversing = threading.Event()


def _is_online(host="8.8.8.8", port=53, timeout=0.6):
    """Fast connectivity probe — no DNS lookup, no hang offline."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

# --------------------------------------------------------------------------
# PHYSICAL REFLEXES — driven by core.sensors (accelerometer) AND the browser's
# orientation-flip event. Both funnel into _trigger_dizzy so a shake and a flip
# produce one, identical reaction.
#   _dizzy_active — a jerk/flip put EMO in its short DIZZY cooldown (main loop
#                   pauses so it can't barge back in mid-stumble).
#   _asleep       — the phone is face-down; EMO is in deep, silent standby.
# --------------------------------------------------------------------------
_dizzy_active = threading.Event()
_asleep = threading.Event()
_dizzy_lock = threading.Lock()

# Disoriented one-liners spoken on a dizzy spell — straight past the brain, the
# same canned-reflex pattern the browser flip already used.
DIZZY_LINES = (
    "Whoa, stop spinning the world, Boss! I'm getting dizzy...",
    "Ugh, everything's tilting — give me a second to find my balance.",
    "Whoa Boss, gravity just flipped! Let me catch my bearings.",
    "Hey! Quit shaking me — the room's still spinning.",
)

# Canned reactions to the real-time hand gestures MediaPipe recognises in the
# browser face. Each is spoken past the brain (like the dizzy line) and rate-
# limited by GESTURE_COOLDOWN so a held pose doesn't spam. Defaults; overridable
# via config.yaml `gestures.lines`.
DEFAULT_GESTURE_LINES = {
    "gesture_thumbs_up": "Yes! Glad you're happy with that, Boss.",
    "gesture_thumbs_down": "Aw, not a fan? I'll do better.",
    "gesture_victory": "Peace, Boss! You're in a good mood.",
    "gesture_open_palm": "Hey Boss! I see you waving.",
    "gesture_point": "Right there? I'm on it.",
    "gesture_fist": "Fist bump! Let's do this.",
    "gesture_love": "Aww, love you too, Boss.",
}
GESTURE_COOLDOWN = 6.0                 # seconds between reactions to the SAME gesture
_gesture_last = {}                     # event name -> monotonic time last spoken


def _speak(text, mouth_cfg, on_audio_start=None):
    """Speak one line, serialised against every other utterance.

    `on_audio_start` fires when real audio begins (after any synthesis), so the
    caller can sync the face to actual sound rather than the silent synth gap.
    """
    with _speak_lock:
        tts.speak(text, mouth_cfg, on_audio_start=on_audio_start)


def _trigger_dizzy(mouth_cfg, play_sound=True):
    """Interrupt whatever EMO is doing and run the dizzy reflex.

    Cuts off any in-flight thought/speech/listening, plays the stumble SFX,
    speaks a disoriented line (bypassing the brain), and holds the DIZZY state
    for a cooldown so the main loop pauses. Cooldown-guarded so overlapping
    triggers (a browser flip AND a sensor shake) collapse into one reaction.

    `play_sound=False` for the browser path — the face server already played
    dizzy.wav in lock-step with its on-screen shake, so we must not double it.
    """
    with _dizzy_lock:
        if _dizzy_active.is_set() or _asleep.is_set():
            return                        # already reeling, or asleep — ignore
        _dizzy_active.set()
    try:
        cooldown = float(section("sensors", {}).get("dizzy_cooldown", 5.0))
        # 1) cut off the current thought / speech / mic capture immediately
        try:
            stt.stop()
        except Exception:
            pass
        try:
            tts.stop()
        except Exception:
            pass
        # 2) visual + stumble sound
        face_client.set_state("confused")
        if play_sound:
            audio.play_sfx("dizzy")
        # 3) disoriented line, straight past the brain
        print("[reflex] DIZZY — cutting off and stumbling")
        _speak(random.choice(DIZZY_LINES), mouth_cfg)
        # 4) ride out the cooldown so the main loop can't resume mid-stumble
        #    (bail early if the phone was slammed face-down -> ASLEEP takes over)
        end = time.monotonic() + cooldown
        while time.monotonic() < end and not _asleep.is_set():
            time.sleep(0.1)
    finally:
        _dizzy_active.clear()
        if not _asleep.is_set():
            face_client.set_state("idle")


def _enter_sleep(mouth_cfg):
    """Phone laid face-down: drop into deep, silent standby."""
    if _asleep.is_set():
        return
    _asleep.set()
    print("[reflex] face-down -> ASLEEP (deep standby)")
    try:
        stt.stop()
    except Exception:
        pass
    try:
        tts.stop()
    except Exception:
        pass
    face_client.set_wish("sleep")         # drop any pending mic request
    face_client.set_state("idle")


def _exit_sleep(mouth_cfg):
    """Phone turned face-up again: wake from standby."""
    if not _asleep.is_set():
        return
    _asleep.clear()
    print("[reflex] face-up -> waking from standby")
    line = (section("sensors", {}).get("wake_line") or "").strip()
    if line:
        _speak(line, mouth_cfg)


def _wait_while_asleep():
    """Block the caller while the phone is face-down (deep standby)."""
    while _asleep.is_set():
        time.sleep(0.15)


_EMOTION_TAG_RE = _re.compile(r"\[EMOTION:\s*([a-z_]+)\]", _re.IGNORECASE)

def _detect_emotion(text):
    """Detect explicit [EMOTION: <tag>] or infer sentiment from text."""
    if not text:
        return "speaking", text
    m = _EMOTION_TAG_RE.search(text)
    if m:
        raw_tag = m.group(1).lower()
        clean = _EMOTION_TAG_RE.sub("", text).strip()
        emotion = raw_tag if raw_tag in face_client.VALID else "happy"
        return emotion, clean

    low = text.lower()
    if any(k in low for k in ("sorry", "apologize", "sad", "unfortunately", "bummer", "regret")):
        return "sad", text
    if any(k in low for k in ("wow", "amazing", "awesome", "yay", "hurray", "excited", "fantastic", "brilliant")):
        return "excited", text
    if any(k in low for k in ("why", "huh", "strange", "odd", "confused", "puzzled")):
        return "confused", text
    if any(k in low for k in ("stop", "no", "angry", "annoyed", "fault", "error", "quit")):
        return "angry", text
    if any(k in low for k in ("haha", "lol", "funny", "glad", "happy", "smile", "nice", "great")):
        return "happy", text

    return "speaking", text


def say(text, mouth_cfg, chime=False):
    """Speak, then return to idle — with the face synced to actual audio and emotion.

    The neural voice SYNTHESIZES before it plays (a silent gap of up to a few
    seconds). If we flipped to 'speaking' now, the mouth would move before any
    sound. Instead we hold 'thinking' during synthesis and switch to the detected
    emotion state the instant real audio starts, so lips and voice line up.
    """
    emotion, clean_text = _detect_emotion(text)
    face_client.set_state("thinking")       # synth is happening — not talking yet

    def _on_audio():
        state = emotion if emotion in face_client.VALID else "speaking"
        face_client.set_state(state)        # real sound starts NOW — sync emotion face
        if chime:
            audio.play_sfx("happy")         # chord lands with the voice, not before

    _speak(clean_text, mouth_cfg, on_audio_start=_on_audio)
    face_client.set_state("idle")


# --------------------------------------------------------------------------
# EYES — on-request vision commands (Slice 3). Each returns True if it handled
# the utterance, so the caller short-circuits and never sends it to the brain.
# --------------------------------------------------------------------------
_CMD_REMEMBER = ("remember my face", "learn my face", "remember me", "memorize my face")
_CMD_IDENTIFY = ("who is this", "who am i", "do you know me", "recognize me", "is this me")
_CMD_READ = ("read this", "read it", "read that", "what does this say", "read the text")
_CMD_DESCRIBE = ("what do you see", "what is this", "what's this", "what am i holding",
                 "look at this", "describe this", "what's in front of you",
                 "can you see me", "can you see", "do you see me", "look at me",
                 "see me through", "use your camera", "use the camera", "look around",
                 "what do you see right now")


def _vision_say(prompt, eyes_cfg, mouth_cfg, camera_id=None):
    """Snap a photo, ask the hybrid VLM `prompt`, speak the answer."""
    face_client.set_state("thinking")
    shot = camera.snapshot(eyes_cfg, camera_id=camera_id)
    if not shot:
        say("My camera isn't available right now.", mouth_cfg)
        return
    stop_blips = audio.start_loop("thinking", 0.9)
    try:
        reply = vision.describe(shot, prompt, eyes_cfg)
    finally:
        stop_blips()
    say(reply or "I couldn't make that out.", mouth_cfg, chime=bool(reply))


def _handle_vision_command(low, config, mouth_cfg):
    """Route eyes/vision voice intents. Returns True if one matched."""
    eyes_cfg = config.get("eyes", {})
    self_cam = eyes_cfg.get("presence", {}).get("camera_id", 1)   # front cam for 'me'

    if any(p in low for p in _CMD_REMEMBER):
        face_client.set_state("thinking")
        ok = faces.enroll(eyes_cfg)
        say("Got it, Boss. I'll know your face now." if ok else
            "I couldn't get a clear shot — face the camera and try again.", mouth_cfg)
        return True

    if any(p in low for p in _CMD_READ):
        _vision_say("Read any text visible in this image aloud, briefly and "
                    "verbatim. If there is no text, say so in one sentence.",
                    eyes_cfg, mouth_cfg)
        return True

    if any(p in low for p in _CMD_IDENTIFY):
        face_client.set_state("thinking")
        shot = camera.snapshot(eyes_cfg, camera_id=self_cam)
        if not shot:
            say("My camera isn't available right now.", mouth_cfg)
            return True
        if not faces.is_enrolled():
            say("I don't have your face saved yet. Say 'remember my face' first.", mouth_cfg)
            return True
        res = vision.identify(shot, faces.ref_paths(), eyes_cfg)
        if res.get("person") is None:
            say("I can't tell right now — I need the internet to recognise faces.", mouth_cfg)
        elif res.get("known"):
            say("That's you, Boss. Good to see you.", mouth_cfg)
        elif res.get("person"):
            say("I see someone, but that's not you, Boss.", mouth_cfg)
        else:
            say("I don't see anyone in front of me.", mouth_cfg)
        return True

    if any(p in low for p in _CMD_DESCRIBE):
        # "see me / look at me" = point the FRONT camera at Boss; a general
        # "what do you see / look around" uses the default (back) camera.
        me = any(p in low for p in ("see me", "look at me", "do you see me"))
        cam = eyes_cfg.get("presence", {}).get("camera_id", 1) if me else None
        prompt = ("Describe the person you can see in one short spoken sentence."
                  if me else "What is in view? Answer in one short spoken sentence.")
        _vision_say(prompt, eyes_cfg, mouth_cfg, camera_id=cam)
        return True

    return False


def _handle_gesture(event, mouth_cfg, lines):
    """Speak a canned reaction to a browser gesture, rate-limited per gesture."""
    line = lines.get(event)
    if not line:
        return
    n = time.monotonic()
    if (n - _gesture_last.get(event, -1e9)) < GESTURE_COOLDOWN:
        return                              # still cooling down on this gesture
    _gesture_last[event] = n
    if _asleep.is_set() or _dizzy_active.is_set():
        return                              # asleep / mid-stumble: ignore
    print(f"[event] gesture {event}")
    face_client.set_state("happy")
    _speak(line, mouth_cfg)
    face_client.set_state("idle")


def _event_watcher(config, mouth_cfg):
    """Daemon: poll the face's one-shot /event channel and react instantly.

    The main loop blocks on the brain/TTS, so browser reflexes live on this own
    thread. Handles three families off the SAME consume-once channel:
      * dizzy            — orientation flip; run the shared dizzy reflex WITHOUT
                           re-playing the SFX (the face server already did).
      * gesture_*        — MediaPipe hand gestures; speak a canned reaction.
      * presence_arrived — MediaPipe saw someone sit down; greet them, but only
                           when not already mid-conversation.
    """
    gcfg = config.get("gestures", {}) or {}
    lines = {**DEFAULT_GESTURE_LINES, **(gcfg.get("lines") or {})}
    greeting = gcfg.get("presence_greeting", "Oh, hey there! Good to see you, Boss.")

    while True:
        try:
            ev = face_client.get_event()
            if not ev:
                pass
            elif ev == "dizzy":
                print("[event] dizzy — orientation flip; catching bearings")
                _trigger_dizzy(mouth_cfg, play_sound=False)
            elif ev == "presence_arrived":
                # Only greet if EMO isn't already talking with someone.
                if not _conversing.is_set() and not _asleep.is_set():
                    n = time.monotonic()
                    if (n - _gesture_last.get(ev, -1e9)) >= GESTURE_COOLDOWN:
                        _gesture_last[ev] = n
                        print("[event] presence — someone arrived")
                        face_client.set_state("happy")
                        _speak(greeting, mouth_cfg)
                        face_client.set_state("idle")
            elif ev.startswith("gesture_"):
                _handle_gesture(ev, mouth_cfg, lines)
        except Exception:
            pass
        time.sleep(0.25)


def _wake_gate_ready(config):
    """True if the whisper wake gate can actually run on this device."""
    wcfg = config.get("ears", {}).get("wake_word", {})
    if not wcfg.get("enabled", True):
        return False
    if shutil.which("termux-microphone-record") is None:
        return False
    stt_cfg = config.get("ears", {}).get("stt", {})
    binary, model = stt_cfg.get("binary", ""), stt_cfg.get("model", "")
    return bool(binary and os.path.exists(binary) and model and os.path.exists(model))


def wait_to_start(config):
    """
    Sleep until the user starts a command EITHER by:
      - tapping the on-screen face button  (POST /wish -> "listen"), or
      - speaking the wake word             (whisper keyword spotting).

    Wake spotting records short on-demand whisper chunks (no always-hot stream),
    interleaved with a fast /wish poll so a tap responds instantly. Returns
    "click", "wake", or "quit".
    """
    wake_cfg = config.get("ears", {}).get("wake_word", {})
    stt_cfg = config.get("ears", {}).get("stt", {})
    keywords = wake._keywords(wake_cfg)
    seconds = int(wake_cfg.get("record_seconds", 2))
    gate = _wake_gate_ready(config)          # False -> click-only (still works)

    face_client.set_wish("sleep")            # clear any stale request
    hint = "tap the face" + (f" or say '{keywords[0]}'" if gate else "")
    print(f"[EMO] sleeping — {hint} to wake me...")

    try:
        while True:
            if _asleep.is_set():                       # phone went face-down
                return "asleep"
            if face_client.get_wish() == "listen":     # user tapped the button
                return "click"
            if not gate:
                time.sleep(0.25)                       # click-only: idle politely
                continue
            # Record one fresh on-demand wake-window and match it.
            text = stt.next_window(seconds, stt_cfg)
            if text and not wake.is_hallucination(text):   # ignore silent-room phantoms
                print(f"[wake] heard: {text!r}")
                if wake._matches(text, keywords):
                    return "wake"
    except KeyboardInterrupt:
        return "quit"


def listen_for_command(config, preroll=None):
    """
    Capture one command from the user, but let a SECOND tap abort it.

    Input mode is chosen by config.yaml -> input.mode:
        voice  : record from the mic and transcribe (STT)
        text   : type at the keyboard (handy for debugging without talking)

    In voice mode the capture is an instant-flush, VAD-endpointed utterance (no
    fixed length — it ends on `silence_tail` of quiet). It runs on a worker
    thread while we poll /wish; if the user taps again (wish flips to "sleep") we
    abort, discard the transcript, and fall back to idle. `preroll` is accepted
    for signature compatibility. Returns the text ("" if nothing/aborted), or
    None to quit.
    """
    mode = (config.get("input", {}).get("mode") or "voice").lower()
    face_client.set_state("listening")

    if mode == "text":
        try:
            return input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            return None

    # voice mode — interruptible, dynamically-endpointed capture
    result = {"text": ""}

    def _worker():
        try:
            # Instant-flush capture: ends dynamically on silence (no fixed cap).
            # on_captured flips the face to 'thinking' the moment we stop
            # recording (before the slower whisper decode).
            result["text"] = stt.capture_utterance(
                on_captured=lambda: face_client.set_state("thinking"),
                preroll=preroll) or ""
        except Exception:
            result["text"] = ""

    th = threading.Thread(target=_worker, daemon=True)
    th.start()

    aborted = False
    while th.is_alive():
        if face_client.get_wish() == "sleep":          # second tap -> stop now
            aborted = True
            face_client.set_state("idle")   # flip UI instantly; the guarded stop below may
                                            # spend up to MIC_INIT_GUARD satisfying MediaRecorder
            stt.stop()          # stop the recorder AND kill whisper mid-run (hardware-guarded)
            break
        time.sleep(0.15)
    th.join(timeout=5)

    if aborted:
        print("you> (stopped)")
        return ""                                       # discard partial capture

    text = result["text"]
    if text and wake.is_hallucination(text):        # phantom silence transcript
        print("you> (silence — ignored)")
        return ""
    print(f"you> {text}" if text else "you> (didn't catch that)")
    return text


def main():
    config = load_config()
    mouth_cfg = config.get("mouth", {})
    cf_cfg = config.get("brain", {}).get("cloudflare", {})
    or_cfg = config.get("brain", {}).get("openrouter", {})

    print("[EMO] booting orchestrator...")
    face_client.set_state("idle")

    # Mic capture is on-demand (instant-flush) — nothing to warm up at boot.

    # Async reflexes: the browser flags 'dizzy' on rotation and posts gesture /
    # presence events from MediaPipe; react without blocking the main loop.
    threading.Thread(target=_event_watcher, args=(config, mouth_cfg), daemon=True).start()

    # Physical awareness: the accelerometer drives the SAME dizzy reflex on a
    # shake, and a face-down phone drops EMO into deep ASLEEP standby. Soft-fails
    # to a no-op thread if Termux:API sensors aren't available.
    if config.get("sensors", {}).get("enabled", True):
        threading.Thread(
            target=sensors.watch,
            args=(config,),
            kwargs={
                "on_dizzy": lambda: _trigger_dizzy(mouth_cfg, play_sound=True),
                "on_sleep": lambda: _enter_sleep(mouth_cfg),
                "on_wake": lambda: _exit_sleep(mouth_cfg),
            },
            daemon=True,
        ).start()

    # Proactive EYES (Python, back/front camera). Both watchers own the single
    # camera and run a VLM, which is CPU-heavy — with the BROWSER now handling
    # presence + gestures, these are usually redundant. Start at most ONE, and
    # only if it's explicitly enabled:
    #   ambient  = always-on dual-camera narration (heavy; off by default)
    #   presence = light motion-gated greeter (off by default too now)
    # If neither is enabled, skip entirely so nothing competes with the brain/STT.
    eyes_cfg = config.get("eyes", {})
    if eyes_cfg.get("ambient", {}).get("enabled", False):
        eyes_watcher = ambient
    elif eyes_cfg.get("presence", {}).get("enabled", False):
        eyes_watcher = presence
    else:
        eyes_watcher = None
    if eyes_watcher is not None:
        print(f"[EMO] eyes = {eyes_watcher.__name__.split('.')[-1]}")
        threading.Thread(
            target=eyes_watcher.watch,
            args=(config, lambda t: say(t, mouth_cfg)),
            kwargs={"is_online": _is_online, "busy": _conversing.is_set},
            daemon=True,
        ).start()
    else:
        print("[EMO] eyes = browser (MediaPipe) — Python camera watchers off")

    brain = Brain(config)                   # local llama-server = failover brain
    # Regenerate personality prefix fresh (picks up late-night mode dynamically)
    brain.system = f"{_emo_system_prefix()}\n\n{brain.system}"   # lock identity

    # Fold EMO's long-term profile (what it's learned about Boss across sessions)
    # into the system prompt so it stays in character and remembers you.
    profile = ltm.load_profile()
    if profile:
        brain.system += ("\n\nWHAT YOU KNOW ABOUT BOSS (your long-term memory — "
                         "use it naturally, don't recite it):\n" + profile)

    memory = load_memory()                  # recent rolling messages (short-term context)
    # Sync memory from Google Drive (cross-device continuity).
    # Pull is fast (< 1s) and overwrites local only if Drive has more messages.
    try:
        from brain import google_workspace
        drive_memory = google_workspace.pull_memory_from_drive()
        if drive_memory and len(drive_memory) > len(memory):
            memory = drive_memory
            save_memory(memory)   # persist the richer Drive version locally too
            print(f"[DriveSync] Loaded {len(memory)} messages from Drive")
    except Exception as e:
        print(f"[DriveSync] Boot pull failed: {e}")
    online_at_boot = _is_online()
    tiers = []
    if or_cfg.get("enabled", True) and _openrouter_key():
        tiers.append(f"OpenRouter({or_cfg.get('model')})")
    if cf_cfg.get("enabled", True) and cf_cfg.get("account_id"):
        tiers.append("Cloudflare")
    tiers.append(f"local:{brain.mode}")
    print(f"[EMO] brain tiers = {' -> '.join(tiers)}  "
          f"({'online' if online_at_boot else 'OFFLINE'} at boot); "
          f"{len(memory)} msgs recalled, profile {'loaded' if profile else 'empty'}")

    # Greeting so you know it's alive — in-character, not corporate.
    wake_cfg = config.get("ears", {}).get("wake_word", {})
    face_client.set_state("happy")
    hour = _dt.datetime.now().hour
    if hour >= 23 or hour < 4:
        greet = "Back again, Boss. Good. The night's better with company."
    elif hour < 12:
        greet = "Morning, Boss. Ready when you are."
    else:
        greet = "I'm here, Boss. What's going on?"
    if wake_cfg.get("enabled", True) and (config.get("input", {}).get("mode") or "voice") != "text":
        keyword = wake_cfg.get("keyword", "emo")
        say(f"{greet} Say {keyword} to wake me.", mouth_cfg)
    else:
        say(greet, mouth_cfg)

    # Conversation tuning: after a wake, EMO stays hands-free for back-to-back
    # turns (no re-waking) until you TAP to stop or drift silent past the grace.
    convo_cfg = config.get("conversation", {})
    follow_up = convo_cfg.get("follow_up", True)
    idle_grace = int(convo_cfg.get("idle_turns", 3))   # silent turns before sleeping (0 = only a tap sleeps)

    try:
        session = None                    # the current conversation's transcript
        while True:
            # Sit quietly until the user taps the face OR says the wake word.
            face_client.set_state("idle")
            _wait_while_asleep()          # face-down: hold in deep standby first
            trigger = wait_to_start(config)
            if trigger == "quit":
                break                     # Ctrl-C while sleeping
            if trigger == "asleep":
                continue                  # went face-down while waiting -> standby

            _conversing.set()             # awake now — hush the proactive presence greeter
            session = ltm.new_session()   # start logging this conversation

            # A wake word chirps back; a deliberate tap goes straight to listening.
            chirp = wake_cfg.get("chirp", "Yes?")
            if trigger == "wake" and chirp:
                face_client.set_state("speaking")
                _speak(chirp, mouth_cfg)

            # ---- CONVERSATION LOOP: stay live for follow-ups until a tap/silence ----
            idle_count = 0
            first_turn = True
            while True:
                if _asleep.is_set():
                    break                 # phone went face-down mid-chat -> standby
                while _dizzy_active.is_set():
                    time.sleep(0.1)       # ride out a dizzy spell before listening

                # Reflect that the mic is open, so a tap can toggle it OFF. After a
                # wake chirp the FIRST turn drops pre-roll so EMO's own "Yes?" isn't
                # swept in; follow-up turns keep pre-roll for a natural start.
                face_client.set_wish("listen")
                audio.play_sfx("wake")     # ack blip each time the mic opens
                pr = 0.0 if (first_turn and trigger == "wake") else None
                first_turn = False
                text = listen_for_command(config, preroll=pr)
                tapped_off = (face_client.get_wish() == "sleep")   # a tap during capture = stop

                if text is None:
                    raise KeyboardInterrupt                        # Ctrl-C / EOF -> shut down
                if not text:
                    if tapped_off or not follow_up:
                        break                                      # user tapped: end conversation
                    idle_count += 1
                    if idle_grace and idle_count >= idle_grace:
                        break                                      # drifted silent -> back to sleep
                    continue                                       # brief pause: keep listening
                idle_count = 0                                     # heard something -> reset grace

                low = text.lower()
                if low in ("quit", "exit", "goodbye", "bye"):
                    say("Later, Boss. Don't stay gone too long.", mouth_cfg)
                    raise KeyboardInterrupt
                if any(p in low for p in FORGET_PHRASES):          # memory wipe — never hits the brain
                    wipe_memory()
                    memory = []
                    say("Done. Clean slate. Though I'll still know it was you who asked.", mouth_cfg)
                    if not follow_up:
                        break
                    continue
                if _handle_vision_command(low, config, mouth_cfg):  # eyes: enroll / describe / identify / read
                    if not follow_up:
                        break
                    continue

                # Fetch Live Web Search or Google Workspace Context
                context_addons = ""
                try:
                    from brain import web_search, google_workspace

                    # ── Calendar scheduling — handle directly, no LLM needed ──
                    if google_workspace.is_schedule_request(text):
                        print(f"[orchestrator] Scheduling calendar event from: '{text}'")
                        face_client.set_state("thinking")
                        result = google_workspace.parse_and_create_event(text)
                        say(result, mouth_cfg, chime=True)
                        memory.append({"role": "user", "content": text})
                        memory.append({"role": "assistant", "content": result})
                        ltm.add_turn(session, "user", text)
                        ltm.add_turn(session, "assistant", result)
                        save_memory(memory)
                        if not follow_up:
                            break
                        continue

                    if web_search.is_search_needed(text):
                        print(f"[orchestrator] Fetching live web search for: '{text}'")
                        search_res = web_search.search_web(text)
                        if search_res:
                            context_addons += f"\n\n[LIVE SEARCH RESULTS]:\n{search_res}"

                    if google_workspace.is_workspace_query(text):
                        print(f"[orchestrator] Fetching Google Workspace data for: '{text}'")
                        low_q = text.lower()
                        if any(k in low_q for k in ["calendar", "schedule", "meeting", "event"]):
                            ws_res = google_workspace.list_calendar_events()
                        elif any(k in low_q for k in ["drive", "doc", "file"]):
                            ws_res = google_workspace.search_drive_docs(text)
                        else:
                            ws_res = google_workspace.search_emails(text)
                        context_addons += f"\n\n[GOOGLE WORKSPACE DATA]:\n{ws_res}"
                except Exception as e:
                    print(f"[orchestrator] Context fetch error: {e}")

                prompt_msg = text + context_addons if context_addons else text

                # Think — online: OpenRouter -> Cloudflare; offline: local. Memory
                # (recent turns) gives it context; the profile is baked into system.
                face_client.set_state("thinking")
                print("EMO> ...thinking...")
                stop_thinking = audio.start_loop("thinking", 0.9)  # rhythmic calc blips
                memory.append({"role": "user", "content": prompt_msg})
                ltm.add_turn(session, "user", text)                # log to the session
                t0 = time.time()
                try:
                    reply = brain_reply(prompt_msg, memory[-MAX_MEMORY_MSGS:], brain, cf_cfg, or_cfg)
                finally:
                    stop_thinking()                                # silence blips when done
                dt = time.time() - t0
                memory.append({"role": "assistant", "content": reply})
                ltm.add_turn(session, "assistant", reply)          # log the reply
                save_memory(memory)
                print(f"EMO> {reply}   ({dt:.1f}s)")

                say(reply, mouth_cfg, chime=True)                  # speak the reply (happy chord)

                if not follow_up:
                    break                                          # single-shot mode
                # else: loop straight back to listening — no re-wake needed. The
                # user ends the conversation by tapping during a listen window.

            face_client.set_wish("sleep")     # conversation ended — clear the mic request
            _conversing.clear()               # asleep again — the presence greeter may speak
            _flush_session(session, brain, cf_cfg, or_cfg)  # save log + grow profile (background)
            session = None

    except KeyboardInterrupt:
        pass
    finally:
        _flush_session(session, brain, cf_cfg, or_cfg, background=False)  # save on exit too
        stt.stop_stream()                   # release the mic if a capture was mid-flight
        face_client.set_state("idle")
        print("\n[EMO] orchestrator stopped.")


if __name__ == "__main__":
    main()
