import os, uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from caldav import DAVClient
from icalendar import Calendar, Event, vText

CALDAV_URL = "https://caldav.icloud.com/"
ICLOUD_USERNAME = os.environ["ICLOUD_USERNAME"]
ICLOUD_APP_PW   = os.environ["ICLOUD_APP_PW"]
LOCAL_TZ        = os.environ.get("TIMEZONE", "America/Chicago")

app = FastAPI(title="Calendar Bridge")

def get_calendar():
    client = DAVClient(url=CALDAV_URL, username=ICLOUD_USERNAME, password=ICLOUD_APP_PW)
    principal = client.principal()
    cals = principal.calendars()
    if not cals:
        raise HTTPException(500, "No calendars found.")
    return cals[0]  # use the first calendar by default

class RangeQuery(BaseModel):
    start_iso: str  # e.g., "2025-08-10T00:00:00Z"
    end_iso: str    # e.g., "2025-08-17T00:00:00Z"

class CreateEvent(BaseModel):
    title: str
    start_local: str   # "YYYY-MM-DDTHH:MM" in your local time
    end_local: str     # "YYYY-MM-DDTHH:MM" in your local time
    location: str | None = None
    description: str | None = None

class DeleteEvent(BaseModel):
    uid: str

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/get_events")
def get_events(q: RangeQuery):
    cal = get_calendar()
    start = datetime.fromisoformat(q.start_iso.replace("Z","+00:00"))
    end   = datetime.fromisoformat(q.end_iso.replace("Z","+00:00"))
    events = cal.date_search(start=start, end=end, expand=True)
    output = []
    for e in events:
        ve = e.vobject_instance.vevent
        output.append({
            "uid": str(ve.uid.value) if hasattr(ve, "uid") else None,
            "summary": ve.summary.value if hasattr(ve, "summary") else None,
            "start": str(ve.dtstart.value) if hasattr(ve, "dtstart") else None,
            "end":   str(ve.dtend.value) if hasattr(ve, "dtend") else None,
        })
    return {"events": output}

@app.post("/create_event")
def create_event(data: CreateEvent):
    cal = get_calendar()
    tz = ZoneInfo(LOCAL_TZ)
    start = datetime.fromisoformat(data.start_local).replace(tzinfo=tz)
    end   = datetime.fromisoformat(data.end_local).replace(tzinfo=tz)

    c = Calendar()
    c.add("prodid", "-//CalendarBridge//EN")
    c.add("version", "2.0")

    ev = Event()
    ev.add("uid", f"{uuid.uuid4()}@calendar-bridge")
    ev.add("summary", data.title)
    ev.add("dtstart", start)
    ev.add("dtend", end)
    if data.location:
        ev.add("location", vText(data.location))
    if data.description:
        ev.add("description", vText(data.description))
    c.add_component(ev)

    ics_bytes = c.to_ical()
    cal.add_event(ics_bytes.decode("utf-8"))
    return {"ok": True, "uid": str(ev.get("uid"))}

@app.post("/delete_event")
def delete_event(d: DeleteEvent):
    cal = get_calendar()
    # search +/- 6 months and match by UID
    start = datetime.now(timezone.utc) - timedelta(days=180)
    end = datetime.now(timezone.utc) + timedelta(days=180)
    events = cal.date_search(start=start, end=end, expand=False)
    for e in events:
        ve = e.vobject_instance.vevent
        if hasattr(ve, "uid") and str(ve.uid.value) == d.uid:
            e.delete()
            return {"ok": True}
    raise HTTPException(404, "Event not found")
