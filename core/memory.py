"""
EMO — Long-term memory & personality
=====================================
Two jobs, both living OUTSIDE the synced EMO folder (in Termux HOME) so the
delete-and-paste code sync never wipes what EMO has learned:

  1. SESSION LOGS  — every conversation (wake -> sleep) is saved verbatim as a
     timestamped JSON in ~/.emo_history/, so there's a full record to look back on.
  2. PROFILE       — a small, persistent "what EMO knows about Boss + the vibe of
     their relationship" note (~/.emo_profile.md). It's injected into the system
     prompt every turn so EMO stays in character and remembers you across runs,
     and it's refreshed at the END of each session by asking the cloud brain to
     fold the new conversation into it (online only — offline we keep the old one).

Design notes
------------
* Pure stdlib. No new deps.
* The profile is a plain-text blob (not rigid JSON) so the LLM can shape it freely
  — facts, preferences, running jokes, tone. Capped so the prompt stays small.
* `update_profile` takes a `summarize(system, user) -> str` callable, so this
  module never needs to know how the brain is reached (cloud vs local) — the
  orchestrator hands it the same router it uses for replies.
"""

import json
from datetime import datetime
from pathlib import Path

HOME = Path.home()
PROFILE_PATH = HOME / ".emo_profile.md"
HISTORY_DIR = HOME / ".emo_history"

# Keep the injected profile small so it never crowds out the actual conversation
# in a small local model's context window.
MAX_PROFILE_CHARS = 3000
# Cap how much of a long session we feed the summarizer (most recent turns matter
# most and this bounds token cost on the end-of-session update).
MAX_SUMMARY_TURNS = 40


# --------------------------------------------------------------------------
# PROFILE — the persistent personality / "about Boss" note
# --------------------------------------------------------------------------
def load_profile():
    """Return the saved profile text, or "" if none yet."""
    try:
        return PROFILE_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def save_profile(text):
    try:
        PROFILE_PATH.write_text((text or "").strip()[:MAX_PROFILE_CHARS],
                                encoding="utf-8")
        return True
    except Exception as e:
        print(f"[memory] profile save failed: {e}")
        return False


def wipe_profile():
    try:
        PROFILE_PATH.unlink(missing_ok=True)
    except Exception as e:
        print(f"[memory] profile wipe failed: {e}")


# --------------------------------------------------------------------------
# SESSION — one conversation, saved verbatim for the record
# --------------------------------------------------------------------------
def new_session():
    """Start a fresh in-memory session record."""
    return {"id": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "started": datetime.now().isoformat(timespec="seconds"),
            "turns": []}


def add_turn(session, role, content):
    """Append one message ('user'/'assistant') to the live session."""
    if session is not None and content:
        session["turns"].append({"role": role, "content": content})


def save_session(session):
    """Write the session transcript to ~/.emo_history/session_<id>.json.
    No-op for an empty session (a wake that said nothing)."""
    if not session or not session.get("turns"):
        return None
    try:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        session["ended"] = datetime.now().isoformat(timespec="seconds")
        out = HISTORY_DIR / f"session_{session['id']}.json"
        out.write_text(json.dumps(session, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        return str(out)
    except Exception as e:
        print(f"[memory] session save failed: {e}")
        return None


# --------------------------------------------------------------------------
# PROFILE UPDATE — fold the session into the profile via the brain
# --------------------------------------------------------------------------
_UPDATE_SYSTEM = (
    "You maintain a concise long-term memory profile for the AI assistant EMO "
    "about its owner (whom EMO calls 'Boss') and their relationship. Given the "
    "existing profile and a new conversation, output an UPDATED profile that "
    "merges any durable new facts, preferences, goals, running jokes, and tone. "
    "Rules: keep only lasting, useful things (not small talk); stay under 200 "
    "words; write terse bullet-style lines; never invent facts; output ONLY the "
    "updated profile text, no preamble."
)


def _transcript_text(session):
    turns = session.get("turns", [])[-MAX_SUMMARY_TURNS:]
    lines = []
    for t in turns:
        who = "Boss" if t.get("role") == "user" else "EMO"
        lines.append(f"{who}: {t.get('content','')}")
    return "\n".join(lines)


def update_profile(session, summarize):
    """Refresh the profile from this session. `summarize(system, user) -> str`
    is the orchestrator's brain router (so this works cloud or local). Called at
    session end; on any failure the old profile is kept untouched.

    Returns the new profile text, or None if nothing was updated.
    """
    if not session or not session.get("turns"):
        return None
    old = load_profile() or "(no profile yet)"
    convo = _transcript_text(session)
    if not convo.strip():
        return None
    user_prompt = (f"EXISTING PROFILE:\n{old}\n\n"
                   f"NEW CONVERSATION:\n{convo}\n\n"
                   "Output the updated profile:")
    try:
        updated = (summarize(_UPDATE_SYSTEM, user_prompt) or "").strip()
    except Exception as e:
        print(f"[memory] profile update skipped ({e.__class__.__name__}: {e}); "
              "keeping the old one.")
        return None
    if not updated or len(updated) < 8:          # guard against an empty/garbage reply
        return None
    save_profile(updated)
    print("[memory] profile updated from this session.")
    return updated
