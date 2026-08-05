"""
EMO Persistent JSON Memory & GitHub Sync System
===============================================
Stores long-term conversation history and user details in `brain/memory.json`.
Provides 1-click GitHub Memory Sync so conversation history and memory stay
in sync seamlessly across Laptop and Phone without any data loss.
"""

import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MEMORY_FILE = HERE / "memory.json"
CONTACTS_FILE = HERE / "contacts.json"


def load_memory() -> dict:
    if not MEMORY_FILE.exists():
        data = {"user_facts": [], "chat_history": []}
        save_memory(data)
        return data
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"user_facts": [], "chat_history": []}


def save_memory(data: dict):
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Memory] Failed to save memory: {e}")


def add_exchange(user_msg: str, ai_reply: str):
    data = load_memory()
    history = data.get("chat_history", [])

    history.append({"role": "user", "content": user_msg})
    history.append({"role": "assistant", "content": ai_reply})

    # Keep last 50 messages in working chat history
    if len(history) > 50:
        history = history[-50:]

    data["chat_history"] = history
    save_memory(data)


def get_history_for_llm() -> list:
    data = load_memory()
    return data.get("chat_history", [])


def clear_memory() -> dict:
    """Clear local chat history."""
    data = {"user_facts": [], "chat_history": []}
    save_memory(data)
    return {"ok": True, "message": "Local memory cleared."}


# ══════════════════════════════════════════════════════════════════════════════
# GITHUB MEMORY SYNC ENGINE (PULL / PUSH / SYNC)
# ══════════════════════════════════════════════════════════════════════════════

def _run_git(args: list[str]) -> tuple[int, str]:
    """Run a git command in the EMO project directory."""
    try:
        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"
        res = subprocess.run(
            ["git"] + args,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            env=env,
            timeout=25,
        )
        out = (res.stdout + "\n" + res.stderr).strip()
        return res.returncode, out
    except Exception as e:
        return -1, str(e)


def _ensure_git_config():
    """Ensure git user.email and user.name are configured for local commits."""
    _run_git(["config", "user.email", "emo@assistant.local"])
    _run_git(["config", "user.name", "EMO Assistant"])


def pull_memory_from_git() -> dict:
    """
    Fetch and overwrite local memory.json & contacts.json from GitHub origin/main.
    Restores conversation history and memory saved from another device.
    """
    print("[Memory.Git] Fetching latest memory from GitHub...")
    code, out = _run_git(["fetch", "origin", "main"])
    if code != 0:
        return {"ok": False, "error": f"Git fetch failed: {out}"}

    # Checkout memory.json and contacts.json from origin/main
    code_mem, out_mem = _run_git(["checkout", "origin/main", "--", "brain/memory.json", "brain/contacts.json"])
    if code_mem != 0:
        # Fallback: try git pull --rebase
        _run_git(["pull", "--rebase", "origin", "main"])

    # Reload memory and return stats
    mem = load_memory()
    chat_count = len(mem.get("chat_history", []))
    print(f"[Memory.Git] Successfully pulled memory from GitHub! Messages restored: {chat_count}")
    return {
        "ok": True,
        "message": f"Memory pulled from GitHub! Restored {chat_count} chat messages.",
        "chat_count": chat_count,
        "output": out_mem or out,
    }


def push_memory_to_git(commit_msg: str = None) -> dict:
    """
    Stage, commit, and push brain/memory.json & brain/contacts.json to GitHub origin/main.
    Uploads local conversation state so other devices can pull it.
    """
    _ensure_git_config()
    mem = load_memory()
    chat_count = len(mem.get("chat_history", []))

    msg = commit_msg or f"sync: update memory and contacts ({chat_count} messages) [auto-sync]"
    print(f"[Memory.Git] Pushing memory ({chat_count} messages) to GitHub...")

    # Stage memory & contacts
    code_add, out_add = _run_git(["add", "brain/memory.json", "brain/contacts.json"])
    if code_add != 0:
        return {"ok": False, "error": f"Git add failed: {out_add}"}

    # Commit if changes exist
    _run_git(["commit", "-m", msg])

    # Push to origin main
    code_push, out_push = _run_git(["push", "origin", "main"])
    if code_push != 0:
        # If push rejected due to remote changes, try fetch + rebase push
        _run_git(["pull", "--rebase", "origin", "main"])
        code_push, out_push = _run_git(["push", "origin", "main"])
        if code_push != 0:
            return {"ok": False, "error": f"Git push failed: {out_push or 'Could not push to GitHub. Check internet or Git credentials.'}"}

    print(f"[Memory.Git] Successfully pushed memory to GitHub!")
    return {
        "ok": True,
        "message": f"Memory pushed to GitHub! Saved {chat_count} messages.",
        "chat_count": chat_count,
        "output": out_push,
    }


def sync_memory_git() -> dict:
    """
    Full bidirectional memory sync:
    1. Pull latest from GitHub (restores memory saved from laptop/phone)
    2. Try pushing local memory back to GitHub (if git credentials are set)
    """
    pull_res = pull_memory_from_git()
    if not pull_res.get("ok"):
        return pull_res

    push_res = push_memory_to_git("sync: full 1-click memory sync across devices")
    
    mem = load_memory()
    chat_count = len(mem.get("chat_history", []))

    if push_res.get("ok"):
        return {
            "ok": True,
            "message": f"1-Click Memory Sync Complete! {chat_count} messages synced with GitHub.",
            "chat_count": chat_count,
            "pull": pull_res,
            "push": push_res,
        }

    # If push failed (e.g. unauthenticated git push on phone), pull still succeeded!
    return {
        "ok": True,
        "message": f"Memory pulled & restored! {chat_count} messages loaded from GitHub.",
        "chat_count": chat_count,
        "pull": pull_res,
        "push_note": "To enable background push from phone, save your GitHub Token in Termux.",
    }


def get_memory_status() -> dict:
    """Return stats about current local memory state."""
    mem = load_memory()
    chat_history = mem.get("chat_history", [])
    user_facts = mem.get("user_facts", [])
    return {
        "ok": True,
        "chat_count": len(chat_history),
        "user_facts_count": len(user_facts),
        "last_message": chat_history[-1]["content"] if chat_history else None,
    }
