#!/data/data/com.termux/files/usr/bin/bash
# ==========================================================================
# EMO — single entrypoint
# Starts: (local brain) llama-server -> face server -> browser -> orchestrator
# Stops everything cleanly on Ctrl-C.
# Run with:  bash run.sh   (from ~/storage/shared/EMO)
# ==========================================================================
cd "$(dirname "$0")" || exit 1

FACE_PID=""
LLAMA_PID=""
VISION_PID=""
WAKELOCK=0
LOG="${TMPDIR:-$HOME}/emo-llama.log"           # Termux has no /tmp — use $TMPDIR
VLOG="${TMPDIR:-$HOME}/emo-vision.log"         # local vision server log (Slice 3)

# --- Keep Termux alive in the background --------------------------------------
# Android aggressively kills a backgrounded Termux — which happens the instant
# you switch to the browser to see EMO's face, taking the whole app down with it.
# termux-wake-lock holds a partial wake lock so the session survives. Requires
# Termux:API (pkg install termux-api). Released again in cleanup().
if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock && WAKELOCK=1 && echo "[run] wake-lock held (survives backgrounding)."
else
    echo "[run] NOTE: termux-wake-lock not found (pkg install termux-api) —"
    echo "      Android may kill EMO when you switch to the browser."
fi

cleanup() {
    echo ""
    echo "[run] shutting down..."
    [ -n "$FACE_PID" ]   && kill "$FACE_PID"   2>/dev/null
    [ -n "$LLAMA_PID" ]  && kill "$LLAMA_PID"  2>/dev/null
    [ -n "$VISION_PID" ] && kill "$VISION_PID" 2>/dev/null
    [ "$WAKELOCK" = "1" ] && termux-wake-unlock 2>/dev/null
    exit 0
}
trap cleanup INT TERM

# --- tiny helper: is something listening on a localhost port? (python is always present) ---
port_open() {
    python -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',$1))==0 else 1)" 2>/dev/null
}

# --- read a couple of config values without needing a YAML parser in bash ---
BRAIN_MODE=$(python -c "from core.config import section; print((section('brain',{}).get('mode') or 'local'))" 2>/dev/null)
MODEL=$(python -c "from core.config import section; print(section('brain',{}).get('local',{}).get('model_path',''))" 2>/dev/null)
FACE_PORT=3000
LLAMA_BIN="$HOME/llama.cpp/build/bin/llama-server"

# --- 1. Local brain: start llama-server if needed ---
if [ "$BRAIN_MODE" = "local" ]; then
    if port_open 8080; then
        echo "[run] local brain already running on :8080"
    elif [ -x "$LLAMA_BIN" ] && [ -f "$MODEL" ]; then
        echo "[run] starting local brain (llama-server)... this takes ~10-30s to load the model"
        LD_LIBRARY_PATH="$HOME/llama.cpp/build/bin" "$LLAMA_BIN" \
            -m "$MODEL" -c 2048 -t 4 --host 127.0.0.1 --port 8080 \
            >"$LOG" 2>&1 &
        LLAMA_PID=$!
        # wait (up to ~60s) for the server to come up
        for _ in $(seq 1 60); do
            port_open 8080 && break
            sleep 1
        done
        port_open 8080 && echo "[run] local brain ready." \
                       || echo "[run] WARNING: llama-server didn't come up — see $LOG"
    else
        echo "[run] NOTE: brain=local but llama-server or model not found."
        echo "      bin:   $LLAMA_BIN"
        echo "      model: $MODEL"
        echo "      EMO will still run but the brain will say it's not available."
    fi
fi

# --- 1b. Local vision server (Slice 3): a SECOND llama-server with an mmproj ---
# Only started if eyes.vision.local is enabled AND the vision model + projector
# exist. Offline vision falls back to this; if it's absent, cloud vision still
# works and the local path simply stays unavailable. Phone has RAM for both.
V_ENABLED=$(python -c "from core.config import section; print(section('eyes',{}).get('vision',{}).get('local',{}).get('enabled', False))" 2>/dev/null)
V_MODEL=$(python -c "from core.config import section; print(section('eyes',{}).get('vision',{}).get('local',{}).get('model_path',''))" 2>/dev/null)
V_MMPROJ=$(python -c "from core.config import section; print(section('eyes',{}).get('vision',{}).get('local',{}).get('mmproj_path',''))" 2>/dev/null)
if [ "$V_ENABLED" = "True" ]; then
    if port_open 8081; then
        echo "[run] local vision server already running on :8081"
    elif [ -x "$LLAMA_BIN" ] && [ -f "$V_MODEL" ] && [ -f "$V_MMPROJ" ]; then
        echo "[run] starting local vision server (llama-server + mmproj)..."
        LD_LIBRARY_PATH="$HOME/llama.cpp/build/bin" "$LLAMA_BIN" \
            -m "$V_MODEL" --mmproj "$V_MMPROJ" \
            -c 2048 -t 4 --host 127.0.0.1 --port 8081 \
            >"$VLOG" 2>&1 &
        VISION_PID=$!
        for _ in $(seq 1 60); do
            port_open 8081 && break
            sleep 1
        done
        port_open 8081 && echo "[run] local vision ready (offline eyes)." \
                       || echo "[run] WARNING: vision server didn't come up — see $VLOG (cloud vision still works)."
    else
        echo "[run] NOTE: offline vision model/projector not found — using cloud vision only."
        echo "      model:  $V_MODEL"
        echo "      mmproj: $V_MMPROJ   (see INSTALL.md Slice 3 to download)"
    fi
fi

# --- 2. Start ttyd (web terminal for EMO HUD popup overlay) ---
if command -v ttyd >/dev/null 2>&1; then
    echo "[run] starting ttyd terminal on :7681..."
    ttyd -p 7681 -W bash >/dev/null 2>&1 &
fi

# --- 2b. Face server (background, port 3000) ---
echo "[run] starting face server on port 3000..."
python face/server.py --port 3000 &
FACE_PID=$!
sleep 1

# --- 3. Open EMO's face in the phone browser ---
URL="http://127.0.0.1:${FACE_PORT:-3000}"
echo "[run] EMO's face:  $URL   (Opening in phone browser...)"
if command -v termux-open-url >/dev/null 2>&1; then
    termux-open-url "$URL" >/dev/null 2>&1 || true
fi

# --- 4. Orchestrator (foreground) ---
# Brain routing: online -> OpenRouter -> Cloudflare; offline -> local llama.
# The OpenRouter key is read from the environment (never stored in the repo).
# Set it once per session:  export OPENROUTER_API_KEY=sk-or-...   (or add it to
# ~/.bashrc so it's always present). We just report whether it's visible here.
if [ -n "$OPENROUTER_API_KEY" ]; then
    echo "[run] OpenRouter key detected — cloud brain tier 1 enabled."
else
    echo "[run] no OPENROUTER_API_KEY set — brain uses Cloudflare then local."
    echo "      (export OPENROUTER_API_KEY=sk-or-...  to enable the top tier.)"
fi

echo "[run] starting EMO. Type to talk; Ctrl-C to quit."
python core/orchestrator.py

cleanup
