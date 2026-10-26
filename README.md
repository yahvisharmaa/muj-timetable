# MUJ Faculty Timetable Planner

A Streamlit web app for the faculty of Manipal University Jaipur. The coordinator enters subjects, teachers, sections, rooms and the course allocation; the app generates a clash-free timetable and every teacher gets their own personal timetable — plus instant options when they need to reschedule a class.

## Features

- **Personal timetables** for every teacher (weekly grid, a specific week with changes, free periods, list view)
- **Section timetables** with "who teaches what"
- **Automatic generation** — no teacher/section/room double-booking, respects teacher unavailability and max periods per day, labs get consecutive periods in a lab room and never cross lunch, subjects are spread across the week
- **Reschedule a class**
  - *Just once*: pick the date you'll miss → see every slot that week (or the next) where you, the section and a room are all free → confirm. Shows up on the teacher's and section's dated view and can be undone.
  - *Permanently*: move the class in the weekly timetable (coordinator approval if a password is set), optionally blocking the old slot for future generations
- **Downloads**: Excel, CSV, printable page (save as PDF), all timetables in one Excel file, full JSON backup/restore
- Demo data (fictional names) loads on first launch so you can try everything immediately

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud

1. Push this folder to a GitHub repository (`app.py` at the root).
2. On [share.streamlit.io](https://share.streamlit.io) → **Create app** → pick the repo, branch, and `app.py` as the main file → **Deploy**.
3. *(Recommended)* Protect the coordinator pages: in the app's **Settings → Secrets**, add

   ```toml
   ADMIN_PASSWORD = "choose-a-strong-password"
   ```

   Without it, anyone with the link can edit data and regenerate the timetable.

### Important: saving data on Streamlit Cloud

Streamlit Cloud's disk is reset whenever the app restarts or redeploys. After setting up your real data:

- download a backup from **Backup & export**, and either
- commit it to the repo as `data/db.json` (it's loaded on startup), or restore it from the same page when needed.

## Using it

1. **Setup data** (coordinator): timings & working days → subjects → teachers → rooms → sections → course allocation → teacher availability. Each tab has its own **Save** button.
2. **Generate timetable**: fix any red errors it lists, then click **Generate**.
3. Teachers open **My timetable** and pick their name. The URL includes their code (e.g. `/my-timetable?teacher=T01`), so they can bookmark it.
4. **Reschedule a class** when busy.

## Files

| File | Purpose |
| --- | --- |
| `app.py` | Streamlit UI (all pages) |
| `scheduler.py` | Timetable generator, validation, reschedule search (no Streamlit dependency) |
| `data_store.py` | JSON storage, demo data, Excel export |
| `.streamlit/config.toml` | Theme |
