"""Loading, saving and exporting the app's data (a single JSON document)."""

from __future__ import annotations

import copy
import io
import json
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "db.json"

DEFAULT_SETTINGS = {
    "institution": "Manipal University Jaipur",
    "department": "Department of Computer Science & Engineering",
    "academic_term": "Odd Semester 2026-27",
    "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
    "slots": [
        {"start": "09:00", "end": "10:00", "is_break": False},
        {"start": "10:00", "end": "11:00", "is_break": False},
        {"start": "11:00", "end": "12:00", "is_break": False},
        {"start": "12:00", "end": "13:00", "is_break": False},
        {"start": "13:00", "end": "14:00", "is_break": True},
        {"start": "14:00", "end": "15:00", "is_break": False},
        {"start": "15:00", "end": "16:00", "is_break": False},
        {"start": "16:00", "end": "17:00", "is_break": False},
    ],
    "allow_same_subject_twice_a_day": False,
}


def empty_db() -> dict:
    return {
        "settings": copy.deepcopy(DEFAULT_SETTINGS),
        "subjects": [],
        "teachers": [],
        "sections": [],
        "rooms": [],
        "assignments": [],
        "unavailability": {},
        "timetable": [],
        "reschedules": [],
    }


def sample_db() -> dict:
    """Fictional demo data so the app is usable on first launch."""
    db = empty_db()
    db["subjects"] = [
        {"code": "CS2101", "name": "Data Structures", "type": "Theory"},
        {"code": "CS2102", "name": "Computer Organization & Architecture", "type": "Theory"},
        {"code": "CS2103", "name": "Object Oriented Programming", "type": "Theory"},
        {"code": "MA2101", "name": "Discrete Mathematics", "type": "Theory"},
        {"code": "CS2130", "name": "Data Structures Lab", "type": "Lab"},
        {"code": "CS2131", "name": "OOP Lab", "type": "Lab"},
        {"code": "CS3101", "name": "Operating Systems", "type": "Theory"},
        {"code": "CS3102", "name": "Database Management Systems", "type": "Theory"},
        {"code": "CS3103", "name": "Computer Networks", "type": "Theory"},
        {"code": "CS3104", "name": "Design & Analysis of Algorithms", "type": "Theory"},
        {"code": "CS3130", "name": "DBMS Lab", "type": "Lab"},
        {"code": "CS3131", "name": "Operating Systems Lab", "type": "Lab"},
    ]
    db["teachers"] = [
        {"code": "T01", "name": "Dr. Anjali Mehta", "department": "CSE", "email": "", "max_per_day": 4},
        {"code": "T02", "name": "Dr. Rohit Verma", "department": "CSE", "email": "", "max_per_day": 4},
        {"code": "T03", "name": "Dr. Neha Gupta", "department": "CSE", "email": "", "max_per_day": 4},
        {"code": "T04", "name": "Dr. Sandeep Rathore", "department": "Mathematics", "email": "", "max_per_day": 4},
        {"code": "T05", "name": "Dr. Kavita Joshi", "department": "CSE", "email": "", "max_per_day": 5},
        {"code": "T06", "name": "Mr. Arjun Singh", "department": "CSE", "email": "", "max_per_day": 5},
        {"code": "T07", "name": "Dr. Priya Saxena", "department": "CSE", "email": "", "max_per_day": 4},
        {"code": "T08", "name": "Dr. Vikas Sharma", "department": "CSE", "email": "", "max_per_day": 4},
    ]
    db["sections"] = [
        {"name": "CSE 3A", "program": "B.Tech CSE", "semester": 3, "strength": 60, "home_room": "AB1-201"},
        {"name": "CSE 3B", "program": "B.Tech CSE", "semester": 3, "strength": 60, "home_room": "AB1-202"},
        {"name": "CSE 5A", "program": "B.Tech CSE", "semester": 5, "strength": 60, "home_room": "AB1-301"},
        {"name": "CSE 5B", "program": "B.Tech CSE", "semester": 5, "strength": 60, "home_room": "AB1-302"},
    ]
    db["rooms"] = [
        {"name": "AB1-201", "type": "Classroom", "capacity": 70},
        {"name": "AB1-202", "type": "Classroom", "capacity": 70},
        {"name": "AB1-301", "type": "Classroom", "capacity": 70},
        {"name": "AB1-302", "type": "Classroom", "capacity": 70},
        {"name": "AB1-305", "type": "Classroom", "capacity": 70},
        {"name": "Lab-1", "type": "Lab", "capacity": 35},
        {"name": "Lab-2", "type": "Lab", "capacity": 35},
    ]

    def alloc(section, subject, teacher, n, dur=1):
        return {"section": section, "subject": subject, "teacher": teacher,
                "sessions_per_week": n, "duration": dur}

    db["assignments"] = [
        alloc("CSE 3A", "CS2101", "T01", 3), alloc("CSE 3A", "CS2102", "T02", 3),
        alloc("CSE 3A", "CS2103", "T03", 3), alloc("CSE 3A", "MA2101", "T04", 3),
        alloc("CSE 3A", "CS2130", "T01", 1, 2), alloc("CSE 3A", "CS2131", "T06", 1, 2),
        alloc("CSE 3B", "CS2101", "T05", 3), alloc("CSE 3B", "CS2102", "T02", 3),
        alloc("CSE 3B", "CS2103", "T03", 3), alloc("CSE 3B", "MA2101", "T04", 3),
        alloc("CSE 3B", "CS2130", "T05", 1, 2), alloc("CSE 3B", "CS2131", "T06", 1, 2),
        alloc("CSE 5A", "CS3101", "T07", 3), alloc("CSE 5A", "CS3102", "T08", 3),
        alloc("CSE 5A", "CS3103", "T05", 3), alloc("CSE 5A", "CS3104", "T01", 3),
        alloc("CSE 5A", "CS3130", "T08", 1, 2), alloc("CSE 5A", "CS3131", "T07", 1, 2),
        alloc("CSE 5B", "CS3101", "T07", 3), alloc("CSE 5B", "CS3102", "T08", 3),
        alloc("CSE 5B", "CS3103", "T06", 3), alloc("CSE 5B", "CS3104", "T03", 3),
        alloc("CSE 5B", "CS3130", "T06", 1, 2), alloc("CSE 5B", "CS3131", "T02", 1, 2),
    ]
    # Example: Dr. Sandeep Rathore is not available on Friday afternoons.
    db["unavailability"] = {"T04": ["Friday|5", "Friday|6", "Friday|7"]}
    return db


def _normalise(db: dict) -> dict:
    """Fill in keys missing from older / hand-edited files."""
    base = empty_db()
    for k, v in base.items():
        db.setdefault(k, v)
    for k, v in DEFAULT_SETTINGS.items():
        db["settings"].setdefault(k, copy.deepcopy(v))
    return db


def load() -> dict:
    if DB_PATH.exists():
        try:
            return _normalise(json.loads(DB_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    # First launch: start with the demo data and a ready-made timetable.
    from scheduler import generate

    db = sample_db()
    db["timetable"] = generate(db, time_limit=2, seed=7)["entries"]
    save(db)
    return db


def save(db: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    tmp = DB_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, indent=2, default=str), encoding="utf-8")
    tmp.replace(DB_PATH)


def from_json_bytes(raw: bytes) -> dict:
    db = json.loads(raw.decode("utf-8"))
    if not isinstance(db, dict) or "settings" not in db:
        raise ValueError("This does not look like a timetable backup file.")
    return _normalise(db)


def to_json_bytes(db: dict) -> bytes:
    return json.dumps(db, indent=2, default=str).encode("utf-8")


def grid_frame(db: dict, entries: list[dict], label_fn) -> pd.DataFrame:
    """Day × period table used for Excel/CSV export."""
    slots = db["settings"]["slots"]
    cols = [f"{s['start']}-{s['end']}" for s in slots]
    df = pd.DataFrame("", index=db["settings"]["days"], columns=cols)
    for i, s in enumerate(slots):
        if s.get("is_break"):
            df[cols[i]] = "BREAK"
    for e in entries:
        if e["day"] not in df.index:
            continue
        for k in range(int(e.get("duration", 1))):
            if e["slot"] + k < len(cols):
                df.loc[e["day"], cols[e["slot"] + k]] = label_fn(e)
    return df


def excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in sheets.items():
            safe = "".join(c for c in name if c not in r"[]:*?/\\")[:31] or "Sheet"
            df.to_excel(xw, sheet_name=safe)
            ws = xw.sheets[safe]
            ws.column_dimensions["A"].width = 14
            for col in ws.iter_cols(min_col=2, max_col=ws.max_column):
                ws.column_dimensions[col[0].column_letter].width = 26
    return buf.getvalue()
