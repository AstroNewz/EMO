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
import re
import json
import urllib.request
import urllib.parse
import base64
from pathlib import Path

CREDS_FILE = Path(os.path.expanduser("~/.emo_google_creds.json"))

_EMBEDDED_B64 = "eyJhY2Nlc3NfdG9rZW4iOiAieWEyOS5hMEFSR251MFpkWEswdDFsWnJlb0FyelYyYXlISDZEVklNSHMydFhybUJSdWdZUXpRMHBfWmpIOU5Ub0ViZUwtQTFsQWdfVGFGX2NBeTZFUjZ3bHJ4ZFRJcTNFWjFoLXhHQjBBMUd1a0VORm1pdmFLd1NCTk8tNVRxdUVrc2xhVllSenQyRWlEemZLdmxsZk53cVV5ay1idUR4bVlrZnFYVVk2c3N4QURZT2lRZmtPYncyRHNsZ0Q3bFQ1S19JeEVIV1lhYUFUandhQ2dZS0FmQVNBUklTRlFIR1gyTWlRNFJRT01FOUZoMUVtSWhPSldodmJRMDIwNiIsICJyZWZyZXNoX3Rva2VuX2V4cGlyZXNfaW4iOiA2MDQ3OTksICJleHBpcmVzX2luIjogMzU5OSwgInRva2VuX3R5cGUiOiAiQmVhcmVyIiwgInNjb3BlIjogImh0dHBzOi8vbWFpbC5nb29nbGUuY29tLyBodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2NhbGVuZGFyIGh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvZHJpdmUiLCAicmVmcmVzaF90b2tlbiI6ICIxLy8wNG5ZT2pWWTZ2aDNqQ2dZSUFSQUFHQVFTTndGLUw5SXJXMTRhUTRLMFdzeldQMmxTY1kxeHY1aXRncVBxaGFaQk4yR0hXdVdWUDRyY1c3LUd4Y0NWLWxIeDQ0YVZiZWJ0T3d3In0="
try:
    EMBEDDED_CREDENTIALS = json.loads(base64.b64decode(_EMBEDDED_B64).decode("utf-8"))
except Exception:
    EMBEDDED_CREDENTIALS = {}

def is_connected():
    """Checks if Google Workspace credentials are connected."""
    token = get_access_token()
    return bool(token)

def save_credentials(token_dict):
    """Saves Google OAuth2 / API credentials."""
    try:
        CREDS_FILE.write_text(json.dumps(token_dict, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        print(f"[GoogleWorkspace] Credential save error: {e}")
        return False

def get_access_token():
    if CREDS_FILE.exists():
        try:
            data = json.loads(CREDS_FILE.read_text(encoding="utf-8"))
            token = data.get("access_token") or data.get("api_key")
            if token:
                return token
        except Exception:
            pass

    # Auto-save embedded fallback credentials to CREDS_FILE if missing
    try:
        save_credentials(EMBEDDED_CREDENTIALS)
    except Exception:
        pass

    return EMBEDDED_CREDENTIALS.get("access_token")

# ---------- GOOGLE CALENDAR ----------
def list_calendar_events(max_results=5):
    """Lists upcoming events from primary Google Calendar."""
    token = get_access_token()
    if not token:
        return "Google Account is not connected yet. Add your Google OAuth token to connect!"
        
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


def create_calendar_event(summary, start_iso, end_iso=None, description="", timezone="Asia/Kolkata"):
    import datetime as _dt, json as _j, urllib.request as _u
    token = get_access_token()
    if not token: return "Google Account not connected."
    try:
        if "T" in start_iso:
            start_dt = _dt.datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        else:
            start_dt = _dt.datetime.fromisoformat(start_iso + "T09:00:00")
        end_dt = start_dt + _dt.timedelta(hours=1)
        if end_iso:
            try: end_dt = _dt.datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
            except: pass
        body = _j.dumps({"summary":summary,"description":description,
            "start":{"dateTime":start_dt.isoformat(),"timeZone":timezone},
            "end":{"dateTime":end_dt.isoformat(),"timeZone":timezone}}).encode("utf-8")
        req = _u.Request("https://www.googleapis.com/calendar/v3/calendars/primary/events",
            data=body, method="POST", headers={
            "Authorization":"Bearer "+token,"Content-Type":"application/json; charset=utf-8"})
        with _u.urlopen(req, timeout=8) as r:
            res = _j.loads(r.read().decode("utf-8"))
            friendly = start_dt.strftime("%A, %d %b %Y at %I:%M %p")
            link = res.get("htmlLink","")
            return "Done. Event on calendar for "+friendly+("." + (" "+link if link else ""))
    except Exception as e: return "Calendar create failed: "+str(e)


def parse_and_create_event(user_text):
    import datetime as _dt, re as _re
    now = _dt.datetime.now(); t = user_text.lower()
    title = _re.sub(r"\b(schedule|add|create|set up|set|book|put|remind me about|remind|new event|event|meeting|appointment|on (my|the) calendar|to (my|the) calendar|on calendar)\b","",user_text,flags=_re.IGNORECASE)
    title = _re.sub(r"\b(tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday|next week|at \d+[:\d]*\s*(am|pm)?|on \w+ \d+|january|february|march|april|may|june|july|august|september|october|november|december|\d{1,2}/\d{1,2})\b","",title,flags=_re.IGNORECASE)
    title = " ".join(title.split()).strip(" ,.-") or "Meeting"
    date = now.date()
    if "tomorrow" in t: date=(now+_dt.timedelta(days=1)).date()
    elif "next week" in t: date=(now+_dt.timedelta(weeks=1)).date()
    else:
        for dn,dv in dict(monday=0,tuesday=1,wednesday=2,thursday=3,friday=4,saturday=5,sunday=6).items():
            if dn in t:
                delta=(dv-now.weekday())%7 or 7; date=(now+_dt.timedelta(days=delta)).date(); break
        else:
            mo_map=dict(january=1,february=2,march=3,april=4,may=5,june=6,july=7,august=8,september=9,october=10,november=11,december=12)
            m=_re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(january|february|march|april|may|june|july|august|september|october|november|december)\b|\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:st|nd|rd|th)?\b",t,_re.IGNORECASE)
            if m:
                if m.group(1): d,mo=int(m.group(1)),mo_map[m.group(2).lower()]
                else: d,mo=int(m.group(4)),mo_map[m.group(3).lower()]
                yr=now.year if mo>=now.month else now.year+1
                try: date=_dt.date(yr,mo,d)
                except: pass
    hour,minute=10,0
    tm=_re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b|\bat\s+(\d{1,2})(?::(\d{2}))?\b",t,_re.IGNORECASE)
    if tm:
        if tm.group(3):
            hour,minute=int(tm.group(1)),int(tm.group(2) or 0)
            if tm.group(3).lower()=="pm" and hour!=12: hour+=12
            elif tm.group(3).lower()=="am" and hour==12: hour=0
        elif tm.group(4): hour,minute=int(tm.group(4)),int(tm.group(5) or 0)
    start_iso=_dt.datetime(date.year,date.month,date.day,hour,minute).isoformat()
    print("[Calendar] Creating: "+title+" at "+start_iso)
    return create_calendar_event(summary=title,start_iso=start_iso)


def is_schedule_request(user_msg):
    low=user_msg.lower()
    return any(x in low for x in ["schedule","add to calendar","add event","create event","set a meeting","book a meeting","set up a meeting","remind me","add a reminder","put on my calendar","add to my calendar","create a reminder","new meeting","set an appointment","book an appointment","create a meeting"])


# ---------- GMAIL ----------
def fetch_emails(query=None, max_results=5):
    """Fetches Gmail messages matching query (or recent inbox messages), including subject and body preview snippet."""
    token = get_access_token()
    if not token:
        return "Google Account is not connected yet. Connect your personal or work Google account to read emails!"
        
    try:
        if query and not query.startswith("q="):
            # Clean up user query for Gmail search
            clean_q = re.sub(r'\b(check|my|emails?|gmail|inbox|search|find|for|about|messages?|any|the|a|an)\b', ' ', query, flags=re.IGNORECASE)
            clean_q = ' '.join(clean_q.split()).strip()
            q_str = f"q={urllib.parse.quote(clean_q)}" if clean_q else "q=is:unread"
        elif query:
            q_str = query
        else:
            q_str = "q=is:unread"

        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages?{q_str}&maxResults={max_results}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            messages = data.get("messages", [])
            if not messages:
                # Fallback to general inbox if specific search returned no results
                if query and "is:unread" not in q_str:
                    return fetch_emails(query="is:unread", max_results=max_results)
                return "You have no relevant unread emails in your Gmail inbox!"
                
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
                    snippet = msg_data.get("snippet", "").strip()
                    email_list.append(f"• From: {sender} | Subject: {subject}\n  Preview: {snippet[:150]}")
            return "\n".join(email_list)
    except Exception as e:
        return f"Gmail query error: {e}"

def list_unread_emails(max_results=5):
    return fetch_emails(query="is:unread", max_results=max_results)

def search_emails(query, max_results=5):
    return fetch_emails(query=query, max_results=max_results)

# ---------- GOOGLE DRIVE & DOCS ----------
def search_drive_docs(query, max_results=4):
    """Searches files and Google Docs in Google Drive."""
    token = get_access_token()
    if not token:
        return "Google Account is not connected yet."
        
    try:
        clean_q = re.sub(r'\b(search|drive|google|doc|docs|files?|find|my|for|about)\b', ' ', query, flags=re.IGNORECASE)
        clean_q = ' '.join(clean_q.split()).strip() or "document"
        q_str = urllib.parse.quote(f"name contains '{clean_q}'")
        url = f"https://www.googleapis.com/drive/v3/files?q={q_str}&pageSize={max_results}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            files = data.get("files", [])
            if not files:
                return f"No Google Drive files matching '{clean_q}' were found."
                
            file_list = [f"• {f.get('name')} ({f.get('mimeType', 'file').split('.')[-1]})" for f in files]
            return "\n".join(file_list)
    except Exception as e:
        return f"Google Drive search error: {e}"

def is_workspace_query(user_msg):
    """Detects if user asks about Google Calendar, Gmail, or Google Docs/Drive."""
    low = user_msg.lower()
    keywords = [
        "google calendar", "schedule", "events", "meetings", "appointment",
        "unread email", "gmail", "inbox", "my emails", "google drive", "google doc", "my files",
        "email", "mail", "messages", "internship", "isro", "stipend", "bank", "received"
    ]
    return any(k in low for k in keywords)


# ---------- GOOGLE DRIVE MEMORY SYNC ----------
_DRIVE_MEMORY_FILENAME = "EMO_memory_sync.json"
_drive_memory_file_id = None   # cached Drive file ID after first upload


def _get_drive_memory_file_id(token):
    """Search Drive for EMO_memory_sync.json and return its file ID, or None."""
    try:
        q = urllib.parse.quote(f"name='{_DRIVE_MEMORY_FILENAME}' and trashed=false")
        url = f"https://www.googleapis.com/drive/v3/files?q={q}&spaces=drive&fields=files(id,modifiedTime)"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            files = data.get("files", [])
            if files:
                return files[0]["id"]
    except Exception:
        pass
    return None


def push_memory_to_drive(memory_list):
    """Push the current memory list to Google Drive as EMO_memory_sync.json.
    Creates the file on first call, patches it on subsequent calls.
    Silently fails if offline or Drive is unavailable."""
    global _drive_memory_file_id
    token = get_access_token()
    if not token:
        return

    try:
        content = json.dumps(memory_list, ensure_ascii=False, indent=2).encode("utf-8")

        # Find existing file if we don't have the ID cached
        if not _drive_memory_file_id:
            _drive_memory_file_id = _get_drive_memory_file_id(token)

        if _drive_memory_file_id:
            # PATCH (update) the existing file's content
            url = (f"https://www.googleapis.com/upload/drive/v3/files/"
                   f"{_drive_memory_file_id}?uploadType=media")
            req = urllib.request.Request(url, data=content, method="PATCH", headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
                "Content-Length": str(len(content)),
            })
        else:
            # POST (create) a new file — multipart: metadata + content
            boundary = "EMO_MEMORY_BOUNDARY_001"
            metadata = json.dumps({"name": _DRIVE_MEMORY_FILENAME,
                                   "mimeType": "application/json"}).encode("utf-8")
            body = (
                f"--{boundary}\r\n".encode() +
                b"Content-Type: application/json; charset=UTF-8\r\n\r\n" +
                metadata + b"\r\n" +
                f"--{boundary}\r\n".encode() +
                b"Content-Type: application/json\r\n\r\n" +
                content + b"\r\n" +
                f"--{boundary}--".encode()
            )
            url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
            req = urllib.request.Request(url, data=body, method="POST", headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/related; boundary={boundary}",
                "Content-Length": str(len(body)),
            })

        with urllib.request.urlopen(req, timeout=8) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if not _drive_memory_file_id:
                _drive_memory_file_id = result.get("id")
            print(f"[DriveSync] Memory pushed to Drive ({len(memory_list)} messages)")
    except Exception as e:
        print(f"[DriveSync] Push failed (offline?): {e}")


def pull_memory_from_drive():
    """Pull EMO_memory_sync.json from Google Drive.
    Returns the parsed memory list, or None if not found / offline."""
    global _drive_memory_file_id
    token = get_access_token()
    if not token:
        return None

    try:
        if not _drive_memory_file_id:
            _drive_memory_file_id = _get_drive_memory_file_id(token)
        if not _drive_memory_file_id:
            print("[DriveSync] No memory file on Drive yet — starting fresh")
            return None

        url = f"https://www.googleapis.com/drive/v3/files/{_drive_memory_file_id}?alt=media"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list):
                print(f"[DriveSync] Memory pulled from Drive ({len(data)} messages)")
                return data
    except Exception as e:
        print(f"[DriveSync] Pull failed (offline?): {e}")
    return None

