# EMO — Install & Setup (Termux, Android ARM64)

This is the running install log. We build EMO in **testable slices**; you don't
need every dependency before testing an early slice.

---

## 0. One-time Termux base setup

Install **Termux** and **Termux:API** from **F-Droid** (NOT the Play Store —
the Play Store builds are deprecated and the API bridge won't pair).

```bash
# Update package lists and upgrade
pkg update -y && pkg upgrade -y

# Core toolchain + python
pkg install -y python git wget clang cmake make termux-api

# Give Termux access to shared storage (creates ~/storage/*)
termux-setup-storage
# ^ Tap "Allow" on the Android permission popup that appears.
```

**Verify the API bridge works** (should make the phone vibrate / print JSON):

```bash
termux-vibrate -d 200
termux-tts-speak "E M O setup is working"
```

If those do nothing, open the **Termux:API app once**, then retry. If still
broken, the API app isn't paired — reinstall it from F-Droid.

---

## 1. Get the EMO folder onto the phone

On your **laptop**, the project lives at:
`C:\Users\ISHAN SHUKLA\Desktop\EMO\`

Sync that whole folder into the phone at:
`~/storage/shared/EMO/`  (this is the Android `Documents`-level shared storage;
`~/storage/shared` == internal storage root your file manager sees).

Use whichever you have: **Syncthing** (best — live two-way sync), Google Drive,
or a USB cable copy. After syncing:

```bash
cd ~/storage/shared/EMO
ls        # you should see: config.yaml  requirements.txt  face/  ...
```

> Tip: `~/storage/shared` can be slow for some ops. If Python complains about
> file permissions when running from shared storage, we can symlink the code
> into `~/EMO` and keep only editable files in shared storage. Not needed yet.

---

## 2. Slice 1 — FACE (test this first)

**No pip installs needed.** The face server is pure Python standard library
(we dropped FastAPI — its Rust-based `pydantic-core` dependency won't compile
on Termux's Python 3.14). Just sync the folder and run it.

> **Termux lesson for later slices:** prefer `pkg install python-<x>` over
> `pip install <x>` whenever a package exists (numpy, etc.). Pip-from-source
> often fails on 3.14 for anything with C/Rust extensions. We'll use `pkg`
> builds where possible.

### Test the face

**Session A — start the server:**
```bash
cd ~/storage/shared/EMO
python face/server.py
# -> [EMO face] serving on http://127.0.0.1:8008
```

Open the phone browser (Chrome/Firefox) to: **http://127.0.0.1:8008**
You should see EMO's cyan face, blinking and gently breathing.

**Session B — drive the expressions** (swipe to a new Termux session, or use
`tmux`; or just open a second Termux tab):
```bash
cd ~/storage/shared/EMO
python face/demo_states.py
```
Watch the browser: the face should cycle idle → listening → thinking →
speaking → happy → confused → error, with smooth transitions and color shifts.

**Quick one-off state change** without the demo script:
```bash
curl -s -X POST http://127.0.0.1:8008/state \
  -H "Content-Type: application/json" -d '{"state":"thinking"}'
```

### If it doesn't work
- **Blank page / can't connect:** make sure the server session is still
  running and you used `127.0.0.1` (not `localhost` on some Android browsers).
- **Face shows but won't change state:** the WebSocket may be blocked; the JS
  falls back to polling every 0.5s, so give it a moment. Check Session A for errors.
- **`pip` build errors:** run `pkg install python-pip` and
  `pip install --upgrade pip` first.

---

## 2b. Slice 2 — MOUTH / TTS (test this second)

**No install needed** — uses the phone's built-in TTS via Termux:API.

```bash
cd ~/storage/shared/EMO
python mouth/tts.py "Hello, I am EMO. Your phone can talk now."
```
You should hear the phone speak. If it's silent:
- Make sure the **Termux:API app** is installed (F-Droid) and media volume is up.
- Test the bridge directly: `termux-tts-speak "test"`.

Optional: install PyYAML so `config.yaml` values (voice rate/pitch, etc.) are
actually read instead of code defaults. TTS works without it.
```bash
pip install pyyaml       # if this fails to build, we'll deal with it; not critical yet
```

---

## 2c. Natural voice — sherpa-onnx neural TTS ⚠️ compile (fixes the robotic voice)

The default `termux-tts-speak` is Google's robotic voice. `config.yaml` now selects
**`mouth.engine: sherpa`** — a genuinely natural neural voice from
[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx), **built from source in Termux**
so it runs on Android's bionic libc natively (the piper binary is glibc-linked and
usually won't launch here — that's why EMO sounded robotic). The fallback ladder is
`sherpa → piper → termux`, so EMO always talks even before this is set up.

### 2c-1. Build the sherpa-onnx TTS CLI (in HOME, not shared storage)
Termux's cmake reports the OS as **Android**, so sherpa's bundled onnxruntime
*downloader* errors out ("Only support Linux, macOS, Windows"). **Do NOT** work
around it with `-DCMAKE_SYSTEM_NAME=Linux` — that pulls a **glibc** onnxruntime
that won't run on Termux's bionic libc. The clean fix is to link Termux's OWN
onnxruntime package (bionic-native):
```bash
pkg install cmake git onnxruntime
git clone https://github.com/k2-fsa/sherpa-onnx ~/sherpa-onnx
cd ~/sherpa-onnx && rm -rf build && mkdir build && cd build

# point sherpa at the pre-installed onnxruntime instead of downloading one
export SHERPA_ONNXRUNTIME_LIB_DIR=$PREFIX/lib
export SHERPA_ONNXRUNTIME_INCLUDE_DIR=$PREFIX/include/onnxruntime

cmake -DCMAKE_BUILD_TYPE=Release \
      -DBUILD_SHARED_LIBS=ON \
      -DSHERPA_ONNX_ENABLE_PYTHON=OFF \
      -DSHERPA_ONNX_ENABLE_TTS=ON \
      -DSHERPA_ONNX_ENABLE_WEBSOCKET=OFF \
      -DSHERPA_ONNX_ENABLE_PORTAUDIO=OFF \
      -DSHERPA_ONNX_USE_PRE_INSTALLED_ONNXRUNTIME_IF_AVAILABLE=ON \
      ..
make -j2                     # NOT `make -j2 <target>` — target name can differ
ls bin/ | grep offline-tts   # -> sherpa-onnx-offline-tts   (confirm it built)
```
Notes: PortAudio is disabled on purpose (no ALSA mic on Termux — TTS just writes a
WAV that ffplay plays). If `make` runs out of RAM, use `-j1`. If you ever re-run
cmake, `rm -rf build` first — a stale `CMakeCache.txt` makes it ignore the `..`
source path. Because we built shared libs, launching needs
`LD_LIBRARY_PATH=~/sherpa-onnx/build/lib` — `mouth/tts.py` sets that automatically
from `mouth.sherpa.lib_dir`, so no manual export at runtime.

### 2c-2. Download a voice (into HOME, re-sync safe)
EMO's default is now a **child voice**, which comes from the multi-speaker
**libritts_r** model (904 speakers — several sound like kids; you pick one by
speaker id). The bundle includes the `.onnx`, `tokens.txt`, **and**
`espeak-ng-data/` — one download:
```bash
mkdir -p ~/models/tts && cd ~/models/tts
BASE=https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models
curl -L -O $BASE/vits-piper-en_US-libritts_r-medium.tar.bz2
tar xf vits-piper-en_US-libritts_r-medium.tar.bz2
rm  vits-piper-en_US-libritts_r-medium.tar.bz2
ls vits-piper-en_US-libritts_r-medium/   # -> en_US-libritts_r-medium.onnx  tokens.txt  espeak-ng-data/
```
The paths in `config.yaml → mouth.sherpa` already point here. (Prefer the adult
male voice instead? Grab `vits-piper-en_US-ryan-medium.tar.bz2` the same way and
point the three `mouth.sherpa` paths at it, and remove the `sid` line.)

### 2c-3. Test the voice
```bash
cd ~/storage/shared/EMO
python mouth/tts.py "Hi Boss! It's me, EMO. Can you hear my new voice?"
```
You should hear a **child-like** voice, slower than before (`speed: 0.9`). If it
still sounds robotic, EMO fell back to termux — check the printed log line
(missing binary or model path) and confirm `ls ~/sherpa-onnx/build/bin` and
`ls ~/models/tts`.

### 2c-4. Pick the child voice you like (audition speaker ids)
libritts_r has 904 speakers, so the exact "child" depends on the `sid`. Config
ships `sid: 109` as a starting point — audition a few and set your favourite:
```bash
cd ~/models/tts
export LD_LIBRARY_PATH=$HOME/sherpa-onnx/build/lib
BIN=$HOME/sherpa-onnx/build/bin/sherpa-onnx-offline-tts
V=vits-piper-en_US-libritts_r-medium
for SID in 40 109 200 500 700; do
  $BIN --vits-model=$V/en_US-libritts_r-medium.onnx \
       --vits-tokens=$V/tokens.txt --vits-data-dir=$V/espeak-ng-data \
       --sid=$SID --vits-length-scale=1.1 \
       --output-filename=sid_$SID.wav "Hi, I am EMO, your little robot friend."
  echo "playing sid $SID"; ffplay -nodisp -autoexit -loglevel quiet sid_$SID.wav
done
```
Note the `sid` that sounds most child-like, then set `mouth.sherpa.sid` in
`config.yaml` to it. (Higher/younger feel: raise `--vits-length-scale` / lower
`speed`. You can also audition every speaker on the
[libritts_r sample page](https://k2-fsa.github.io/sherpa/onnx/tts/all/English/vits-piper-en_US-libritts_r-medium.html).)

---

## 3. Upcoming slices (not yet — installed when we build each)

| Slice | Module | Heavy? | Notes |
|------|--------|--------|-------|
| 2 | Mouth / TTS | no | Starts with `termux-tts-speak` (zero setup). sherpa-onnx neural voice in §2c. |
| 3 | Eyes / Camera + Vision | opt. | `termux-camera-photo` + hybrid VLM (cloud, or local llama-server+mmproj). See §4f. |
| 4 | Ears / Wake word (Porcupine) | maybe | Needs Picovoice key; `pvporcupine` ARM wheel may fail — fallback planned. |
| 5 | Ears / STT (whisper.cpp) | **yes** | Compile whisper.cpp + download `base.en` (~140MB). |
| 6 | Brain / Local GGUF | **yes** | `llama-cpp-python` source build + ~2GB model download. |
| 7 | Core / Orchestrator + run.sh | no | Ties it all together. |

---

## 4. Slice 6 — BRAIN (local GGUF via llama.cpp) ⚠️ heavy

This is the big one: a C++ compile plus a multi-hundred-MB model download.
EMO's `brain.py` talks to a local `llama-server` over HTTP, so nothing is
compiled in Python.

### 4a. Build llama.cpp (compile in HOME, not shared storage)

Shared storage (`/storage/emulated/0`) doesn't handle build artifacts/symlinks
well — build under `~` instead. The binary location doesn't need to be synced.

```bash
pkg upgrade -y                      # IMPORTANT: get a current base first (see gotcha below)
pkg install -y clang cmake git
cd ~
git clone --depth=1 https://github.com/ggml-org/llama.cpp
cd ~/llama.cpp
cmake -B build \
  -DBUILD_SHARED_LIBS=ON \
  -DLLAMA_CURL=OFF \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_FLAGS_RELEASE="-O2 -DNDEBUG" \
  -DCMAKE_CXX_FLAGS_RELEASE="-O2 -DNDEBUG"
cmake --build build -j2 --target llama-server
# -> produces ~/llama.cpp/build/bin/llama-server
```

**Common failures & fixes:**
- **`'spawn.h' file not found`** (fails building `mtmd`, ~70–86%): your Termux
  base is out of date and missing that header. Run `pkg upgrade -y`, confirm
  `ls $PREFIX/include/spawn.h` exists, then re-run the build (it resumes).
- **`unknown argument: '-02'`**: that's a zero — the flag is `-O2` (letter O).
- **Compiler `Killed` / OOM**: drop to `-j1`, and if a single file still dies,
  lower to `-O1` in both FLAGS lines.
- Building with `BUILD_SHARED_LIBS=ON` means the binary needs its `.so` files;
  if launch complains about `libggml.so`, prefix with
  `LD_LIBRARY_PATH=~/llama.cpp/build/bin`.

### 4b. Download a model (start SMALL)

A 1–1.5B model in Q4 (~1 GB) is the realistic starting point on a phone —
still expect several seconds per reply.

> ⚠️ **Download into Termux HOME, not the EMO folder.** The EMO folder gets
> deleted-and-replaced every time you sync code from the laptop. Anything
> generated on the phone that lives inside it (the multi-GB model, camera
> snapshots) would be wiped. Keep generated data in `~` where sync can't reach.

```bash
mkdir -p ~/models
cd ~/models
# Qwen2.5-1.5B-Instruct, Q4_K_M (~1.1 GB) — good quality/size balance:
wget -O qwen2.5-1.5b-instruct-q4_k_m.gguf \
  "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf?download=true"
```
`config.yaml` → `brain.local.model_path` already points at
`~/models/qwen2.5-1.5b-instruct-q4_k_m.gguf`. The bigger `Phi-3-mini` (~2.3 GB)
is the "ideal but slower" option once the pipeline works.

### 4c. Test the brain

**Session 1 — start the model server** (model lives in `~/models`, not the EMO folder):
```bash
LD_LIBRARY_PATH=~/llama.cpp/build/bin ~/llama.cpp/build/bin/llama-server \
  -m ~/models/qwen2.5-1.5b-instruct-q4_k_m.gguf \
  -c 2048 -t 4 --host 127.0.0.1 --port 8080
# wait for: "server is listening on http://127.0.0.1:8080"
```

**Session 2 — chat with EMO's brain:**
```bash
cd ~/storage/shared/EMO
python brain/brain.py "In one short sentence: who are you?"
# or interactive:
python brain/brain.py
```

If you see *"My local brain isn't running"*, the server session isn't up yet.

### 4d. (Optional) test the API brain instead
```bash
export ANTHROPIC_API_KEY=sk-ant-...      # your key
# set brain.mode: api in config.yaml, then:
python brain/brain.py "Say hi in five words."
```

---

## 4d-2. Cloud brain + vision via OpenRouter (online = cloud, offline = local)

EMO routes both its **brain** and its **vision** by connectivity, best-first:

```
ONLINE :  OpenRouter  ->  Cloudflare  ->  local model
OFFLINE:  local model  (cloud tiers skipped — no wasted timeouts)
```

OpenRouter is tier 1 (best free models). Everything still works without it
(it just falls to Cloudflare, then the on-device models), so this is optional —
but it gives EMO much stronger answers and OCR when online.

### 4d-2a. Get a key + set it in the environment (never in the repo)
1. Make a free key at <https://openrouter.ai/keys>.
2. Set it in Termux. Per-session:
   ```bash
   export OPENROUTER_API_KEY=sk-or-...
   ```
   Or make it permanent (so every `bash run.sh` sees it) — add that line to
   `~/.bashrc`:
   ```bash
   echo 'export OPENROUTER_API_KEY=sk-or-...' >> ~/.bashrc
   source ~/.bashrc
   ```
   The key is read from the environment **only** — it is never written into the
   synced EMO folder, so a re-sync can't leak or wipe it.

### 4d-2b. Verify the model slugs (IMPORTANT — avoids silent 404s)
`config.yaml` ships with these defaults, but **free model IDs drift and some get
retired**. Confirm each is current, or EMO silently drops to Cloudflare:

| Job | config key | shipped default |
|-----|-----------|-----------------|
| Brain | `brain.openrouter.model` | `nvidia/nemotron-3-super-120b-a12b:free` |
| Vision | `eyes.vision.openrouter.model` | `nvidia/nemotron-nano-12b-v2-vl:free` |

Open <https://openrouter.ai/models?q=free>, click the model, copy the exact ID
shown on its page into `config.yaml`. **Avoid slugs marked "going away"** — as of
mid-2026 Llama 3.3/3.2, Qwen3, Hermes 3, Hy3 and Venice were all being retired.
Durable fast alternatives if Nemotron feels slow (it's a reasoning model):
`openai/gpt-oss-20b`, `nvidia/nemotron-nano-9b-v2`.

### 4d-2c. Confirm it's live
```bash
cd ~/storage/shared/EMO
bash run.sh          # prints "[run] OpenRouter key detected" if the key is set
```
Then ask EMO something (online) and watch the terminal:
- `[brain] via OpenRouter (nvidia/nemotron-3-super)` → tier 1 working.
- `[brain] OpenRouter failed (... 404 ...)` → wrong/retired slug; fix per 4d-2b.
- `[brain] via local llama-server (offline)` → no internet; local took over.
Camera commands print the same three ways as `[eyes] vision via ...`.

**Memory & personality:** every conversation is saved to `~/.emo_history/` and
EMO keeps a growing profile of you in `~/.emo_profile.md` (injected each session,
refreshed by the cloud brain at the end of each chat). Both live OUTSIDE the
synced folder, so re-syncing never wipes what EMO has learned. `cat
~/.emo_profile.md` to see what it remembers; "forget everything" wipes short-term
memory.

---

## 4e. Slice 5 — EARS / STT (whisper.cpp) ⚠️ another compile

Lets you **speak** to EMO. Same build pattern as llama.cpp (simpler — no `mtmd`,
so no `spawn.h` issue), plus `ffmpeg` to convert mic audio for whisper.

### 4e-1. Build whisper.cpp (in HOME)
```bash
pkg install -y ffmpeg
cd ~
git clone --depth=1 https://github.com/ggml-org/whisper.cpp
cd ~/whisper.cpp
cmake -B build \
  -DWHISPER_CURL=OFF \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_FLAGS_RELEASE="-O2 -DNDEBUG" \
  -DCMAKE_CXX_FLAGS_RELEASE="-O2 -DNDEBUG"
cmake --build build -j2 --target whisper-cli
# -> ~/whisper.cpp/build/bin/whisper-cli
```

### 4e-2. Download the whisper models (into HOME)
The upgraded default is **quantized medium.en** for commands (the best on-device
English accuracy — noticeably fewer mis-hearings than small/base) plus **quantized
tiny.en** for the snappy wake check. Both are prebuilt on Hugging Face:
```bash
cd ~/models
BASE=https://huggingface.co/ggerganov/whisper.cpp/resolve/main
# command model — medium.en, q5_0 (~539 MB): most accurate, slower decode
wget -O ggml-medium.en-q5_0.bin "$BASE/ggml-medium.en-q5_0.bin?download=true"
# wake model — tiny.en, q5_1 (~32 MB): loads fast for keyword spotting
wget -O ggml-tiny.en-q5_1.bin   "$BASE/ggml-tiny.en-q5_1.bin?download=true"
```
`config.yaml` → `ears.stt.model` / `wake_model` / `binary` already point at these
home paths, and `ears.stt.flash_attn: true` adds whisper-cli's `-fa` (flash
attention) for a faster decode.

**Latency note:** medium.en is markedly more accurate but slower per utterance on
the Dimensity 700 (expect a few seconds; only *commands* pay this — wake stays on
tiny.en). If it drags too much, download `ggml-small.en-q5_1.bin` (~190 MB) or
`ggml-base.en-q5_1.bin` (~60 MB) and point `ears.stt.model` there instead — same
URL pattern. *Custom quantization:* build whisper.cpp's `quantize`, e.g.
`./build/bin/quantize models/ggml-base.en.bin models/ggml-base.en-q4_0.bin q4_0`.
*Old whisper-cli* that errors on `-fa`? Set `ears.stt.flash_attn: false`.

### 4e-3. Test STT in isolation
```bash
cd ~/storage/shared/EMO
python ears/stt.py
```
Default `capture_mode: single` records **one continuous ~6s take** (no mic
restarts, so no dropped words) — **start speaking the moment it says "speak NOW"**
and say a full sentence. It then prints what it heard. The **first** run pops an
Android mic-permission prompt: tap **Allow**, then run it again.

If it prints your words → ears work. Common snags:
- *"mic failed to start"* → grant mic permission to the Termux:API app.
- *"ffmpeg not found"* → `pkg install ffmpeg`.
- *"whisper binary/model not found"* → check the build finished and `ls ~/models`.
- Empty/garbled → try `tiny.en`, or speak closer/clearer; on-device STT of a
  few seconds takes a moment, that's normal.

---

## 4f. Slice 3 — EYES (camera + vision)

Gives EMO sight: **presence detection** (greets you when you sit down, says
goodbye when you leave), **face memory** ("EMO, remember my face" → later
"Welcome back, Boss"), and on-request **"what do you see / read this"**.

There are **two eye modes**, and the orchestrator runs exactly ONE (both own the
single camera): **`ambient`** — always-on, alternates BOTH cameras and narrates
the scene aloud whenever it changes (heavy: a VLM call per frame + a shutter each
shot); and **`presence`** — the light motion-gated greeter. `ambient` is on by
default (`eyes.ambient.enabled: true`); set it false to fall back to `presence`.
Offline vision (§4f-3) makes ambient narrate without internet — otherwise it
needs the cloud path.

Design (same hybrid pattern as the brain): **cloud vision first** (Cloudflare
Workers AI, no setup — reuses the token already in `config.yaml`), **local
`llama-server` + a vision model as the offline failover.** All pure stdlib +
`termux-camera-photo` + `ffmpeg`; **no opencv/tflite/dlib** (none build on 3.14).

### 4f-1. Camera permission (zero install — Termux:API is already set up)
```bash
cd ~/storage/shared/EMO
python eyes/camera.py
```
The **first** run pops the Android **camera-permission** prompt → tap **Allow**,
then run it again. Success prints a path under `~/.emo_eyes/`. Snapshots and
enrolled faces live in `~` (OUTSIDE the EMO folder) so a code re-sync never wipes
them.

> ⚠️ `termux-camera-photo` is a real shutter — on some ROMs it makes a shutter
> **sound**, flashes the lens, or briefly shows a preview. `presence` polls
> slowly (`eyes.presence.poll_seconds: 25`) to soften this; **`ambient` fires
> continuously**, so expect frequent shutter clicks — raise
> `eyes.ambient.interval_seconds` or set `eyes.ambient.enabled: false` if it's
> too much. Both are toggleable; the on-request commands are unaffected.

### 4f-2. Test cloud vision (online — works immediately)
Point the camera at something, then:
```bash
python -c "from core.config import load_config as L; from eyes import camera,vision; c=L()['eyes']; s=camera.snapshot(c); print(vision.describe(s,'What is this? One short sentence.',c))"
```
You should get a sensible caption "via Cloudflare". If the chosen CF vision model
rejects the request, swap `eyes.vision.cloudflare.model` in `config.yaml`
(e.g. to `@cf/llava-hf/llava-1.5-7b-hf`).

### 4f-3. (Optional) offline vision — a small vision GGUF + its mmproj ⚠️ heavy
Only needed if you want **"what do you see"** to work with no internet (presence
greetings work offline without it — they just stay generic). Download BOTH a
vision model AND its **mmproj** (the image projector) into `~/models/vision`.
These are the **verified** filenames from the ggml-org moondream2 repo (the
text model is F16, ~2.8 GB; the mmproj ~910 MB — the phone's 12 GB RAM holds it):

```bash
mkdir -p ~/models/vision
BASE=https://huggingface.co/ggml-org/moondream2-20250414-GGUF/resolve/main
# text model (note the real filename ends _ct-vicuna — the plain f16 URL 404s)
curl -L -o ~/models/vision/moondream2-text-model-f16.gguf $BASE/moondream2-text-model-f16_ct-vicuna.gguf
# mmproj (image projector)
curl -L -o ~/models/vision/moondream2-mmproj-f16.gguf     $BASE/moondream2-mmproj-f16-20250414.gguf
```
`eyes.vision.local.model_path` / `mmproj_path` already point at these two files.
`run.sh` starts a **second** `llama-server` on **:8081** with `--mmproj` when both files exist — the phone's
12 GB RAM holds it alongside the text brain. Alternatives: **Qwen2-VL-2B-Instruct
GGUF** (also needs its mmproj). Test the offline path by turning Wi-Fi off and
re-running the 4f-2 command — it should answer "via local llama-server" (slower).

### 4f-4. Enroll your face + recognition
```bash
# Look at the FRONT camera, then:
python -c "from core.config import load_config as L; from eyes import faces; print('enrolled' if faces.enroll(L()['eyes']) else 'failed'); print(faces.ref_paths())"
```
Recognition ("who am I", and personalised presence greetings) is **online-only**
— local Q4 vision models aren't reliable at *same-specific-person* matching, so
offline EMO greets generically. Once enrolled, in a conversation say **"who am
I"** to test.

### 4f-5. Full run
`bash run.sh` now also launches the vision server (if configured) and starts the
presence watcher. Sit in front of the front camera → EMO greets you; leave the
frame for a few polls → it says goodbye. In conversation, try: **"remember my
face"**, **"what do you see"**, **"who am I"**, **"read this"**. Watch the logs
for `[presence]` motion values and tune `eyes.presence.motion_threshold`.

---

## 4g. Physical awareness — DIZZY shake + face-down ASLEEP (zero install)

Gives EMO a sense of its body via the phone's accelerometer. A background thread
(`core/sensors.py`, started by the orchestrator) streams `termux-sensor` and
reacts to motion — **no new packages** beyond Termux:API, which STT already uses.

- **Shake it** → total force spikes past `sensors.dizzy_threshold` (25 m/s²) →
  EMO **cuts off** whatever it's saying/thinking, plays `sound/dizzy.wav`,
  stumbles out a disoriented line, and rides a 5 s cooldown before resuming.
- **Lay it face-DOWN** on the desk → after `facedown_seconds` EMO goes **ASLEEP**
  (silent deep standby, mic closed). **Turn it face-up** → it wakes (and speaks
  `sensors.wake_line`, if set).

Test the sensor layer in isolation first (prints each reflex as it fires):
```bash
cd ~/storage/shared/EMO
python core/sensors.py
# SHAKE the phone  -> ">> DIZZY"
# lay it FACE-DOWN -> ">> ASLEEP"   ;  turn it FACE-UP -> ">> AWAKE"
```
First run pops the Termux:API **sensor** permission — tap **Allow**, rerun.
Drop a short `sound/dizzy.wav` into the synced `EMO/sound/` folder for the
stumble SFX (optional — it soft-skips if missing). Tune thresholds in
`config.yaml → sensors`; set `sensors.enabled: false` to turn the feature off.

*Snags:* `termux-sensor not found` → `pkg install termux-api` + install the
Termux:API app. Too touchy / never triggers → raise/lower `dizzy_threshold`.
Sleeps when just tilted → make `facedown_z` more negative (e.g. `-8.5`).

---

## 4h. Real-time gestures + presence (in the browser face, zero compile)

EMO watches your **hand gestures** (👍 👎 ✌️ ☝️ ✊ 👋 🤟) and notices when
**someone sits down** in front of the camera — and reacts out loud in real time.

**Why in the browser?** The face is already a browser tab, and the browser is the
only place on an unrooted phone that gets a genuine shutter-free ~30fps,
GPU-accelerated (Mali-G57) camera feed. Google's **MediaPipe Tasks (WASM)** runs
the same gesture + body-pose models right there, fully offline. Detections POST to
the face server's `/event` channel and the orchestrator speaks a canned reaction —
the same path the dizzy reflex already uses. **MediaPipe's Python package can't
install on this phone** (glibc + Python 3.9–3.12 only), which is why this lives in
the browser instead.

### 4h-1. Fetch the MediaPipe assets (one-time, on the phone)
```bash
cd ~/storage/shared/EMO
pkg install curl
bash face/static/vendor/fetch_mediapipe.sh
# downloads ~15-30 MB into face/static/vendor/mediapipe/ (git/sync-ignored)
ls -la face/static/vendor/mediapipe face/static/vendor/mediapipe/wasm
```
The script pins an exact MediaPipe version (never `@latest` — the wasm folder
layout has broken across releases). If a URL 404s, open
<https://www.jsdelivr.com/package/npm/@mediapipe/tasks-vision>, bump `VER` in the
script to a current version, and re-run. These assets live OUTSIDE the code sync,
so re-run this once after each delete-and-paste sync.

### 4h-2. Grant the browser camera permission
On the next `bash run.sh`, when the face opens the browser prompts for **camera**
access — tap **Allow**. Then:
- **Wave / thumbs-up / ✌️** at the front camera → EMO speaks the matching line.
- **Sit down in frame** → EMO greets you ("Oh, hey there!").

Tune in `config.yaml → gestures`: `min_confidence`, `cooldown_seconds`,
`presence_greeting`, and per-gesture `lines`. Set `gestures.enabled: false` to turn
it all off. Watch the browser's dev console (`chrome://inspect` or Kiwi/Firefox
dev tools) for `[vision]` logs, and the orchestrator terminal for `[event]` lines.

### 4h-3. Camera sharing note (front vs. back)
The browser holds the **front** camera continuously for gestures; the Python eyes
(`eyes.ambient` / `presence`, §4f) use the **back** camera (`eyes.camera_id: 0`),
so they don't fight. If your ROM refuses two camera clients at once, either set
`eyes.ambient.enabled: false` (front-cam gestures already cover "someone's here"),
or set `gestures.camera: environment` to move gestures to the back camera. No code
change needed either way.

---

## 4i. Free up space — remove superseded models

After the new voice + ears verify (§2c-3, §4e-3), delete the models they replaced.
**Only run these once the new setup works** — nothing is auto-deleted.
```bash
# old non-quantized / smaller whisper models replaced by medium.en:
rm -f ~/models/ggml-base.en.bin            # if you ever had the plain base.en
rm -f ~/models/ggml-small.en-q5_1.bin      # OPTIONAL: keep it as a fast fallback
                                           #   (config comments point back to it)
# old piper voice, now that sherpa is the voice (OPTIONAL — piper is a fallback):
# rm -rf ~/models/piper
```
**Keep:** `ggml-medium.en-q5_0.bin` + `ggml-tiny.en-q5_1.bin` (ears), `~/models/tts`
(sherpa voice), the vision moondream model + mmproj (§4f), and the qwen brain.

---

## 5. Slice 7 — RUN EMO (Face + Brain + TTS together)

This is the payoff: one command starts the local brain, the face server, opens
the face in your browser, and drops you into a conversation. You type, EMO's
face reacts (idle → listening → thinking → speaking), and it talks back.

```bash
cd ~/storage/shared/EMO
bash run.sh
```

What you should see/hear:
1. `[run] starting local brain...` then `local brain ready.` (~10–30s first load)
2. The face opens in your browser and greets you out loud ("EMO online...").
3. A `you>` prompt. Type something, watch the face go **thinking** then
   **speaking** while EMO replies.
4. `Ctrl-C` stops everything cleanly (brain server + face server included).

Notes:
- If the face tab doesn't auto-open, browse to `http://127.0.0.1:8008` manually.
- Local replies take a few seconds on-device — that's expected. To use the fast
  Claude brain instead: set `brain.mode: api` in `config.yaml` and
  `export ANTHROPIC_API_KEY=sk-ant-...` before `bash run.sh`.
- Voice input isn't wired yet — that's the next slice (STT via whisper.cpp),
  after which you'll talk to EMO instead of typing. The orchestrator is already
  built to swap typed input for speech with a one-function change.
