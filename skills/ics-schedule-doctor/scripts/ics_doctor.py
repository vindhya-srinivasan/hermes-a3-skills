#!/usr/bin/env python3
"""ics_doctor.py — find conflicts, free slots and best slots in an iCalendar (.ics) file.

Standard library only. Reads a local .ics path or an http(s) URL (e.g. a calendar's
secret iCal address). Handles DTSTART/DTEND with TZID, UTC 'Z' times, all-day events
and DURATION. Recurring events (RRULE) are expanded for DAILY/WEEKLY rules.

Usage:
  ics_doctor.py --ics FILE_OR_URL [--date YYYY-MM-DD] [--days N] [--tz America/Los_Angeles]
                [--duration MIN] [--work 09:00-18:00] [--json]
"""
import argparse
import json
import re
import sys
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def unfold(text: str) -> list[str]:
    out = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.startswith((" ", "\t")) and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def parse_dt(prop: str, value: str, default_tz) -> tuple[datetime, bool]:
    params = dict(p.split("=", 1) for p in prop.split(";")[1:] if "=" in p)
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        d = datetime.strptime(value, "%Y%m%d").replace(tzinfo=default_tz)
        return d, True
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc), False
    tz = ZoneInfo(params["TZID"]) if "TZID" in params else default_tz
    return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=tz), False


def parse_duration(v: str) -> timedelta:
    m = re.fullmatch(r"P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", v)
    if not m:
        return timedelta(0)
    w, d, h, mi, s = (int(x or 0) for x in m.groups())
    return timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


def load_events(src: str, tz) -> list[dict]:
    if re.match(r"https?://", src):
        with urllib.request.urlopen(src, timeout=20) as r:
            text = r.read().decode("utf-8", "replace")
    else:
        text = open(src, encoding="utf-8").read()
    events, cur = [], None
    for line in unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT" and cur is not None:
            if "start" in cur:
                if "end" not in cur:
                    cur["end"] = cur["start"] + (cur.pop("dur", None) or
                                                 (timedelta(days=1) if cur["all_day"] else timedelta(0)))
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            prop, value = line.split(":", 1)
            name = prop.split(";")[0].upper()
            if name == "SUMMARY":
                cur["title"] = value.replace("\\,", ",").replace("\\n", " ")
            elif name == "DTSTART":
                cur["start"], cur["all_day"] = parse_dt(prop, value, tz)
            elif name == "DTEND":
                cur["end"], _ = parse_dt(prop, value, tz)
            elif name == "DURATION":
                cur["dur"] = parse_duration(value)
            elif name == "RRULE":
                cur["rrule"] = dict(p.split("=", 1) for p in value.split(";") if "=" in p)
            elif name == "STATUS":
                cur["status"] = value
    return [e for e in events if e.get("status") != "CANCELLED"]


def expand(events: list[dict], start: datetime, end: datetime) -> list[dict]:
    out = []
    for e in events:
        rr = e.get("rrule")
        if not rr or rr.get("FREQ") not in ("DAILY", "WEEKLY"):
            if e["start"] < end and e["end"] > start:
                out.append(e)
            continue
        step = timedelta(days=1 if rr["FREQ"] == "DAILY" else 7) * int(rr.get("INTERVAL", "1"))
        until = None
        if "UNTIL" in rr:
            until, _ = parse_dt("UNTIL", rr["UNTIL"], e["start"].tzinfo)
        count = int(rr.get("COUNT", "100000"))
        s, n = e["start"], 0
        while s < end and n < count and (until is None or s <= until):
            if s + (e["end"] - e["start"]) > start:
                out.append({**e, "start": s, "end": s + (e["end"] - e["start"])})
            s += step
            n += 1
    return sorted(out, key=lambda x: x["start"])


def analyse(events, day: date, days: int, tz, work: tuple[time, time], duration: int) -> dict:
    report = []
    for i in range(days):
        d = day + timedelta(days=i)
        d0 = datetime.combine(d, time(0), tz)
        evs = [e for e in expand(events, d0, d0 + timedelta(days=1))]
        timed = [e for e in evs if not e.get("all_day")]
        conflicts = []
        for a in range(len(timed)):
            for b in range(a + 1, len(timed)):
                x, y = timed[a], timed[b]
                if x["start"] < y["end"] and y["start"] < x["end"]:
                    ov = int((min(x["end"], y["end"]) - max(x["start"], y["start"])).total_seconds() // 60)
                    conflicts.append({"a": x.get("title", "?"), "b": y.get("title", "?"), "overlap_min": ov})
        ws, we = datetime.combine(d, work[0], tz), datetime.combine(d, work[1], tz)
        cur, free = ws, []
        for e in sorted(timed, key=lambda e: e["start"]):
            s, en = e["start"].astimezone(tz), e["end"].astimezone(tz)
            if s > cur:
                free.append((cur, min(s, we)))
            cur = max(cur, en)
        if we > cur:
            free.append((cur, we))
        free = [(a, b) for a, b in free if b > a]
        fits = [(a, b) for a, b in free if (b - a) >= timedelta(minutes=duration)]
        # best slot: earliest slot that fits with a 15-min buffer after the previous event
        best = None
        for a, b in fits:
            start = a + timedelta(minutes=15) if a > ws else a
            if b - start >= timedelta(minutes=duration):
                best = (start, start + timedelta(minutes=duration))
                break
        fmt = lambda t: t.astimezone(tz).strftime("%H:%M")
        report.append({
            "date": d.isoformat(),
            "events": [{"title": e.get("title", "?"),
                        "start": "all-day" if e.get("all_day") else fmt(e["start"]),
                        "end": "" if e.get("all_day") else fmt(e["end"])} for e in evs],
            "conflicts": conflicts,
            "free_slots": [f"{fmt(a)}-{fmt(b)}" for a, b in free],
            "suggested_slot": f"{fmt(best[0])}-{fmt(best[1])}" if best else None,
        })
    return {"timezone": str(tz), "duration_min": duration, "days": report}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ics", required=True)
    ap.add_argument("--date", default=None)
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--tz", default="America/Los_Angeles")
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--work", default="09:00-18:00")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    tz = ZoneInfo(a.tz)
    day = date.fromisoformat(a.date) if a.date else datetime.now(tz).date()
    w0, w1 = (time.fromisoformat(x) for x in a.work.split("-"))
    rep = analyse(load_events(a.ics, tz), day, max(1, min(a.days, 31)), tz, (w0, w1), a.duration)
    if a.json:
        print(json.dumps(rep, indent=2))
        return
    for d in rep["days"]:
        print(f"== {d['date']} ({rep['timezone']})")
        for e in d["events"]:
            print(f"  - {e['start']}{'-' + e['end'] if e['end'] else ''}  {e['title']}")
        for c in d["conflicts"]:
            print(f"  ! CONFLICT: '{c['a']}' overlaps '{c['b']}' by {c['overlap_min']} min")
        print(f"  free: {', '.join(d['free_slots']) or 'none'}")
        print(f"  suggested {rep['duration_min']}-min slot: {d['suggested_slot'] or 'none fits'}")


if __name__ == "__main__":
    main()
