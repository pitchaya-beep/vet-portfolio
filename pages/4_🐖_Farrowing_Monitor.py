"""
Farrowing Monitor — บันทึกเวลาคลอดลูกสุกรแบบเรียลไทม์ ผูกกับผังคอก

Flow การใช้งาน:
1. หน้าแรก (แท็บ "หน้าคอก") แสดงผังคอกทั้งหมดเป็นกล่อง — ว่าง / กำลังคลอด
2. คลิกกล่องคอกที่ต้องการ -> เข้าสู่หน้าเฝ้าคลอดของคอกนั้น
3. กดปุ่มเดียว "ลูกคลอดแล้ว" ทันทีที่ลูกออก ระบบ timestamp ให้อัตโนมัติ
   พร้อมนาฬิกาจับเวลาสดที่แจ้งเตือนเมื่อห่างจากตัวก่อนหน้านานผิดปกติ
4. แท็บ "ประวัติ" ดูข้อมูลย้อนหลัง แก้ไข/เปิดรอบใหม่ (เผื่อหลงกดจบ) หรือลบได้
"""

import streamlit as st
import streamlit.components.v1 as components
import sqlite3
import os
from datetime import datetime

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Farrowing Monitor", page_icon="🐖", layout="wide")

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "farrowing.db")

STATUS_OPTS = ["alive", "stillborn", "died_after", "mummy"]
STATUS_LABELS = {
    "alive": "มีชีวิต",
    "stillborn": "ตายคลอด (stillborn)",
    "died_after": "ตายหลังคลอด",
    "mummy": "มัมมี่ (mummified)",
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
    # migrations for anyone who already ran the previous version of this page
    ensure_column(conn, "farrowing_sessions", "pen_id", "INTEGER")
    ensure_column(conn, "farrowing_piglets", "mummy_length_cm", "REAL")
    return conn


def get_pens_with_status(conn):
    return conn.execute("""
        SELECT p.id, p.pen_code, s.id, s.sow_id, s.start_time, s.alert_threshold_min
        FROM pens p
        LEFT JOIN farrowing_sessions s
            ON s.pen_id = p.id AND s.status = 'in_progress'
        ORDER BY p.sort_order, p.id
    """).fetchall()


def get_piglets(conn, session_id):
    return conn.execute(
        "SELECT id, seq_number, birth_time, interval_minutes, sex, weight_kg, "
        "status, assisted, notes, mummy_length_cm "
        "FROM farrowing_piglets WHERE session_id = ? ORDER BY seq_number",
        (session_id,),
    ).fetchall()


def renumber_and_recalc(conn, session_id, session_start_time):
    """Re-sorts piglets by birth time, reassigns seq numbers and recalculates
    intervals. Needed after inserting or deleting a piglet record."""
    rows = conn.execute(
        "SELECT id, birth_time FROM farrowing_piglets WHERE session_id=? ORDER BY birth_time",
        (session_id,),
    ).fetchall()
    prev = datetime.fromisoformat(session_start_time)
    for idx, (pid, bt) in enumerate(rows, start=1):
        bt_dt = datetime.fromisoformat(bt)
        interval = (bt_dt - prev).total_seconds() / 60.0
        conn.execute(
            "UPDATE farrowing_piglets SET seq_number=?, interval_minutes=? WHERE id=?",
            (idx, round(interval, 2), pid),
        )
        prev = bt_dt
    conn.commit()


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


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


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "fm_view" not in st.session_state:
    st.session_state.fm_view = "layout"     # "layout" | "monitor"
if "fm_pen_id" not in st.session_state:
    st.session_state.fm_pen_id = None

conn = get_conn()

st.title("🐖 Farrowing Monitor — เฝ้าคลอดลูกสุกร")
st.caption("เลือกคอกจากผัง แล้วบันทึกเวลาคลอดทันทีด้วยปุ่มเดียว พร้อมแจ้งเตือนเมื่อระยะห่างระหว่างตัวนานผิดปกติ")

tab_live, tab_history = st.tabs(["🏠 หน้าคอก / เฝ้าคลอด", "📜 ประวัติการคลอด"])

# =====================================================================
# TAB: LIVE (pen layout <-> monitor state machine)
# =====================================================================
with tab_live:

    # ---------------- LAYOUT VIEW ----------------
    if st.session_state.fm_view == "layout":
        pens = get_pens_with_status(conn)

        with st.expander("⚙️ จัดการผังคอก"):
            if not pens:
                st.caption("ยังไม่มีคอกในระบบ — สร้างชุดแรกได้เลย")
                n_pens = st.number_input("จำนวนคอกที่ต้องการสร้าง", min_value=1, max_value=200, value=12)
                if st.button("➕ สร้างคอกอัตโนมัติ (คอก 1, คอก 2, ...)"):
                    for i in range(1, int(n_pens) + 1):
                        try:
                            conn.execute(
                                "INSERT INTO pens (pen_code, sort_order) VALUES (?, ?)",
                                (f"คอก {i}", i),
                            )
                        except sqlite3.IntegrityError:
                            pass
                    conn.commit()
                    st.rerun()

            col_add1, col_add2 = st.columns([3, 1])
            with col_add1:
                new_pen_code = st.text_input("เพิ่มคอกใหม่ (ระบุชื่อ/หมายเลข)", key="new_pen_code")
            with col_add2:
                st.write("")
                st.write("")
                if st.button("➕ เพิ่มคอก", use_container_width=True):
                    if new_pen_code.strip():
                        try:
                            max_order = conn.execute("SELECT COALESCE(MAX(sort_order),0) FROM pens").fetchone()[0]
                            conn.execute(
                                "INSERT INTO pens (pen_code, sort_order) VALUES (?, ?)",
                                (new_pen_code.strip(), max_order + 1),
                            )
                            conn.commit()
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("มีชื่อคอกนี้อยู่แล้ว")

            if pens:
                st.markdown("**ลบคอก** (ลบได้เฉพาะคอกที่ไม่มีรอบคลอดกำลังดำเนินอยู่)")
                for pen_id, pen_code, sess_id, sow_id, start_time, threshold in pens:
                    c1, c2 = st.columns([4, 1])
                    c1.write(pen_code + ("  🔴 กำลังใช้งาน" if sess_id else ""))
                    if c2.button("🗑️", key=f"delpen_{pen_id}", disabled=sess_id is not None):
                        conn.execute("DELETE FROM pens WHERE id=?", (pen_id,))
                        conn.commit()
                        st.rerun()

        st.divider()

        if not pens:
            st.info("ยังไม่มีคอกในระบบ — เปิด '⚙️ จัดการผังคอก' ด้านบนเพื่อสร้างผังคอกก่อนเริ่มใช้งาน")
        else:
            st.markdown("#### ผังคอก — คลิกคอกที่ต้องการบันทึกข้อมูล")
            pens_per_row = 4
            for i in range(0, len(pens), pens_per_row):
                chunk = pens[i:i + pens_per_row]
                cols = st.columns(pens_per_row)
                for (pen_id, pen_code, sess_id, sow_id, start_time, threshold), col in zip(chunk, cols):
                    with col:
                        with st.container(border=True):
                            st.markdown(f"**{pen_code}**")
                            if sess_id:
                                st.markdown("🔴 กำลังคลอด")
                                st.caption(f"แม่: {sow_id}")
                                st.caption(f"เริ่ม {start_time.split('T')[1] if 'T' in start_time else start_time}")
                            else:
                                st.markdown("⚪ ว่าง")
                                st.caption(" ")
                            if st.button("เข้าคอกนี้", key=f"enter_{pen_id}", use_container_width=True):
                                st.session_state.fm_view = "monitor"
                                st.session_state.fm_pen_id = pen_id
                                st.rerun()

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
            "SELECT id, sow_id, breed, parity, start_time, alert_threshold_min "
            "FROM farrowing_sessions WHERE pen_id=? AND status='in_progress' LIMIT 1",
            (pen_id,),
        ).fetchone()

        st.subheader(f"📍 {pen_code}")

        if active is None:
            st.info("คอกนี้ว่าง — เริ่มรอบเฝ้าคลอดใหม่ได้เลย")
            with st.form("start_session"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    sow_id = st.text_input("หมายเลขแม่สุกร (Sow ID) *")
                with col2:
                    breed = st.text_input("สายพันธุ์")
                with col3:
                    parity = st.number_input("ท้องที่ (parity)", min_value=0, step=1)
                threshold = st.slider(
                    "ตั้งเกณฑ์เตือน — ถ้าไม่มีลูกคลอดภายในกี่นาที ให้แจ้งเตือน",
                    min_value=15, max_value=60, value=30, step=5,
                )
                submitted = st.form_submit_button("▶️ เริ่มเฝ้าคลอด", type="primary", use_container_width=True)
                if submitted:
                    if not sow_id.strip():
                        st.error("กรุณากรอกหมายเลขแม่สุกร")
                    else:
                        conn.execute(
                            "INSERT INTO farrowing_sessions "
                            "(sow_id, breed, parity, start_time, alert_threshold_min, status, pen_id) "
                            "VALUES (?, ?, ?, ?, ?, 'in_progress', ?)",
                            (sow_id.strip(), breed.strip(), int(parity), now_iso(), int(threshold), pen_id),
                        )
                        conn.commit()
                        st.rerun()

        else:
            session_id, sow_id, breed, parity, start_time, threshold_min = active
            piglets = get_piglets(conn, session_id)

            st.markdown(f"**แม่สุกร: {sow_id}**" + (f"  ·  สายพันธุ์: {breed}" if breed else ""))
            st.caption(f"เริ่มเฝ้าคลอดเวลา {start_time}  ·  ท้องที่ {parity}")

            last_birth_iso = piglets[-1][2] if piglets else start_time
            render_live_timer(last_birth_iso, threshold_min)

            col_a, col_b, col_c = st.columns([2, 1, 1])
            with col_a:
                if st.button("🐷 ลูกคลอดแล้ว! (บันทึกเวลาทันที)", type="primary", use_container_width=True):
                    birth_time = now_iso()
                    conn.execute(
                        "INSERT INTO farrowing_piglets (session_id, seq_number, birth_time, status) "
                        "VALUES (?, 0, ?, 'alive')",
                        (session_id, birth_time),
                    )
                    conn.commit()
                    renumber_and_recalc(conn, session_id, start_time)
                    st.rerun()
            with col_b:
                st.metric("จำนวนลูกที่คลอดแล้ว", len(piglets))
            with col_c:
                if st.button("🏁 จบรอบคลอด", use_container_width=True):
                    conn.execute(
                        "UPDATE farrowing_sessions SET status='completed', end_time=? WHERE id=?",
                        (now_iso(), session_id),
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
                    p_id, seq, birth_time, interval, sex, weight, status, assisted, notes, mummy_len = p
                    flag = "⚠️ " if interval and interval > threshold_min else ""
                    with st.expander(
                        f"{flag}ตัวที่ {seq} — {birth_time.split('T')[1] if 'T' in birth_time else birth_time}"
                        + (f"  (ห่างจากตัวก่อนหน้า {interval:.1f} นาที)" if interval is not None else "")
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
                                "สถานะ", STATUS_OPTS,
                                index=STATUS_OPTS.index(status) if status in STATUS_OPTS else 0,
                                format_func=lambda x: STATUS_LABELS[x],
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
        "SELECT s.id, s.sow_id, s.breed, s.parity, s.start_time, s.end_time, s.status, "
        "s.alert_threshold_min, s.pen_id, p.pen_code "
        "FROM farrowing_sessions s LEFT JOIN pens p ON p.id = s.pen_id "
        "ORDER BY s.id DESC"
    ).fetchall()

    if not sessions:
        st.caption("ยังไม่มีประวัติการคลอด")
    else:
        all_pens = conn.execute("SELECT id, pen_code FROM pens ORDER BY sort_order").fetchall()

        for s in sessions:
            sid, sow_id, breed, parity, start_time, end_time, status, threshold_min, pen_id, pen_code = s
            piglets = get_piglets(conn, sid)
            n_total = len(piglets)
            n_alive = sum(1 for p in piglets if p[6] == "alive")
            n_still = sum(1 for p in piglets if p[6] == "stillborn")
            n_mummy = sum(1 for p in piglets if p[6] == "mummy")
            intervals = [p[3] for p in piglets if p[3] is not None]
            avg_int = sum(intervals) / len(intervals) if intervals else 0
            max_int = max(intervals) if intervals else 0
            status_badge = "🔴 กำลังคลอด" if status == "in_progress" else "✅ จบแล้ว"
            pen_label = pen_code or "(ไม่ระบุคอก)"

            with st.expander(
                f"{status_badge}  ·  {pen_label}  ·  {sow_id}  ·  {start_time}  ·  ลูกทั้งหมด {n_total} ตัว"
            ):
                c1, c2, c3, c4, c5, c6 = st.columns(6)
                c1.metric("ทั้งหมด", n_total)
                c2.metric("มีชีวิต", n_alive)
                c3.metric("ตายคลอด", n_still)
                c4.metric("มัมมี่", n_mummy)
                c5.metric("ระยะเฉลี่ย (นาที)", f"{avg_int:.1f}")
                c6.metric("ระยะสูงสุด (นาที)", f"{max_int:.1f}")

                if piglets:
                    st.markdown("**รายละเอียดแต่ละตัว**")
                    table_rows = []
                    for p in piglets:
                        p_id, seq, birth_time, interval, sex, weight, pstatus, assisted, notes, mummy_len = p
                        table_rows.append({
                            "ลำดับ": seq,
                            "เวลาคลอด": birth_time,
                            "ระยะห่าง (นาที)": round(interval, 1) if interval is not None else "-",
                            "เพศ": sex or "-",
                            "น้ำหนัก (kg)": weight or "-",
                            "สถานะ": STATUS_LABELS.get(pstatus, pstatus or "-"),
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
                    if status == "completed":
                        if st.button("↩️ เปิดรอบอีกครั้ง (ยกเลิกการจบ)", key=f"reopen_{sid}", use_container_width=True):
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
                        e1, e2, e3 = st.columns(3)
                        with e1:
                            edit_sow = st.text_input("หมายเลขแม่สุกร", value=sow_id)
                        with e2:
                            edit_breed = st.text_input("สายพันธุ์", value=breed or "")
                        with e3:
                            edit_parity = st.number_input("ท้องที่", min_value=0, step=1, value=parity or 0)

                        pen_options = [p[0] for p in all_pens]
                        pen_labels_map = {p[0]: p[1] for p in all_pens}
                        current_idx = pen_options.index(pen_id) if pen_id in pen_options else 0
                        edit_pen_id = st.selectbox(
                            "คอก", pen_options,
                            index=current_idx if pen_options else 0,
                            format_func=lambda x: pen_labels_map.get(x, "?"),
                        ) if pen_options else None

                        edit_threshold = st.slider(
                            "เกณฑ์เตือน (นาที)", min_value=15, max_value=60,
                            value=threshold_min or 30, step=5,
                        )

                        save_col, cancel_col = st.columns(2)
                        save_clicked = save_col.form_submit_button("💾 บันทึกการแก้ไข", use_container_width=True)
                        cancel_clicked = cancel_col.form_submit_button("ยกเลิก", use_container_width=True)

                        if save_clicked:
                            conn.execute(
                                "UPDATE farrowing_sessions SET sow_id=?, breed=?, parity=?, pen_id=?, "
                                "alert_threshold_min=? WHERE id=?",
                                (edit_sow.strip(), edit_breed.strip(), int(edit_parity),
                                 edit_pen_id, int(edit_threshold), sid),
                            )
                            conn.commit()
                            st.session_state[edit_key] = False
                            st.success("บันทึกการแก้ไขแล้ว")
                            st.rerun()
                        if cancel_clicked:
                            st.session_state[edit_key] = False
                            st.rerun()

conn.close()
