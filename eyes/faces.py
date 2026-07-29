"""
EMO — Eyes / Faces (enrollment + persistence)
=============================================
Remembers what "Boss" looks like. Enrollment is a VOICE command ("EMO, remember
my face"): we snap a photo and stash it, plus a small JSON manifest. Recognition
itself is done later by `vision.identify()` comparing a live frame against these
reference shots.

Everything lives in `~/.emo_faces/` — OUTSIDE the synced EMO folder — so the
delete-and-paste code sync never wipes your enrolled identity. Pure stdlib.

Public API:
    enroll(cfg=None, label="Boss") -> bool     # capture + save one reference
    ref_paths()                    -> list[str]# saved reference image paths
    is_enrolled()                  -> bool
    forget()                       -> None      # wipe all enrolled faces
"""

import os
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import section   # noqa: E402
from eyes import camera           # noqa: E402

_DEFAULT_DIR = "~/.emo_faces"


def _dir(cfg):
    fc = (cfg or section("eyes", {})).get("faces", {}) if isinstance(cfg, dict) else {}
    d = fc.get("dir", _DEFAULT_DIR)
    path = Path(os.path.expanduser(d))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _manifest_path(cfg=None):
    return _dir(cfg or section("eyes", {})) / "manifest.json"


def _load_manifest(cfg=None):
    try:
        data = json.loads(_manifest_path(cfg).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_manifest(entries, cfg=None):
    try:
        _manifest_path(cfg).write_text(
            json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[faces] manifest save failed: {e}")


def ref_paths():
    """Enrolled reference image paths that still exist on disk."""
    return [e["path"] for e in _load_manifest() if os.path.exists(e.get("path", ""))]


def is_enrolled():
    return bool(ref_paths())


def enroll(cfg=None, label="Boss", camera_id=None):
    """Capture one photo NOW and save it as a reference. Returns True on success.

    Defaults to the FRONT (selfie) camera — you face the phone when enrolling.
    Call it a few times (different angles) for more robust matching — each shot
    is appended, never overwritten.
    """
    cfg = cfg if isinstance(cfg, dict) else section("eyes", {})
    if camera_id is None:                 # prefer the selfie cam (same one presence uses)
        camera_id = cfg.get("presence", {}).get("camera_id", cfg.get("camera_id", 1))
    entries = _load_manifest(cfg)
    n = len(entries) + 1
    # Snapshot straight into the faces dir under a stable name (camera writes
    # <name>.jpg into eyes.snapshot_dir, so capture then move into place).
    shot = camera.snapshot(cfg, camera_id=camera_id, name="_enroll_tmp")
    if not shot:
        return False
    dest = _dir(cfg) / f"{label.lower()}_{n}.jpg"
    try:
        os.replace(shot, dest)          # move the temp capture into the faces store
    except Exception as e:
        print(f"[faces] could not store reference: {e}")
        return False
    entries.append({"label": label, "path": str(dest)})
    _save_manifest(entries, cfg)
    print(f"[faces] enrolled {label} -> {dest}")
    return True


def forget():
    """Delete all enrolled references and the manifest."""
    for p in ref_paths():
        try:
            os.remove(p)
        except OSError:
            pass
    try:
        _manifest_path().unlink()
    except OSError:
        pass


if __name__ == "__main__":
    print("[faces] enrolling current view as Boss (look at the camera)...")
    ok = enroll()
    print("[faces] enrolled." if ok else "[faces] enrollment failed (see above).")
    print("[faces] references:", ref_paths())
