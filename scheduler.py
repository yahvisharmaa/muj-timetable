"""Timetable generation and rescheduling engine.

Pure Python, no Streamlit imports, so it can be tested on its own.

Terminology
-----------
- slot:    one period of the day (index into settings["slots"])
- session: one class meeting; a lab session usually spans 2 consecutive slots
- entry:   a placed session in the timetable
"""

from __future__ import annotations

import random
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

# India has no DST, so a fixed offset is exact and needs no tz database (Streamlit Cloud runs in UTC).
IST = timezone(timedelta(hours=5, minutes=30))

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def now_ist() -> datetime:
    return datetime.now(IST).replace(tzinfo=None)


def today_ist() -> date:
    return now_ist().date()


def slot_label(slot: dict) -> str:
    return f"{slot['start']}–{slot['end']}"


def valid_starts(slots: list[dict], duration: int) -> list[int]:
    """Start indices where `duration` consecutive teaching slots fit without crossing a break."""
    starts = []
    for s in range(len(slots) - duration + 1):
        if all(not slots[s + k].get("is_break") for k in range(duration)):
            starts.append(s)
    return starts


def teaching_slot_count(settings: dict) -> int:
    return sum(1 for s in settings["slots"] if not s.get("is_break")) * len(settings["days"])


def new_id() -> str:
    return uuid.uuid4().hex[:10]


@dataclass
class Unit:
    """One session that needs to be placed."""

    uid: int
    assignment_idx: int
    section: str
    subject: str
    teacher: str
    duration: int
    room_type: str


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def validate(db: dict) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) that should be shown before generating."""
    errors, warnings = [], []
    settings = db["settings"]
    subjects = {s["code"]: s for s in db["subjects"]}
    teachers = {t["code"]: t for t in db["teachers"]}
    sections = {s["name"] for s in db["sections"]}
    room_types = defaultdict(int)
    for r in db["rooms"]:
        room_types[r["type"]] += 1

    if not settings["days"]:
        errors.append("No working days selected.")
    if not any(not s.get("is_break") for s in settings["slots"]):
        errors.append("No teaching slots defined.")

    capacity = teaching_slot_count(settings)
    teacher_load = defaultdict(int)
    section_load = defaultdict(int)

    for i, a in enumerate(db["assignments"], start=1):
        tag = f"Allocation row {i}"
        if a["section"] not in sections:
            errors.append(f"{tag}: section '{a['section']}' does not exist.")
        if a["subject"] not in subjects:
            errors.append(f"{tag}: subject '{a['subject']}' does not exist.")
            continue
        if a["teacher"] not in teachers:
            errors.append(f"{tag}: teacher '{a['teacher']}' does not exist.")
        dur = int(a.get("duration") or 1)
        n = int(a.get("sessions_per_week") or 0)
        if n <= 0:
            warnings.append(f"{tag}: 0 sessions per week, it will be skipped.")
        if not valid_starts(settings["slots"], dur):
            errors.append(f"{tag}: no {dur} consecutive teaching slots exist in a day.")
        rtype = "Lab" if subjects[a["subject"]].get("type") == "Lab" else "Classroom"
        if room_types and room_types[rtype] == 0:
            warnings.append(f"{tag}: no rooms of type '{rtype}' defined, room will be left blank.")
        teacher_load[a["teacher"]] += n * dur
        section_load[a["section"]] += n * dur

    unavail = db.get("unavailability", {})
    for code, load in teacher_load.items():
        if code not in teachers:
            continue
        free = capacity - len(unavail.get(code, []))
        name = teachers[code]["name"]
        if load > free:
            errors.append(f"{name} needs {load} periods/week but has only {free} available slots.")
        max_day = int(teachers[code].get("max_per_day") or 0)
        if max_day and load > max_day * len(settings["days"]):
            errors.append(
                f"{name} needs {load} periods/week but max-per-day {max_day} × "
                f"{len(settings['days'])} days allows only {max_day * len(settings['days'])}."
            )
    for sec, load in section_load.items():
        if load > capacity:
            errors.append(f"Section {sec} needs {load} periods/week but the week has only {capacity}.")
    return errors, warnings


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
class _Board:
    """Occupancy tracking for one generation attempt."""

    def __init__(self, db: dict):
        self.settings = db["settings"]
        self.days = self.settings["days"]
        self.slots = self.settings["slots"]
        self.teachers = {t["code"]: t for t in db["teachers"]}
        self.sections = {s["name"]: s for s in db["sections"]}
        self.rooms_by_type = defaultdict(list)
        for r in db["rooms"]:
            self.rooms_by_type[r["type"]].append(r["name"])
        self.unavail = {k: set(v) for k, v in db.get("unavailability", {}).items()}
        self.allow_repeat = bool(self.settings.get("allow_same_subject_twice_a_day", False))

        self.teacher_busy: dict[tuple, int] = {}  # (teacher, day, slot) -> uid
        self.section_busy: dict[tuple, int] = {}
        self.room_busy: dict[tuple, int] = {}
        self.teacher_day = defaultdict(int)  # (teacher, day) -> periods
        self.section_day = defaultdict(int)
        self.subject_day = defaultdict(int)  # (section, subject, day) -> sessions
        self.placed: dict[int, tuple] = {}  # uid -> (day, start, room)

    # ----- feasibility ---------------------------------------------------- #
    def _room_for(self, u: Unit, day: str, start: int) -> str | None:
        """Return a free room ('' when no rooms of that type exist) or None when all are taken."""
        candidates = list(self.rooms_by_type.get(u.room_type, []))
        if not candidates:
            return ""
        home = self.sections.get(u.section, {}).get("home_room")
        if home in candidates:
            candidates.remove(home)
            candidates.insert(0, home)
        for room in candidates:
            if all((room, day, start + k) not in self.room_busy for k in range(u.duration)):
                return room
        return None

    def feasible(self, u: Unit, day: str, start: int, strict: bool = True) -> str | None:
        for k in range(u.duration):
            s = start + k
            if (u.teacher, day, s) in self.teacher_busy:
                return None
            if (u.section, day, s) in self.section_busy:
                return None
            if f"{day}|{s}" in self.unavail.get(u.teacher, ()):
                return None
        max_day = int(self.teachers.get(u.teacher, {}).get("max_per_day") or 0)
        if max_day and self.teacher_day[(u.teacher, day)] + u.duration > max_day:
            return None
        if strict and not self.allow_repeat and self.subject_day[(u.section, u.subject, day)] > 0:
            return None
        return self._room_for(u, day, start)

    def score(self, u: Unit, day: str, start: int, rng: random.Random) -> float:
        """Lower is better: spread sessions across the week and keep daily loads even."""
        return (
            self.subject_day[(u.section, u.subject, day)] * 20
            + self.section_day[(u.section, day)] * 1.5
            + self.teacher_day[(u.teacher, day)] * 1.5
            + rng.random() * 2
        )

    def candidates(self, u: Unit, starts: list[int], rng: random.Random):
        for strict in (True, False):
            opts = []
            for day in self.days:
                for st in starts:
                    room = self.feasible(u, day, st, strict)
                    if room is not None:
                        opts.append((self.score(u, day, st, rng), day, st, room))
            if opts:
                opts.sort(key=lambda o: o[0])
                return opts
        return []

    # ----- mutation ------------------------------------------------------- #
    def place(self, u: Unit, day: str, start: int, room: str):
        for k in range(u.duration):
            s = start + k
            self.teacher_busy[(u.teacher, day, s)] = u.uid
            self.section_busy[(u.section, day, s)] = u.uid
            if room:
                self.room_busy[(room, day, s)] = u.uid
        self.teacher_day[(u.teacher, day)] += u.duration
        self.section_day[(u.section, day)] += u.duration
        self.subject_day[(u.section, u.subject, day)] += 1
        self.placed[u.uid] = (day, start, room)

    def remove(self, u: Unit):
        day, start, room = self.placed.pop(u.uid)
        for k in range(u.duration):
            s = start + k
            self.teacher_busy.pop((u.teacher, day, s), None)
            self.section_busy.pop((u.section, day, s), None)
            if room:
                self.room_busy.pop((room, day, s), None)
        self.teacher_day[(u.teacher, day)] -= u.duration
        self.section_day[(u.section, day)] -= u.duration
        self.subject_day[(u.section, u.subject, day)] -= 1


def _build_units(db: dict) -> list[Unit]:
    subjects = {s["code"]: s for s in db["subjects"]}
    units, uid = [], 0
    for idx, a in enumerate(db["assignments"]):
        subj = subjects.get(a["subject"])
        if not subj:
            continue
        room_type = "Lab" if subj.get("type") == "Lab" else "Classroom"
        for _ in range(int(a.get("sessions_per_week") or 0)):
            units.append(
                Unit(uid, idx, a["section"], a["subject"], a["teacher"], int(a.get("duration") or 1), room_type)
            )
            uid += 1
    return units


def _try_repair(board: _Board, u: Unit, units_by_id: dict, starts_by_dur: dict, rng: random.Random) -> bool:
    """Place `u` by moving one blocking session somewhere else."""
    for day in board.days:
        for st in starts_by_dur[u.duration]:
            if any(f"{day}|{st + k}" in board.unavail.get(u.teacher, ()) for k in range(u.duration)):
                continue
            blockers = set()
            for k in range(u.duration):
                for key, table in (((u.teacher, day, st + k), board.teacher_busy), ((u.section, day, st + k), board.section_busy)):
                    if key in table:
                        blockers.add(table[key])
            if len(blockers) != 1:
                continue
            b = units_by_id[blockers.pop()]
            old = board.placed[b.uid]
            board.remove(b)
            room = board.feasible(u, day, st, strict=False)
            if room is not None:
                board.place(u, day, st, room)
                opts = board.candidates(b, starts_by_dur[b.duration], rng)
                if opts:
                    _, d2, s2, r2 = opts[0]
                    board.place(b, d2, s2, r2)
                    return True
                board.remove(u)
            board.place(b, *old)
    return False


def generate(db: dict, time_limit: float = 6.0, seed: int | None = None) -> dict:
    """Generate a timetable. Returns {"entries": [...], "unplaced": [...], "attempts": n}."""
    rng = random.Random(seed)
    units = _build_units(db)
    units_by_id = {u.uid: u for u in units}
    slots = db["settings"]["slots"]
    starts_by_dur = {d: valid_starts(slots, d) for d in {u.duration for u in units}}

    teacher_load = defaultdict(int)
    for u in units:
        teacher_load[u.teacher] += u.duration
    unavail_count = {k: len(v) for k, v in db.get("unavailability", {}).items()}

    best_board, best_unplaced, attempts = None, None, 0
    deadline = time.time() + time_limit
    while True:
        attempts += 1
        board = _Board(db)
        # Hardest sessions first: long labs, busy teachers, teachers with many blocked slots.
        order = sorted(
            units,
            key=lambda u: (
                -u.duration,
                -(teacher_load[u.teacher] + unavail_count.get(u.teacher, 0)),
                rng.random(),
            ),
        )
        unplaced = []
        for u in order:
            opts = board.candidates(u, starts_by_dur[u.duration], rng)
            if opts:
                # Pick among the top few options to diversify attempts.
                _, day, st, room = opts[rng.randrange(min(2, len(opts)))] if attempts > 1 else opts[0]
                board.place(u, day, st, room)
            elif not _try_repair(board, u, units_by_id, starts_by_dur, rng):
                unplaced.append(u)

        if best_unplaced is None or len(unplaced) < len(best_unplaced):
            best_board, best_unplaced = board, unplaced
        if not best_unplaced or time.time() > deadline:
            break

    entries = []
    for uid, (day, start, room) in best_board.placed.items():
        u = units_by_id[uid]
        entries.append(
            {
                "id": new_id(),
                "section": u.section,
                "subject": u.subject,
                "teacher": u.teacher,
                "room": room,
                "day": day,
                "slot": start,
                "duration": u.duration,
            }
        )
    day_order = {d: i for i, d in enumerate(db["settings"]["days"])}
    entries.sort(key=lambda e: (e["section"], day_order[e["day"]], e["slot"]))
    unplaced = [
        {"section": u.section, "subject": u.subject, "teacher": u.teacher, "duration": u.duration}
        for u in best_unplaced
    ]
    return {"entries": entries, "unplaced": unplaced, "attempts": attempts}


# --------------------------------------------------------------------------- #
# Rescheduling
# --------------------------------------------------------------------------- #
def week_dates(any_day: date, days: list[str]) -> dict[str, date]:
    """Map each working day name to its date in the week containing `any_day`."""
    monday = any_day - timedelta(days=any_day.weekday())
    return {d: monday + timedelta(days=WEEKDAY_NAMES.index(d)) for d in days}


def effective_entries_on(db: dict, on: date) -> list[dict]:
    """Classes actually happening on a date: weekly timetable + one-time reschedules."""
    day = WEEKDAY_NAMES[on.weekday()]
    iso = on.isoformat()
    by_id = {e["id"]: e for e in db["timetable"]}
    moved_out = {r["entry_id"] for r in db.get("reschedules", []) if r["from_date"] == iso}
    out = [dict(e, moved_in=False) for e in db["timetable"] if e["day"] == day and e["id"] not in moved_out]
    for r in db.get("reschedules", []):
        if r["to_date"] == iso and r["entry_id"] in by_id:
            e = dict(by_id[r["entry_id"]])
            e.update(day=day, slot=r["to_slot"], room=r.get("to_room", e["room"]), moved_in=True,
                     from_date=r["from_date"], from_slot=r["from_slot"])
            out.append(e)
    return out


def _occupancy(entries: list[dict]):
    teacher, section, room = set(), set(), set()
    for e in entries:
        for k in range(int(e.get("duration", 1))):
            s = e["slot"] + k
            teacher.add((e["teacher"], e["day"], s))
            section.add((e["section"], e["day"], s))
            if e.get("room"):
                room.add((e["room"], e["day"], s))
    return teacher, section, room


def _subject_room_type(db: dict, subject_code: str) -> str:
    for s in db["subjects"]:
        if s["code"] == subject_code:
            return "Lab" if s.get("type") == "Lab" else "Classroom"
    return "Classroom"


def _options_for(db: dict, entry: dict, day_entries: dict[str, list[dict]], dates: dict[str, date | None],
                 exclude: tuple | None) -> list[dict]:
    """Shared search used by both permanent and one-time rescheduling.

    day_entries: day name -> entries occupying that day
    dates:       day name -> concrete date (None for permanent / weekly mode)
    exclude:     (day, slot) of the original class: it is not offered back, and on that
                 day the class itself does not count as occupying its slot
    """
    settings = db["settings"]
    slots = settings["slots"]
    dur = int(entry.get("duration", 1))
    unavail = set(db.get("unavailability", {}).get(entry["teacher"], []))
    teacher_obj = next((t for t in db["teachers"] if t["code"] == entry["teacher"]), {})
    max_day = int(teacher_obj.get("max_per_day") or 0)
    rtype = _subject_room_type(db, entry["subject"])
    rooms = [r["name"] for r in db["rooms"] if r["type"] == rtype]

    options = []
    for day in settings["days"]:
        skip_id = entry["id"] if exclude and day == exclude[0] else None
        todays = [e for e in day_entries.get(day, []) if not (e["id"] == skip_id and not e.get("moved_in"))]
        t_busy, s_busy, r_busy = _occupancy(todays)
        load = sum(int(e.get("duration", 1)) for e in todays if e["teacher"] == entry["teacher"])
        sec_load = sum(int(e.get("duration", 1)) for e in todays if e["section"] == entry["section"])
        for st in valid_starts(slots, dur):
            if exclude and (day, st) == exclude:
                continue
            span = range(st, st + dur)
            if any((entry["teacher"], day, s) in t_busy for s in span):
                continue
            if any((entry["section"], day, s) in s_busy for s in span):
                continue
            if any(f"{day}|{s}" in unavail for s in span):
                continue
            room = None
            if entry.get("room") and all((entry["room"], day, s) not in r_busy for s in span):
                room = entry["room"]
            else:
                room = next((r for r in rooms if all((r, day, s) not in r_busy for s in span)), None)
            if room is None and not rooms:
                room = ""
            notes = []
            if room is None:
                notes.append("no free room")
            elif room != entry.get("room"):
                notes.append(f"room changes to {room}" if room else "")
            if max_day and load + dur > max_day:
                notes.append(f"exceeds your {max_day}/day limit")
            if exclude and day == exclude[0]:
                notes.append("same day")
            # Rank: room available, within daily limit, same day, lighter days first.
            rank = (
                (room is None) * 100
                + (max_day and load + dur > max_day) * 50
                - (exclude is not None and day == exclude[0]) * 5
                + load * 2 + sec_load
            )
            options.append(
                {
                    "day": day,
                    "date": dates.get(day),
                    "slot": st,
                    "time": f"{slots[st]['start']}–{slots[st + dur - 1]['end']}",
                    "room": room,
                    "your_classes_that_day": load,
                    "section_classes_that_day": sec_load,
                    "notes": ", ".join(n for n in notes if n),
                    "rank": rank,
                    "recommended": False,
                }
            )
    options.sort(key=lambda o: (o["rank"], settings["days"].index(o["day"]), o["slot"]))
    for o in options[:3]:
        if o["rank"] < 50:
            o["recommended"] = True
    return options


def permanent_options(db: dict, entry: dict) -> list[dict]:
    """Free slots in the weekly timetable where teacher, section and a room are all free."""
    day_entries = defaultdict(list)
    for e in db["timetable"]:
        day_entries[e["day"]].append(e)
    return _options_for(db, entry, day_entries, {d: None for d in db["settings"]["days"]},
                        exclude=(entry["day"], entry["slot"]))


def one_time_options(db: dict, entry: dict, missed_date: date, weeks: int = 1,
                     now: datetime | None = None) -> list[dict]:
    """Free slots on concrete dates, starting from the week of the missed class. Past slots are skipped."""
    now = now or now_ist()
    slots = db["settings"]["slots"]
    results = []
    for w in range(weeks):
        dates = week_dates(missed_date + timedelta(weeks=w), db["settings"]["days"])
        day_entries = {d: effective_entries_on(db, dt) for d, dt in dates.items()}
        exclude = (entry["day"], entry["slot"]) if w == 0 else None
        opts = _options_for(db, entry, day_entries, dates, exclude)
        results.extend(
            o for o in opts
            if o["date"] > now.date() or (o["date"] == now.date() and slots[o["slot"]]["start"].zfill(5) > now.strftime("%H:%M"))
        )
    results.sort(key=lambda o: (o["rank"], o["date"], o["slot"]))
    for o in results:
        o["recommended"] = False
    for o in results[:3]:
        if o["rank"] < 50:
            o["recommended"] = True
    return results


def conflicts(db: dict) -> list[str]:
    """Clashes in the current weekly timetable (useful after manual edits / imports)."""
    seen = {}
    problems = []
    for e in db["timetable"]:
        for k in range(int(e.get("duration", 1))):
            s = e["slot"] + k
            for kind, who in (("Teacher", e["teacher"]), ("Section", e["section"]), ("Room", e.get("room"))):
                if not who:
                    continue
                key = (kind, who, e["day"], s)
                if key in seen and seen[key] != e["id"]:
                    problems.append(f"{kind} {who} double-booked on {e['day']} period {s + 1}")
                seen[key] = e["id"]
    return sorted(set(problems))
