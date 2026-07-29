"""
EMO Persistent Face Lock, Gesture & Environment Vision Engine
============================================================
Recognizes Boss among multiple people, detects hand gestures,
and analyzes surroundings using NVIDIA Multimodal Vision + Local Features.
"""

import os
import json
import base64
import time
from pathlib import Path
from PIL import Image
import io

FACES_DIR = Path(os.path.expanduser("~/.emo_faces"))
FACES_DIR.mkdir(parents=True, exist_ok=True)
MANIFEST_FILE = FACES_DIR / "manifest.json"

def _load_manifest():
    try:
        if MANIFEST_FILE.exists():
            return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []

def _save_manifest(data):
    try:
        MANIFEST_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[FaceLock] Manifest save error: {e}")

def is_enrolled():
    manifest = _load_manifest()
    return len(manifest) > 0

def enroll_image_b64(b64_data, label="Boss"):
    """Saves base64 camera image as enrolled reference."""
    try:
        if "," in b64_data:
            b64_data = b64_data.split(",", 1)[1]
        raw_bytes = base64.b64decode(b64_data)
        
        manifest = _load_manifest()
        idx = len(manifest) + 1
        img_path = FACES_DIR / f"{label.lower()}_{idx}.jpg"
        
        img = Image.open(io.BytesIO(raw_bytes))
        img.convert("RGB").save(img_path, "JPEG")
        
        manifest.append({
            "label": label,
            "path": str(img_path),
            "timestamp": time.time()
        })
        _save_manifest(manifest)
        print(f"[FaceLock] Enrolled {label} at {img_path}")
        return True, f"Face enrolled successfully as {label}!"
    except Exception as e:
        print(f"[FaceLock] Enrollment failed: {e}")
        return False, str(e)

def recognize_image_b64(b64_data):
    """Compares incoming frame with enrolled reference images."""
    if not is_enrolled():
        return {"enrolled": False, "known": False, "person": True, "name": "Unknown"}
        
    try:
        if "," in b64_data:
            b64_data = b64_data.split(",", 1)[1]
        raw_bytes = base64.b64decode(b64_data)
        
        tmp_path = FACES_DIR / "_tmp_query.jpg"
        img = Image.open(io.BytesIO(raw_bytes))
        img.convert("RGB").save(tmp_path, "JPEG")
        
        manifest = _load_manifest()
        ref_paths = [m["path"] for m in manifest if os.path.exists(m.get("path", ""))]
        
        if ref_paths:
            try:
                from eyes import vision
                res = vision.identify(str(tmp_path), ref_paths)
                if res.get("person") is not None:
                    return {
                        "enrolled": True,
                        "person": res.get("person", True),
                        "known": res.get("known", False),
                        "name": "Boss" if res.get("known") else "Guest"
                    }
            except Exception:
                pass
                
        # Fast local PIL perceptual similarity fallback
        query_img = img.convert("L").resize((16, 16))
        query_pixels = list(query_img.getdata())
        
        best_diff = float("inf")
        for ref_p in ref_paths:
            try:
                ref_img = Image.open(ref_p).convert("L").resize((16, 16))
                ref_pixels = list(ref_img.getdata())
                diff = sum(abs(q - r) for q, r in zip(query_pixels, ref_pixels)) / len(query_pixels)
                if diff < best_diff:
                    best_diff = diff
            except Exception:
                continue
                
        is_known = best_diff < 45.0
        return {
            "enrolled": True,
            "person": True,
            "known": is_known,
            "name": "Boss" if is_known else "Guest",
            "diff_score": round(best_diff, 2)
        }
    except Exception as e:
        print(f"[FaceLock] Recognition error: {e}")
        return {"enrolled": is_enrolled(), "known": True, "person": True, "name": "Boss"}

def analyze_frame_b64(b64_data):
    """
    Analyzes frame for:
    1) Multi-person identification (Recognizes Boss among people)
    2) Gesture Detection (Waves, Peace sign, Thumbs up)
    3) Environment observation
    """
    rec_res = recognize_image_b64(b64_data)
    
    # Try VLM for gesture and environment if cloud is connected
    try:
        if "," in b64_data:
            b64_data = b64_data.split(",", 1)[1]
        raw_bytes = base64.b64decode(b64_data)
        tmp_path = FACES_DIR / "_tmp_analyze.jpg"
        img = Image.open(io.BytesIO(raw_bytes))
        img.convert("RGB").save(tmp_path, "JPEG")

        from eyes import vision
        prompt = (
            "Analyze this camera frame in ONE short spoken sentence for an AI companion. "
            "1. State if you see a person, multiple people, or Boss. "
            "2. Note any hand gesture (waving, peace sign, thumbs up) or key object visible."
        )
        scene_desc = vision.describe(str(tmp_path), prompt)
        if scene_desc:
            return {
                "ok": True,
                "known": rec_res.get("known", False),
                "person": rec_res.get("person", True),
                "name": "Boss" if rec_res.get("known") else "Guest",
                "description": scene_desc
            }
    except Exception:
        pass

    # Default structured reply
    if rec_res.get("known"):
        desc = "I see you, Boss! You're looking right at me!"
    elif rec_res.get("person"):
        desc = "I see someone in front of the camera!"
    else:
        desc = "I'm keeping an eye on the room!"

    return {
        "ok": True,
        "known": rec_res.get("known", False),
        "person": rec_res.get("person", True),
        "name": rec_res.get("name", "Boss"),
        "description": desc
    }
