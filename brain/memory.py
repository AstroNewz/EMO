"""
EMO Persistent JSON Memory System
================================
Stores long-term conversation history and user details in `brain/memory.json`
so EMO remembers every single detail shared by the user across turns and sessions.
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
MEMORY_FILE = HERE / "memory.json"

def load_memory():
    if not MEMORY_FILE.exists():
        data = {"user_facts": [], "chat_history": []}
        save_memory(data)
        return data
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"user_facts": [], "chat_history": []}

def save_memory(data):
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Memory] Failed to save memory: {e}")

def add_exchange(user_msg, ai_reply):
    data = load_memory()
    history = data.get("chat_history", [])
    
    history.append({"role": "user", "content": user_msg})
    history.append({"role": "assistant", "content": ai_reply})
    
    # Keep last 30 messages in working chat history
    if len(history) > 30:
        history = history[-30:]
        
    data["chat_history"] = history
    save_memory(data)

def get_history_for_llm():
    data = load_memory()
    return data.get("chat_history", [])
