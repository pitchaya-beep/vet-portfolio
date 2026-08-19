"""
หน้า: Serology Interpretation Guide
เลือกโรคที่ต้องการดูผลตรวจภูมิคุ้มกัน แล้วแสดง titer/cutoff ที่ใช้แปลผล
ข้อมูลอ้างอิงจาก WOAH Terrestrial Manual และงานวิจัยที่ตรวจสอบแล้ว (ดูคอลัมน์ reference)
"""

import streamlit as st
import pandas as pd
import os

st.set_page_config(page_title="Serology Interpretation - Swine", page_icon="🧪", layout="wide")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "..", "serology_data.csv")


@st.cache_data
def load_serology():
    return pd.read_csv(CSV_PATH)


sero_df = load_serology()

st.title("🧪 Serology Interpretation Guide")
st.caption("แนวทางแปลผลระดับภูมิคุ้มกันฟาร์มสุกร (herd immunity profile) จากผลตรวจทางห้องปฏิบัติการ")

st.info(
    "⚠️ **ข้อควรทราบก่อนใช้งาน:** ค่า titer/cutoff ด้านล่างเป็นค่าที่ใช้กันแพร่หลายในเอกสารวิชาการ "
    "แต่ **ค่าที่แท้จริงอาจแตกต่างกันตามชุดตรวจ (test kit) ของแต่ละบริษัทและห้องแล็บ** "
    "ควรตรวจสอบ insert/manual ของชุดตรวจที่ใช้จริงเสมอ ก่อนนำไปตัดสินใจเชิงคลินิก"
)

disease_choice = st.selectbox("เลือกโรคที่ต้องการแปลผล", sero_df["disease"].tolist())

row = sero_df[sero_df["disease"] == disease_choice].iloc[0]

st.subheader(f"📌 {row['disease']}")

col1, col2 = st.columns(2)
with col1:
    st.markdown("**🔬 วิธีตรวจ (Test Method)**")
    st.write(row["test_method"])

    st.markdown("**✅ เกณฑ์ titer ที่ถือว่าป้องกันได้ / ผล Positive**")
    st.write(row["protective_or_positive_cutoff"])

with col2:
    st.markdown("**🦠 ตัวบ่งชี้การติดเชื้อ (Infection indicator)**")
    st.write(row["infection_indicator"])

    st.markdown("**📝 หมายเหตุเพิ่มเติมสำหรับแปลผลระดับฝูง**")
    st.write(row["notes"])

st.caption(f"อ้างอิง: {row['reference']}")

st.divider()

# ----------------------------
# ตารางเทียบทุกโรคในหน้าเดียว (สำหรับดูภาพรวมฟาร์ม)
# ----------------------------
st.subheader("📊 ตารางสรุปทุกโรค (สำหรับใช้เทียบภาพรวมฝูง)")
display_df = sero_df.rename(columns={
    "disease": "โรค",
    "test_method": "วิธีตรวจ",
    "protective_or_positive_cutoff": "เกณฑ์ titer/cutoff",
    "infection_indicator": "ตัวบ่งชี้การติดเชื้อ",
})[["โรค", "วิธีตรวจ", "เกณฑ์ titer/cutoff", "ตัวบ่งชี้การติดเชื้อ"]]

st.dataframe(display_df, use_container_width=True, hide_index=True)

st.divider()
st.caption(
    "ฐานข้อมูลในไฟล์ serology_data.csv สามารถเพิ่มโรคใหม่หรือปรับค่า titer ให้ตรงกับชุดตรวจที่ฟาร์มใช้จริงได้ "
    "โดยไม่ต้องแก้โค้ด — แค่เพิ่มแถวใหม่ในไฟล์ CSV"
)
