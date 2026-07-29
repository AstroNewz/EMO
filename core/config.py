"""
EMO — shared config loader
Loads config.yaml once and hands modules their section. Tolerant of a missing
PyYAML (falls back to {} so callers use their own defaults) so early slices
run before we've installed anything.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # .../EMO
CONFIG_PATH = ROOT / "config.yaml"

_cache = None
_warned = False


def load_config():
    """Return the parsed config dict, or {} if it can't be read/parsed."""
    global _cache, _warned
    if _cache is not None:
        return _cache

    try:
        text = CONFIG_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        _cache = {}
        return _cache

    try:
        import yaml
        _cache = yaml.safe_load(text) or {}
    except ImportError:
        if not _warned:
            print("[config] PyYAML not installed; using built-in defaults. "
                  "Install later with: pip install pyyaml")
            _warned = True
        _cache = {}
    except Exception as e:
        print(f"[config] failed to parse config.yaml ({e}); using defaults.")
        _cache = {}

    return _cache


def section(name, default=None):
    """Convenience: return a top-level section dict (e.g. 'mouth')."""
    return load_config().get(name, default if default is not None else {})
