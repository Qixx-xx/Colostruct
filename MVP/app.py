import html
import json
from string import Template

import streamlit as st
import streamlit.components.v1 as components
import time

st.set_page_config(page_title="Clinical Audio Proofreading", layout="wide")

# ------------------------------------------------------------------ 文本字典
L = {
    "title": "Clinical Audio Proofreading Workstation",
    "nav_upload": "Upload", "nav_review": "Review", "nav_export": "Export",
    "upload_sub": "Create New Report",
    "upload_cap": "Upload required audio files. You can upload multiple files per category.",
    "btn_submit": "🚀 Generate Combined Report",
    "status_title": "Processing Status",
    "status_waiting": "Waiting for file upload...",
    "status_info": "Please click the [Generate Combined Report] button to start.",
    "steps": ["ASR transcription...", "Extracting fields...", "Formatting text...", "Verifying..."],
    "status_success": "✅ Report generated successfully!",
    "btn_proceed_review": "👉 Proceed to Review",
    "review_left": "Original Transcript / Audio Tracks",
    "review_right": "Final Report Draft",
    "confirm_title": "Confirmation",
    "chk_confirm": "✅ I have reviewed and confirmed this draft.",
    "btn_export": "👉 Confirm and Proceed to Export",
    "btn_return_upload": "🔙 Return to Upload",
    "err_not_confirm": "⛔ Please check the confirmation box first.",
    "err_validation": "🚨 Validation Failed! Block-level issues or service errors remain.",
    "export_left": "Confirm Export",
    "export_ready": "✔ Document reviewed",
    "export_confirmed": "✔ Doctor confirmed",
    "export_fmt": "**Export Format:** Markdown",
    "btn_download": "⬇️ Export Markdown",
    "btn_return_edit": "Return to Edit",
    "export_right": "Final Document Preview",
    "export_note": "💡 Note: This document is an AI-assisted draft and is **not** directly written into the EHR.",
    "doc_title": "Surgical Pathology Report",
    "watermark": "AI-Assisted Draft",
    "ph_not_mentioned": "[Not Mentioned]",
    "not_uploaded": "[Not Uploaded]",
    "service_failed": "AI service temporarily unavailable. Please retry this section.",
    "ph_to_verify": "[To Be Verified]",
    "timeline_hint": "Click a timeline block to seek audio. Click segment buttons to highlight fields.",
    "active_segment": "Active segment: `{}` · {:.1f}s – {:.1f}s",
    "clear_highlight": "Clear highlight",
    "override_log": "View override log",
    "source_old": "Old evidence ({}): {}",
    "source_new": "New evidence ({}): {}",
    "badge_absent": "Not Mentioned", "badge_ok": "Populated", "badge_flagged": "⚠ Verify",
    "override_badge": "🔄 Overridden",
    "flagged_summary": "{} field(s) are flagged for verification.",
    "load_error": "Load failed: {}",
}

FIELD_LABELS = {
    "tumour_site": "Tumour Site", "operative_procedure": "Operative Procedure",
    "tumour_dimension": "Tumour Dimension", "tumour_perforation": "Tumour Perforation",
    "relation_to_anterior_peritoneal_reflection": "Relation to Anterior Peritoneal Reflection",
    "plane_of_mesorectal_excision": "Plane of Mesorectal Excision",
    "histological_tumour_type": "Histological Tumour Type", "histological_tumour_grade": "Histological Tumour Grade",
    "extent_of_invasion": "Extent of Invasion", "lymphatic_and_venous_invasion": "Lymphatic and Venous Invasion",
    "perineural_invasion": "Perineural Invasion", "lymph_node_status": "Lymph Node Status",
    "tumour_deposits": "Tumour Deposits", "proximal_and_distal_margins": "Proximal and Distal Margins",
    "circumferential_margin": "Circumferential Margin",
}

MSG_MAPPING = {
    "值校验失败：引用未支持值中的核心词": "Value validation failed: The quote does not support the core word of the value.",
    "值校验失败：值中的数字与引用不一致": "Value validation failed: The number in the value does not match the quote.",
    "证据缺失：字段有值但未提供任何证据": "Evidence missing: Value provided but no evidence attached.",
    "值校验失败：值与引用的否定/肯定极性相反": "Value validation failed: The polarity (positive/negative) contradicts the quote."
}

# ------------------------------------------------------------------ Session
if "page" not in st.session_state: st.session_state.page = "upload"
if "highlight_field" not in st.session_state: st.session_state.highlight_field = None
if "active_segment" not in st.session_state: st.session_state.active_segment = None
if "processed" not in st.session_state: st.session_state.processed = False
if "payload" not in st.session_state: st.session_state.payload = None


# ------------------------------------------------------------------ 数据层 (模拟后端接口契约)
def load_mock_payload(simulate_fail: bool = False):
    diag_status = "failed" if simulate_fail else "success"

    return {
        "diagnosis": {
            "status": diag_status,
            "data": {
                "audio_url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
                "clean_segments": [
                    {"segment_id": "DIAG-S1", "start": 0.21, "end": 5.21,
                     "text": "Sailing on length, say, right corner..."},
                    {"segment_id": "DIAG-S2", "start": 5.21, "end": 8.21, "text": "Attendance squamous, carcinoma..."},
                ],
                "fields": {
                    "tumour_site": {"value": "right colon", "evidence": [
                        {"segment_id": "DIAG-S1", "quote": "right corner", "start": 0.21, "end": 5.21}],
                                    "status": "flagged", "validation_msg": "值校验失败：引用未支持值中的核心词"},
                    "lymph_node_status": {"value": "no metastasis", "evidence": [], "status": "flagged",
                                          "validation_msg": "证据缺失：字段有值但未提供任何证据"},
                },
                "override_logs": [],
                "has_block": False
            }
        },
        "macro": {
            "status": "success",
            "data": {
                "audio_url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
                "clean_segments": [
                    {"segment_id": "MAC-S1", "start": 1.0, "end": 4.0, "text": "Macroscopic examination reveals..."}
                ],
                "text": "Macroscopic examination reveals a resected segment..."
            }
        },
        "micro": {
            "status": "success",
            "data": {
                "audio_url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
                "clean_segments": [
                    {"segment_id": "MIC-S1", "start": 2.0, "end": 6.0, "text": "Microscopic sections demonstrate..."}
                ],
                "text": "Microscopic sections demonstrate an invasive adenosquamous carcinoma..."
            }
        }
    }


def hydrate_evidence(clean_segments):
    segs = {}
    for cs in clean_segments:
        segs[cs["segment_id"]] = {
            "segment_id": cs["segment_id"], "start": float(cs["start"]),
            "end": float(cs["end"]), "text": cs.get("text", ""), "quotes": [cs.get("text", "")]
        }
    return sorted(segs.values(), key=lambda s: s["start"])


def build_segment_index(fields):
    idx = {}
    for fname, fd in fields.items():
        for ev in fd.get("evidence") or []:
            idx.setdefault(ev["segment_id"], []).append(fname)
    return idx


# ------------------------------------------------------------------ 联动回调
def _select_segment(sid: str):
    st.session_state.active_segment = sid if st.session_state.active_segment != sid else None
    fields = st.session_state.get("seg_to_fields", {}).get(sid, [])
    st.session_state.highlight_field = fields[0] if fields and st.session_state.active_segment else None


def _select_evidence(fname: str, sid: str):
    st.session_state.active_segment = sid
    st.session_state.highlight_field = fname


def _clear_highlight():
    st.session_state.active_segment = None
    st.session_state.highlight_field = None


# ------------------------------------------------------------------ 头部
def render_header(current_page):
    col_title, _ = st.columns([8, 2])
    with col_title:
        st.title(L["title"])
        if current_page == "upload":
            st.markdown(f"🔵 **{L['nav_upload']}** ➔ ⚪ {L['nav_review']} ➔ ⚪ {L['nav_export']}")
        elif current_page == "review":
            st.markdown(f"⚪ {L['nav_upload']} ➔ 🔵 **{L['nav_review']}** ➔ ⚪ {L['nav_export']}")
        elif current_page == "export":
            st.markdown(f"⚪ {L['nav_upload']} ➔ ⚪ {L['nav_review']} ➔ 🔵 **{L['nav_export']}**")
    st.divider()


# ------------------------------------------------------------------ 时间轴组件 (升级：支持多实例)
TIMELINE_TEMPLATE = Template(r"""
<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <!-- ⚠️ 这里的 id 是动态的，防止三个 tab 里的播放器冲突 -->
  <audio id="$audio_id" src="$audio_url" controls style="width:100%;margin-bottom:12px;"></audio>
  <div id="tl-$audio_id" style="position:relative;height:84px;background:#fafafa;border:1px solid #e6e6e6;border-radius:8px;overflow:hidden;">
    <div style="position:absolute;top:6px;left:8px;font-size:10px;color:#9e9e9e;letter-spacing:.5px;">TIMELINE</div>
  </div>
  <div style="font-size:11px;color:#999;margin-top:4px;">$hint</div>
</div>
<script>
(function(){
  var DUR = $dur;
  var SEGS = $segs;
  var ACTIVE = $active;
  var tl = document.getElementById('tl-$audio_id');
  var audio = document.getElementById('$audio_id');
  SEGS.forEach(function(s){
    var act = ACTIVE && s.segment_id === ACTIVE;
    var d = document.createElement('div');
    d.style.cssText =
      'position:absolute;top:24px;height:24px;border-radius:4px;font-size:10px;' +
      'line-height:24px;padding:0 2px;overflow:hidden;white-space:nowrap;cursor:pointer;text-overflow:ellipsis;' +
      'color:' + (act ? '#ffffff' : '#1b5e20') + ';' +
      'background:' + (act ? '#ff7043' : '#c8e6c9') + ';' +
      'border: 1px solid #ffffff;' +
      'box-shadow:' + (act ? '0 0 0 2px #ffab91' : 'none') + ';' +
      'left:' + (s.start / DUR * 100) + '%;' +
      'width:' + Math.max((s.end - s.start) / DUR * 100, 0.2) + '%;';
    d.textContent = s.segment_id;
    d.title = (s.quotes || []).join(' | ');
    d.onclick = function() { if(audio) { audio.currentTime = s.start; audio.play(); } };
    tl.appendChild(d);
  });
})();
</script>
""")


def render_timeline(segments, active_sid, duration, hint: str, audio_url: str, audio_id: str):
    segs = [{"segment_id": s["segment_id"], "start": s["start"], "end": s["end"], "quotes": s["quotes"]} for s in
            segments]
    components.html(
        TIMELINE_TEMPLATE.substitute(
            audio_id=audio_id, audio_url=audio_url or "", dur=duration,
            segs=json.dumps(segs, ensure_ascii=False).replace("</", "<\\/"),
            active=json.dumps(active_sid, ensure_ascii=False) if active_sid else "null",
            hint=html.escape(hint),
        ),
        height=190, scrolling=False,
    )


# ------------------------------------------------------------------ 字段卡片渲染
def render_field_card(fname: str, fd: dict, active_sid: str | None, highlight: str | None, override: dict | None):
    label = FIELD_LABELS.get(fname, fname)
    status, value, vm = fd.get("status"), fd.get("value"), fd.get("validation_msg")
    evidence = fd.get("evidence") or []

    absent = (status == "absent") or (value is None)
    flagged = (status == "flagged") and not absent

    if absent:
        bg, border, accent, badge, badge_color = "#f7f7f7", "#ececec", "#bdbdbd", L["badge_absent"], "#9e9e9e"
    elif flagged:
        bg, border, accent, badge, badge_color = "#fff8e1", "#ffe082", "#f9a825", L["badge_flagged"], "#e65100"
    else:
        bg, border, accent, badge, badge_color = "#f4f9f4", "#dbe9db", "#43a047", L["badge_ok"], "#2e7d32"

    if highlight == fname: border, accent = "#1e88e5", "#1e88e5"

    value_html = f'<span style="color:#bdbdbd;font-style:italic;">{html.escape(L["ph_not_mentioned"])}</span>' if absent else f'<span style="color:#1a1a1a;font-size:15px;font-weight:600;">{html.escape(str(value))}</span>'
    override_badge = f'<span style="font-size:11px;color:#6a1b9a;margin-left:6px;">{L["override_badge"]}</span>' if override else ""
    target_prefix = f'📍 ' if highlight == fname else ""

    st.markdown(
        f'<div style="padding:10px 14px;margin-bottom:6px;border-radius:8px;background:{bg};border:1px solid {border};border-left:4px solid {accent};">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">'
        f'<span style="font-weight:600;color:#37474f;font-size:13px;">{target_prefix}{html.escape(label)}{override_badge}</span>'
        f'<span style="font-size:11px;color:{badge_color};white-space:nowrap;">{badge}</span>'
        f'</div><div style="margin-top:6px;">{value_html}</div></div>', unsafe_allow_html=True,
    )

    if flagged and vm:
        display_msg = MSG_MAPPING.get(vm, vm) if isinstance(vm, str) else vm.get("en", "")
        st.markdown(
            f'<div style="margin:-2px 0 8px 4px;font-size:12px;color:#e65100;">⚠ {html.escape(display_msg)}</div>',
            unsafe_allow_html=True)

    if evidence:
        cols = st.columns(min(len(evidence), 3))
        for i, ev in enumerate(evidence):
            with cols[i % len(cols)]:
                st.button(f"▶ {ev['segment_id']}", key=f"ev_{fname}_{ev['segment_id']}",
                          type="primary" if ev["segment_id"] == active_sid else "secondary",
                          use_container_width=True, on_click=_select_evidence, args=(fname, ev["segment_id"]))

    current = st.session_state.get(f"input_{fname}")
    if current is None: current = "" if value is None else str(value)
    st.text_area(fname, value=current, key=f"input_{fname}", label_visibility="collapsed",
                 placeholder=L["ph_not_mentioned"] if absent else "", height=68)


# ------------------------------------------------------------------ 页面：上传
def page_upload():
    render_header("upload")
    col_main, _ = st.columns([8, 2])

    if "has_diag" not in st.session_state: st.session_state.has_diag = False
    if "has_macro" not in st.session_state: st.session_state.has_macro = False
    if "has_micro" not in st.session_state: st.session_state.has_micro = False

    with col_main:
        st.subheader(L["upload_sub"])
        st.caption(L["upload_cap"])

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
        simulate_fail = st.checkbox("⚙️ (Dev) Simulate AI Service Failure for Diagnosis", value=False)

        if st.session_state.has_diag or st.session_state.has_macro or st.session_state.has_micro:
            if st.button(L["btn_submit"], type="primary", use_container_width=True):
                progress_bar = st.progress(0)
                status = st.empty()
                for i, step in enumerate(L["steps"]):
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
                        st.session_state.segments = hydrate_evidence(mock["diagnosis"]["data"]["clean_segments"])
                        st.session_state.seg_to_fields = build_segment_index(mock["diagnosis"]["data"]["fields"])
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
                    st.error(L["load_error"].format(e))
        else:
            st.info("Please upload at least one file to generate the report.")

        st.write("")
        st.subheader(L["status_title"])
        with st.container(border=True):
            if not (st.session_state.has_diag or st.session_state.has_macro or st.session_state.has_micro):
                st.write(L["status_waiting"])
            elif not st.session_state.processed:
                st.info(L["status_info"])
            else:
                st.success(L["status_success"])
                if st.button(L["btn_proceed_review"], type="primary", use_container_width=True):
                    st.session_state.page = "review"
                    st.rerun()


# ------------------------------------------------------------------ 页面：审校
def page_review():
    render_header("review")
    payload = st.session_state.payload
    if not payload:
        st.warning(L["status_info"])
        if st.button(L["btn_return_upload"]):
            st.session_state.page = "upload"
            st.rerun()
        return

    active_sid = st.session_state.active_segment
    highlight = st.session_state.highlight_field
    col_left, col_right = st.columns([4.5, 5.5])

    # ================== 左栏：多轨时间轴 ==================
    with col_left:
        st.subheader(L["review_left"])

        # 收集所有有音轨数据的模块
        tracks = []
        if payload["diagnosis"]["status"] == "success":
            tracks.append(("Diagnosis", payload["diagnosis"]["data"]))
        if payload["macro"]["status"] == "success":
            tracks.append(("Macro", payload["macro"]["data"]))
        if payload["micro"]["status"] == "success":
            tracks.append(("Micro", payload["micro"]["data"]))

        if not tracks:
            st.warning("No audio timelines available.")
        else:
            # 💡 核心：使用 Tabs 实现多轨切换
            tabs = st.tabs([f"🎧 {name}" for name, _ in tracks])

            for tab, (name, data) in zip(tabs, tracks):
                with tab:
                    # 针对每个模块单独生成片段
                    module_segments = hydrate_evidence(data.get("clean_segments", []))
                    duration = max([s["end"] for s in module_segments] + [60.0]) + 10.0

                    # 渲染独立的时间轴和播放器
                    audio_id = f"audio-{name.lower()}"
                    render_timeline(module_segments, active_sid, duration, L["timeline_hint"],
                                    data.get("audio_url", ""), audio_id)

                    if active_sid:
                        seg = next((s for s in module_segments if s["segment_id"] == active_sid), None)
                        if seg:
                            st.caption(L["active_segment"].format(seg["segment_id"], seg["start"], seg["end"]))
                            for q in seg["quotes"]: st.markdown(f"> {q}")
                        st.button(L["clear_highlight"], key=f"clear_hl_{name}", on_click=_clear_highlight)

                    # 下方按钮列表
                    with st.container(height=250, border=True):
                        for seg in module_segments:
                            cols = st.columns([2, 3, 1])
                            cols[0].button(f"⏱ {seg['segment_id']}", key=f"seg_{name}_{seg['segment_id']}",
                                           type="primary" if seg["segment_id"] == active_sid else "secondary",
                                           use_container_width=True, on_click=_select_segment,
                                           args=(seg["segment_id"],))
                            cols[1].caption(f"**{seg['start']:.1f}s – {seg['end']:.1f}s**  \n{seg.get('text', '')}")
                            cols[2].caption(f"{len(st.session_state.seg_to_fields.get(seg['segment_id'], []))} f")

        if payload["diagnosis"]["status"] == "failed" or payload["macro"]["status"] == "failed" or payload["micro"][
            "status"] == "failed":
            st.error(f"❌ {L['service_failed']} (Partial service failure)")

    # ================== 右栏：完整报告草稿 ==================
    with col_right:
        st.subheader(L["review_right"])

        with st.container(height=650, border=True):
            st.markdown("## 🩺 Diagnosis")

            if payload["diagnosis"]["status"] == "not_uploaded":
                st.error(L["not_uploaded"])
            elif payload["diagnosis"]["status"] == "failed":
                st.error(f"🚨 {L['service_failed']}")
            else:
                override_map = {o["field_name"]: o for o in payload["diagnosis"]["data"].get("override_logs") or []}
                for fname, fd in payload["diagnosis"]["data"]["fields"].items():
                    render_field_card(fname, fd, active_sid, highlight, override_map.get(fname))

            st.divider()

            st.markdown("## 🔬 Pathological Section")

            st.markdown("#### Macro")
            if payload["macro"]["status"] == "not_uploaded":
                st.error(L["not_uploaded"])
                st.text_area("Macro", value=L["not_uploaded"], disabled=True, label_visibility="collapsed")
            elif payload["macro"]["status"] == "failed":
                st.error(f"🚨 {L['service_failed']}")
                st.text_area("Macro", value=L["service_failed"], disabled=True, label_visibility="collapsed")
            else:
                # 注意：这里取的是后端返回的纯文本 text，而不是 segments
                cur_macro = st.session_state.get("input_macro_text", payload["macro"]["data"].get("text", ""))
                st.text_area("Macro", value=cur_macro, key="input_macro_text", height=150)

            st.markdown("#### Micro")
            if payload["micro"]["status"] == "not_uploaded":
                st.error(L["not_uploaded"])
                st.text_area("Micro", value=L["not_uploaded"], disabled=True, label_visibility="collapsed")
            elif payload["micro"]["status"] == "failed":
                st.error(f"🚨 {L['service_failed']}")
                st.text_area("Micro", value=L["service_failed"], disabled=True, label_visibility="collapsed")
            else:
                cur_micro = st.session_state.get("input_micro_text", payload["micro"]["data"].get("text", ""))
                st.text_area("Micro", value=cur_micro, key="input_micro_text", height=150)

        st.write("")
        st.subheader(L["confirm_title"])

        has_error = False
        if payload["diagnosis"]["status"] == "failed" or payload["macro"]["status"] == "failed" or payload["micro"][
            "status"] == "failed":
            has_error = True
        if payload["diagnosis"]["status"] == "success" and payload["diagnosis"]["data"].get("has_block"):
            has_error = True

        confirm = st.checkbox(L["chk_confirm"])
        if st.button(L["btn_export"], type="primary", use_container_width=True):
            if not confirm:
                st.error(L["err_not_confirm"])
            elif has_error:
                st.error(L["err_validation"])
            else:
                st.session_state.page = "export"
                st.rerun()

        st.markdown("---")
        if st.button(L["btn_return_upload"], use_container_width=True):
            st.session_state.page = "upload"
            _clear_highlight()
            st.rerun()


# ------------------------------------------------------------------ 页面：导出
def page_export():
    render_header("export")
    payload = st.session_state.payload
    if not payload:
        st.warning(L["status_info"])
        if st.button(L["btn_return_upload"]):
            st.session_state.page = "upload"
            st.rerun()
        return

    def get_field_val(fname, fd):
        edited = st.session_state.get(f"input_{fname}")
        if edited is not None and str(edited).strip(): return str(edited).strip()
        if fd.get("value") is not None: return str(fd["value"])
        return L["ph_not_mentioned"]

    col_left, col_right = st.columns([3, 7])
    md_content = f"# {L['doc_title']}\n\n"

    md_content += "## 🩺 Diagnosis\n\n"
    if payload["diagnosis"]["status"] == "not_uploaded":
        md_content += f"*{L['not_uploaded']}*\n\n"
    elif payload["diagnosis"]["status"] == "failed":
        md_content += f"*[Error: {L['service_failed']}]*\n\n"
    else:
        for fname, fd in payload["diagnosis"]["data"]["fields"].items():
            label = FIELD_LABELS.get(fname, fname)
            md_content += f"### {label}\n{get_field_val(fname, fd)}\n\n"

    md_content += "## 🔬 Pathological Section\n\n"

    md_content += "### Macro\n"
    if payload["macro"]["status"] == "not_uploaded":
        md_content += f"*{L['not_uploaded']}*\n\n"
    elif payload["macro"]["status"] == "failed":
        md_content += f"*[Error: {L['service_failed']}]*\n\n"
    else:
        md_content += f"{st.session_state.get('input_macro_text', payload['macro']['data'].get('text', ''))}\n\n"

    md_content += "### Micro\n"
    if payload["micro"]["status"] == "not_uploaded":
        md_content += f"*{L['not_uploaded']}*\n\n"
    elif payload["micro"]["status"] == "failed":
        md_content += f"*[Error: {L['service_failed']}]*\n\n"
    else:
        md_content += f"{st.session_state.get('input_micro_text', payload['micro']['data'].get('text', ''))}\n\n"

    with col_left:
        with st.container(border=True):
            st.subheader(L["export_left"])
            st.success(L["export_ready"])
            st.success(L["export_confirmed"])
            st.write(L["export_fmt"])
            st.download_button(label=L["btn_download"], data=md_content, file_name="clinical_report.md",
                               mime="text/markdown", type="primary", use_container_width=True)
            if st.button(L["btn_return_edit"], use_container_width=True):
                st.session_state.page = "review"
                st.rerun()

    with st.container(border=True):
        st.subheader(L["export_right"])
        css_watermark = f"""
        <style>
        .watermark-bg {{
            background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' version='1.1' height='100px' width='250px'><text transform='translate(20, 60) rotate(-25)' fill='rgba(200, 200, 200, 0.2)' font-size='24'>{L['watermark']}</text></svg>");
            padding: 30px; border-radius: 5px;
        }}
        .md-h1 {{ color: #1E88E5; border-bottom: 2px solid #1E88E5; padding-bottom: 10px; margin-bottom: 20px;}}
        .md-h2 {{ color: #333; margin-top: 20px; margin-bottom: 5px; font-size: 1.2em; font-weight: bold;}}
        .md-h3 {{ color: #555; margin-top: 15px; margin-bottom: 5px; font-size: 1.0em; font-weight: bold;}}
        .md-p {{ color: #555; font-size: 15px; margin-top: 0; }}
        </style>
        """
        st.markdown(css_watermark, unsafe_allow_html=True)

        html_preview = '<div class="watermark-bg">'
        html_preview += f'<h1 class="md-h1">{L["doc_title"]}</h1>'

        html_preview += '<h2 class="md-h2">🩺 Diagnosis</h2>'
        if payload["diagnosis"]["status"] == "not_uploaded":
            html_preview += f'<p class="md-p" style="color:red;">{L["not_uploaded"]}</p>'
        elif payload["diagnosis"]["status"] == "failed":
            html_preview += f'<p class="md-p" style="color:red;">[Error: {L["service_failed"]}]</p>'
        else:
            for fname, fd in payload["diagnosis"]["data"]["fields"].items():
                label = FIELD_LABELS.get(fname, fname)
                html_preview += f'<h3 class="md-h3">{html.escape(label)}</h3>'
                html_preview += f'<p class="md-p">{html.escape(get_field_val(fname, fd))}</p>'

        html_preview += '<h2 class="md-h2">🔬 Pathological Section</h2>'

        html_preview += '<h3 class="md-h3">Macro</h3>'
        if payload["macro"]["status"] == "not_uploaded":
            html_preview += f'<p class="md-p" style="color:red;">{L["not_uploaded"]}</p>'
        elif payload["macro"]["status"] == "failed":
            html_preview += f'<p class="md-p" style="color:red;">[Error: {L["service_failed"]}]</p>'
        else:
            html_preview += f'<p class="md-p">{html.escape(st.session_state.get("input_macro_text", payload["macro"]["data"].get("text", "")))}</p>'

        html_preview += '<h3 class="md-h3">Micro</h3>'
        if payload["micro"]["status"] == "not_uploaded":
            html_preview += f'<p class="md-p" style="color:red;">{L["not_uploaded"]}</p>'
        elif payload["micro"]["status"] == "failed":
            html_preview += f'<p class="md-p" style="color:red;">[Error: {L["service_failed"]}]</p>'
        else:
            html_preview += f'<p class="md-p">{html.escape(st.session_state.get("input_micro_text", payload["micro"]["data"].get("text", "")))}</p>'

        html_preview += "</div>"
        st.markdown(html_preview, unsafe_allow_html=True)

    st.info(L["export_note"])


# ------------------------------------------------------------------ 路由
if st.session_state.page == "upload":
    page_upload()
elif st.session_state.page == "review":
    page_review()
elif st.session_state.page == "export":
    page_export()