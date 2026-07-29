"""
EMO Google Workspace Integration
=================================
Connects EMO to your Google Workspace:
- Google Calendar (View schedule, add meetings)
- Gmail (Read unread emails, send emails)
- Google Drive & Docs (Search documents)

Supports OAuth2 credentials, Service Account JSON, or API Key.
Configured via `~/.emo_google_creds.json` or `config.yaml` (google_workspace block).
"""

import os
import json
import urllib.request
import urllib.parse
from pathlib import Path

CREDS_FILE = Path(os.path.expanduser("~/.emo_google_creds.json"))

def is_connected():
    """Checks if Google Workspace credentials are connected."""
    if CREDS_FILE.exists():
        try:
            data = json.loads(CREDS_FILE.read_text(encoding="utf-8"))
            return "access_token" in data or "api_key" in data or "client_id" in data
        except Exception:
            pass
    return False

def save_credentials(token_dict):
    """Saves Google OAuth2 / API credentials."""
    try:
        CREDS_FILE.write_text(json.dumps(token_dict, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        print(f"[GoogleWorkspace] Credential save error: {e}")
        return False

def get_access_token():
    if not CREDS_FILE.exists():
        return None
    try:
        data = json.loads(CREDS_FILE.read_text(encoding="utf-8"))
        return data.get("access_token") or data.get("api_key")
    except Exception:
        return None

# ---------- GOOGLE CALENDAR ----------
def list_calendar_events(max_results=5):
    """Lists upcoming events from primary Google Calendar."""
    token = get_access_token()
    if not token:
        return "Google Workspace is not connected yet. Add your Google OAuth token to connect!"
        
    try:
        url = f"https://www.googleapis.com/calendar/v3/calendars/primary/events?maxResults={max_results}&orderBy=startTime&singleEvents=true"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            items = data.get("items", [])
            if not items:
                return "No upcoming events found on your Google Calendar."
            
            events = []
            for item in items:
                summary = item.get("summary", "No Title")
                start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
                events.append(f"• {summary} at {start}")
            return "\n".join(events)
    except Exception as e:
        return f"Google Calendar query error: {e}"

# ---------- GMAIL ----------
def list_unread_emails(max_results=5):
    """Lists recent unread emails from Gmail inbox."""
    token = get_access_token()
    if not token:
        return "Google Workspace is not connected yet. Connect your Google account to read emails!"
        
    try:
        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages?q=is:unread&maxResults={max_results}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            messages = data.get("messages", [])
            if not messages:
                return "You have no unread emails in your Gmail inbox!"
                
            email_list = []
            for m in messages[:max_results]:
                m_id = m.get("id")
                msg_url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{m_id}?format=full"
                msg_req = urllib.request.Request(msg_url, headers={"Authorization": f"Bearer {token}"})
                with urllib.request.urlopen(msg_req, timeout=4) as m_resp:
                    msg_data = json.loads(m_resp.read().decode("utf-8"))
                    headers = msg_data.get("payload", {}).get("headers", [])
                    subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "No Subject")
                    sender = next((h["value"] for h in headers if h["name"].lower() == "from"), "Unknown Sender")
                    email_list.append(f"• From: {sender} | Subject: {subject}")
            return "\n".join(email_list)
    except Exception as e:
        return f"Gmail query error: {e}"

# ---------- GOOGLE DRIVE & DOCS ----------
def search_drive_docs(query, max_results=4):
    """Searches files and Google Docs in Google Drive."""
    token = get_access_token()
    if not token:
        return "Google Workspace is not connected yet."
        
    try:
        q_str = urllib.parse.quote(f"name contains '{query}'")
        url = f"https://www.googleapis.com/drive/v3/files?q={q_str}&pageSize={max_results}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            files = data.get("files", [])
            if not files:
                return f"No Google Drive files matching '{query}' were found."
                
            file_list = [f"• {f.get('name')} ({f.get('mimeType', 'file').split('.')[-1]})" for f in files]
            return "\n".join(file_list)
    except Exception as e:
        return f"Google Drive search error: {e}"

def is_workspace_query(user_msg):
    """Detects if user asks about Google Calendar, Gmail, or Google Docs/Drive."""
    low = user_msg.lower()
    keywords = [
        "google calendar", "schedule", "events", "meetings", "appointment",
        "unread email", "gmail", "inbox", "my emails", "google drive", "google doc", "my files"
    ]
    return any(k in low for k in keywords)
