"""
EMO — Brain backend: LOCAL (llama.cpp server)
=============================================
Talks to a locally-running `llama-server` (from llama.cpp) over its
OpenAI-compatible HTTP endpoint. Pure standard library — no pip packages.

Why a server instead of the llama-cpp-python binding?
  The binding needs a fragile source compile on Termux's Python 3.14.
  Building llama.cpp itself (cmake) is reliable, and its llama-server loads
  the model ONCE and answers many requests over localhost. EMO just does HTTP.

Start the server (see INSTALL.md Slice 6) before using this backend:
    ./llama.cpp/build/bin/llama-server -m models/<model>.gguf -c 2048 -t 4

Public function: generate(system, messages, cfg) -> str
"""

import json
import urllib.request
import urllib.error


def health(cfg):
    """Return True if the llama server is up and responding."""
    url = cfg.get("server_url", "http://127.0.0.1:8080").rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def generate(system, messages, cfg):
    """
    system  : the persona/system prompt string
    messages: list of {"role": "user"|"assistant", "content": str}
    cfg     : the brain.local config dict
    Returns EMO's reply text, or a short error sentence EMO can speak.
    """
    base = cfg.get("server_url", "http://127.0.0.1:8080").rstrip("/")
    url = base + "/v1/chat/completions"

    # Prepend the system message; llama-server accepts OpenAI chat format.
    chat = [{"role": "system", "content": system}] + messages

    body = json.dumps({
        "model": "local",                     # server ignores this; it serves its loaded model
        "messages": chat,
        "max_tokens": cfg.get("max_tokens", 200),
        "temperature": cfg.get("temperature", 0.7),
        "stream": False,
    }).encode()

    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )

    try:
        # Local inference on a phone can be slow — allow a generous timeout.
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read().decode())
        return data["choices"][0]["message"]["content"].strip()
    except urllib.error.URLError:
        return ("My local brain isn't running. Start the llama server, "
                "then try again.")
    except (KeyError, IndexError, json.JSONDecodeError):
        return "My local brain gave me something I couldn't read."
    except Exception as e:
        print(f"[brain.local] error: {e}")
        return "Something went wrong in my local brain."
