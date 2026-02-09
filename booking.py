# booking.py
import os, re, datetime as dt

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def make_ics(invite_dir: str, candidate_name: str, start_dt: dt.datetime,
             duration_min: int = 30,
             meeting_link: str = "",
             title: str = "Interview"):
    """Generate an .ics invite including your meeting link (LOCATION/URL/DESCRIPTION)."""
    ensure_dir(invite_dir)
    end_dt = start_dt + dt.timedelta(minutes=duration_min)

    def fmt(d: dt.datetime) -> str:
        return d.strftime("%Y%m%dT%H%M%S")

    safe_name = re.sub(r'[^a-zA-Z0-9 _.-]+','_', candidate_name) or "candidate"
    uid = f"{re.sub(r'[^a-zA-Z0-9]+','-',candidate_name)}-{fmt(start_dt)}@smart-engine"

    desc = "Interview auto-booked from resume matcher."
    if meeting_link:
        desc += f"\\nJoin: {meeting_link}"

    ics = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Smart-Engine//Interview Scheduler//EN
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{fmt(dt.datetime.now())}
DTSTART:{fmt(start_dt)}
DTEND:{fmt(end_dt)}
SUMMARY:Interview – {title}
LOCATION:{meeting_link}
DESCRIPTION:{desc}
URL:{meeting_link}
END:VEVENT
END:VCALENDAR
"""
    path = os.path.join(invite_dir, f"{safe_name}.ics")
    with open(path, "w", encoding="utf-8") as f:
        f.write(ics)
    return path
