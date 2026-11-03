# app.py
import streamlit as st

st.set_page_config(page_title="Clinical Audio Proofreading", layout="wide")

# 初始化全局 session state
if "page" not in st.session_state: st.session_state.page = "upload"
if "highlight_field" not in st.session_state: st.session_state.highlight_field = None
if "active_segment" not in st.session_state: st.session_state.active_segment = None
if "processed" not in st.session_state: st.session_state.processed = False
if "payload" not in st.session_state: st.session_state.payload = None
if "segments" not in st.session_state: st.session_state.segments = []
if "seg_to_fields" not in st.session_state: st.session_state.seg_to_fields = {}

# 导入 ui 模块
from ui import upload_panel, review_panel, export_panel

# 路由分发
if st.session_state.page == "upload":
    upload_panel.render()
elif st.session_state.page == "review":
    review_panel.render()
elif st.session_state.page == "export":
    export_panel.render()