# ui/upload_panel.py
import streamlit as st
import time
from ui import common

import json
import requests
import os
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()


def load_mock_payload(simulate_fail: bool = False):
    # 这个函数留着备用，万一明天断网了还可以切回来看 UI 效果
    json_string = """
    {
      "audio_url": "storage/audio/demo_rectal_case.wav",
      "clean_segments": [
        {
          "segment_id": "seg-001",
          "start": 0.0,
          "end": 3.0,
          "text": "Rectal: anterior recession, moderately to poorly differentiated adenocarcinoma."
        }
      ],
      "fields": {
        "tumour_site": {
          "value": "Rectal",
          "evidence": [{"segment_id": "seg-001", "quote": "Rectal: anterior recession", "start": 0.0, "end": 3.0}],
          "status": "populated",
          "validation_msg": null
        }
      },
      "override_logs": [],
      "has_block": false
    }
    """
    demo_data = json.loads(json_string)
    return {
        "diagnosis": {"status": "failed" if simulate_fail else "success", "data": demo_data},
        "macro": {"status": "not_uploaded", "data": None},
        "micro": {"status": "not_uploaded", "data": None}
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
                diag_files = st.file_uploader("Upload Diagnosis Audio(s)", type=["mp3", "wma"],
                                              accept_multiple_files=True, key="u_diag")
                if diag_files:
                    st.session_state.has_diag = True
                else:
                    st.session_state.has_diag = False

        with col2:
            with st.container(border=True):
                st.markdown("### 🔬 Pathological Section")
                st.caption("Converts audio to plain text directly.")
                macro_files = st.file_uploader("Upload Macro Audio(s)", type=["mp3", "wma"], accept_multiple_files=True,
                                               key="u_macro")
                micro_files = st.file_uploader("Upload Micro Audio(s)", type=["mp3", "wma"], accept_multiple_files=True,
                                               key="u_micro")
                if macro_files:
                    st.session_state.has_macro = True
                else:
                    st.session_state.has_macro = False
                if micro_files:
                    st.session_state.has_micro = True
                else:
                    st.session_state.has_micro = False

        st.divider()

        # 保留 Dev 选项
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
                    # ========================================================
                    # 🌟 核心改动：从环境变量读取接口 URL，默认值为本地 8000 端口
                    # ========================================================
                    BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000/api/process")

                    # 1. 收集文件
                    files = {}
                    if st.session_state.has_diag and diag_files:
                        files['diag_audio'] = (diag_files[0].name, diag_files[0].getvalue(), diag_files[0].type)
                    if st.session_state.has_macro and macro_files:
                        files['macro_audio'] = (macro_files[0].name, macro_files[0].getvalue(), macro_files[0].type)
                    if st.session_state.has_micro and micro_files:
                        files['micro_audio'] = (micro_files[0].name, micro_files[0].getvalue(), micro_files[0].type)

                    # 2. 发送 POST 请求给后端 (改为全英文)
                    status.info(f"Sending audio to AI backend ({BACKEND_API_URL}), please wait...")

                    response = requests.post(BACKEND_API_URL, files=files, timeout=300)

                    if response.status_code == 200:
                        # 3. 接收后端返回的真实数据
                        real_payload = response.json()

                        # ⚠️ 安全校验：防止后端返回的格式不对导致前端崩溃 (改为全英文)
                        if "diagnosis" not in real_payload:
                            st.error(
                                "Invalid response format from backend: missing 'diagnosis' field. Please check A/B group's code.")
                            st.json(real_payload)  # 打印出来看看组员到底返回了啥
                            st.stop()

                        st.session_state.payload = real_payload

                        # 4. 解析时间轴数据
                        if real_payload["diagnosis"]["status"] == "success":
                            st.session_state.segments = common.hydrate_evidence(
                                real_payload["diagnosis"]["data"]["clean_segments"])
                            st.session_state.seg_to_fields = common.build_segment_index(
                                real_payload["diagnosis"]["data"]["fields"])
                        else:
                            st.session_state.segments = []
                            st.session_state.seg_to_fields = {}

                        st.session_state.active_segment = None
                        st.session_state.highlight_field = None
                        st.session_state.processed = True

                        # 清理输入缓存
                        for k in list(st.session_state.keys()):
                            if k.startswith("input_"): del st.session_state[k]

                        status.success("✅ Processing complete! Redirecting...")
                        time.sleep(0.5)
                        st.session_state.page = "review"
                        st.rerun()
                    else:
                        # 改为全英文
                        st.error(f"Server error: {response.status_code} - {response.text}")

                except requests.exceptions.ConnectionError:
                    # 改为全英文
                    st.error(
                        f"❌ Cannot connect to backend service ({BACKEND_API_URL}). Please ensure B group's backend is running and the IP address is correct.")
                except Exception as e:
                    # 改为全英文
                    st.error(f"Unknown error occurred: {e}")
        else:
            st.info("Please upload at least one file to generate the report.")

        st.write("")
        st.subheader(common.L["status_title"])
        with st.container(border=True):
            if not (st.session_state.has_diag or st.session_state.has_macro or st.session_state.has_micro):
                st.write(common.L["status_waiting"])
            elif not st.session_state.processed:
                st.info(common.L["status_info"])
            else:
                st.success(common.L["status_success"])
                if st.button(common.L["btn_proceed_review"], type="primary", use_container_width=True):
                    st.session_state.page = "review"
                    st.rerun()