# ui/upload_panel.py
# ui/upload_panel.py
import streamlit as st
import time
from ui import common

# 👇👇👇 这个函数里就是你说的“没找到”的 15 个字段的 Mock 数据 👇👇👇
def load_mock_payload(simulate_fail: bool = False):
    diag_status = "failed" if simulate_fail else "success"
    return {
        "diagnosis": {
            "status": diag_status,
            "data": {
                "audio_url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
                "clean_segments": [
                    {"segment_id": "DIAG-S1", "start": 0.21, "end": 5.21, "text": "Sailing on length..."},
                    {"segment_id": "DIAG-S2", "start": 5.21, "end": 8.21, "text": "Attendance squamous..."},
                    {"segment_id": "DIAG-S3", "start": 8.21, "end": 13.97, "text": "pulid differentiated..."},
                    {"segment_id": "DIAG-S4", "start": 13.97, "end": 15.97, "text": "no perforation..."},
                    {"segment_id": "DIAG-S5", "start": 15.97, "end": 17.97, "text": "invasion to pericolic..."}
                ],
                "fields": {
                    "tumour_site": {"value": "right colon", "evidence": [{"segment_id": "DIAG-S1", "quote": "right corner", "start": 0.21, "end": 5.21}], "status": "flagged", "validation_msg": "值校验失败：引用未支持值中的核心词"},
                    "operative_procedure": {"value": "right hemicolectomy", "evidence": [{"segment_id": "DIAG-S1", "quote": "right hand", "start": 0.21, "end": 5.21}], "status": "flagged", "validation_msg": "值校验失败：引用未支持值中的核心词"},
                    "tumour_dimension": {"value": "5.5 cm", "evidence": [{"segment_id": "DIAG-S3", "quote": "size of tumor", "start": 8.21, "end": 13.97}], "status": "flagged", "validation_msg": "值校验失败：值中的数字与引用不一致"},
                    "tumour_perforation": {"value": "absent", "evidence": [{"segment_id": "DIAG-S4", "quote": "no perforation", "start": 13.97, "end": 15.97}], "status": "populated", "validation_msg": None},
                    "relation_to_anterior_peritoneal_reflection": {"value": "not applicable", "evidence": [], "status": "flagged", "validation_msg": "证据缺失：字段有值但未提供任何证据"},
                    "plane_of_mesorectal_excision": {"value": "not applicable", "evidence": [], "status": "flagged", "validation_msg": "证据缺失：字段有值但未提供任何证据"},
                    "histological_tumour_type": {"value": "adenosquamous carcinoma", "evidence": [{"segment_id": "DIAG-S2", "quote": "squamous", "start": 5.21, "end": 8.21}], "status": "populated", "validation_msg": None},
                    "histological_tumour_grade": {"value": "poorly differentiated", "evidence": [{"segment_id": "DIAG-S3", "quote": "pulid differentiated", "start": 8.21, "end": 13.97}], "status": "flagged", "validation_msg": "值校验失败：引用未支持值中的核心词"},
                    "extent_of_invasion": {"value": "invasion to pericolic fat", "evidence": [{"segment_id": "DIAG-S5", "quote": "invasion to pericolic fats", "start": 15.97, "end": 17.97}], "status": "populated", "validation_msg": None},
                    "lymphatic_and_venous_invasion": {"value": "present", "evidence": [{"segment_id": "DIAG-S1", "quote": "venous emission", "start": 19.97, "end": 21.97}], "status": "flagged", "validation_msg": "值校验失败：值与引用的否定/肯定极性相反"},
                    "perineural_invasion": {"value": "absent", "evidence": [{"segment_id": "DIAG-S1", "quote": "perineural", "start": 21.97, "end": 23.97}], "status": "populated", "validation_msg": None},
                    "lymph_node_status": {"value": "no metastasis, 0 out of 22", "evidence": [{"segment_id": "DIAG-S1", "quote": "no metastases", "start": 23.97, "end": 25.97}], "status": "flagged", "validation_msg": "值校验失败：值中的数字与引用不一致"},
                    "tumour_deposits": {"value": "absent", "evidence": [{"segment_id": "DIAG-S1", "quote": "tumor deposits absent", "start": 29.66, "end": 31.66}], "status": "populated", "validation_msg": None},
                    "proximal_and_distal_margins": {"value": "proximal: negative; distal: negative", "evidence": [{"segment_id": "DIAG-S1", "quote": "proximal distal N", "start": 31.66, "end": 32.66}], "status": "flagged", "validation_msg": "值校验失败：值与引用的否定/肯定极性相反"},
                    "circumferential_margin": {"value": "negative", "evidence": [{"segment_id": "DIAG-S1", "quote": "circumferential margins negative", "start": 32.66, "end": 34.66}], "status": "populated", "validation_msg": None}
                },
                "override_logs": [],
                "has_block": False
            }
        },
        "macro": {
            "status": "success",
            "data": {
                "audio_url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
                "clean_segments": [{"segment_id": "MAC-S1", "start": 1.0, "end": 4.0, "text": "Macroscopic examination..."}],
                "text": "Macroscopic examination reveals a resected segment..."
            }
        },
        "micro": {
            "status": "success",
            "data": {
                "audio_url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
                "clean_segments": [{"segment_id": "MIC-S1", "start": 2.0, "end": 6.0, "text": "Microscopic sections demonstrate..."}],
                "text": "Microscopic sections demonstrate an invasive adenosquamous carcinoma..."
            }
        }
    }

def render():
    common.render_header("upload")
    col_main, _ = st.columns([8, 2])

    if "has_diag" not in st.session_state: st.session_state.has_diag = False
    if "has_macro" not in st.session_state: st.session_state.has_macro = False
    if "has_micro" not in st.session_state: st.session_state.has_micro = False

    with col_main:
        st.subheader(common.L["upload_sub"])
        st.caption(common.L["upload_cap"])

        col1, col2 = st.columns(2)

        with col1:
            with st.container(border=True):
                st.markdown("### 🩺 Diagnosis")
                st.caption("Extracts 15 structured fields from audio.")
                diag_files = st.file_uploader("Upload Diagnosis Audio(s)", type=["mp3", "wma"], accept_multiple_files=True, key="u_diag")
                if diag_files: st.session_state.has_diag = True
                else: st.session_state.has_diag = False

        with col2:
            with st.container(border=True):
                st.markdown("### 🔬 Pathological Section")
                st.caption("Converts audio to plain text directly.")
                macro_files = st.file_uploader("Upload Macro Audio(s)", type=["mp3", "wma"], accept_multiple_files=True, key="u_macro")
                micro_files = st.file_uploader("Upload Micro Audio(s)", type=["mp3", "wma"], accept_multiple_files=True, key="u_micro")
                if macro_files: st.session_state.has_macro = True
                else: st.session_state.has_macro = False
                if micro_files: st.session_state.has_micro = True
                else: st.session_state.has_micro = False

        st.divider()
        simulate_fail = st.checkbox("⚙️ (Dev) Simulate AI Service Failure for Diagnosis", value=False)

        if st.session_state.has_diag or st.session_state.has_macro or st.session_state.has_micro:
            if st.button(common.L["btn_submit"], type="primary", use_container_width=True):
                progress_bar = st.progress(0)
                status = st.empty()
                for i, step in enumerate(common.L["steps"]):
                    status.info(f"Current status: **{step}**")
                    time.sleep(0.3)
                    progress_bar.progress((i + 1) * 25)

                try:
                    mock = load_mock_payload(simulate_fail=simulate_fail)

                    if not st.session_state.has_diag: mock["diagnosis"]["status"] = "not_uploaded"
                    if not st.session_state.has_macro: mock["macro"]["status"] = "not_uploaded"
                    if not st.session_state.has_micro: mock["micro"]["status"] = "not_uploaded"

                    st.session_state.payload = mock

                    if mock["diagnosis"]["status"] == "success":
                        st.session_state.segments = common.hydrate_evidence(mock["diagnosis"]["data"]["clean_segments"])
                        st.session_state.seg_to_fields = common.build_segment_index(mock["diagnosis"]["data"]["fields"])
                    else:
                        st.session_state.segments = []
                        st.session_state.seg_to_fields = {}

                    st.session_state.active_segment = None
                    st.session_state.highlight_field = None
                    st.session_state.processed = True

                    for k in list(st.session_state.keys()):
                        if k.startswith("input_"): del st.session_state[k]

                    status.success("✅ Loading complete! Redirecting...")
                    time.sleep(0.5)
                    st.session_state.page = "review"
                    st.rerun()
                except Exception as e:
                    st.error(common.L["load_error"].format(e))
        else:
            st.info("Please upload at least one file to generate the report.")

        st.write("")
        st.subheader(common.L["status_title"])
        with st.container(border=True):
            if not (st.session_state.has_diag or st.session_state.has_macro or st.session_state.has_micro): st.write(common.L["status_waiting"])
            elif not st.session_state.processed: st.info(common.L["status_info"])
            else:
                st.success(common.L["status_success"])
                if st.button(common.L["btn_proceed_review"], type="primary", use_container_width=True):
                    st.session_state.page = "review"
                    st.rerun()