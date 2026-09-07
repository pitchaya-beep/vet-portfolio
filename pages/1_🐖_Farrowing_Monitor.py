"""
Farrowing Monitor — บันทึกเวลาคลอดลูกสุกรแบบเรียลไทม์ ผูกกับผังคอกจริงของโรงเรือน

Flow การใช้งาน:
1. หน้าแรก (แท็บ "หน้าคอก") แสดงผังคอกเป็น 2 ฝั่งซ้าย-ขวา คั่นด้วยทางเดินตรงกลาง
   เหมือนผังโรงเรือนจริง แต่ละคอกมีสถานะ: ว่าง / แม่รอคลอด / กำลังคลอด / คลอดเสร็จแล้ว
2. คลิก "เข้าคอกนี้" -> ถ้าคอกว่าง จะให้กรอกข้อมูลแม่ + เลือกสถานะเริ่มต้นได้เลย
   (เผื่อกรณีแม่คลอดไปแล้วแต่คนงานเพิ่งมากรอกทีหลัง)
3. กดปุ่มเดียว "ลูกคลอดแล้ว" ทันทีที่ลูกออก ระบบ timestamp ให้อัตโนมัติ
   พร้อมนาฬิกาจับเวลาสดที่แจ้งเตือนเมื่อห่างจากตัวก่อนหน้านานผิดปกติ
4. แท็บ "ประวัติ" ดูข้อมูลย้อนหลัง แก้ไข/เปิดรอบใหม่ (เผื่อหลงกดจบ) หรือลบได้
"""

import streamlit as st
import streamlit.components.v1 as components
import sqlite3
import os
import csv
import io
from datetime import datetime, timezone, timedelta
from streamlit_autorefresh import st_autorefresh

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Farrowing Monitor", page_icon="🐖", layout="wide")

# Streamlit Community Cloud runs its servers on UTC, not Thai time — if we
# just called datetime.now() every timestamp saved would be 7 hours off
# once deployed (even though it looks correct when run locally on a Thai
# machine). Pin everything to Thai local time explicitly instead.
THAI_TZ = timezone(timedelta(hours=7), name="ICT")

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "farrowing.db")

PIGLET_STATUS_OPTS = ["alive", "stillborn", "died_after", "mummy"]
PIGLET_STATUS_LABELS = {
    "alive": "มีชีวิต",
    "stillborn": "ตายคลอด (stillborn)",
    "died_after": "ตายหลังคลอด",
    "mummy": "มัมมี่ (mummified)",
}

# session/pen-occupancy status — this drives what color/label the pen box shows
SESSION_STATUS_OPTS = ["waiting", "in_progress", "completed"]
SESSION_STATUS_LABELS = {
    "waiting": "แม่รอคลอด",
    "in_progress": "กำลังคลอด",
    "completed": "คลอดเสร็จแล้ว",
    "vacated": "ย้ายออกแล้ว",
}
SESSION_STATUS_COLORS = {
    None: "#ffffff",           # ว่าง
    "waiting": "#fff9c4",      # เหลืองอ่อน
    "in_progress": "#ffcdd2",  # แดงอ่อน
    "completed": "#c8e6c9",    # เขียวอ่อน
}


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def ensure_column(conn, table, column, coltype):
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
        conn.commit()


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pen_code TEXT UNIQUE NOT NULL,
            side TEXT DEFAULT 'left',
            sort_order INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS farrowing_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sow_id TEXT NOT NULL,
            breed TEXT,
            parity INTEGER,
            start_time TEXT NOT NULL,
            end_time TEXT,
            alert_threshold_min INTEGER DEFAULT 30,
            status TEXT DEFAULT 'in_progress',
            notes TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS farrowing_piglets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            seq_number INTEGER NOT NULL,
            birth_time TEXT NOT NULL,
            interval_minutes REAL,
            sex TEXT,
            weight_kg REAL,
            status TEXT,
            assisted INTEGER DEFAULT 0,
            notes TEXT,
            FOREIGN KEY(session_id) REFERENCES farrowing_sessions(id)
        )
    """)
    conn.commit()
    # migrations for anyone who already ran an earlier version of this page
    ensure_column(conn, "pens", "side", "TEXT DEFAULT 'left'")
    ensure_column(conn, "farrowing_sessions", "pen_id", "INTEGER")
    ensure_column(conn, "farrowing_sessions", "sire_id", "TEXT")
    # "breed" has always meant the dam's breed; sire_breed is new and tracked
    # separately since a litter's sire is very often a different breed
    # (common in crossbred commercial herds, e.g. Landrace dam x Duroc sire).
    ensure_column(conn, "farrowing_sessions", "sire_breed", "TEXT")
    # Used only while status='waiting' — the date she's expected to farrow by,
    # so staff can be warned if she goes overdue before real labor starts.
    ensure_column(conn, "farrowing_sessions", "due_date", "TEXT")
    ensure_column(conn, "farrowing_piglets", "mummy_length_cm", "REAL")
    return conn


def get_pens_with_status(conn):
    """Each pen's *current occupying* session = the most recent session on
    that pen whose status isn't 'vacated'. If none, the pen is 'ว่าง'.
    Also pulls the latest piglet birth time for that session so the layout
    page can flag overdue pens without anyone clicking into them."""
    return conn.execute("""
        SELECT p.id, p.pen_code, p.side,
               s.id, s.sow_id, s.start_time, s.alert_threshold_min, s.status, s.due_date,
               (SELECT MAX(birth_time) FROM farrowing_piglets WHERE session_id = s.id) AS last_birth_time
        FROM pens p
        LEFT JOIN farrowing_sessions s
            ON s.id = (
                SELECT id FROM farrowing_sessions
                WHERE pen_id = p.id AND status != 'vacated'
                ORDER BY id DESC LIMIT 1
            )
        ORDER BY p.side, p.sort_order, p.id
    """).fetchall()


def get_piglets(conn, session_id):
    return conn.execute(
        "SELECT id, seq_number, birth_time, interval_minutes, sex, weight_kg, "
        "status, assisted, notes, mummy_length_cm "
        "FROM farrowing_piglets WHERE session_id = ? ORDER BY seq_number",
        (session_id,),
    ).fetchall()


def pen_occupied_by_other_session(conn, pen_id, exclude_session_id):
    """True if some *other* non-vacated session already claims this pen.
    Used to stop a pen from ending up with two 'active' sessions at once —
    e.g. reopening an old completed round after a new sow has already
    started using the same pen."""
    if pen_id is None:
        return False
    row = conn.execute(
        "SELECT id FROM farrowing_sessions WHERE pen_id=? AND status!='vacated' AND id!=? LIMIT 1",
        (pen_id, exclude_session_id),
    ).fetchone()
    return row is not None


def build_session_summary_row(conn, session_row):
    """One summary row per farrowing session — how many piglets, what shape
    the litter took, and the key numbers a vet student would want to
    report on (sex split, weight, assistance, spacing between piglets)."""
    (sid, sow_id, sire_id, breed, sire_breed, parity, start_time, end_time,
     status, threshold_min, pen_id, pen_code, due_date) = session_row
    piglets = get_piglets(conn, sid)

    n_total = len(piglets)
    n_alive = sum(1 for p in piglets if p[6] == "alive")
    n_still = sum(1 for p in piglets if p[6] == "stillborn")
    n_died_after = sum(1 for p in piglets if p[6] == "died_after")
    n_mummy = sum(1 for p in piglets if p[6] == "mummy")
    n_male = sum(1 for p in piglets if p[4] == "ผู้")
    n_female = sum(1 for p in piglets if p[4] == "เมีย")
    n_assisted = sum(1 for p in piglets if p[7])

    weights = [p[5] for p in piglets if p[5]]
    avg_weight = sum(weights) / len(weights) if weights else None

    mummy_lengths = [p[9] for p in piglets if p[6] == "mummy" and p[9]]
    avg_mummy_len = sum(mummy_lengths) / len(mummy_lengths) if mummy_lengths else None
    mummy_lengths_list = ", ".join(f"{v:g}" for v in mummy_lengths) if mummy_lengths else "-"

    # seq==1's stored interval is time-since-session-start, not a real gap
    # between piglets, so it's excluded here — same reasoning as why it's
    # hidden in the live monitor and history table.
    intervals = [p[3] for p in piglets if p[1] > 1 and p[3] is not None]
    avg_int = sum(intervals) / len(intervals) if intervals else None
    max_int = max(intervals) if intervals else None

    return {
        "แม่": sow_id,
        "พ่อ": sire_id or "-",
        "สายพันธุ์แม่": breed or "-",
        "สายพันธุ์พ่อ": sire_breed or "-",
        "คอก": pen_code or "(ไม่ระบุคอก)",
        "ท้องที่": parity if parity is not None else "-",
        "วันที่เริ่มคลอด": fmt_datetime(start_time),
        "สถานะ": SESSION_STATUS_LABELS.get(status, status),
        "ลูกทั้งหมด": n_total,
        "มีชีวิต": n_alive,
        "ตายคลอด": n_still,
        "ตายหลังคลอด": n_died_after,
        "มัมมี่": n_mummy,
        "ขนาดมัมมี่เฉลี่ย (cm)": round(avg_mummy_len, 1) if avg_mummy_len is not None else "-",
        "ขนาดมัมมี่แต่ละตัว (cm)": mummy_lengths_list,
        "เพศผู้": n_male,
        "เพศเมีย": n_female,
        "ช่วยคลอด (ตัว)": n_assisted,
        "น้ำหนักเฉลี่ยแรกคลอด (kg)": round(avg_weight, 2) if avg_weight is not None else "-",
        "ระยะห่างเฉลี่ยระหว่างตัว (นาที)": round(avg_int, 1) if avg_int is not None else "-",
        "ระยะห่างสูงสุดระหว่างตัว (นาที)": round(max_int, 1) if max_int is not None else "-",
    }


def build_csv_bytes(rows):
    if not rows:
        return b""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def renumber_and_recalc(conn, session_id, session_start_time):
    """Re-sorts piglets by birth time, reassigns seq numbers and recalculates
    intervals. Needed after inserting or deleting a piglet record."""
    rows = conn.execute(
        "SELECT id, birth_time FROM farrowing_piglets WHERE session_id=? ORDER BY birth_time",
        (session_id,),
    ).fetchall()
    prev = parse_iso(session_start_time)
    for idx, (pid, bt) in enumerate(rows, start=1):
        bt_dt = parse_iso(bt)
        interval = (bt_dt - prev).total_seconds() / 60.0
        conn.execute(
            "UPDATE farrowing_piglets SET seq_number=?, interval_minutes=? WHERE id=?",
            (idx, round(interval, 2), pid),
        )
        prev = bt_dt
    conn.commit()


def now_iso():
    return datetime.now(THAI_TZ).isoformat(timespec="seconds")


def parse_iso(s):
    """Parses a stored timestamp. New timestamps always carry a +07:00
    offset (see now_iso). Older rows saved before this fix may be naive
    (no offset) — those were written using whatever clock the app happened
    to run on at the time, so we assume Thai wall-clock time for them too."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=THAI_TZ)
    return dt


def fmt_time(iso_str):
    return parse_iso(iso_str).strftime("%H:%M:%S")


def fmt_datetime(iso_str):
    return parse_iso(iso_str).strftime("%Y-%m-%d %H:%M:%S")


def parse_datetime_or_now(date_val, time_val):
    """Combine a date_input + time_input into an ISO string. Falls back to
    now() if either is missing — used so staff can backfill a real start
    time when they log a farrowing after the fact."""
    if date_val is None or time_val is None:
        return now_iso()
    return datetime.combine(date_val, time_val, tzinfo=THAI_TZ).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Live stopwatch + alert component (pure client-side JS, no reruns needed)
# ---------------------------------------------------------------------------
def render_live_timer(last_birth_iso: str, threshold_min: int):
    html = f"""
    <div id="timer-wrap" style="
        font-family: -apple-system, Segoe UI, sans-serif;
        padding: 20px; border-radius: 12px; text-align:center;
        background:#f0f2f6; transition: background 0.4s;">
      <div style="font-size:14px; color:#555; margin-bottom:6px;">
        ⏱️ เวลาที่ผ่านมาตั้งแต่ลูกตัวล่าสุด
      </div>
      <div id="timer-display" style="font-size:48px; font-weight:700; color:#31333F;">
        00:00
      </div>
      <div id="timer-status" style="font-size:14px; margin-top:6px; color:#555;">
        เกณฑ์เตือน: {threshold_min} นาที
      </div>
    </div>
    <script>
      const target = new Date("{last_birth_iso}").getTime();
      const thresholdMs = {threshold_min} * 60 * 1000;
      let beeped = false;

      function beep() {{
        try {{
          const ctx = new (window.AudioContext || window.webkitAudioContext)();
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.connect(gain); gain.connect(ctx.destination);
          osc.frequency.value = 880;
          gain.gain.setValueAtTime(0.15, ctx.currentTime);
          osc.start();
          osc.stop(ctx.currentTime + 0.35);
        }} catch (e) {{}}
      }}

      function tick() {{
        const elapsed = Date.now() - target;
        const totalSec = Math.max(0, Math.floor(elapsed / 1000));
        const mm = String(Math.floor(totalSec / 60)).padStart(2, '0');
        const ss = String(totalSec % 60).padStart(2, '0');
        document.getElementById('timer-display').textContent = mm + ":" + ss;

        const wrap = document.getElementById('timer-wrap');
        const status = document.getElementById('timer-status');
        if (elapsed > thresholdMs) {{
          wrap.style.background = "#ffe3e3";
          document.getElementById('timer-display').style.color = "#c0392b";
          status.textContent = "⚠️ เกินเกณฑ์แล้ว! ควรเข้าไปตรวจ / เตรียมช่วยคลอด";
          status.style.color = "#c0392b";
          status.style.fontWeight = "700";
          if (!beeped) {{ beep(); beeped = true; }}
        }} else {{
          wrap.style.background = "#f0f2f6";
          document.getElementById('timer-display').style.color = "#31333F";
          status.textContent = "เกณฑ์เตือน: {threshold_min} นาที";
          status.style.color = "#555";
          status.style.fontWeight = "400";
        }}
      }}
      tick();
      setInterval(tick, 1000);
    </script>
    """
    components.html(html, height=150)


def compute_overdue_minutes(session_status, start_time, last_birth_time, threshold_min):
    """Minutes past the alert threshold since the last piglet (or session
    start if none yet) — only meaningful while a sow is 'in_progress'.
    Returns None if not overdue, not applicable, or already 'completed'."""
    if session_status != "in_progress" or not threshold_min:
        return None
    reference = parse_iso(last_birth_time) if last_birth_time else (parse_iso(start_time) if start_time else None)
    if not reference:
        return None
    elapsed_min = (datetime.now(THAI_TZ) - reference).total_seconds() / 60.0
    return elapsed_min if elapsed_min > threshold_min else None


APPROACHING_RATIO = 0.8  # flag a pen once it's used up 80% of its alert threshold


def compute_approaching_minutes(session_status, start_time, last_birth_time, threshold_min):
    """Like compute_overdue_minutes, but for the earlier warning window —
    close to the threshold but not over it yet, so staff get a heads-up
    before it actually becomes overdue."""
    if session_status != "in_progress" or not threshold_min:
        return None
    reference = parse_iso(last_birth_time) if last_birth_time else (parse_iso(start_time) if start_time else None)
    if not reference:
        return None
    elapsed_min = (datetime.now(THAI_TZ) - reference).total_seconds() / 60.0
    if APPROACHING_RATIO * threshold_min <= elapsed_min <= threshold_min:
        return elapsed_min
    return None


def render_pen_box(pen_code, session_status, sow_id, due_date=None, last_birth_time=None,
                    start_time=None, threshold_min=None):
    color = SESSION_STATUS_COLORS.get(session_status, "#ffffff")
    label = "ว่าง" if session_status is None else SESSION_STATUS_LABELS.get(session_status, session_status)
    # Text color is fixed dark regardless of the app's light/dark theme, since
    # these boxes always sit on a light pastel background — using the theme's
    # default (often light-colored in dark mode) makes the text unreadable.
    text_color = "#1a1a1a"
    sub_color = "#3a3a3a"
    sow_line = f"<br><span style='font-size:11px;color:{sub_color};'>{sow_id}</span>" if sow_id else ""

    due_line = ""
    if session_status == "waiting" and due_date:
        due_dt = datetime.fromisoformat(due_date).date()
        today = datetime.now(THAI_TZ).date()
        if today > due_dt:
            overdue_days = (today - due_dt).days
            due_line = (
                f"<br><span style='font-size:11px;color:#b71c1c;font-weight:700;'>"
                f"⚠️ เลยกำหนด {overdue_days} วัน</span>"
            )
        else:
            due_line = f"<br><span style='font-size:11px;color:{sub_color};'>กำหนดคลอด {due_dt.strftime('%d/%m/%Y')}</span>"

    # Only 'in_progress' pens get the minute-based overdue flag — a 'waiting'
    # sow uses the due-date system above instead, and a 'completed' sow is
    # no longer being timed for the next piglet at all (there won't be one).
    overdue_line = ""
    overdue_min = compute_overdue_minutes(session_status, start_time, last_birth_time, threshold_min)
    if overdue_min is not None:
        overdue_line = (
            f"<br><span style='font-size:11px;color:#b71c1c;font-weight:700;'>"
            f"⚠️ เลยเวลามา {overdue_min:.0f} นาที</span>"
        )
    else:
        approaching_min = compute_approaching_minutes(session_status, start_time, last_birth_time, threshold_min)
        if approaching_min is not None:
            overdue_line = (
                f"<br><span style='font-size:11px;color:#e65100;font-weight:700;'>"
                f"🟠 ใกล้ถึงเกณฑ์ ({approaching_min:.0f}/{threshold_min:.0f} นาที)</span>"
            )

    st.markdown(
        f"""
        <div style='background:{color}; border:1px solid #999; border-radius:6px;
                    padding:10px 6px; text-align:center; margin-bottom:2px;
                    box-shadow:0 1px 3px rgba(0,0,0,0.15);'>
          <b style='color:{text_color}; font-size:15px;'>{pen_code}</b><br>
          <span style='font-size:12px; color:{sub_color}; font-weight:600;'>{label}</span>{sow_line}{due_line}{overdue_line}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "fm_view" not in st.session_state:
    st.session_state.fm_view = "layout"     # "layout" | "monitor"
if "fm_pen_id" not in st.session_state:
    st.session_state.fm_pen_id = None

conn = get_conn()

st.title("🐖 Farrowing Monitor — เฝ้าคลอดลูกสุกร")
st.caption("เลือกคอกจากผังโรงเรือน แล้วบันทึกเวลาคลอดทันทีด้วยปุ่มเดียว พร้อมแจ้งเตือนเมื่อระยะห่างระหว่างตัวนานผิดปกติ")

tab_live, tab_history = st.tabs(["🏠 หน้าคอก / เฝ้าคลอด", "📜 ประวัติการคลอด"])

# =====================================================================
# TAB: LIVE (pen layout <-> monitor state machine)
# =====================================================================
with tab_live:

    # ---------------- LAYOUT VIEW ----------------
    if st.session_state.fm_view == "layout":
        # Re-runs this page automatically every 20s while it's open, so the
        # "เลยเวลามา X นาที" labels and the alert sound update on their own —
        # no need to click into a pen or touch anything.
        st_autorefresh(interval=20_000, key="layout_autorefresh")

        pens = get_pens_with_status(conn)

        # ---- compute overdue / approaching pens up front so the banners can
        # sit at the very top of the page, above the grid itself ----
        overdue_session_ids = []
        approaching_session_ids = []
        for p in pens:
            _pid, _pcode, _side, _sid, _sow, _start, _thr, _status, _due, _lastbirth = p
            if not _sid:
                continue
            if compute_overdue_minutes(_status, _start, _lastbirth, _thr) is not None:
                overdue_session_ids.append((_sid, _pcode))
            elif compute_approaching_minutes(_status, _start, _lastbirth, _thr) is not None:
                approaching_session_ids.append((_sid, _pcode))

        if overdue_session_ids:
            st.error("⚠️ คอกที่เลยเวลาคลอดตัวถัดไปแล้ว: " + ", ".join(code for _, code in overdue_session_ids))
        if approaching_session_ids:
            st.warning("🟠 คอกที่ใกล้ถึงเกณฑ์เตือนแล้ว (จับตาดูใกล้ๆ): " + ", ".join(code for _, code in approaching_session_ids))

        legend_cols = st.columns(4)
        legend_items = [
            ("ว่าง", "#ffffff"), ("แม่รอคลอด", "#fff9c4"),
            ("กำลังคลอด", "#ffcdd2"), ("คลอดเสร็จแล้ว", "#c8e6c9"),
        ]
        for col, (label, color) in zip(legend_cols, legend_items):
            col.markdown(
                f"<div style='display:flex;align-items:center;gap:6px;font-size:13px;'>"
                f"<div style='width:14px;height:14px;background:{color};border:1px solid #999;border-radius:3px;'></div>"
                f"{label}</div>",
                unsafe_allow_html=True,
            )

        with st.expander("⚙️ จัดการผังคอก"):
            if not pens:
                st.caption("ยังไม่มีคอกในระบบ — สร้างผังเริ่มต้นได้เลย (แบ่งฝั่งซ้าย/ขวาเหมือนโรงเรือนจริง)")
                sc1, sc2 = st.columns(2)
                with sc1:
                    n_left = st.number_input("จำนวนคอกฝั่งซ้าย", min_value=0, max_value=100, value=10)
                with sc2:
                    n_right = st.number_input("จำนวนคอกฝั่งขวา", min_value=0, max_value=100, value=10)
                if st.button("➕ สร้างผังคอกอัตโนมัติ"):
                    for i in range(1, int(n_left) + 1):
                        try:
                            conn.execute(
                                "INSERT INTO pens (pen_code, side, sort_order) VALUES (?, 'left', ?)",
                                (f"L{i}", i),
                            )
                        except sqlite3.IntegrityError:
                            pass
                    for i in range(1, int(n_right) + 1):
                        try:
                            conn.execute(
                                "INSERT INTO pens (pen_code, side, sort_order) VALUES (?, 'right', ?)",
                                (f"R{i}", i),
                            )
                        except sqlite3.IntegrityError:
                            pass
                    conn.commit()
                    st.rerun()

            st.markdown("**เพิ่มคอกทีละคอก**")
            ac1, ac2, ac3 = st.columns([2, 1, 1])
            with ac1:
                new_pen_code = st.text_input("ชื่อ/หมายเลขคอก", key="new_pen_code")
            with ac2:
                new_pen_side = st.selectbox("ฝั่ง", ["left", "right"], format_func=lambda x: "ซ้าย" if x == "left" else "ขวา")
            with ac3:
                st.write("")
                st.write("")
                if st.button("➕ เพิ่มคอก", use_container_width=True):
                    if new_pen_code.strip():
                        try:
                            max_order = conn.execute(
                                "SELECT COALESCE(MAX(sort_order),0) FROM pens WHERE side=?", (new_pen_side,)
                            ).fetchone()[0]
                            conn.execute(
                                "INSERT INTO pens (pen_code, side, sort_order) VALUES (?, ?, ?)",
                                (new_pen_code.strip(), new_pen_side, max_order + 1),
                            )
                            conn.commit()
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("มีชื่อคอกนี้อยู่แล้ว")

            if pens:
                st.markdown("**ลบคอก** (ลบได้เฉพาะคอกที่ว่างอยู่)")
                for pen_id, pen_code, side, sess_id, sow_id, start_time, threshold, sess_status, due_date, last_birth_time in pens:
                    c1, c2 = st.columns([4, 1])
                    side_th = "ซ้าย" if side == "left" else "ขวา"
                    occ = f"  🔴 {SESSION_STATUS_LABELS.get(sess_status, sess_status)}" if sess_id else ""
                    c1.write(f"{pen_code} ({side_th}){occ}")
                    if c2.button("🗑️", key=f"delpen_{pen_id}", disabled=sess_id is not None):
                        conn.execute("DELETE FROM pens WHERE id=?", (pen_id,))
                        conn.commit()
                        st.rerun()

        st.divider()

        if not pens:
            st.info("ยังไม่มีคอกในระบบ — เปิด '⚙️ จัดการผังคอก' ด้านบนเพื่อสร้างผังคอกก่อนเริ่มใช้งาน")
        else:
            left_pens = [p for p in pens if p[2] == "left"]
            right_pens = [p for p in pens if p[2] == "right"]
            max_rows = max(len(left_pens), len(right_pens), 1)

            with st.container(border=True):
                col_left, col_mid, col_right = st.columns([4, 1, 4])

                with col_mid:
                    st.markdown(
                        "<div style='text-align:center; font-weight:600; margin-top:20px;'>ทางเดิน</div>",
                        unsafe_allow_html=True,
                    )

                with col_left:
                    for pen in left_pens:
                        pen_id, pen_code, side, sess_id, sow_id, start_time, threshold, sess_status, due_date, last_birth_time = pen
                        render_pen_box(pen_code, sess_status, sow_id, due_date, last_birth_time, start_time, threshold)
                        if st.button("เข้าคอกนี้", key=f"enter_{pen_id}", use_container_width=True):
                            st.session_state.fm_view = "monitor"
                            st.session_state.fm_pen_id = pen_id
                            st.rerun()

                with col_right:
                    for pen in right_pens:
                        pen_id, pen_code, side, sess_id, sow_id, start_time, threshold, sess_status, due_date, last_birth_time = pen
                        render_pen_box(pen_code, sess_status, sow_id, due_date, last_birth_time, start_time, threshold)
                        if st.button("เข้าคอกนี้", key=f"enter_{pen_id}", use_container_width=True):
                            st.session_state.fm_view = "monitor"
                            st.session_state.fm_pen_id = pen_id
                            st.rerun()

                st.markdown(
                    "<div style='text-align:center; border-top:1px solid #ccc; padding-top:8px; "
                    "margin-top:12px; font-weight:600;'>ท้ายโรงเรือน</div>",
                    unsafe_allow_html=True,
                )

            # ---- sound alert for pens that just became overdue ----
            # (the banner itself is shown at the top of the page already;
            # this just handles the beep, using the same list computed there.
            # Works while this tab is open in the browser — see chat notes on
            # why a locked/closed phone screen can't be reached this way)
            if "alerted_sessions" not in st.session_state:
                st.session_state.alerted_sessions = set()

            current_overdue = {sid for sid, _code in overdue_session_ids}
            newly_overdue = current_overdue - st.session_state.alerted_sessions
            # drop sessions that resolved, so a *future* overdue episode can alert again
            st.session_state.alerted_sessions &= current_overdue
            st.session_state.alerted_sessions |= current_overdue

            if newly_overdue:
                components.html(
                    """
                    <script>
                      try {
                        const ctx = new (window.AudioContext || window.webkitAudioContext)();
                        const beepOnce = (delay) => setTimeout(() => {
                          const osc = ctx.createOscillator();
                          const gain = ctx.createGain();
                          osc.connect(gain); gain.connect(ctx.destination);
                          osc.frequency.value = 880;
                          gain.gain.setValueAtTime(0.15, ctx.currentTime);
                          osc.start();
                          osc.stop(ctx.currentTime + 0.35);
                        }, delay);
                        // three short beeps so it's noticeable even if missed the first time
                        beepOnce(0); beepOnce(500); beepOnce(1000);
                      } catch (e) {}
                    </script>
                    """,
                    height=0,
                )

    # ---------------- MONITOR VIEW ----------------
    else:
        pen_id = st.session_state.fm_pen_id
        pen_row = conn.execute("SELECT pen_code FROM pens WHERE id=?", (pen_id,)).fetchone()

        if pen_row is None:
            st.warning("ไม่พบคอกนี้ในระบบแล้ว")
            st.session_state.fm_view = "layout"
            st.rerun()

        pen_code = pen_row[0]

        if st.button("⬅️ กลับไปหน้าผังคอก"):
            st.session_state.fm_view = "layout"
            st.rerun()

        active = conn.execute(
            "SELECT id, sow_id, sire_id, breed, sire_breed, parity, start_time, alert_threshold_min, status, due_date "
            "FROM farrowing_sessions WHERE pen_id=? AND status != 'vacated' "
            "ORDER BY id DESC LIMIT 1",
            (pen_id,),
        ).fetchone()

        st.subheader(f"📍 {pen_code}")

        # ---------- pen is empty: start form (with backfill-friendly status choice) ----------
        if active is None:
            st.info("คอกนี้ว่าง — เริ่มบันทึกได้เลย")

            col1, col2 = st.columns(2)
            with col1:
                sow_id = st.text_input("หมายเลขแม่สุกร (Sow ID) *", key="new_sow_id")
            with col2:
                sire_id = st.text_input("หมายเลข/ชื่อพ่อพันธุ์ (Sire ID)", key="new_sire_id")

            col3, col4, col5 = st.columns(3)
            with col3:
                breed = st.text_input("สายพันธุ์แม่", key="new_breed")
            with col4:
                sire_breed = st.text_input("สายพันธุ์พ่อ", key="new_sire_breed")
            with col5:
                parity = st.number_input("ท้องที่ (parity)", min_value=0, step=1, key="new_parity")

            st.markdown("**สถานะเริ่มต้น** — เผื่อกรณีแม่คลอดไปแล้วแต่เพิ่งมากรอกข้อมูลทีหลัง")
            # Kept outside any st.form so the fields below react immediately
            # when the status changes, instead of only updating after submit.
            initial_status = st.selectbox(
                "เลือกสถานะ", SESSION_STATUS_OPTS,
                format_func=lambda x: SESSION_STATUS_LABELS[x], index=0,
                key="new_initial_status",
            )

            due_date_val = None
            start_time_val = None

            if initial_status == "waiting":
                st.caption("แม่ยังไม่คลอด แค่เข้าคอกมารอ — กรอกแค่วันที่ก็พอ ไม่ต้องระบุเวลา")
                start_date = st.date_input(
                    "วันที่เริ่มรอคลอด", value=datetime.now(THAI_TZ).date(), key="new_wait_date",
                )
                st.caption("ตั้งวันครบกำหนดคลอด — ถ้าเลยวันนี้แล้วยังไม่คลอด ระบบจะขึ้นเตือนที่ผังคอก")
                due_date_val = st.date_input(
                    "วันที่ควรคลอด (กำหนดคลอด)",
                    value=datetime.now(THAI_TZ).date() + timedelta(days=3),
                    key="new_due_date",
                )
            else:
                st.caption("ระบุเวลาที่แม่เริ่มคลอดจริง ถ้าไม่ทราบให้ปล่อยเป็นเวลาปัจจุบัน")
                tcol1, tcol2 = st.columns(2)
                with tcol1:
                    start_date = st.date_input("วันที่เริ่มคลอด", value=datetime.now(THAI_TZ).date(), key="new_start_date")
                with tcol2:
                    start_time_val = st.time_input("เวลาที่เริ่มคลอด", value=datetime.now(THAI_TZ).time(), key="new_start_time")

            threshold = st.slider(
                "ตั้งเกณฑ์เตือน — ถ้าไม่มีลูกคลอดภายในกี่นาที ให้แจ้งเตือน (ใช้ตอนคลอดจริง)",
                min_value=15, max_value=60, value=30, step=5, key="new_threshold",
            )

            if st.button("▶️ บันทึก", type="primary", use_container_width=True, key="new_submit"):
                if not sow_id.strip():
                    st.error("กรุณากรอกหมายเลขแม่สุกร")
                else:
                    if start_time_val is not None:
                        actual_start = parse_datetime_or_now(start_date, start_time_val)
                    else:
                        # waiting mode: date only, time isn't meaningful yet
                        actual_start = datetime.combine(
                            start_date, datetime.min.time(), tzinfo=THAI_TZ
                        ).isoformat(timespec="seconds")
                    due_date_str = due_date_val.isoformat() if due_date_val else None
                    conn.execute(
                        "INSERT INTO farrowing_sessions "
                        "(sow_id, sire_id, breed, sire_breed, parity, start_time, due_date, "
                        "alert_threshold_min, status, pen_id) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (sow_id.strip(), sire_id.strip(), breed.strip(), sire_breed.strip(), int(parity),
                         actual_start, due_date_str, int(threshold), initial_status, pen_id),
                    )
                    conn.commit()
                    st.rerun()

        # ---------- pen occupied: monitor / edit ----------
        else:
            session_id, sow_id, sire_id, breed, sire_breed, parity, start_time, threshold_min, sess_status, due_date = active
            piglets = get_piglets(conn, session_id)

            st.markdown(
                f"**แม่สุกร: {sow_id}**"
                + (f"  ·  พ่อพันธุ์: {sire_id}" if sire_id else "")
                + (f"  ·  สายพันธุ์แม่: {breed}" if breed else "")
                + (f"  ·  สายพันธุ์พ่อ: {sire_breed}" if sire_breed else "")
            )
            st.caption(f"เริ่มเฝ้าคลอดเวลา {fmt_datetime(start_time)}  ·  ท้องที่ {parity}")

            # ---- quick-edit: fix a wrong date/name right here, no need to hunt through History ----
            edit_toggle_key = f"monitor_edit_{session_id}"
            if edit_toggle_key not in st.session_state:
                st.session_state[edit_toggle_key] = False

            if st.button("✏️ แก้ไขข้อมูล (แม่ / พ่อ / วันที่ / เกณฑ์)", key=f"monitor_edit_btn_{session_id}"):
                st.session_state[edit_toggle_key] = not st.session_state[edit_toggle_key]
                st.rerun()

            if st.session_state[edit_toggle_key]:
                with st.form(f"monitor_edit_form_{session_id}"):
                    ec1, ec2 = st.columns(2)
                    with ec1:
                        edit_sow = st.text_input("หมายเลขแม่สุกร", value=sow_id)
                    with ec2:
                        edit_sire = st.text_input("หมายเลข/ชื่อพ่อพันธุ์", value=sire_id or "")

                    ec3, ec4, ec5 = st.columns(3)
                    with ec3:
                        edit_breed = st.text_input("สายพันธุ์แม่", value=breed or "")
                    with ec4:
                        edit_sire_breed = st.text_input("สายพันธุ์พ่อ", value=sire_breed or "")
                    with ec5:
                        edit_parity = st.number_input("ท้องที่", min_value=0, step=1, value=parity or 0)

                    current_start_dt = parse_iso(start_time)
                    edit_due = None
                    edit_start_time_val = None
                    if sess_status == "waiting":
                        edit_start_date = st.date_input("วันที่เริ่มรอคลอด", value=current_start_dt.date())
                        existing_due = datetime.fromisoformat(due_date).date() if due_date else current_start_dt.date() + timedelta(days=3)
                        edit_due = st.date_input("วันที่ควรคลอด (กำหนดคลอด)", value=existing_due)
                    else:
                        stc1, stc2 = st.columns(2)
                        with stc1:
                            edit_start_date = st.date_input("วันที่เริ่มคลอด", value=current_start_dt.date())
                        with stc2:
                            edit_start_time_val = st.time_input("เวลาที่เริ่มคลอด", value=current_start_dt.time())

                    edit_threshold_new = st.slider(
                        "เกณฑ์เตือน (นาที)", min_value=15, max_value=60,
                        value=threshold_min or 30, step=5,
                    )

                    save_c, cancel_c = st.columns(2)
                    save_clicked = save_c.form_submit_button("💾 บันทึกการแก้ไข", use_container_width=True)
                    cancel_clicked = cancel_c.form_submit_button("ยกเลิก", use_container_width=True)

                    if save_clicked:
                        if not edit_sow.strip():
                            st.error("กรุณากรอกหมายเลขแม่สุกร")
                        else:
                            if edit_start_time_val is not None:
                                new_start_iso = parse_datetime_or_now(edit_start_date, edit_start_time_val)
                            else:
                                new_start_iso = datetime.combine(
                                    edit_start_date, datetime.min.time(), tzinfo=THAI_TZ
                                ).isoformat(timespec="seconds")
                            new_due_str = edit_due.isoformat() if edit_due else None
                            conn.execute(
                                "UPDATE farrowing_sessions SET sow_id=?, sire_id=?, breed=?, sire_breed=?, "
                                "parity=?, start_time=?, due_date=?, alert_threshold_min=? WHERE id=?",
                                (edit_sow.strip(), edit_sire.strip(), edit_breed.strip(), edit_sire_breed.strip(),
                                 int(edit_parity), new_start_iso, new_due_str, int(edit_threshold_new), session_id),
                            )
                            conn.commit()
                            renumber_and_recalc(conn, session_id, new_start_iso)
                            st.session_state[edit_toggle_key] = False
                            st.success("บันทึกการแก้ไขแล้ว")
                            st.rerun()
                    if cancel_clicked:
                        st.session_state[edit_toggle_key] = False
                        st.rerun()

            st.divider()

            status_col1, status_col2 = st.columns([2, 1])
            with status_col1:
                st.markdown(f"**สถานะปัจจุบัน:** {SESSION_STATUS_LABELS.get(sess_status, sess_status)}")
            with status_col2:
                new_status_pick = st.selectbox(
                    "เปลี่ยนสถานะ", SESSION_STATUS_OPTS,
                    index=SESSION_STATUS_OPTS.index(sess_status) if sess_status in SESSION_STATUS_OPTS else 1,
                    format_func=lambda x: SESSION_STATUS_LABELS[x],
                    key="status_change_pick", label_visibility="collapsed",
                )
                if new_status_pick != sess_status:
                    if st.button("🔄 อัปเดตสถานะ", use_container_width=True):
                        conn.execute(
                            "UPDATE farrowing_sessions SET status=? WHERE id=?",
                            (new_status_pick, session_id),
                        )
                        conn.commit()
                        st.rerun()

            if sess_status == "waiting":
                if due_date:
                    due_dt = datetime.fromisoformat(due_date).date()
                    today = datetime.now(THAI_TZ).date()
                    days_left = (due_dt - today).days
                    if today > due_dt:
                        st.error(f"⚠️ เลยกำหนดคลอดแล้ว {abs(days_left)} วัน (กำหนดคลอด {due_dt.strftime('%d/%m/%Y')}) — ควรตรวจแม่ใกล้ชิด")
                    elif days_left == 0:
                        st.warning(f"📅 วันนี้ถึงกำหนดคลอดพอดี ({due_dt.strftime('%d/%m/%Y')})")
                    else:
                        st.info(f"📅 กำหนดคลอด {due_dt.strftime('%d/%m/%Y')} — อีก {days_left} วัน")
                else:
                    st.caption("ยังไม่ได้ตั้งวันครบกำหนดคลอดไว้")
            elif sess_status == "in_progress":
                last_birth_iso = piglets[-1][2] if piglets else start_time
                render_live_timer(last_birth_iso, threshold_min)
            else:
                # 'completed' — farrowing is done, so there's no "next piglet"
                # to time or alert on anymore.
                st.success("✅ คลอดเสร็จสิ้นแล้ว ไม่มีการจับเวลารอลูกตัวถัดไปอีก")

            col_a, col_b, col_c = st.columns([2, 1, 1])
            with col_a:
                if st.button("🐷 ลูกคลอดแล้ว! (บันทึกเวลาทันที)", type="primary", use_container_width=True):
                    birth_time = now_iso()
                    conn.execute(
                        "INSERT INTO farrowing_piglets (session_id, seq_number, birth_time, status) "
                        "VALUES (?, 0, ?, 'alive')",
                        (session_id, birth_time),
                    )
                    if sess_status == "waiting":
                        conn.execute(
                            "UPDATE farrowing_sessions SET status='in_progress' WHERE id=?", (session_id,)
                        )
                    conn.commit()
                    renumber_and_recalc(conn, session_id, start_time)
                    st.rerun()
            with col_b:
                st.metric("จำนวนลูกที่คลอดแล้ว", len(piglets))
            with col_c:
                if st.button("🏁 บันทึกว่าคลอดเสร็จแล้ว", use_container_width=True):
                    conn.execute(
                        "UPDATE farrowing_sessions SET status='completed', end_time=? WHERE id=?",
                        (now_iso(), session_id),
                    )
                    conn.commit()
                    st.rerun()

            if st.button("🚪 ย้ายแม่ออกจากคอก (ล้างคอกให้ว่างสำหรับตัวถัดไป)", use_container_width=True):
                conn.execute(
                    "UPDATE farrowing_sessions SET status='vacated' WHERE id=?", (session_id,)
                )
                conn.commit()
                st.session_state.fm_view = "layout"
                st.rerun()

            st.divider()
            st.markdown("#### รายละเอียดลูกแต่ละตัว (กรอกภายหลังได้)")

            if not piglets:
                st.caption("ยังไม่มีลูกคลอด — กดปุ่มด้านบนทันทีที่ลูกตัวแรกออกมา")
            else:
                for p in piglets:
                    p_id, seq, birth_time_p, interval, sex, weight, status, assisted, notes, mummy_len = p
                    show_interval = seq > 1 and interval is not None
                    flag = "⚠️ " if show_interval and interval > threshold_min else ""
                    with st.expander(
                        f"{flag}ตัวที่ {seq} — {fmt_time(birth_time_p)}"
                        + (f"  (ห่างจากตัวก่อนหน้า {interval:.1f} นาที)" if show_interval else "")
                    ):
                        ec1, ec2, ec3 = st.columns(3)
                        with ec1:
                            new_sex = st.selectbox(
                                "เพศ", ["ไม่ระบุ", "ผู้", "เมีย"],
                                index=["ไม่ระบุ", "ผู้", "เมีย"].index(sex) if sex in ["ผู้", "เมีย"] else 0,
                                key=f"sex_{p_id}",
                            )
                        with ec2:
                            new_weight = st.number_input(
                                "น้ำหนักแรกคลอด (kg)", min_value=0.0, step=0.05,
                                value=float(weight) if weight else 0.0, key=f"w_{p_id}",
                            )
                        with ec3:
                            new_status = st.selectbox(
                                "สถานะ", PIGLET_STATUS_OPTS,
                                index=PIGLET_STATUS_OPTS.index(status) if status in PIGLET_STATUS_OPTS else 0,
                                format_func=lambda x: PIGLET_STATUS_LABELS[x],
                                key=f"st_{p_id}",
                            )

                        new_mummy_len = mummy_len
                        if new_status == "mummy":
                            new_mummy_len = st.number_input(
                                "ความยาวมัมมี่ (cm)", min_value=0.0, step=0.5,
                                value=float(mummy_len) if mummy_len else 0.0, key=f"mlen_{p_id}",
                            )

                        new_assisted = st.checkbox("ต้องช่วยคลอด (assisted)", value=bool(assisted), key=f"as_{p_id}")
                        new_notes = st.text_input("บันทึกเพิ่มเติม", value=notes or "", key=f"n_{p_id}")

                        bcol1, bcol2 = st.columns(2)
                        with bcol1:
                            if st.button("💾 บันทึก", key=f"save_{p_id}", use_container_width=True):
                                conn.execute(
                                    "UPDATE farrowing_piglets SET sex=?, weight_kg=?, status=?, assisted=?, "
                                    "notes=?, mummy_length_cm=? WHERE id=?",
                                    (new_sex, new_weight, new_status, int(new_assisted), new_notes,
                                     new_mummy_len if new_status == "mummy" else None, p_id),
                                )
                                conn.commit()
                                st.success("บันทึกแล้ว")
                                st.rerun()
                        with bcol2:
                            if st.button("🗑️ ลบตัวนี้ (บันทึกผิด/กดซ้ำ)", key=f"delpig_{p_id}", use_container_width=True):
                                conn.execute("DELETE FROM farrowing_piglets WHERE id=?", (p_id,))
                                conn.commit()
                                renumber_and_recalc(conn, session_id, start_time)
                                st.rerun()

# =====================================================================
# TAB: HISTORY
# =====================================================================
with tab_history:
    st.markdown("### ประวัติการเฝ้าคลอดทั้งหมด")
    sessions = conn.execute(
        "SELECT s.id, s.sow_id, s.sire_id, s.breed, s.sire_breed, s.parity, s.start_time, s.end_time, s.status, "
        "s.alert_threshold_min, s.pen_id, p.pen_code, s.due_date "
        "FROM farrowing_sessions s LEFT JOIN pens p ON p.id = s.pen_id "
        "ORDER BY s.id DESC"
    ).fetchall()

    if not sessions:
        st.caption("ยังไม่มีประวัติการคลอด")
    else:
        summary_rows = [build_session_summary_row(conn, s) for s in sessions]
        st.download_button(
            "📥 ดาวน์โหลดสรุปการเฝ้าคลอดทั้งหมด (CSV)",
            data=build_csv_bytes(summary_rows),
            file_name=f"farrowing_summary_{datetime.now(THAI_TZ).strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            use_container_width=True,
        )
        st.caption("สรุป 1 แถวต่อ 1 รอบคลอด — จำนวนลูก มีชีวิต/ตาย/มัมมี่ เพศ น้ำหนักเฉลี่ย และระยะห่างระหว่างตัว")
        st.divider()

        all_pens = conn.execute("SELECT id, pen_code FROM pens ORDER BY side, sort_order").fetchall()
        all_session_ids = [s[0] for s in sessions]

        # ---- select all / clear / bulk delete controls ----
        sel_col1, sel_col2, sel_col3 = st.columns([1.3, 1.3, 3])
        with sel_col1:
            if st.button("☑️ เลือกทั้งหมด", use_container_width=True):
                for sid_ in all_session_ids:
                    st.session_state[f"hist_chk_{sid_}"] = True
                st.rerun()
        with sel_col2:
            if st.button("⬜ ยกเลิกการเลือก", use_container_width=True):
                for sid_ in all_session_ids:
                    st.session_state[f"hist_chk_{sid_}"] = False
                st.rerun()

        selected_ids = [sid_ for sid_ in all_session_ids if st.session_state.get(f"hist_chk_{sid_}", False)]
        with sel_col3:
            st.write(f"เลือกอยู่ {len(selected_ids)} รายการ")

        if selected_ids:
            bulk_confirm_key = "hist_confirm_bulk_delete"
            if bulk_confirm_key not in st.session_state:
                st.session_state[bulk_confirm_key] = False

            if not st.session_state[bulk_confirm_key]:
                if st.button(f"🗑️ ลบรายการที่เลือกทั้งหมด ({len(selected_ids)} รายการ)", type="primary"):
                    st.session_state[bulk_confirm_key] = True
                    st.rerun()
            else:
                st.warning(f"⚠️ ยืนยันลบ {len(selected_ids)} รายการที่เลือกไว้ (ลบถาวร ย้อนกลับไม่ได้)")
                bc1, bc2 = st.columns(2)
                if bc1.button("✅ ยืนยันลบทั้งหมด", use_container_width=True):
                    for sid_ in selected_ids:
                        conn.execute("DELETE FROM farrowing_piglets WHERE session_id=?", (sid_,))
                        conn.execute("DELETE FROM farrowing_sessions WHERE id=?", (sid_,))
                        st.session_state[f"hist_chk_{sid_}"] = False
                    conn.commit()
                    st.session_state[bulk_confirm_key] = False
                    st.rerun()
                if bc2.button("ยกเลิก", use_container_width=True):
                    st.session_state[bulk_confirm_key] = False
                    st.rerun()

        st.divider()

        for s in sessions:
            sid, sow_id, sire_id, breed, sire_breed, parity, start_time, end_time, status, threshold_min, pen_id, pen_code, due_date = s
            piglets = get_piglets(conn, sid)
            n_total = len(piglets)
            n_alive = sum(1 for p in piglets if p[6] == "alive")
            n_still = sum(1 for p in piglets if p[6] == "stillborn")
            n_mummy = sum(1 for p in piglets if p[6] == "mummy")
            intervals = [p[3] for p in piglets if p[1] > 1 and p[3] is not None]
            avg_int = sum(intervals) / len(intervals) if intervals else 0
            max_int = max(intervals) if intervals else 0
            status_badge = "✅ " + SESSION_STATUS_LABELS.get(status, status)
            pen_label = pen_code or "(ไม่ระบุคอก)"
            sire_label = f" · พ่อ: {sire_id}" if sire_id else ""

            chk_col, exp_col = st.columns([0.05, 0.95])
            with chk_col:
                st.checkbox("เลือก", key=f"hist_chk_{sid}", label_visibility="collapsed")

            with exp_col.expander(
                f"{status_badge}  ·  {pen_label}  ·  แม่: {sow_id}{sire_label}  ·  "
                f"{fmt_datetime(start_time)}  ·  ลูกทั้งหมด {n_total} ตัว"
            ):
                c1, c2, c3, c4, c5, c6 = st.columns(6)
                c1.metric("ทั้งหมด", n_total)
                c2.metric("มีชีวิต", n_alive)
                c3.metric("ตายคลอด", n_still)
                c4.metric("มัมมี่", n_mummy)
                c5.metric("ระยะเฉลี่ย (นาที)", f"{avg_int:.1f}")
                c6.metric("ระยะสูงสุด (นาที)", f"{max_int:.1f}")

                breed_bits = []
                if breed:
                    breed_bits.append(f"สายพันธุ์แม่: {breed}")
                if sire_breed:
                    breed_bits.append(f"สายพันธุ์พ่อ: {sire_breed}")
                if breed_bits:
                    st.caption("  ·  ".join(breed_bits))

                if piglets:
                    st.markdown("**รายละเอียดแต่ละตัว**")
                    table_rows = []
                    for p in piglets:
                        p_id, seq, birth_time_p, interval, sex, weight, pstatus, assisted, notes, mummy_len = p
                        table_rows.append({
                            "ลำดับ": seq,
                            "แม่": sow_id or "-",
                            "พ่อ": sire_id or "-",
                            "คอก": pen_label,
                            "เวลาคลอด": fmt_datetime(birth_time_p),
                            "ระยะห่าง (นาที)": round(interval, 1) if (seq > 1 and interval is not None) else "-",
                            "เพศ": sex or "-",
                            "น้ำหนัก (kg)": weight or "-",
                            "สถานะ": PIGLET_STATUS_LABELS.get(pstatus, pstatus or "-"),
                            "ความยาวมัมมี่ (cm)": mummy_len if mummy_len else "-",
                            "ช่วยคลอด": "✅" if assisted else "",
                        })
                    st.dataframe(table_rows, use_container_width=True, hide_index=True)

                st.divider()
                bcol1, bcol2, bcol3 = st.columns(3)

                # ---- Edit toggle ----
                edit_key = f"edit_mode_{sid}"
                if edit_key not in st.session_state:
                    st.session_state[edit_key] = False

                with bcol1:
                    if st.button("✏️ แก้ไขข้อมูลรอบนี้", key=f"edit_btn_{sid}", use_container_width=True):
                        st.session_state[edit_key] = not st.session_state[edit_key]
                        st.rerun()

                with bcol2:
                    if status in ("completed", "vacated"):
                        if st.button("↩️ เปิดรอบอีกครั้ง (ยกเลิกการจบ)", key=f"reopen_{sid}", use_container_width=True):
                            if pen_occupied_by_other_session(conn, pen_id, sid):
                                st.error(
                                    f"เปิดรอบนี้คืนไม่ได้ — ตอนนี้ {pen_label} มีรอบคลอดอื่นที่กำลังใช้งานอยู่แล้ว "
                                    "(อาจมีแม่ตัวใหม่เข้าคอกนี้ไปแล้ว) กรุณาย้ายรอบนั้นออกก่อน หรือแก้ไขคอกของรอบนี้ให้เป็นคอกอื่น"
                                )
                            else:
                                conn.execute(
                                    "UPDATE farrowing_sessions SET status='in_progress', end_time=NULL WHERE id=?",
                                    (sid,),
                                )
                                conn.commit()
                                st.rerun()
                    else:
                        st.caption("รอบนี้กำลังดำเนินอยู่ — แก้ไขต่อได้ที่หน้าคอก")

                # ---- Delete with confirm ----
                confirm_key = f"confirm_del_{sid}"
                if confirm_key not in st.session_state:
                    st.session_state[confirm_key] = False

                with bcol3:
                    if not st.session_state[confirm_key]:
                        if st.button("🗑️ ลบข้อมูลรอบนี้", key=f"del_btn_{sid}", use_container_width=True):
                            st.session_state[confirm_key] = True
                            st.rerun()

                if st.session_state[confirm_key]:
                    st.warning(f"⚠️ ยืนยันลบข้อมูลรอบคลอดของ {sow_id} ทั้งหมด (ลบถาวร ย้อนกลับไม่ได้)")
                    cc1, cc2 = st.columns(2)
                    if cc1.button("✅ ยืนยันลบ", key=f"confirm_yes_{sid}", use_container_width=True):
                        conn.execute("DELETE FROM farrowing_piglets WHERE session_id=?", (sid,))
                        conn.execute("DELETE FROM farrowing_sessions WHERE id=?", (sid,))
                        conn.commit()
                        st.session_state[confirm_key] = False
                        st.rerun()
                    if cc2.button("ยกเลิก", key=f"confirm_no_{sid}", use_container_width=True):
                        st.session_state[confirm_key] = False
                        st.rerun()

                # ---- Edit form ----
                if st.session_state[edit_key]:
                    st.markdown("**แก้ไขข้อมูลรอบนี้**")
                    with st.form(f"edit_form_{sid}"):
                        e1, e2 = st.columns(2)
                        with e1:
                            edit_sow = st.text_input("หมายเลขแม่สุกร", value=sow_id)
                        with e2:
                            edit_sire = st.text_input("หมายเลข/ชื่อพ่อพันธุ์", value=sire_id or "")

                        e3, e4, e5 = st.columns(3)
                        with e3:
                            edit_breed = st.text_input("สายพันธุ์แม่", value=breed or "")
                        with e4:
                            edit_sire_breed = st.text_input("สายพันธุ์พ่อ", value=sire_breed or "")
                        with e5:
                            edit_parity = st.number_input("ท้องที่", min_value=0, step=1, value=parity or 0)

                        pen_options = [p[0] for p in all_pens]
                        pen_labels_map = {p[0]: p[1] for p in all_pens}
                        current_idx = pen_options.index(pen_id) if pen_id in pen_options else 0
                        edit_pen_id = st.selectbox(
                            "คอก", pen_options,
                            index=current_idx if pen_options else 0,
                            format_func=lambda x: pen_labels_map.get(x, "?"),
                        ) if pen_options else None

                        edit_status = st.selectbox(
                            "สถานะ", SESSION_STATUS_OPTS + ["vacated"],
                            index=(SESSION_STATUS_OPTS + ["vacated"]).index(status)
                            if status in SESSION_STATUS_OPTS + ["vacated"] else 0,
                            format_func=lambda x: SESSION_STATUS_LABELS[x],
                        )

                        existing_due = datetime.fromisoformat(due_date).date() if due_date else None
                        edit_due_date = st.date_input(
                            "วันที่ควรคลอด (กำหนดคลอด) — ใช้ตอนสถานะแม่รอคลอด",
                            value=existing_due,
                        )

                        edit_threshold = st.slider(
                            "เกณฑ์เตือน (นาที)", min_value=15, max_value=60,
                            value=threshold_min or 30, step=5,
                        )

                        save_col, cancel_col = st.columns(2)
                        save_clicked = save_col.form_submit_button("💾 บันทึกการแก้ไข", use_container_width=True)
                        cancel_clicked = cancel_col.form_submit_button("ยกเลิก", use_container_width=True)

                        if save_clicked:
                            conflict = (
                                edit_status != "vacated"
                                and pen_occupied_by_other_session(conn, edit_pen_id, sid)
                            )
                            if conflict:
                                st.error(
                                    f"บันทึกไม่ได้ — {pen_labels_map.get(edit_pen_id, '?')} "
                                    "มีรอบคลอดอื่นที่กำลังใช้งานอยู่แล้ว เลือกคอกอื่น หรือตั้งสถานะรอบนี้เป็น "
                                    "'ย้ายออกแล้ว' ก่อน"
                                )
                            else:
                                edit_due_date_str = edit_due_date.isoformat() if edit_due_date else None
                                conn.execute(
                                    "UPDATE farrowing_sessions SET sow_id=?, sire_id=?, breed=?, sire_breed=?, "
                                    "parity=?, pen_id=?, alert_threshold_min=?, status=?, due_date=? WHERE id=?",
                                    (edit_sow.strip(), edit_sire.strip(), edit_breed.strip(), edit_sire_breed.strip(),
                                     int(edit_parity), edit_pen_id, int(edit_threshold), edit_status,
                                     edit_due_date_str, sid),
                                )
                                conn.commit()
                                st.session_state[edit_key] = False
                                st.success("บันทึกการแก้ไขแล้ว")
                                st.rerun()
                        if cancel_clicked:
                            st.session_state[edit_key] = False
                            st.rerun()

conn.close()
