"""
Database Viewer — ดูข้อมูลดิบของทุกหน้าในเว็บนี้ผ่านเบราว์เซอร์เดียว
ไม่ต้องเปิดโค้ดหรือโปรแกรมภายนอกเพื่อดูว่าแต่ละหน้าดึงข้อมูลจากไหน

สแกนหาไฟล์ .db / .sqlite (เช่นฐานข้อมูลของ Diagnosis Support และ Farrowing Monitor)
และไฟล์ .csv (เช่น diseases.csv ของ Diagnosis Support, serology_data.csv ของ
Serology Interpretation) ในโปรเจกต์อัตโนมัติ แล้วแสดงเป็นตารางเดียวกัน
"""

import streamlit as st
import sqlite3
import pandas as pd
import os
import csv as csv_module

st.set_page_config(page_title="Database Viewer", page_icon="🗄️", layout="wide")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IGNORE_DIRS = {".git", "venv", ".venv", "__pycache__", "node_modules", ".streamlit"}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def find_data_files(root):
    db_files, csv_files = [], []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            if fn.endswith((".db", ".sqlite", ".sqlite3")):
                db_files.append(rel)
            elif fn.endswith(".csv"):
                csv_files.append(rel)
    return sorted(db_files), sorted(csv_files)


def get_tables(db_path):
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_schema(db_path, table):
    conn = sqlite3.connect(db_path)
    schema = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    conn.close()
    return pd.DataFrame(schema, columns=["ลำดับ", "คอลัมน์", "ชนิดข้อมูล", "ห้ามว่าง", "ค่าเริ่มต้น", "Primary Key"])


def get_table_df(db_path, table):
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(f"SELECT * FROM '{table}'", conn)
    conn.close()
    return df


def read_csv_smart(csv_path):
    """Handles both normal CSVs and ones written with csv.QUOTE_ALL,
    with a couple of common encoding fallbacks."""
    attempts = [
        dict(encoding="utf-8-sig"),
        dict(encoding="utf-8-sig", quoting=csv_module.QUOTE_ALL),
        dict(encoding="utf-8"),
        dict(encoding="tis-620"),  # common legacy Thai encoding fallback
    ]
    last_err = None
    for kwargs in attempts:
        try:
            return pd.read_csv(csv_path, **kwargs)
        except Exception as e:
            last_err = e
    raise last_err


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.title("🗄️ Database Viewer")
st.caption("ดูข้อมูลดิบของทุกหน้าในเว็บนี้ — SQLite และ CSV ทั้งหมด ไม่ต้องเปิดโค้ด")

db_files, csv_files = find_data_files(PROJECT_ROOT)

if not db_files and not csv_files:
    st.warning("ไม่พบไฟล์ฐานข้อมูล (.db) หรือ CSV ในโปรเจกต์นี้เลย")
    st.stop()

# Build one flat list of sources with a type tag so everything is pickable
# from a single dropdown: SQLite dbs first (each still needs a table pick),
# then CSV files (which are themselves already "one table").
source_options = []
for f in db_files:
    source_options.append(("db", f))
for f in csv_files:
    source_options.append(("csv", f))

def label_source(item):
    kind, path = item
    return f"{'🗄️' if kind == 'db' else '📄'} {path}"

selected = st.selectbox("เลือกแหล่งข้อมูล", source_options, format_func=label_source)
kind, rel_path = selected
full_path = os.path.join(PROJECT_ROOT, rel_path)

st.divider()

if kind == "db":
    tables = get_tables(full_path)
    if not tables:
        st.info("ไฟล์นี้ยังไม่มีตารางข้อมูล")
        st.stop()

    selected_table = st.selectbox("เลือกตาราง", tables)
    df = get_table_df(full_path, selected_table)

    m1, m2, m3 = st.columns(3)
    m1.metric("ไฟล์", rel_path)
    m2.metric("ตาราง", selected_table)
    m3.metric("จำนวนแถว", len(df))

    with st.expander("📐 โครงสร้างตาราง (schema)"):
        st.dataframe(get_schema(full_path, selected_table), use_container_width=True, hide_index=True)

    default_name = selected_table

else:
    try:
        df = read_csv_smart(full_path)
    except Exception as e:
        st.error(f"อ่านไฟล์ CSV นี้ไม่ได้: {e}")
        st.stop()

    m1, m2, m3 = st.columns(3)
    m1.metric("ไฟล์", rel_path)
    m2.metric("คอลัมน์", len(df.columns))
    m3.metric("จำนวนแถว", len(df))

    with st.expander("📐 รายชื่อคอลัมน์"):
        st.write(list(df.columns))

    default_name = os.path.splitext(os.path.basename(rel_path))[0]

search = st.text_input("🔍 ค้นหา (ค้นหาข้อความในทุกคอลัมน์)")
if search:
    mask = df.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False)).any(axis=1)
    df_view = df[mask]
else:
    df_view = df

st.dataframe(df_view, use_container_width=True, hide_index=True)

st.download_button(
    "⬇️ ดาวน์โหลดเป็น CSV",
    data=df_view.to_csv(index=False).encode("utf-8-sig"),
    file_name=f"{default_name}.csv",
    mime="text/csv",
)
