import sys, re
SRC = "brain/google_workspace.py"
content = open(SRC, encoding="utf-8").read()
if "create_calendar_event" in content:
    print("Already patched"); sys.exit(0)
MARKER = '        return f"Google Calendar query error: {e}"\n'
if MARKER not in content:
    print("ERROR: marker not found"); sys.exit(1)
NEW = """

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
    title = _re.sub(r"\\b(schedule|add|create|set up|set|book|put|remind me about|remind|new event|event|meeting|appointment|on (my|the) calendar|to (my|the) calendar|on calendar)\\b","",user_text,flags=_re.IGNORECASE)
    title = _re.sub(r"\\b(tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday|next week|at \\d+[:\\d]*\\s*(am|pm)?|on \\w+ \\d+|january|february|march|april|may|june|july|august|september|october|november|december|\\d{1,2}/\\d{1,2})\\b","",title,flags=_re.IGNORECASE)
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
            m=_re.search(r"\\b(\\d{1,2})(?:st|nd|rd|th)?\\s+(january|february|march|april|may|june|july|august|september|october|november|december)\\b|\\b(january|february|march|april|may|june|july|august|september|october|november|december)\\s+(\\d{1,2})(?:st|nd|rd|th)?\\b",t,_re.IGNORECASE)
            if m:
                if m.group(1): d,mo=int(m.group(1)),mo_map[m.group(2).lower()]
                else: d,mo=int(m.group(4)),mo_map[m.group(3).lower()]
                yr=now.year if mo>=now.month else now.year+1
                try: date=_dt.date(yr,mo,d)
                except: pass
    hour,minute=10,0
    tm=_re.search(r"\\b(\\d{1,2})(?::(\\d{2}))?\\s*(am|pm)\\b|\\bat\\s+(\\d{1,2})(?::(\\d{2}))?\\b",t,_re.IGNORECASE)
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

"""
new_content = content.replace(MARKER, MARKER + NEW, 1)
open(SRC,"w",encoding="utf-8").write(new_content)
print("Patched!")
