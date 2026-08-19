import streamlit as st

st.set_page_config(page_title="Pitchaya Donsakul | Portfolio", page_icon="🩺", layout="wide")

# ----------------------------
# ส่วนหัว: ชื่อ + ข้อมูลติดต่อ
# ----------------------------
col_photo, col_info = st.columns([1, 3])
with col_photo:
    st.markdown(
        """
        <div style="width:100%;aspect-ratio:1;border-radius:12px;background:#8b1e1e;
        display:flex;align-items:center;justify-content:center;color:white;font-size:48px;">
        🩺
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("แทนที่ไฟล์นี้ด้วยรูปจริงของคุณ — ดูวิธีในหมายเหตุท้ายหน้า")

with col_info:
    st.title("Pitchaya Donsakul")
    st.caption("Nickname: Thoong-na")
    st.write("📞 093-339-5214  |  ✉️ pitchaya.d@kkumail.com")
    st.write("📍 Roi Et, Thailand")

st.divider()

# ----------------------------
# Profile Summary
# ----------------------------
st.subheader("Profile Summary")
st.write(
    "6th-year veterinary student with a solution-oriented approach to problem-solving and a focus on "
    "identifying root causes. Calm, adaptable, and persistent, with experience working effectively under "
    "pressure and coordinating student activities."
)

st.divider()

# ----------------------------
# Education / Achievement (2 คอลัมน์)
# ----------------------------
col_edu, col_ach = st.columns(2)

with col_edu:
    st.subheader("🎓 Education")
    st.markdown(
        """
        **Faculty of Veterinary Medicine, Khon Kaen University**
        6th-year student · GPA 3.62
        """
    )

    st.subheader("🛠️ Technical Skills")
    st.markdown(
        """
        - Microsoft Word (Intermediate)
        - Microsoft PowerPoint (Intermediate)
        - Canva (Intermediate) — graphic & social media design
        - Video editing (Intermediate)
        - Python & Streamlit *(this website!)*
        """
    )

    st.subheader("🗣️ Languages")
    st.markdown("- Thai (Native)\n- English (Intermediate)")

with col_ach:
    st.subheader("🏆 Achievement")
    st.markdown(
        """
        **2025** — Best Oral Presentation Award, Veterinary Research II (VM KKU):
        *"Screening of Selected Thai Herbs for Anti-Classical Swine Fever Virus (CSFV) Activity"*

        **2020** — 1st Runner-up (Gold Medal), Computer Science Poster Presentation —
        12th Upper Northeastern Regional SMTE Academic Conference
        """
    )

    st.subheader("🤝 Soft Skills")
    st.markdown(
        """
        - Approachability & Conflict De-escalation
        - Solution-oriented & proactive
        - Calm & adaptable under pressure
        - Strong leadership & coordination
        """
    )

st.divider()

# ----------------------------
# Experience
# ----------------------------
st.subheader("💼 Experience")

tab1, tab2 = st.tabs(["Internships & Practical Training", "Camps & Student Activities"])

with tab1:
    st.markdown(
        """
        **2025**
        - Swine Farm Intern (Breeder Farm) — Tha Cha Lung Swine Farm, CPF, Nakhon Ratchasima
        - Swine Veterinary Intern — "Follow a Veterinarian" Program, CPF

        **2024**
        - Goat and Cattle Farm, JJ Sirifarm, Roi Et

        **2023**
        - Korat Zoo
        - Nakhon Ratchasima Provincial Livestock Office
        """
    )

with tab2:
    st.markdown(
        """
        **2025** — Executive Committee, Veterinary Student Union & Vet KKU Open House

        **2024** — Leader, Veterinary Volunteer Club & Rabies Camp · Secretary, 17th Freshmen Camp ·
        Round-Mor Camp, Rabies Club

        **2023** — Rabies & Aquatic Camp · Veterinary Volunteer Camp · Veterinary Volunteer Club & Rabies Camp

        **2022** — Committee Member, Vet KKU Archery Club · Veterinary Volunteer Camp
        """
    )

st.divider()

# ----------------------------
# Projects (ลิงก์ไปหน้าอื่นในเว็บ)
# ----------------------------
st.subheader("💻 Projects on this site")
st.write("โปรเจกต์ด้านล่างพัฒนาด้วย Python (Streamlit) เพื่อประยุกต์ใช้ความรู้ทางสัตวแพทย์ร่วมกับทักษะการเขียนโปรแกรม")

pcol1, pcol2, pcol3 = st.columns(3)
with pcol1:
    st.info("**🐷 Diagnosis Support Tools in Swine**\n\nช่วยคัดกรองแยกโรคเบื้องต้นจากอาการ อัตราป่วย-ตาย และปัจจัยเสี่ยง พร้อมแนวทางเก็บตัวอย่างส่งตรวจ")
with pcol2:
    st.info("**🧪 Serology Interpretation Guide**\n\nแปลผลระดับภูมิคุ้มกันฟาร์มจากค่า titer ของโรคสำคัญในสุกร")
with pcol3:
    st.info("**🔮 Future Projects**\n\nพื้นที่สำหรับโปรเจกต์ถัดไป — กำลังพัฒนา")

st.caption("ใช้เมนูด้านซ้ายเพื่อไปยังแต่ละโปรเจกต์")

st.divider()
st.caption(
    "หมายเหตุ: ต้องการใส่รูปจริงแทนไอคอน 🩺 ด้านบน ให้นำไฟล์รูปมาวางในโฟลเดอร์นี้ (เช่น photo.jpg) "
    "แล้วแก้โค้ดส่วนคอลัมน์รูปจาก st.markdown(...) เป็น st.image('photo.jpg') แทน"
)
