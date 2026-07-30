"""
brain/whatsapp.py — EMO WhatsApp Messaging Module

Handles intent detection, NLU parsing, and contacts management
so EMO can send WhatsApp messages on Boss's behalf.
"""

import re
import json
from pathlib import Path

# ── Contacts store ──────────────────────────────────────────────────────────
_CONTACTS_PATH = Path(__file__).parent / "contacts.json"

def _load_contacts() -> dict:
    """Load contacts.json, return {} on any error."""
    try:
        if _CONTACTS_PATH.exists():
            data = json.loads(_CONTACTS_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}

def _save_contacts(contacts: dict) -> bool:
    """Persist contacts dict to disk."""
    try:
        _CONTACTS_PATH.write_text(
            json.dumps(contacts, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        return True
    except Exception:
        return False

def get_contacts() -> dict:
    """Return the full contacts map {name: phone}."""
    return _load_contacts()

def upsert_contact(name: str, phone: str) -> bool:
    """Add or update a contact. Returns True on success."""
    if not name or not phone:
        return False
    c = _load_contacts()
    c[name.strip().title()] = phone.strip()
    return _save_contacts(c)

def delete_contact(name: str) -> bool:
    """Remove a contact by name. Returns True if it existed."""
    c = _load_contacts()
    key = name.strip().title()
    if key not in c:
        for k in list(c.keys()):
            if k.lower() == name.strip().lower():
                key = k
                break
        else:
            return False
    del c[key]
    return _save_contacts(c)

def lookup_phone(name: str):
    """
    Look up a phone number by contact name.
    Returns E.164 phone string or None.
    """
    contacts = _load_contacts()
    if name in contacts:
        return contacts[name]
    titled = name.strip().title()
    if titled in contacts:
        return contacts[titled]
    low = name.strip().lower()
    for k, v in contacts.items():
        if k.lower() == low:
            return v
    return None

# ── Intent Detection ────────────────────────────────────────────────────────
_WA_PATTERNS = [
    # "send maa a whatsapp: ..."  /  "send whatsapp to maa saying ..."
    re.compile(
        r"(?:send|shoot|fire|drop)\s+(?:a\s+)?(?:whatsapp|wp|wapp|wa|message|msg|text)\s+"
        r"(?:to\s+)?(?P<contact>[A-Za-z][A-Za-z\s]{0,28}?)"
        r"\s*(?:saying|that|please|:|,|-|—)\s*(?P<message>.+)",
        re.IGNORECASE | re.DOTALL,
    ),
    # "whatsapp maa: ..."
    re.compile(
        r"(?:whatsapp|wp|wapp)\s+(?P<contact>[A-Za-z][A-Za-z\s]{0,28}?)"
        r"\s*(?:saying|that|please|:|,|-|—)\s*(?P<message>.+)",
        re.IGNORECASE | re.DOTALL,
    ),
    # "send/message/text maa on whatsapp: ..."
    re.compile(
        r"(?:send|message|text|msg)\s+(?P<contact>[A-Za-z][A-Za-z\s]{0,28}?)"
        r"\s+(?:on\s+)?(?:whatsapp|wp)"
        r"\s*(?:saying|that|please|:|,|-|—)?\s*(?P<message>.+)",
        re.IGNORECASE | re.DOTALL,
    ),
    # fallback: "whatsapp maa I'll be home" (no separator)
    re.compile(
        r"(?:whatsapp|wp|wapp)\s+(?P<contact>[A-Za-z]+(?:\s+[A-Za-z]+)?)"
        r"\s+(?P<message>[A-Za-z].+)",
        re.IGNORECASE | re.DOTALL,
    ),
]

_STOP_WORDS = {"a", "an", "the", "please", "emo", "boss", "and", "that", "to"}

def is_whatsapp_command(text: str) -> bool:
    """Return True if text looks like a WhatsApp send command."""
    low = text.lower()
    has_wa = any(kw in low for kw in ["whatsapp", " wp ", "wapp"])
    has_verb = any(kw in low for kw in ["send", "message", "msg", "text", "shoot", "drop"])
    return has_wa or (has_verb and "whatsapp" in low)

def _clean_contact(raw: str) -> str:
    """Strip filler words from a parsed contact name."""
    parts = raw.strip().split()
    parts = [p for p in parts if p.lower() not in _STOP_WORDS]
    return " ".join(parts).strip().title()

def parse_command(text: str) -> dict:
    """
    Parse a WhatsApp send command.

    Returns:
        {"contact": "Maa", "phone": "+91...", "message": "..."}  -- ready to send
        {"contact": "Maa", "phone": None, "message": "..."}      -- contact not found
        {"error": "parse_failed"}                                  -- could not parse
    """
    for pat in _WA_PATTERNS:
        m = pat.search(text)
        if m:
            raw_contact = m.group("contact").strip()
            raw_message = m.group("message").strip()
            contact_name = _clean_contact(raw_contact)
            if not contact_name or not raw_message:
                continue
            phone = lookup_phone(contact_name)
            return {
                "contact": contact_name,
                "phone": phone,
                "message": raw_message,
            }
    return {"error": "parse_failed"}

def build_whatsapp_url(phone: str, message: str) -> str:
    """Build a WhatsApp deep-link URL. phone should be digits only."""
    from urllib.parse import quote
    clean_phone = re.sub(r"[^\d]", "", phone)
    encoded_msg = quote(message, safe="")
    return f"https://api.whatsapp.com/send?phone={clean_phone}&text={encoded_msg}"
