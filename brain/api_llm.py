"""
EMO — Brain backend: NVIDIA NIM API
====================================
Talks to the NVIDIA NIM OpenAI-compatible Chat Completions API over HTTPS.
Pure standard library (urllib) — no external SDK needed.

Supported models:
  - meta/llama-3.3-70b-instruct (default: ultra-fast, high intelligence)
  - meta/llama-3.1-70b-instruct
  - nvidia/llama-3.1-nemotron-70b-instruct
"""

import os
import json
import urllib.request
import urllib.error

NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
DEFAULT_NVIDIA_KEY = "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"
DEFAULT_MODEL = "meta/llama-3.1-8b-instruct"


def generate(system, messages, cfg=None):
    """
    system  : persona/system prompt string
    messages: list of {"role": "user"|"assistant", "content": str}
    cfg     : the brain.api config dict
    Returns EMO's reply text, or a short spoken error.
    """
    if cfg is None:
        cfg = {}

    key = os.environ.get("NVIDIA_API_KEY") or os.environ.get("NVAPI_KEY") or DEFAULT_NVIDIA_KEY
    model = cfg.get("model") or DEFAULT_MODEL
    max_tokens = cfg.get("max_tokens", 120)

    # Format payload with system message and context history
    formatted_messages = []
    if system:
        formatted_messages.append({"role": "system", "content": system})

    for msg in messages:
        formatted_messages.append({
            "role": msg.get("role", "user"),
            "content": msg.get("content", "")
        })

    payload = {
        "model": model,
        "messages": formatted_messages,
        "temperature": 0.5,
        "max_tokens": max_tokens,
        "top_p": 1.0
    }

    req = urllib.request.Request(
        NVIDIA_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            res_data = json.loads(r.read().decode("utf-8"))
            choices = res_data.get("choices", [])
            if choices and "message" in choices[0]:
                reply = choices[0]["message"].get("content", "").strip()
                if reply:
                    return reply
            return "I got an empty response."
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        print(f"[brain.api] NVIDIA HTTP Error {e.code}: {detail}")
        if e.code == 401:
            return "My NVIDIA API key was rejected."
        return f"NVIDIA API Error {e.code}"
    except Exception as e:
        print(f"[brain.api] NVIDIA Error: {e}")
        return "I had trouble reaching my online brain."
