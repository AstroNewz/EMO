"""
EMO — face demo driver
Cycles the face through every expression so you can watch transitions without
the wake-word / STT / brain pipeline existing yet.

Run the face server first (python face/server.py), then in a SECOND Termux
session run this:  python face/demo_states.py
"""
import time
import urllib.request
import json

URL = "http://127.0.0.1:8008/state"
STATES = ["idle", "listening", "thinking", "speaking", "happy", "confused", "error", "idle"]


def set_state(state):
    data = json.dumps({"state": state}).encode()
    req = urllib.request.Request(URL, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3) as r:
        print(f"-> {state}: {r.read().decode()}")


if __name__ == "__main__":
    print("Cycling EMO through all expressions (Ctrl-C to stop)...")
    try:
        while True:
            for s in STATES:
                set_state(s)
                time.sleep(2.5)
    except KeyboardInterrupt:
        set_state("idle")
        print("\nDone.")
