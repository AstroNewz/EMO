"""
EMO — Physical sensor awareness (accelerometer)
================================================
Gives EMO a sense of its body. A single daemon thread streams the phone's
accelerometer through Termux:API's `termux-sensor` and turns raw (x, y, z)
vector forces into two reflexes:

  DIZZY   — a sudden shake / jerk. The total force magnitude sqrt(x²+y²+z²)
            spikes well past gravity's ~9.8 m/s² (default trigger > 25 m/s²),
            so a good shove makes EMO stumble.
  ASLEEP  — the phone is laid face-DOWN. With the screen pointing at the table,
            gravity sits on the negative Z axis (z ≈ -9.8). Held there for a
            couple of seconds, EMO drops into a deep, silent standby.

Design notes
------------
* Pure stdlib. `termux-sensor` emits pretty-printed JSON blocks back-to-back;
  we reassemble each object by tracking brace depth (sensor values are plain
  numbers, so no braces hide inside strings) and parse it with `json`.
* This module knows NOTHING about the orchestrator. It only detects physics and
  fires the callbacks it was handed (`on_dizzy`, `on_sleep`, `on_wake`), so it
  stays reusable and easy to test in isolation.
* We use the accelerometer specifically because both signals are expressed in
  m/s²: total force for the shake threshold, and the gravity vector for
  face-down. (A gyroscope reports rad/s and can't see "down", so it's not used.)
* Robust for the flaky Termux API layer: a missing binary soft-fails and the
  thread just exits; any streaming/parse error is caught, logged, and the reader
  relaunches after a short pause; on shutdown we always run `termux-sensor -c`
  to release the sensor HAL (it stays registered otherwise and drains battery).

Standalone test (shake the phone, then lay it face-down):
    python core/sensors.py
"""

import json
import math
import shutil
import threading
import subprocess
import time


def _sensor_available():
    return shutil.which("termux-sensor") is not None


def _iter_json_objects(stream, stop_event):
    """Yield each complete JSON object from `termux-sensor`'s pretty-printed
    stream. We accumulate lines and emit once the brace depth returns to zero."""
    buf = []
    depth = 0
    started = False
    for line in stream:
        if stop_event.is_set():
            break
        buf.append(line)
        depth += line.count("{") - line.count("}")
        if "{" in line:
            started = True
        if started and depth <= 0:
            text = "".join(buf).strip()
            buf, depth, started = [], 0, False
            if not text:
                continue
            try:
                yield json.loads(text)
            except Exception:
                continue          # a torn/partial block — skip it, keep reading


def _xyz(reading):
    """Pull the first (x, y, z) triple out of a termux-sensor reading dict.

    Shape: {"<sensor label>": {"values": [x, y, z, ...]}}. The label varies by
    device (e.g. "LSM6DSO Accelerometer"), so we grab the first nested dict that
    carries a numeric `values` list rather than hard-coding a key. None on miss.
    """
    if not isinstance(reading, dict):
        return None
    for val in reading.values():
        if isinstance(val, dict):
            vals = val.get("values")
            if isinstance(vals, list) and len(vals) >= 3:
                try:
                    return float(vals[0]), float(vals[1]), float(vals[2])
                except (TypeError, ValueError):
                    return None
    return None


def _safe(cb):
    """Fire a callback without ever letting its failure kill the reader thread."""
    if cb is None:
        return
    try:
        cb()
    except Exception as e:
        print(f"[sensors] callback error: {e.__class__.__name__}: {e}")


def _shutdown_proc(proc):
    if not proc:
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except Exception:
            proc.kill()
    except Exception:
        pass


def _release_sensors():
    """Unregister every sensor termux-sensor left active (frees the HAL)."""
    if not _sensor_available():
        return
    try:
        subprocess.run(["termux-sensor", "-c"], timeout=5,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def watch(config, on_dizzy=None, on_sleep=None, on_wake=None, stop_event=None):
    """Stream the accelerometer and fire reflex callbacks. Blocks (run me on a
    daemon thread). Returns immediately if sensors are disabled/unavailable.

    Callbacks (each optional, called with no args):
        on_dizzy — a jerk spike crossed `dizzy_threshold` (debounced by the
                   cooldown so one shake = one call).
        on_sleep — the phone has been face-down for `facedown_seconds`.
        on_wake  — the phone was turned back face-up after being asleep.
    """
    scfg = (config or {}).get("sensors", {}) or {}
    if not scfg.get("enabled", True):
        return
    if not _sensor_available():
        print("[sensors] termux-sensor not found (pkg install termux-api); "
              "physical awareness off.")
        return

    sensor = scfg.get("sensor_name", "accelerometer")
    delay = int(scfg.get("poll_delay_ms", 200))
    dizzy_thr = float(scfg.get("dizzy_threshold", 25.0))
    dizzy_cd = float(scfg.get("dizzy_cooldown", 5.0))
    fd_z = float(scfg.get("facedown_z", -7.0))
    fd_secs = float(scfg.get("facedown_seconds", 2.0))
    # Hysteresis so a phone hovering near the threshold can't flap sleep on/off.
    fd_release = fd_z + float(scfg.get("facedown_release_margin", 2.0))

    stop_event = stop_event or threading.Event()

    asleep = False
    facedown_since = None
    last_dizzy = -1e9              # monotonic of last dizzy fire (debounce)

    print(f"[sensors] physical awareness on — shake > {dizzy_thr:g} m/s² = dizzy, "
          f"face-down > {fd_secs:g}s = sleep.")

    try:
        while not stop_event.is_set():
            proc = None
            try:
                proc = subprocess.Popen(
                    ["termux-sensor", "-s", sensor, "-d", str(delay)],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, bufsize=1,
                )
                for reading in _iter_json_objects(proc.stdout, stop_event):
                    if stop_event.is_set():
                        break
                    xyz = _xyz(reading)
                    if xyz is None:
                        continue
                    x, y, z = xyz
                    mag = math.sqrt(x * x + y * y + z * z)
                    now = time.monotonic()

                    # --- ASLEEP: sustained face-down (gravity on -Z) ----------
                    if z < fd_z:
                        if facedown_since is None:
                            facedown_since = now
                        elif not asleep and (now - facedown_since) >= fd_secs:
                            asleep = True
                            _safe(on_sleep)
                    elif z > fd_release:
                        facedown_since = None
                        if asleep:
                            asleep = False
                            _safe(on_wake)

                    # --- DIZZY: sharp jerk / total-force spike ----------------
                    # Suppressed while asleep (a resting phone shouldn't reel)
                    # and debounced so one shove = exactly one stumble.
                    if (not asleep and mag > dizzy_thr
                            and (now - last_dizzy) >= dizzy_cd):
                        last_dizzy = now
                        _safe(on_dizzy)
            except Exception as e:
                print(f"[sensors] reader error ({e.__class__.__name__}: {e}); "
                      "retrying...")
            finally:
                _shutdown_proc(proc)

            # Stream ended without a stop request => sensor hiccup. Pause, relaunch.
            if not stop_event.is_set():
                time.sleep(1.0)
    finally:
        _release_sensors()


if __name__ == "__main__":
    # Minimal standalone harness: print the reflexes as they fire.
    from core.config import load_config

    stop = threading.Event()
    print("[sensors] test — SHAKE the phone (dizzy), then lay it FACE-DOWN "
          "(sleep). Ctrl-C to quit.")
    try:
        watch(
            load_config(),
            on_dizzy=lambda: print("  >> DIZZY (shake detected)"),
            on_sleep=lambda: print("  >> ASLEEP (face-down)"),
            on_wake=lambda: print("  >> AWAKE (face-up)"),
            stop_event=stop,
        )
    except KeyboardInterrupt:
        stop.set()
        print("\n[sensors] stopped.")
