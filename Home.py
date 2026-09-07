import streamlit as st
import os
import base64

st.set_page_config(page_title="Pitchaya Donsakul | Portfolio", page_icon="🩺", layout="wide")

PHOTO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile_photo.jpg")

# Drop these files in the same folder as Home.py to show them under each
# achievement — any missing ones are simply skipped, nothing breaks.
RESEARCH_IMAGE_DIR = os.path.dirname(os.path.abspath(__file__))

CSFV_IMAGES = [
    ("research_poster.jpg", "โปสเตอร์งานวิจัย"),
    ("research_presentation.jpg", "ภาพตอนนำเสนอผลงาน"),
    ("research_award.jpg", "ภาพรับรางวัล"),
]

CS_POSTER_IMAGES = [
    ("cs_poster.jpg", "ตัวอย่าง หน้าเว็บส่วนแบบฟอร์มสมัครสอบออนไลน์"),
    ("cs_presentation.jpg", "ตัวอย่าง ส่วนการแจ้งชำระค่าสมัครสอบ"),
    ("cs_award.jpg", "ภาพเกียรติบัตร"),
]


def render_achievement_images(expander_label, images):
    """Renders an expander with up to 3 images side by side. Files that
    don't exist yet are skipped silently — nothing breaks if the user
    hasn't added them to the folder."""
    with st.expander(expander_label):
        found_any = False
        img_cols = st.columns(len(images))
        for (fname, img_caption), col in zip(images, img_cols):
            fpath = os.path.join(RESEARCH_IMAGE_DIR, fname)
            with col:
                if os.path.exists(fpath):
                    st.image(fpath, caption=img_caption, use_container_width=True)
                    found_any = True
                else:
                    st.caption(f"_(ยังไม่มีไฟล์ {fname})_")
        if not found_any:
            names = ", ".join(f for f, _ in images)
            st.caption(f"วางไฟล์ {names} ไว้ในโฟลเดอร์เดียวกับ Home.py เพื่อแสดงรูป")


def get_base64_image(image_path):
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode()

# ----------------------------
# ส่วนหัว: ชื่อ + ข้อมูลติดต่อ
# ----------------------------
col_photo, col_info = st.columns([1, 3])
with col_photo:
    if os.path.exists(PHOTO_PATH):
        img_b64 = get_base64_image(PHOTO_PATH)
        st.markdown(
            f"""
            <img src="data:image/jpeg;base64,{img_b64}"
                 style="width:100%;aspect-ratio:1;object-fit:cover;object-position:center top;border-radius:12px;">
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <div style="width:100%;aspect-ratio:1;border-radius:12px;background:#8b1e1e;
            display:flex;align-items:center;justify-content:center;color:white;font-size:48px;">
            🩺
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("วางไฟล์ profile_photo.jpg ไว้ในโฟลเดอร์เดียวกับ Home.py เพื่อแสดงรูปจริง")

with col_info:
    st.title("Pitchaya Donsakul")
    st.markdown(
        "<span style='font-size:1.15rem;color:gray;'>6th-Year Veterinary Student | Swine Production</span>",
        unsafe_allow_html=True,
    )
    st.write("📞 093-339-5214  |  ✉️ pitchaya.d@kkumail.com")

st.divider()

# ----------------------------
# Profile Summary
# ----------------------------
st.subheader("Profile Summary")
st.write(
    "6th-year veterinary student passionate about swine production, with hands-on farm training and CSFV "
    "research experience. Additionally, applies an award-winning IT background to develop swine management "
    "web prototypes. An approachable and adaptable team player, eager to learn."
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
        - AI-Assisted Web Development
        - Microsoft Word (Intermediate)
        - Microsoft PowerPoint (Intermediate)
        - Canva (Intermediate)
        - Video editing (Intermediate)
        """
    )

    st.subheader("🗣️ Languages")
    st.markdown("- Thai — Native\n- English — Intermediate (Everyday Communication)")

    st.caption("📋 Other: Driving License")

with col_ach:
    st.subheader("🏆 Achievement")
    st.markdown(
        """
        **2025** — Best Oral Presentation Award, Veterinary Research II (VM KKU):
        *"Screening of Selected Thai Herbs for Anti-Classical Swine Fever Virus (CSFV) Activity"*
        """
    )

    render_achievement_images("📸 ดูรูปภาพเพิ่มเติม (CSFV)", CSFV_IMAGES)

    st.markdown(
        """
        **2020** — 1st Runner-up (Gold Medal), Computer Science Poster Presentation —
        12th Upper Northeastern Regional SMTE Academic Conference
        *"Developed and presented a web-based examination registration project."*
        """
    )

    render_achievement_images("📸 ดูรูปภาพเพิ่มเติม (Web-based examination registration project)", CS_POSTER_IMAGES)

    st.subheader("🤝 Soft Skills")
    st.markdown(
        """
        - Approachability & Conflict De-escalation
        - Adaptability & Eagerness to Learn
        - Leadership & Team Coordination
        """
    )

st.divider()

# ----------------------------
# Experience
# ----------------------------
st.subheader("💼 Internships & Practical Training")

tab1, tab2 = st.tabs(["Internships & Practical Training", "Leadership & Activities"])

with tab1:
    st.markdown(
        """
        **2025**
        - Swine Farm Intern – Breeder Farm | Tha Cha Lung Swine Farm, CPF
        - Swine Veterinary Intern – Follow a Veterinarian Program | CPF

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
        **2025**
        - Executive Committee of Veterinary Student Union
        - Staff, Vet KKU Open House
        - Staff, 7th Health Sciences Faculties Music Festival for Srinagarind Hospital
        
        **2024**
        - Leader, Veterinary Volunteer Club & Rabies Camp
        - Secretary, 17th Freshmen Camp
        - Executive Committee of Rabies Club KKU
        - Staff, Rob-Mor Camp, Rabies Club

        **2023** 
        - Rabies & Aquatic Camp
        - Veterinary Volunteer Camp
        - Veterinary Volunteer Club & Rabies Camp

        **2022** 
        - Committee Member of Vet KKU Archery Club
        - Veterinary Volunteer Camp
        - Staff, 7th Health Sciences Faculties Open House, KKU
        """
    )

st.divider()

# ----------------------------
# Projects (ลิงก์ไปหน้าอื่นในเว็บ)
# ----------------------------
st.subheader("💻 Technology & Personal Project")
st.markdown("**Swine Management & Veterinary Learning Tool (2026)**")
st.write("- Developed a web-based prototype for sow farrowing monitoring.")
st.write("- Revisited web development skills through AI-assisted learning and development, integrating veterinary knowledge with technology.")
st.write("") # เว้นบรรทัด

pcol1, pcol2, pcol3 = st.columns(3)
with pcol1:
    st.info("**🐖 Farrowing Monitor**\n\nระบบเฝ้าคลอดลูกสุกรแบบเรียลไทม์ แจ้งเตือนเมื่อระยะห่างระหว่างตัวนานผิดปกติ")
with pcol2:
    st.info("**🐷 Diagnosis Support Tools in Swine**\n\nตัวอย่างแนวทางเก็บตัวอย่างส่งตรวจติดเชื้อต่างๆ")
with pcol3:
    st.info("**🧪 Serology Interpretation Guide**\n\nแปลผลระดับภูมิคุ้มกันฟาร์มจากค่า titer ของโรคสำคัญในสุกร")

pcol4, pcol5 = st.columns(2)
with pcol4:
    st.info("**🗄️ Database Viewer**\n\nดูข้อมูลของทุกหน้าในเว็บนี้ผ่านเบราว์เซอร์เดียว")

st.caption("ใช้เมนูด้านซ้ายเพื่อไปยังแต่ละโปรเจกต์")