"""MUJ Faculty Timetable Planner — Streamlit app.

Run locally:   streamlit run app.py
"""

from __future__ import annotations

import hmac
import html
import zlib
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

import data_store as ds
import scheduler as sc

st.set_page_config(page_title="MUJ Timetable Planner", page_icon="🗓️", layout="wide")

ACCENT = "#E8590C"
PALETTE = [
    "#FFE3D3", "#D9ECFF", "#DFF5E1", "#F3E1FF", "#FFF4C2", "#D6F5F2",
    "#FFDDE6", "#E4E7FF", "#EAF7CF", "#FBE3C8", "#D9F0FF", "#F0E6DA",
]

CSS = f"""
<style>
.block-container {{ padding-top: 2rem; }}
.hero {{
  background: linear-gradient(120deg, {ACCENT} 0%, #F59F00 100%);
  color: #fff; border-radius: 16px; padding: 22px 26px; margin-bottom: 18px;
}}
.hero h1 {{ color: #fff; font-size: 1.9rem; margin: 0 0 4px 0; padding: 0; }}
.hero p {{ margin: 0; opacity: .95; }}
.step {{ border: 1px solid rgba(128,128,128,.25); border-radius: 12px; padding: 14px 16px; height: 100%; }}
.step b {{ color: {ACCENT}; }}
.tt-wrap {{ overflow-x: auto; border: 1px solid rgba(128,128,128,.25); border-radius: 12px; padding: 6px; }}
table.tt {{ border-collapse: separate; border-spacing: 4px; width: 100%; min-width: 980px; font-size: 13px;
  table-layout: fixed; }}
table.tt th {{ background: rgba(232,89,12,.12); color: inherit; font-weight: 600; padding: 6px; border-radius: 8px;
  text-align: center; white-space: nowrap; }}
table.tt td {{ vertical-align: top; }}
table.tt td.tt-day {{ font-weight: 600; white-space: nowrap; padding: 6px 8px; background: rgba(128,128,128,.10);
  border-radius: 8px; vertical-align: middle; }}
.tt-cell {{ color: #1f2937; border-radius: 8px; padding: 6px 8px; min-height: 58px; line-height: 1.3;
  overflow-wrap: break-word; }}
.tt-cell .t {{ font-weight: 700; font-size: 12.5px; }}
.tt-cell .l {{ font-size: 12px; opacity: .85; }}
.tt-empty {{ background: rgba(128,128,128,.07); border-radius: 8px; min-height: 58px; }}
.tt-break {{ background: repeating-linear-gradient(45deg, rgba(232,89,12,.10), rgba(232,89,12,.10) 6px,
  transparent 6px, transparent 12px); border-radius: 8px; text-align: center; vertical-align: middle !important;
  font-weight: 600; color: {ACCENT}; letter-spacing: 2px; writing-mode: vertical-rl; transform: rotate(180deg);
  width: 34px; }}
.tt-sel {{ outline: 3px solid {ACCENT}; outline-offset: -3px; }}
.tt-moved {{ outline: 2px dashed #1f2937; outline-offset: -2px; }}
.tt-cancel {{ background: rgba(128,128,128,.12) !important; color: inherit; opacity: .7; text-decoration: line-through; }}
.tt-option {{ background: #D3F9D8; border: 2px dashed #2B8A3E; color: #1f2937; }}
.tt-badge {{ display: inline-block; font-size: 10px; background: #1f2937; color: #fff; border-radius: 6px;
  padding: 1px 6px; margin-top: 3px; text-decoration: none; }}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def get_db() -> dict:
    # Read from disk on every run so all users see the latest saved data.
    return ds.load()


def save_db(db: dict) -> None:
    ds.save(db)


def flash(msg: str, kind: str = "success") -> None:
    st.session_state["_flash"] = (kind, msg)


def show_flash() -> None:
    if "_flash" in st.session_state:
        kind, msg = st.session_state.pop("_flash")
        getattr(st, kind)(msg)


def admin_password() -> str | None:
    try:
        return st.secrets.get("ADMIN_PASSWORD")
    except Exception:
        return None


def require_admin(reason: str = "This section is for the timetable coordinator.") -> bool:
    pw = admin_password()
    if not pw or st.session_state.get("is_admin"):
        return True
    st.info(f"🔒 {reason} Enter the admin password to continue.")
    with st.form("admin_login"):
        entered = st.text_input("Admin password", type="password")
        if st.form_submit_button("Unlock"):
            if hmac.compare_digest(entered, pw):
                st.session_state["is_admin"] = True
                st.rerun()
            st.error("Incorrect password.")
    return False


def page_header(title: str, subtitle: str = "") -> None:
    db = get_db()
    st.title(title)
    s = db["settings"]
    st.caption(f"{s['institution']} · {s.get('department', '')} · {s.get('academic_term', '')}")
    if subtitle:
        st.write(subtitle)


def subj_map(db):
    return {s["code"]: s for s in db["subjects"]}


def teacher_map(db):
    return {t["code"]: t for t in db["teachers"]}


def subject_name(db, code):
    return subj_map(db).get(code, {}).get("name", code)


def teacher_name(db, code):
    return teacher_map(db).get(code, {}).get("name", code)


def subject_color(db, code):
    codes = [s["code"] for s in db["subjects"]]
    idx = codes.index(code) if code in codes else zlib.crc32(code.encode())
    return PALETTE[idx % len(PALETTE)]


def time_range(db, slot, duration=1):
    slots = db["settings"]["slots"]
    end = min(slot + int(duration) - 1, len(slots) - 1)
    return f"{slots[slot]['start']}–{slots[end]['end']}"


def entry_label(db, e):
    return f"{e['day']} · {time_range(db, e['slot'], e['duration'])} · {subject_name(db, e['subject'])} · {e['section']}"


def fmt_date(d) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return d.strftime("%a %d %b")


def no_timetable_notice():
    st.info("No timetable has been generated yet. The coordinator can create one from **Generate timetable**.")
    if st.button("Go to Generate timetable"):
        st.switch_page(PAGES["generate"])


def teacher_picker(db, key: str) -> str | None:
    teachers = db["teachers"]
    if not teachers:
        st.warning("No teachers added yet. Add them under **Setup data → Teachers**.")
        return None
    codes = [t["code"] for t in teachers]
    preferred = st.session_state.get("selected_teacher") or st.query_params.get("teacher")
    idx = codes.index(preferred) if preferred in codes else 0
    code = st.selectbox(
        "Teacher",
        codes,
        index=idx,
        key=key,
        format_func=lambda c: f"{teacher_map(db)[c]['name']}  ({c})",
    )
    st.session_state["selected_teacher"] = code
    st.query_params["teacher"] = code
    return code


# --------------------------------------------------------------------------- #
# Timetable grid rendering
# --------------------------------------------------------------------------- #
def grid_html(db: dict, cells: list[dict], days: list[str] | None = None, day_labels: dict | None = None) -> str:
    """cells: {day, slot, duration, title, lines, color, cls, badge}. First cell at a position wins."""
    settings = db["settings"]
    slots = settings["slots"]
    days = days or settings["days"]
    day_labels = day_labels or {}
    at, covered = {}, set()
    for c in cells:
        key = (c["day"], c["slot"])
        if key in at or key in covered:
            continue
        dur = 1
        while dur < int(c.get("duration", 1)) and (c["day"], c["slot"] + dur) not in at                 and (c["day"], c["slot"] + dur) not in covered:
            dur += 1
        at[key] = dict(c, duration=dur)
        for k in range(1, dur):
            covered.add((c["day"], c["slot"] + k))

    head, period = "<th style='width:96px'>Day</th>", 0
    for s in slots:
        if s.get("is_break"):
            name, width = "Break", "width:48px;white-space:normal;font-size:11px"
        else:
            period += 1
            name, width = f"P{period}", ""
        head += f"<th style='{width}'>{name}<br><span style='font-weight:400;font-size:11px'>{s['start']}–{s['end']}</span></th>"
    rows = []
    for r, day in enumerate(days):
        tds = [f"<td class='tt-day'>{html.escape(day_labels.get(day, day))}</td>"]
        i = 0
        while i < len(slots):
            if slots[i].get("is_break"):
                if r == 0:
                    tds.append(f"<td class='tt-break' rowspan='{len(days)}'>LUNCH BREAK</td>")
                i += 1
                continue
            c = at.get((day, i))
            if c:
                dur = 1
                while dur < int(c.get("duration", 1)) and i + dur < len(slots) and not slots[i + dur].get("is_break"):
                    dur += 1
                lines = "".join(f"<div class='l'>{html.escape(str(x))}</div>" for x in c.get("lines", []) if x)
                badge = f"<span class='tt-badge'>{html.escape(c['badge'])}</span>" if c.get("badge") else ""
                style = f"background:{c['color']}" if c.get("color") else ""
                tds.append(
                    f"<td colspan='{dur}'><div class='tt-cell {c.get('cls', '')}' style='{style}'>"
                    f"<div class='t'>{html.escape(c.get('title', ''))}</div>{lines}{badge}</div></td>"
                )
                i += dur
            elif (day, i) in covered:
                i += 1
            else:
                tds.append("<td><div class='tt-empty'></div></td>")
                i += 1
        rows.append("<tr>" + "".join(tds) + "</tr>")
    return f"<div class='tt-wrap'><table class='tt'><tr>{head}</tr>{''.join(rows)}</table></div>"


def teacher_cell(db, e, **extra):
    return {
        "day": e["day"], "slot": e["slot"], "duration": e["duration"],
        "title": subject_name(db, e["subject"]),
        "lines": [f"{e['subject']} · {e['section']}", f"Room {e['room']}" if e.get("room") else ""],
        "color": subject_color(db, e["subject"]), **extra,
    }


def section_cell(db, e, **extra):
    return {
        "day": e["day"], "slot": e["slot"], "duration": e["duration"],
        "title": subject_name(db, e["subject"]),
        "lines": [teacher_name(db, e["teacher"]), f"Room {e['room']}" if e.get("room") else ""],
        "color": subject_color(db, e["subject"]), **extra,
    }


def week_cells(db, week_of: date, match, cell_fn):
    """Cells for a concrete week, with one-time reschedules applied."""
    dates = sc.week_dates(week_of, db["settings"]["days"])
    by_id = {e["id"]: e for e in db["timetable"]}
    cells = []
    for day, d in dates.items():
        for e in sc.effective_entries_on(db, d):
            if not match(e):
                continue
            if e.get("moved_in"):
                cells.append(cell_fn(db, e, cls="tt-moved",
                                     badge=f"Moved from {fmt_date(e['from_date'])} {time_range(db, e['from_slot'], e['duration'])}"))
            else:
                cells.append(cell_fn(db, e))
    for r in db.get("reschedules", []):
        e = by_id.get(r["entry_id"])
        if e and match(e) and r["from_date"] in {d.isoformat() for d in dates.values()}:
            cells.append(cell_fn(db, e, cls="tt-cancel", color="",
                                 badge=f"Moved to {fmt_date(r['to_date'])} {time_range(db, r['to_slot'], e['duration'])}"))
    labels = {day: f"{day[:3]} {d.strftime('%d %b')}" for day, d in dates.items()}
    return cells, labels


def printable_html(db, title, subtitle, grid) -> bytes:
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
{CSS}<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#1f2937;background:#fff}}
h1{{margin:0;font-size:22px}} p{{margin:4px 0 14px;color:#555}}
@page{{size:A4 landscape;margin:10mm}} @media print{{.tt-wrap{{border:none}}}}</style></head>
<body><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p>{grid}
<p style="font-size:11px;margin-top:12px">Generated {sc.now_ist():%d %b %Y %H:%M} · {html.escape(db['settings']['institution'])}</p>
</body></html>"""
    return page.encode("utf-8")


def downloads(db, name: str, entries: list[dict], label_fn, grid: str, file_stub: str):
    s = db["settings"]
    df = ds.grid_frame(db, entries, label_fn)
    c1, c2, c3 = st.columns(3)
    c1.download_button("⬇️ Excel", ds.excel_bytes({name: df}), f"{file_stub}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
    c2.download_button("⬇️ CSV", df.to_csv().encode("utf-8"), f"{file_stub}.csv", "text/csv", width="stretch")
    c3.download_button("🖨️ Printable page (save as PDF)",
                       printable_html(db, f"Timetable — {name}", f"{s['institution']} · {s.get('academic_term', '')}", grid),
                       f"{file_stub}.html", "text/html", width="stretch")


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
def page_home():
    db = get_db()
    s = db["settings"]
    st.markdown(
        f"""<div class="hero"><h1>🗓️ Faculty Timetable Planner</h1>
        <p>{html.escape(s['institution'])} · {html.escape(s.get('department', ''))} · {html.escape(s.get('academic_term', ''))}</p>
        <p style="margin-top:8px">Personal timetables for every teacher, clash-free — and instant options when you need to reschedule a class.</p>
        </div>""",
        unsafe_allow_html=True,
    )
    show_flash()
    c = st.columns(4)
    c[0].metric("Teachers", len(db["teachers"]))
    c[1].metric("Sections", len(db["sections"]))
    c[2].metric("Subjects", len(db["subjects"]))
    c[3].metric("Classes / week", len(db["timetable"]))

    st.subheader("Find your timetable")
    if db["teachers"] and db["timetable"]:
        col1, col2 = st.columns([3, 1], vertical_alignment="bottom")
        with col1:
            code = st.selectbox("Your name", [t["code"] for t in db["teachers"]],
                                format_func=lambda c: f"{teacher_name(db, c)}  ({c})", key="home_teacher")
        if col2.button("Open my timetable", type="primary", width="stretch"):
            st.session_state["selected_teacher"] = code
            st.switch_page(PAGES["my"])
    else:
        no_timetable_notice()

    st.subheader("How it works")
    steps = [
        ("1. Set up", "The coordinator enters subjects, teachers, sections, rooms and which teacher takes which class."),
        ("2. Generate", "One click builds a clash-free timetable for every section, teacher and room."),
        ("3. View", "Each teacher opens their personal timetable and downloads it as Excel or a printable page."),
        ("4. Reschedule", "Busy in a slot? See every period where you, your students and a room are all free."),
    ]
    cols = st.columns(4)
    for col, (h, body) in zip(cols, steps):
        col.markdown(f"<div class='step'><b>{h}</b><br>{body}</div>", unsafe_allow_html=True)


def page_my_timetable():
    db = get_db()
    page_header("👩‍🏫 My timetable")
    show_flash()
    if not db["timetable"]:
        no_timetable_notice()
        return
    code = teacher_picker(db, "my_teacher")
    if not code:
        return
    t = teacher_map(db)[code]
    mine = [e for e in db["timetable"] if e["teacher"] == code]
    periods = sum(e["duration"] for e in mine)
    per_day = {d: sum(e["duration"] for e in mine if e["day"] == d) for d in db["settings"]["days"]}
    busiest = max(per_day, key=per_day.get) if per_day else "-"

    c = st.columns(4)
    c[0].metric("Classes / week", len(mine))
    c[1].metric("Teaching hours / week", periods)
    c[2].metric("Sections taught", len({e["section"] for e in mine}))
    c[3].metric("Busiest day", f"{busiest} ({per_day.get(busiest, 0)})")
    st.caption("🔗 Tip: bookmark this page — the link includes your teacher code, so it opens straight to your timetable.")

    tab_week, tab_dated, tab_free, tab_list = st.tabs(["Weekly timetable", "A specific week (with changes)", "My free periods", "List & downloads"])
    with tab_week:
        grid = grid_html(db, [teacher_cell(db, e) for e in mine])
        st.markdown(grid, unsafe_allow_html=True)
    with tab_dated:
        week_of = st.date_input("Show the week of", value=sc.today_ist(), key="my_week")
        cells, labels = week_cells(db, week_of, lambda e: e["teacher"] == code, teacher_cell)
        st.markdown(grid_html(db, cells, day_labels=labels), unsafe_allow_html=True)
        st.caption("Dashed outline = class moved into this slot. Struck-through = class moved away.")
    with tab_free:
        slots = db["settings"]["slots"]
        unavail = set(db.get("unavailability", {}).get(code, []))
        busy = {(e["day"], e["slot"] + k) for e in mine for k in range(e["duration"])}
        rows = []
        for d in db["settings"]["days"]:
            free = [f"{s['start']}–{s['end']}" for i, s in enumerate(slots)
                    if not s.get("is_break") and (d, i) not in busy and f"{d}|{i}" not in unavail]
            rows.append({"Day": d, "Free periods": ", ".join(free) or "—", "Count": len(free)})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    with tab_list:
        day_order = {d: i for i, d in enumerate(db["settings"]["days"])}
        rows = [
            {"Day": e["day"], "Time": time_range(db, e["slot"], e["duration"]), "Subject": subject_name(db, e["subject"]),
             "Code": e["subject"], "Section": e["section"], "Room": e["room"]}
            for e in sorted(mine, key=lambda e: (day_order[e["day"]], e["slot"]))
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        downloads(db, t["name"], mine, lambda e: f"{subject_name(db, e['subject'])} | {e['section']} | {e['room']}",
                  grid_html(db, [teacher_cell(db, e) for e in mine]), f"timetable_{code}")

    upcoming = [r for r in db.get("reschedules", []) if r["teacher"] == code and max(r["from_date"], r["to_date"]) >= sc.today_ist().isoformat()]
    st.subheader("My upcoming one-time reschedules")
    if not upcoming:
        st.caption("None. Use **Reschedule a class** if you can't take a class.")
    for r in sorted(upcoming, key=lambda r: r["from_date"]):
        e = next((x for x in db["timetable"] if x["id"] == r["entry_id"]), None)
        if not e:
            continue
        col1, col2 = st.columns([5, 1], vertical_alignment="center")
        col1.markdown(
            f"**{subject_name(db, e['subject'])}** ({e['section']}): "
            f"{fmt_date(r['from_date'])} {time_range(db, r['from_slot'], e['duration'])} → "
            f"**{fmt_date(r['to_date'])} {time_range(db, r['to_slot'], e['duration'])}**"
            f"{' · Room ' + r['to_room'] if r.get('to_room') else ''}"
            f"{' · _' + r['reason'] + '_' if r.get('reason') else ''}"
        )
        if col2.button("Undo", key=f"undo_{r['id']}"):
            db["reschedules"] = [x for x in db["reschedules"] if x["id"] != r["id"]]
            save_db(db)
            flash("Reschedule cancelled — the class is back in its original slot.")
            st.rerun()


def page_reschedule():
    db = get_db()
    page_header("🔁 Reschedule a class",
                "Busy during one of your classes? Pick it below and see every slot where **you, the section and a room are all free**.")
    show_flash()
    if not db["timetable"]:
        no_timetable_notice()
        return
    code = teacher_picker(db, "rs_teacher")
    if not code:
        return
    day_order = {d: i for i, d in enumerate(db["settings"]["days"])}
    mine = sorted([e for e in db["timetable"] if e["teacher"] == code], key=lambda e: (day_order[e["day"]], e["slot"]))
    if not mine:
        st.info("This teacher has no classes in the timetable.")
        return
    by_id = {e["id"]: e for e in mine}
    eid = st.selectbox("Which class can't you take?", list(by_id), format_func=lambda i: entry_label(db, by_id[i]))
    entry = by_id[eid]

    mode = st.radio("What do you need?", ["once", "permanent"], horizontal=True,
                    format_func=lambda m: {"once": "📅 Just once — I'm busy on a particular date",
                                           "permanent": "📌 Permanently — move it in the weekly timetable"}[m])

    if mode == "once":
        today = sc.today_ist()
        target_wd = sc.WEEKDAY_NAMES.index(entry["day"])
        next_occ = today + timedelta(days=(target_wd - today.weekday()) % 7)
        c1, c2 = st.columns(2)
        missed = c1.date_input("Date of the class you'll miss", value=next_occ, min_value=today, key=f"missed_{eid}")
        weeks = c2.radio("Look for free slots in", [1, 2], horizontal=True,
                         format_func=lambda w: "That week" if w == 1 else "That week + the next")
        if sc.WEEKDAY_NAMES[missed.weekday()] != entry["day"]:
            st.error(f"{fmt_date(missed)} is a {sc.WEEKDAY_NAMES[missed.weekday()]}, but this class is on {entry['day']}s.")
            return
        done = [r for r in db.get("reschedules", []) if r["entry_id"] == eid and r["from_date"] == missed.isoformat()]
        if done:
            r = done[0]
            st.info(f"This class on {fmt_date(missed)} is already moved to {fmt_date(r['to_date'])} "
                    f"{time_range(db, r['to_slot'], entry['duration'])}. Undo it from **My timetable** to choose again.")
            return
        options = sc.one_time_options(db, entry, missed, weeks)
        first_week = {d.isoformat() for d in sc.week_dates(missed, db["settings"]["days"]).values()}
        base_cells, labels = week_cells(db, missed, lambda e: e["teacher"] == code, teacher_cell)
        grid_opts = [o for o in options if o["date"].isoformat() in first_week]
    else:
        if not require_admin("Permanent changes to the weekly timetable need the coordinator's approval."):
            return
        options = sc.permanent_options(db, entry)
        base_cells = [teacher_cell(db, e) for e in mine]
        labels, grid_opts = None, options

    if not options:
        st.warning("No free slot found where you, the section and a room are all free. "
                   "Try the two-week search, or ask the coordinator to adjust the timetable.")
        return

    st.markdown(f"#### {len(options)} possible slot{'s' if len(options) != 1 else ''} found")
    others, moving = [], []
    for c in base_cells:
        if c["day"] == entry["day"] and c["slot"] == entry["slot"] and not c.get("cls"):
            moving.append(dict(c, cls="tt-sel", badge="Class to move"))
        elif c.get("cls") == "tt-cancel":
            moving.append(c)
        else:
            others.append(c)
    numbered = {id(o): n for n, o in enumerate(options, start=1)}
    opt_cells = [
        {"day": o["day"], "slot": o["slot"], "duration": 1, "cls": "tt-option",
         "title": f"Option {numbered[id(o)]}{' ⭐' if o['recommended'] else ''}", "lines": [o["room"] and f"Room {o['room']}"]}
        for o in grid_opts
    ]
    with st.expander("See the options on your timetable", expanded=True):
        st.markdown(grid_html(db, others + opt_cells + moving, day_labels=labels), unsafe_allow_html=True)
        st.caption("Green = free option (shows where the class would start). ⭐ = recommended.")

    table = pd.DataFrame([
        {
            "#": n, "⭐": "⭐" if o["recommended"] else "",
            "Day": o["day"] if o["date"] is None else f"{o['day']}, {o['date'].strftime('%d %b')}",
            "Time": o["time"], "Room": o["room"] if o["room"] is not None else "⚠️ none free",
            "Your classes that day": o["your_classes_that_day"],
            "Section's classes that day": o["section_classes_that_day"],
            "Notes": o["notes"],
        }
        for n, o in enumerate(options, start=1)
    ])
    st.caption("👇 Click a row to choose it.")
    event = st.dataframe(table, hide_index=True, width="stretch", on_select="rerun",
                         selection_mode="single-row", key=f"opts_{eid}_{mode}")
    rows = event.selection.rows if event and event.selection else []
    if not rows:
        st.info("Select one of the slots above to continue.")
        return
    choice = options[rows[0]]
    when = choice["day"] if choice["date"] is None else f"{choice['day']} {choice['date'].strftime('%d %b %Y')}"
    st.success(f"Selected: **{when}, {choice['time']}**" + (f" in **{choice['room']}**" if choice["room"] else ""))
    reason = st.text_input("Reason (optional)", placeholder="e.g. Examination duty, conference, department meeting")
    mark_unavail = False
    if mode == "permanent":
        mark_unavail = st.checkbox(
            f"Also mark me unavailable on {entry['day']} {time_range(db, entry['slot'], entry['duration'])} "
            "so future timetables avoid it", value=True)

    if st.button("✅ Confirm reschedule", type="primary"):
        if mode == "once":
            db["reschedules"].append({
                "id": sc.new_id(), "entry_id": eid, "teacher": code, "section": entry["section"],
                "subject": entry["subject"], "from_date": missed.isoformat(), "from_slot": entry["slot"],
                "to_date": choice["date"].isoformat(), "to_slot": choice["slot"], "to_room": choice["room"] or "",
                "reason": reason, "created": sc.now_ist().isoformat(timespec="minutes"),
            })
        else:
            old_day, old_slot = entry["day"], entry["slot"]
            for e in db["timetable"]:
                if e["id"] == eid:
                    e.update(day=choice["day"], slot=choice["slot"], room=choice["room"] or "")
            # One-time moves of this class were based on the old slot; drop them.
            db["reschedules"] = [r for r in db["reschedules"] if r["entry_id"] != eid]
            if mark_unavail:
                lst = db["unavailability"].setdefault(code, [])
                for k in range(entry["duration"]):
                    key = f"{old_day}|{old_slot + k}"
                    if key not in lst:
                        lst.append(key)
        save_db(db)
        flash(f"Done! {subject_name(db, entry['subject'])} ({entry['section']}) moved to {when}, {choice['time']}.")
        st.rerun()


def page_section():
    db = get_db()
    page_header("🏫 Section timetable")
    show_flash()
    if not db["timetable"]:
        no_timetable_notice()
        return
    names = [s["name"] for s in db["sections"]]
    if not names:
        st.warning("No sections defined.")
        return
    sec = st.selectbox("Section", names)
    entries = [e for e in db["timetable"] if e["section"] == sec]
    tab1, tab2 = st.tabs(["Weekly timetable", "A specific week (with changes)"])
    with tab1:
        grid = grid_html(db, [section_cell(db, e) for e in entries])
        st.markdown(grid, unsafe_allow_html=True)
        downloads(db, sec, entries, lambda e: f"{subject_name(db, e['subject'])} | {teacher_name(db, e['teacher'])} | {e['room']}",
                  grid, f"timetable_{sec.replace(' ', '_')}")
    with tab2:
        week_of = st.date_input("Show the week of", value=sc.today_ist(), key="sec_week")
        cells, labels = week_cells(db, week_of, lambda e: e["section"] == sec, section_cell)
        st.markdown(grid_html(db, cells, day_labels=labels), unsafe_allow_html=True)

    st.subheader("Who teaches what")
    alloc = [a for a in db["assignments"] if a["section"] == sec]
    st.dataframe(pd.DataFrame([
        {"Subject": subject_name(db, a["subject"]), "Code": a["subject"], "Teacher": teacher_name(db, a["teacher"]),
         "Sessions / week": a["sessions_per_week"], "Periods per session": a["duration"]} for a in alloc
    ]), hide_index=True, width="stretch")


def page_generate():
    page_header("🧮 Generate timetable")
    show_flash()
    if not require_admin():
        return
    db = get_db()
    errors, warnings = sc.validate(db)
    n_sessions = sum(int(a.get("sessions_per_week") or 0) for a in db["assignments"])
    n_periods = sum(int(a.get("sessions_per_week") or 0) * int(a.get("duration") or 1) for a in db["assignments"])
    c = st.columns(4)
    c[0].metric("Sessions to place", n_sessions)
    c[1].metric("Periods to place", n_periods)
    c[2].metric("Teaching periods / week", sc.teaching_slot_count(db["settings"]))
    c[3].metric("Rooms", len(db["rooms"]))

    st.markdown("""
**Rules the generator follows**
- A teacher, a section and a room are never in two places at once
- Teacher unavailability (from **Setup data → Teacher availability**) is respected
- Teachers never exceed their *max periods per day*
- Labs get consecutive periods in a lab room and never cross the lunch break
- The same subject isn't repeated in a day for a section (unless allowed in settings), and classes are spread across the week
""")
    for e in errors:
        st.error(e)
    for w in warnings:
        st.warning(w)

    time_limit = st.slider("Maximum search time (seconds)", 2, 30, 6,
                           help="Larger departments may need longer to find a timetable that places every class.")
    if db["timetable"]:
        msg = "Generating again **replaces the current timetable**"
        if db["reschedules"]:
            msg += f" and clears {len(db['reschedules'])} one-time reschedule(s)"
        st.warning(msg + ". Download a backup first if you want to keep it.")
    if st.button("⚡ Generate timetable", type="primary", disabled=bool(errors)):
        with st.spinner("Building a clash-free timetable…"):
            result = sc.generate(db, time_limit=time_limit)
        db["timetable"], db["reschedules"] = result["entries"], []
        save_db(db)
        st.session_state["last_gen"] = result
        st.rerun()

    res = st.session_state.get("last_gen")
    if res:
        if res["unplaced"]:
            st.error(f"Placed {len(res['entries'])} sessions, but **{len(res['unplaced'])} could not be placed** "
                     f"(searched {res['attempts']} arrangements).")
            st.dataframe(pd.DataFrame([
                {"Section": u["section"], "Subject": subject_name(db, u["subject"]),
                 "Teacher": teacher_name(db, u["teacher"]), "Periods": u["duration"]} for u in res["unplaced"]
            ]), hide_index=True, width="stretch")
            st.caption("Try: allowing the same subject twice a day, adding rooms, raising teachers' max periods/day, "
                       "reducing unavailability, or a longer search time.")
        else:
            st.success(f"✅ All {len(res['entries'])} sessions placed with no clashes.")

    if db["timetable"]:
        clashes = sc.conflicts(db)
        if clashes:
            st.error("Clashes found in the current timetable:\n\n- " + "\n- ".join(clashes))
        st.subheader("Teacher workload (periods per day)")
        days = db["settings"]["days"]
        rows = []
        for t in db["teachers"]:
            mine = [e for e in db["timetable"] if e["teacher"] == t["code"]]
            row = {"Teacher": t["name"]}
            row.update({d[:3]: sum(e["duration"] for e in mine if e["day"] == d) for d in days})
            row["Total"] = sum(e["duration"] for e in mine)
            rows.append(row)
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        st.subheader("Preview a section")
        sec = st.selectbox("Section", [s["name"] for s in db["sections"]], key="gen_preview")
        st.markdown(grid_html(db, [section_cell(db, e) for e in db["timetable"] if e["section"] == sec]),
                    unsafe_allow_html=True)


# ---------------------------- Setup ------------------------------------------ #
def _clean(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v.strip() if isinstance(v, str) else v


def _records(df: pd.DataFrame, cols: list[str], key: str) -> list[dict]:
    out = []
    for rec in df.to_dict("records"):
        r = {c: _clean(rec.get(c)) for c in cols}
        if r.get(key):
            out.append(r)
    return out


def _dupes(rows, key):
    seen, d = set(), set()
    for r in rows:
        k = str(r[key]).strip().lower()
        if k in seen:
            d.add(r[key])
        seen.add(k)
    return d


def _int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def setup_simple_table(db, field, cols, key, column_config, label, normalise=None):
    df = pd.DataFrame(db[field], columns=cols)
    with st.form(f"form_{field}"):
        edited = st.data_editor(df, num_rows="dynamic", width="stretch", hide_index=True,
                                column_config=column_config, key=f"ed_{field}")
        submitted = st.form_submit_button(f"💾 Save {label}", type="primary")
    if submitted:
        rows = _records(edited, cols, key)
        if normalise:
            rows = [normalise(r) for r in rows]
        d = _dupes(rows, key)
        if d:
            st.error(f"Duplicate {key}: {', '.join(map(str, d))}")
            return
        db[field] = rows
        save_db(db)
        flash(f"Saved {len(rows)} {label}.")
        st.rerun()


def page_setup():
    page_header("⚙️ Setup data", "Enter everything once; the generator does the rest. Add or delete rows directly in the tables.")
    show_flash()
    if not require_admin():
        return
    db = get_db()
    tabs = st.tabs(["🏛️ Institution & timings", "📚 Subjects", "👩‍🏫 Teachers", "👥 Sections", "🚪 Rooms",
                    "🔗 Course allocation", "⛔ Teacher availability"])

    with tabs[0]:
        s = db["settings"]
        with st.form("form_settings"):
            c1, c2, c3 = st.columns(3)
            inst = c1.text_input("Institution", s["institution"])
            dept = c2.text_input("Department / School", s.get("department", ""))
            term = c3.text_input("Academic term", s.get("academic_term", ""))
            days = st.multiselect("Working days", sc.WEEKDAY_NAMES, default=s["days"])
            st.markdown("**Daily periods** — tick *Break / lunch* for non-teaching periods. Times as HH:MM.")
            slots_df = pd.DataFrame(s["slots"], columns=["start", "end", "is_break"])
            slots_ed = st.data_editor(
                slots_df, num_rows="dynamic", hide_index=True, width="stretch", key="ed_slots",
                column_config={
                    "start": st.column_config.TextColumn("Start", required=True),
                    "end": st.column_config.TextColumn("End", required=True),
                    "is_break": st.column_config.CheckboxColumn("Break / lunch", default=False),
                })
            repeat = st.checkbox("Allow the same subject twice in a day for a section (only used when needed)",
                                 value=s.get("allow_same_subject_twice_a_day", False))
            ok = st.form_submit_button("💾 Save settings", type="primary")
        if ok:
            slots = [{"start": str(r["start"]), "end": str(r["end"]), "is_break": bool(r["is_break"])}
                     for r in _records(slots_ed, ["start", "end", "is_break"], "start")]
            slots.sort(key=lambda x: x["start"].zfill(5))
            changed = days != s["days"] or len(slots) != len(s["slots"])
            s.update(institution=inst, department=dept, academic_term=term,
                     days=[d for d in sc.WEEKDAY_NAMES if d in days], slots=slots,
                     allow_same_subject_twice_a_day=repeat)
            save_db(db)
            flash("Settings saved." + (" Days or periods changed — please regenerate the timetable." if changed and db["timetable"] else ""))
            st.rerun()

    with tabs[1]:
        setup_simple_table(db, "subjects", ["code", "name", "type"], "code", {
            "code": st.column_config.TextColumn("Code", required=True),
            "name": st.column_config.TextColumn("Subject name", required=True, width="large"),
            "type": st.column_config.SelectboxColumn("Type", options=["Theory", "Lab"], default="Theory", required=True),
        }, "subjects")

    with tabs[2]:
        setup_simple_table(db, "teachers", ["code", "name", "department", "email", "max_per_day"], "code", {
            "code": st.column_config.TextColumn("Code", required=True, help="Short unique ID, e.g. T01 or employee ID"),
            "name": st.column_config.TextColumn("Name", required=True, width="medium"),
            "department": st.column_config.TextColumn("Department"),
            "email": st.column_config.TextColumn("Email"),
            "max_per_day": st.column_config.NumberColumn("Max periods / day", min_value=1, max_value=12, default=4),
        }, "teachers", normalise=lambda r: {**r, "max_per_day": _int(r["max_per_day"], 4)})

    with tabs[3]:
        rooms = [r["name"] for r in db["rooms"] if r["type"] == "Classroom"]
        setup_simple_table(db, "sections", ["name", "program", "semester", "strength", "home_room"], "name", {
            "name": st.column_config.TextColumn("Section", required=True, help="e.g. CSE 3A"),
            "program": st.column_config.TextColumn("Programme"),
            "semester": st.column_config.NumberColumn("Semester", min_value=1, max_value=10),
            "strength": st.column_config.NumberColumn("Students", min_value=1),
            "home_room": st.column_config.SelectboxColumn("Home classroom", options=rooms,
                                                          help="Preferred room for theory classes"),
        }, "sections", normalise=lambda r: {**r, "semester": _int(r["semester"], None), "strength": _int(r["strength"], None)})

    with tabs[4]:
        setup_simple_table(db, "rooms", ["name", "type", "capacity"], "name", {
            "name": st.column_config.TextColumn("Room", required=True),
            "type": st.column_config.SelectboxColumn("Type", options=["Classroom", "Lab"], default="Classroom", required=True),
            "capacity": st.column_config.NumberColumn("Capacity", min_value=1),
        }, "rooms", normalise=lambda r: {**r, "capacity": _int(r["capacity"], None)})

    with tabs[5]:
        st.markdown("Which teacher teaches which subject to which section, and how often. "
                    "Labs usually need **2 periods per session**.")
        subj_opts = {f"{s['code']} — {s['name']}": s["code"] for s in db["subjects"]}
        teach_opts = {f"{t['code']} — {t['name']}": t["code"] for t in db["teachers"]}
        subj_rev = {v: k for k, v in subj_opts.items()}
        teach_rev = {v: k for k, v in teach_opts.items()}
        df = pd.DataFrame([
            {"section": a["section"], "subject": subj_rev.get(a["subject"], a["subject"]),
             "teacher": teach_rev.get(a["teacher"], a["teacher"]),
             "sessions_per_week": a["sessions_per_week"], "duration": a["duration"]}
            for a in db["assignments"]
        ], columns=["section", "subject", "teacher", "sessions_per_week", "duration"])
        with st.form("form_alloc"):
            edited = st.data_editor(df, num_rows="dynamic", hide_index=True, width="stretch", key="ed_alloc",
                column_config={
                    "section": st.column_config.SelectboxColumn("Section", options=[s["name"] for s in db["sections"]], required=True),
                    "subject": st.column_config.SelectboxColumn("Subject", options=list(subj_opts), required=True, width="medium"),
                    "teacher": st.column_config.SelectboxColumn("Teacher", options=list(teach_opts), required=True, width="medium"),
                    "sessions_per_week": st.column_config.NumberColumn("Sessions / week", min_value=1, max_value=10, default=3),
                    "duration": st.column_config.NumberColumn("Periods / session", min_value=1, max_value=4,
                                                              help="Leave empty: 2 for labs, 1 otherwise"),
                })
            ok = st.form_submit_button("💾 Save allocation", type="primary")
        if ok:
            rows = []
            types = {s["code"]: s.get("type") for s in db["subjects"]}
            for r in _records(edited, ["section", "subject", "teacher", "sessions_per_week", "duration"], "subject"):
                if not (r["section"] and r["teacher"]):
                    continue
                subj = subj_opts.get(r["subject"], r["subject"])
                rows.append({
                    "section": r["section"], "subject": subj, "teacher": teach_opts.get(r["teacher"], r["teacher"]),
                    "sessions_per_week": _int(r["sessions_per_week"], 3),
                    "duration": _int(r["duration"], 2 if types.get(subj) == "Lab" else 1),
                })
            db["assignments"] = rows
            save_db(db)
            flash(f"Saved {len(rows)} allocations.")
            st.rerun()

        cap = sc.teaching_slot_count(db["settings"])
        load = {}
        for a in db["assignments"]:
            load[a["teacher"]] = load.get(a["teacher"], 0) + a["sessions_per_week"] * a["duration"]
        st.markdown("**Weekly load per teacher**")
        st.dataframe(pd.DataFrame([
            {"Teacher": t["name"], "Periods / week": load.get(t["code"], 0),
             "Available periods": cap - len(db["unavailability"].get(t["code"], []))} for t in db["teachers"]
        ]), hide_index=True, width="stretch")

    with tabs[6]:
        st.markdown("Untick the periods when a teacher **cannot** take classes (meetings, other campus duties, etc.).")
        if not db["teachers"]:
            st.info("Add teachers first.")
        else:
            code = st.selectbox("Teacher", [t["code"] for t in db["teachers"]],
                                format_func=lambda c: f"{teacher_name(db, c)} ({c})", key="av_teacher")
            slots = db["settings"]["slots"]
            days = db["settings"]["days"]
            un = set(db["unavailability"].get(code, []))
            idx = [i for i, s in enumerate(slots) if not s.get("is_break")]
            grid = pd.DataFrame({"Period": [f"{slots[i]['start']}–{slots[i]['end']}" for i in idx],
                                 **{d: [f"{d}|{i}" not in un for i in idx] for d in days}})
            with st.form(f"form_av_{code}"):
                ed = st.data_editor(grid, width="stretch", hide_index=True, key=f"ed_av_{code}", disabled=["Period"],
                                    column_config={d: st.column_config.CheckboxColumn(d) for d in days})
                ok = st.form_submit_button("💾 Save availability", type="primary")
            if ok:
                blocked = [f"{d}|{i}" for d in days for row, i in enumerate(idx) if not bool(ed[d].iloc[row])]
                if blocked:
                    db["unavailability"][code] = blocked
                else:
                    db["unavailability"].pop(code, None)
                save_db(db)
                flash(f"Availability saved for {teacher_name(db, code)} ({len(blocked)} blocked periods). "
                      "Regenerate the timetable to apply it.")
                st.rerun()


def page_backup():
    page_header("💾 Backup & export")
    show_flash()
    db = get_db()
    st.info("On Streamlit Community Cloud the app's storage resets when the app restarts or redeploys. "
            "**Download a backup after making changes** and restore it here if needed — or commit `data/db.json` "
            "to your GitHub repo so it's loaded on startup.")
    c1, c2 = st.columns(2)
    c1.download_button("⬇️ Download full backup (JSON)", ds.to_json_bytes(db),
                       f"timetable_backup_{sc.today_ist().isoformat()}.json", "application/json", width="stretch")
    if db["timetable"]:
        sheets = {}
        for t in db["teachers"]:
            sheets[f"{t['code']} {t['name']}"] = ds.grid_frame(
                db, [e for e in db["timetable"] if e["teacher"] == t["code"]],
                lambda e: f"{subject_name(db, e['subject'])} | {e['section']} | {e['room']}")
        for s in db["sections"]:
            sheets[f"Sec {s['name']}"] = ds.grid_frame(
                db, [e for e in db["timetable"] if e["section"] == s["name"]],
                lambda e: f"{subject_name(db, e['subject'])} | {teacher_name(db, e['teacher'])} | {e['room']}")
        c2.download_button("⬇️ All timetables (Excel, one sheet each)", ds.excel_bytes(sheets),
                           "all_timetables.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")

    st.divider()
    st.subheader("Restore or reset")
    if not require_admin():
        return
    up = st.file_uploader("Restore from a backup file", type=["json"])
    if up and st.button("Restore this backup", type="primary"):
        try:
            save_db(ds.from_json_bytes(up.getvalue()))
            flash("Backup restored.")
            st.rerun()
        except Exception as ex:
            st.error(f"Could not restore: {ex}")
    sure = st.checkbox("I understand this replaces all current data")
    c1, c2 = st.columns(2)
    if c1.button("Load demo data", disabled=not sure, width="stretch"):
        save_db(ds.sample_db())
        flash("Demo data loaded.")
        st.rerun()
    if c2.button("Start empty (keep settings)", disabled=not sure, width="stretch"):
        fresh = ds.empty_db()
        fresh["settings"] = db["settings"]
        save_db(fresh)
        flash("All data cleared.")
        st.rerun()


# --------------------------------------------------------------------------- #
# Navigation
# --------------------------------------------------------------------------- #
PAGES = {
    "home": st.Page(page_home, title="Home", icon="🏠", default=True),
    "my": st.Page(page_my_timetable, title="My timetable", icon="👩‍🏫", url_path="my-timetable"),
    "reschedule": st.Page(page_reschedule, title="Reschedule a class", icon="🔁", url_path="reschedule"),
    "section": st.Page(page_section, title="Section timetable", icon="🏫", url_path="section"),
    "generate": st.Page(page_generate, title="Generate timetable", icon="🧮", url_path="generate"),
    "setup": st.Page(page_setup, title="Setup data", icon="⚙️", url_path="setup"),
    "backup": st.Page(page_backup, title="Backup & export", icon="💾", url_path="backup"),
}

nav = st.navigation({
    "For teachers": [PAGES["home"], PAGES["my"], PAGES["reschedule"], PAGES["section"]],
    "Coordinator": [PAGES["generate"], PAGES["setup"], PAGES["backup"]],
})
with st.sidebar:
    st.markdown(f"<div style='font-weight:700;color:{ACCENT};font-size:1.05rem'>MUJ Timetable Planner</div>",
                unsafe_allow_html=True)
    st.caption("Built for the faculty of Manipal University Jaipur")
    if admin_password() and st.session_state.get("is_admin"):
        if st.button("🔓 Lock coordinator pages"):
            st.session_state["is_admin"] = False
            st.rerun()
nav.run()
