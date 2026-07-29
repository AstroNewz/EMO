"""
EMO — Eyes / Vision (hybrid VLM)
================================
Turns a JPEG into words. Mirrors the brain's routing exactly: try the CLOUD
vision models first (better quality, needs internet) — OpenRouter, then
Cloudflare — and on ANY failure fall back to a LOCAL `llama-server` running a
vision GGUF + mmproj. Pure standard library — one `urllib` POST, no SDKs.

Unified transport: ALL backends speak the OpenAI-compatible
`/v1/chat/completions` multimodal format — a user message whose `content` is a
list mixing text with `{"type":"image_url","image_url":{"url":"data:...base64"}}`
parts. So there is ONE request builder; only the base URL + auth header differ.

  openrouter : https://openrouter.ai/api/v1/chat/completions
               (Authorization: Bearer $OPENROUTER_API_KEY — env only; model =
               eyes.vision.openrouter.model, default nemotron-nano-12b-2-vl)
  cloud      : https://api.cloudflare.com/client/v4/accounts/<acct>/ai/v1/chat/completions
               (Authorization: Bearer <token>; creds shared with brain.cloudflare)
  local      : http://127.0.0.1:8081/v1/chat/completions   (no auth; run.sh starts it)

Public API:
    describe(image_path, question, cfg)          -> str   ("" on total failure)
    identify(image_path, ref_paths, cfg)         -> {"person": bool|None, "known": bool}
    cloud_reachable(cfg)                          -> bool  (used as the is_online probe)

`identify` is ONLINE-ONLY on purpose: local Q4 VLMs are too weak at "is this the
SAME specific person". Offline it returns {"person": None} so the caller degrades
to a generic, presence-only greeting.
"""

import os
import sys
import json
import base64
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import section   # noqa: E402


def _vision_cfg(cfg):
    """Accept either the whole `eyes` dict or an already-unwrapped `eyes.vision`."""
    if isinstance(cfg, dict) and "vision" in cfg:
        return cfg["vision"]
    return cfg if isinstance(cfg, dict) else section("eyes", {}).get("vision", {})


def _b64_data_uri(path):
    """Read a JPEG and return a data: URI, or None if unreadable."""
    try:
        raw = Path(path).read_bytes()
    except Exception:
        return None
    if not raw:
        return None
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


def _content(text, image_uris):
    """Build an OpenAI multimodal `content` list: the text plus each image."""
    parts = [{"type": "text", "text": text}]
    for uri in image_uris:
        if uri:
            parts.append({"type": "image_url", "image_url": {"url": uri}})
    return parts


def _openai_chat(base_url, headers, model, text, image_uris, timeout, max_tokens):
    """One multimodal POST. Returns the reply text. Raises on any transport error
    so the caller can fall back (same contract as brain._cf_generate)."""
    url = base_url.rstrip("/") + "/v1/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": _content(text, image_uris)}],
        "max_tokens": max_tokens,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    # OpenAI shape: choices[0].message.content
    msg = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")
    reply = (msg or "").strip()
    if not reply:
        raise RuntimeError(f"vision backend returned no text: {str(data)[:200]}")
    return reply


# --- backend calls -----------------------------------------------------------
def _openrouter_call(text, image_uris, cfg):
    """OpenRouter vision (OpenAI-compat multimodal). Raises on failure so the
    caller can fall back to Cloudflare then local — mirrors the brain router.

    Key comes from $OPENROUTER_API_KEY (env only, never in the synced repo).
    Model from eyes.vision.openrouter.model; disabled if the block says so or no
    key is set (then this raises and we drop straight to the next tier)."""
    orc = _vision_cfg(cfg).get("openrouter", {})
    if not orc.get("enabled", True):
        raise RuntimeError("openrouter vision disabled")
    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("no OPENROUTER_API_KEY in environment")
    return _openai_chat(
        "https://openrouter.ai/api",
        {"Authorization": f"Bearer {key}",
         "HTTP-Referer": "https://github.com/emo-assistant", "X-Title": "EMO"},
        orc.get("model", "nvidia/nemotron-nano-12b-2-vl"),
        text, image_uris,
        timeout=orc.get("timeout", 20),
        max_tokens=orc.get("max_tokens", 128),
    )


def _cloud_call(text, image_uris, cfg):
    """Cloudflare Workers AI, OpenAI-compat vision endpoint. Raises on failure.

    NOTE: if a given model rejects data-URI images on this endpoint, the fix is
    isolated here (swap to CF's native /ai/run/<model> image schema)."""
    vc = _vision_cfg(cfg)
    cf = vc.get("cloudflare", {})
    if not cf.get("enabled", True):
        raise RuntimeError("cloud vision disabled")
    # Credentials are single-sourced from the brain's Cloudflare block.
    creds = section("brain", {}).get("cloudflare", {})
    acct, token = creds.get("account_id"), creds.get("api_token")
    if not (acct and token):
        raise RuntimeError("no Cloudflare account_id/api_token in brain.cloudflare")
    base = f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/v1"
    return _openai_chat(
        base, {"Authorization": f"Bearer {token}"},
        cf.get("model", "@cf/meta/llama-3.2-11b-vision-instruct"),
        text, image_uris,
        timeout=cf.get("timeout", 12),
        max_tokens=cf.get("max_tokens", 128),
    )


def _local_call(text, image_uris, cfg):
    """Local llama-server (vision GGUF + mmproj). Raises on failure.

    Primary path is the OpenAI-compatible /v1/chat/completions multimodal schema
    (data-URI image_url blocks). Some llama.cpp builds reject that schema with an
    HTTP 400 — for those we fall back to the server's NATIVE /completion endpoint,
    which takes a llava-style `image_data` array + `[img-N]` markers in the prompt.
    """
    lc = _vision_cfg(cfg).get("local", {})
    if not lc.get("enabled", True):
        raise RuntimeError("local vision disabled")
    base = lc.get("server_url", "http://127.0.0.1:8081")
    timeout = lc.get("timeout", 120)
    max_tokens = lc.get("max_tokens", 128)
    try:
        return _openai_chat(base, {}, "local", text, image_uris, timeout, max_tokens)
    except urllib.error.HTTPError as e:
        if e.code != 400:
            raise                          # not a schema problem — let it propagate
        return _llama_native(base, text, image_uris, timeout, max_tokens)


def _llama_native(base_url, text, image_uris, timeout, max_tokens):
    """llama.cpp's native /completion multimodal format: raw base64 images in an
    `image_data` array, referenced from the prompt as [img-1], [img-2], ...."""
    url = base_url.rstrip("/") + "/completion"
    imgs, markers = [], ""
    for i, uri in enumerate([u for u in image_uris if u], start=1):
        b64 = uri.split(",", 1)[1] if "," in uri else uri     # strip data: prefix
        imgs.append({"id": i, "data": b64})
        markers += f"[img-{i}]"
    body = json.dumps({
        "prompt": f"USER:{markers}\n{text}\nASSISTANT:",
        "image_data": imgs,
        "n_predict": max_tokens,
        "temperature": 0.1,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    reply = (data.get("content") or "").strip()
    if not reply:
        raise RuntimeError(f"local /completion returned no text: {str(data)[:200]}")
    return reply


def cloud_reachable(cfg=None):
    """Cheap probe: is ANY cloud vision tier currently usable? Used as is_online.

    Pings OpenRouter, then Cloudflare, with a tiny text-only request. Returns
    True if either answers; False on total failure (no internet / disabled / bad
    creds), so presence falls back to offline mode.
    """
    cfg = cfg if cfg is not None else section("eyes", {})
    try:
        _cloud_tier("Reply with the single word OK.", [], cfg)
        return True
    except Exception:
        return False


def _cloud_tier(text, image_uris, cfg):
    """The online vision tier: OpenRouter first (best OCR/scene model), then
    Cloudflare. Raises only if BOTH fail, so callers fall through to local."""
    try:
        reply = _openrouter_call(text, image_uris, cfg)
        print("[eyes] vision via OpenRouter")
        return reply
    except Exception as e:
        print(f"[eyes] OpenRouter vision failed ({e.__class__.__name__}: {e}); trying Cloudflare.")
    reply = _cloud_call(text, image_uris, cfg)
    print("[eyes] vision via Cloudflare")
    return reply


# --- public API --------------------------------------------------------------
def describe(image_path, question, cfg=None):
    """Answer `question` about the image. Cloud first, local failover. "" if both fail."""
    cfg = cfg if cfg is not None else section("eyes", {})
    uri = _b64_data_uri(image_path)
    if not uri:
        print("[eyes] describe: no readable image.")
        return ""
    try:
        reply = _cloud_tier(question, [uri], cfg)     # OpenRouter -> Cloudflare
        return reply
    except Exception as e:
        print(f"[eyes] cloud vision failed ({e.__class__.__name__}: {e}); trying local.")
    try:
        reply = _local_call(question, [uri], cfg)
        print("[eyes] vision via local llama-server")
        return reply
    except Exception as e:
        print(f"[eyes] local vision failed ({e.__class__.__name__}: {e}).")
        return ""


# Strict, easy-to-parse identity prompt. We ask for two labelled yes/no tokens so
# a small model can't wander into prose we then have to guess at.
_ID_PROMPT = (
    "Image 1 is a REFERENCE photo of a known person. Image 2 is a NEW photo. "
    "Answer on ONE line, EXACTLY in this format and nothing else: "
    "PERSON=YES_or_NO SAME=YES_or_NO . "
    "PERSON = is there a human clearly visible in image 2. "
    "SAME = is the person in image 2 the same individual as in image 1."
)


def identify(image_path, ref_paths, cfg=None):
    """ONLINE-ONLY: is a person present, and are they the enrolled 'Boss'?

    Returns {"person": bool|None, "known": bool}. person=None means we couldn't
    ask (offline / no cloud / no reference) — the caller should treat presence
    generically. `ref_paths` is a list; the first readable one is used.
    """
    cfg = cfg if cfg is not None else section("eyes", {})
    cur = _b64_data_uri(image_path)
    ref = next((u for u in (_b64_data_uri(p) for p in (ref_paths or [])) if u), None)
    if not cur or not ref:
        return {"person": None, "known": False}
    try:
        # ref first, current second — the prompt refers to them as image 1 / 2.
        raw = _cloud_tier(_ID_PROMPT, [ref, cur], cfg)
    except Exception as e:
        print(f"[eyes] identify (cloud) failed ({e.__class__.__name__}); presence-only.")
        return {"person": None, "known": False}
    # Normalise "PERSON = YES" / "SAME: yes" etc. down to compact PERSON=YES tokens.
    compact = raw.upper().replace(" ", "").replace(":", "=")
    person = "PERSON=YES" in compact
    same = "SAME=YES" in compact
    return {"person": person, "known": person and same}


_PERSON_PROMPT = ("Is there a human being clearly visible in this photo? "
                  "Answer with ONE word only: YES or NO.")


def person_present(image_path, cfg=None):
    """ONLINE-ONLY yes/no: is a person in frame? Returns True/False, or None if
    we couldn't ask (offline / cloud down). Used to confirm arrivals/departures
    without needing an enrolled reference."""
    cfg = cfg if cfg is not None else section("eyes", {})
    uri = _b64_data_uri(image_path)
    if not uri:
        return None
    try:
        raw = _cloud_tier(_PERSON_PROMPT, [uri], cfg)
    except Exception:
        return None
    return "YES" in raw.upper()


if __name__ == "__main__":
    # Quick manual check: describe whatever the camera sees right now.
    from eyes import camera
    cfg = section("eyes", {})
    shot = camera.snapshot(cfg)
    if not shot:
        print("[eyes] no camera image; can't test vision.")
    else:
        print("[eyes] describe ->", describe(shot, "What is in view? One short sentence.", cfg))
