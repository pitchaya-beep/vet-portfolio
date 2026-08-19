"""
หน้า: Diagnosis Support Tools in Swine
เพิ่มเติมจากเวอร์ชันแรก:
  1) หลังขึ้นผลวิเคราะห์ แสดงคำแนะนำว่าควรเก็บตัวอย่างอะไร ส่งตรวจด้วยวิธีไหน (gold standard)
  2) บันทึกทุกเคสที่วิเคราะห์ลงฐานข้อมูล SQLite (cases.db) เพื่อดูประวัติย้อนหลังได้
"""

import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import os

# ----------------------------
# ตั้งค่าเบื้องต้น
# ----------------------------
st.set_page_config(page_title="Diagnosis Support - Swine", page_icon="🐷", layout="wide")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "..", "diseases.csv")
DB_PATH = os.path.join(BASE_DIR, "..", "cases.db")


# ----------------------------
# 1) โหลดฐานข้อมูลโรค
# ----------------------------
@st.cache_data
def load_diseases():
    df = pd.read_csv(CSV_PATH)
    df["key_symptoms_list"] = df["key_symptoms"].apply(lambda x: [s.strip() for s in str(x).split(";")])
    df["risk_factors_list"] = df["risk_factors"].apply(lambda x: [s.strip() for s in str(x).split(";")])
    return df


diseases_df = load_diseases()
ALL_SYMPTOMS = sorted({s for lst in diseases_df["key_symptoms_list"] for s in lst})
ALL_RISK_FACTORS = sorted({s for lst in diseases_df["risk_factors_list"] for s in lst})
AGE_GROUPS = ["แรกเกิด-7 วัน", "ดูดนม (0-3 สัปดาห์)", "หย่านม-อนุบาล (3-8 สัปดาห์)",
              "รุ่น-ขุน (2-6 เดือน)", "แม่พันธุ์/พ่อพันธุ์", "ทุกช่วงอายุ"]


# ----------------------------
# 2) ตั้งค่าฐานข้อมูล SQLite สำหรับเก็บประวัติเคส
# ----------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            farm_name TEXT,
            age_group TEXT,
            morbidity REAL,
            mortality REAL,
            symptoms TEXT,
            risk_factors TEXT,
            top_disease TEXT,
            top_score REAL
        )
    """)
    conn.commit()
    conn.close()


def save_case(farm_name, age_group, morbidity, mortality, symptoms, risks, top_disease, top_score):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT INTO cases (timestamp, farm_name, age_group, morbidity, mortality,
           symptoms, risk_factors, top_disease, top_score) VALUES (?,?,?,?,?,?,?,?,?)""",
        (datetime.now().strftime("%Y-%m-%d %H:%M"), farm_name, age_group, morbidity, mortality,
         "; ".join(symptoms), "; ".join(risks), top_disease, top_score),
    )
    conn.commit()
    conn.close()


def load_cases():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM cases ORDER BY id DESC", conn)
    conn.close()
    return df


init_db()


# ----------------------------
# 3) ฟังก์ชันคำนวณคะแนน (เหมือนเดิม)
# ----------------------------
def score_disease(row, selected_symptoms, morbidity, mortality, age_group, selected_risks):
    score = 0.0
    max_score = 0.0

    symptom_weight = 3
    max_score += symptom_weight * len(row["key_symptoms_list"])
    matched_symptoms = set(selected_symptoms) & set(row["key_symptoms_list"])
    score += symptom_weight * len(matched_symptoms)

    max_score += 2
    if morbidity is not None and row["morbidity_min"] <= morbidity <= row["morbidity_max"]:
        score += 2

    max_score += 2
    if mortality is not None and row["mortality_min"] <= mortality <= row["mortality_max"]:
        score += 2

    max_score += 2
    age_text = str(row["age_group"]).lower()
    if age_group and (age_group.split()[0].lower() in age_text or "all ages" in age_text):
        score += 2

    risk_weight = 1
    max_score += risk_weight * len(row["risk_factors_list"])
    matched_risks = set(selected_risks) & set(row["risk_factors_list"])
    score += risk_weight * len(matched_risks)

    percent = (score / max_score * 100) if max_score > 0 else 0
    return round(percent, 1), matched_symptoms, matched_risks


# ----------------------------
# 4) หน้าเว็บ
# ----------------------------
st.title("🐷 Diagnosis Support Tools in Swine")
st.caption("ระบบช่วยวินิจฉัยแยกโรคเบื้องต้นในฟาร์มสุกร — rule-based matching จากอาการ, อัตราป่วย-ตาย, อายุ, และปัจจัยเสี่ยง")

tab_analyze, tab_history = st.tabs(["🔍 วิเคราะห์เคสใหม่", "📋 ประวัติเคสย้อนหลัง"])

# ============================================================
# TAB 1: วิเคราะห์เคส
# ============================================================
with tab_analyze:
    with st.form("case_form"):
        st.subheader("1. ข้อมูลฟาร์ม/เคส")
        farm_name = st.text_input("ชื่อฟาร์ม/รหัสเคส (ใส่หรือไม่ใส่ก็ได้)", placeholder="เช่น ฟาร์ม A - เล้า 3")

        col1, col2 = st.columns(2)
        with col1:
            age_group = st.selectbox("ช่วงอายุสุกรที่ป่วย", AGE_GROUPS)
            morbidity = st.slider("อัตราการป่วย (Morbidity %)", 0, 100, 20)
        with col2:
            mortality = st.slider("อัตราการตาย (Mortality %)", 0, 100, 5)

        st.subheader("2. อาการที่พบ (เลือกได้หลายข้อ)")
        selected_symptoms = st.multiselect("อาการ", ALL_SYMPTOMS)

        st.subheader("3. ปัจจัยเสี่ยง/สิ่งแวดล้อม/การจัดการ (ถ้ามี)")
        selected_risks = st.multiselect("ปัจจัยเสี่ยง", ALL_RISK_FACTORS)

        submitted = st.form_submit_button("วิเคราะห์ผล")

    if submitted:
        if not selected_symptoms:
            st.warning("กรุณาเลือกอาการอย่างน้อย 1 ข้อ เพื่อให้ระบบวิเคราะห์ได้แม่นยำขึ้น")
        else:
            results = []
            for _, row in diseases_df.iterrows():
                pct, matched_sym, matched_risk = score_disease(
                    row, selected_symptoms, morbidity, mortality, age_group, selected_risks
                )
                results.append({
                    "โรค": row["disease"],
                    "โอกาส (%)": pct,
                    "อาการที่ตรงกัน": ", ".join(matched_sym) if matched_sym else "-",
                    "คำอธิบาย": row["description"],
                    "อ้างอิง": row["reference"],
                    "sample_type": row.get("sample_type", ""),
                    "gold_standard_test": row.get("gold_standard_test", ""),
                    "other_tests": row.get("other_tests", ""),
                    "notify_authority": row.get("notify_authority", "No"),
                })

            results_df = pd.DataFrame(results).sort_values("โอกาส (%)", ascending=False)
            results_df = results_df[results_df["โอกาส (%)"] > 0].head(5)

            st.subheader("ผลการวิเคราะห์ — เรียงลำดับความน่าจะเป็น (Top 5)")
            if results_df.empty:
                st.info("ไม่พบโรคที่ตรงกับข้อมูลที่กรอก ลองปรับอาการหรือข้อมูลเพิ่มเติม")
            else:
                for _, r in results_df.iterrows():
                    with st.expander(f"🔹 {r['โรค']} — โอกาสประมาณ {r['โอกาส (%)']}%"):
                        st.write(f"**อาการที่ตรงกับเคสนี้:** {r['อาการที่ตรงกัน']}")
                        st.write(f"**คำอธิบาย:** {r['คำอธิบาย']}")

                        if r["notify_authority"] == "Yes":
                            st.error("⚠️ **โรคระบาดสัตว์ที่ต้องแจ้งกรมปศุสัตว์ทันทีตามกฎหมาย** หากสงสัยโรคนี้ "
                                      "ห้ามเคลื่อนย้ายสัตว์ออกจากฟาร์ม และแจ้งเจ้าหน้าที่ปศุสัตว์ในพื้นที่ทันที")

                        st.markdown("**🧪 แนวทางเก็บตัวอย่างและส่งตรวจยืนยัน**")
                        st.write(f"- **ตัวอย่างที่ควรเก็บ:** {r['sample_type']}")
                        st.write(f"- **Gold standard test:** {r['gold_standard_test']}")
                        st.write(f"- **การตรวจเสริม/อื่นๆ:** {r['other_tests']}")

                        st.caption(f"อ้างอิง: {r['อ้างอิง']}")

                # บันทึกเคสลง SQLite อัตโนมัติ
                top = results_df.iloc[0]
                save_case(farm_name, age_group, morbidity, mortality,
                          selected_symptoms, selected_risks, top["โรค"], top["โอกาส (%)"])
                st.success(f"✅ บันทึกเคสนี้ลงประวัติแล้ว (ดูได้ที่แท็บ 'ประวัติเคสย้อนหลัง')")

            st.error("⚠️ ผลลัพธ์นี้เป็นเพียงการคัดกรองเบื้องต้นจากกฎที่ตั้งไว้ล่วงหน้า "
                      "**ไม่ใช่การวินิจฉัยที่แน่ชัด** ต้องยืนยันด้วยประวัติเพิ่มเติม การตรวจร่างกาย "
                      "และการตรวจทางห้องปฏิบัติการเสมอ")

# ============================================================
# TAB 2: ประวัติเคส
# ============================================================
with tab_history:
    st.subheader("ประวัติเคสที่เคยวิเคราะห์")
    history_df = load_cases()

    if history_df.empty:
        st.info("ยังไม่มีประวัติเคส ลองวิเคราะห์เคสแรกที่แท็บ 'วิเคราะห์เคสใหม่'")
    else:
        st.dataframe(
            history_df.rename(columns={
                "timestamp": "วันเวลา", "farm_name": "ฟาร์ม/รหัสเคส", "age_group": "ช่วงอายุ",
                "morbidity": "Morbidity %", "mortality": "Mortality %",
                "top_disease": "โรคที่น่าจะเป็นสูงสุด", "top_score": "โอกาส (%)",
                "symptoms": "อาการ", "risk_factors": "ปัจจัยเสี่ยง"
            })[["วันเวลา", "ฟาร์ม/รหัสเคส", "ช่วงอายุ", "Morbidity %", "Mortality %",
                "โรคที่น่าจะเป็นสูงสุด", "โอกาส (%)", "อาการ", "ปัจจัยเสี่ยง"]],
            use_container_width=True, hide_index=True
        )

        csv_export = history_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇️ ดาวน์โหลดประวัติทั้งหมดเป็น CSV", csv_export, "case_history.csv", "text/csv")

        if st.button("🗑️ ล้างประวัติทั้งหมด", type="secondary"):
            conn = sqlite3.connect(DB_PATH)
            conn.execute("DELETE FROM cases")
            conn.commit()
            conn.close()
            st.rerun()

st.divider()
st.caption("ฐานข้อมูลโรคในไฟล์ diseases.csv สามารถแก้ไข/เพิ่มโรค หรือปรับข้อมูลให้อ้างอิงตามงานวิจัยที่ค้นจาก PubMed/OIE ได้โดยตรง")
