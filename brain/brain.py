"""
EMO — Brain (reasoning engine)
==============================
Pluggable backend selected by config.yaml (brain.mode: local | api). The
orchestrator creates one Brain and calls .think(user_text) each turn; the Brain
keeps a short rolling conversation history so EMO has some memory within a run.

Backends are swappable and both speak the same simple contract:
    generate(system, messages, cfg) -> reply_string

Test standalone (interactive chat in the terminal):
    python brain/brain.py
Or one-shot:
    python brain/brain.py "What's the capital of France?"
"""

import sys
from pathlib import Path

# Make 'core' and sibling modules importable when run from the project root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import load_config          # noqa: E402
from brain import local_llm, api_llm         # noqa: E402


class Brain:
    def __init__(self, config=None):
        cfg = config if config is not None else load_config()
        brain_cfg = cfg.get("brain", {})
        self.mode = (brain_cfg.get("mode") or "local").lower()
        self.local_cfg = brain_cfg.get("local", {})
        self.api_cfg = brain_cfg.get("api", {})

        # Persona / system prompt from config; sensible fallback.
        persona = cfg.get("persona", {})
        self.system = (persona.get("style") or
                       "You are EMO, a concise, witty phone assistant. "
                       "Answer in one or two short spoken sentences.").strip()

        # Rolling conversation history (list of {role, content}).
        self.history = []
        self.max_turns = 6   # keep the last N user/assistant pairs

    def _backend_generate(self, messages):
        if self.mode == "api":
            return api_llm.generate(self.system, messages, self.api_cfg)
        return local_llm.generate(self.system, messages, self.local_cfg)

    def think(self, user_text):
        """Take the user's text, return EMO's reply, and update history."""
        if not user_text or not user_text.strip():
            return "I didn't catch that."

        self.history.append({"role": "user", "content": user_text.strip()})
        # Trim to the last max_turns*2 messages so the prompt stays small/fast.
        trimmed = self.history[-(self.max_turns * 2):]

        reply = self._backend_generate(trimmed)

        self.history.append({"role": "assistant", "content": reply})
        return reply

    def reset(self):
        """Forget the conversation (e.g. new session)."""
        self.history = []


def _health_note(brain):
    """Print a hint if the selected backend probably isn't ready."""
    if brain.mode == "local" and not local_llm.health(brain.local_cfg):
        print("[brain] NOTE: local llama server not detected at "
              f"{brain.local_cfg.get('server_url')}. Start it first (INSTALL.md Slice 6).")


if __name__ == "__main__":
    brain = Brain()
    print(f"[brain] mode = {brain.mode}")
    _health_note(brain)

    # One-shot mode if args given, else interactive loop.
    if len(sys.argv) > 1:
        msg = " ".join(sys.argv[1:])
        print(f"you> {msg}")
        print(f"EMO> {brain.think(msg)}")
    else:
        print("Chat with EMO (Ctrl-C or empty line to quit).")
        try:
            while True:
                msg = input("you> ").strip()
                if not msg:
                    break
                print(f"EMO> {brain.think(msg)}")
        except (KeyboardInterrupt, EOFError):
            print("\n[brain] bye.")
