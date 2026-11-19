# ui/common.py
import html
import json
from string import Template
import streamlit as st
import streamlit.components.v1 as components

# ------------------------------------------------------------------ 文本与字典
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


# ------------------------------------------------------------------ 工具函数
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


# ------------------------------------------------------------------ UI 组件
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


TIMELINE_TEMPLATE = Template(r"""
<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
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

    # 状态颜色
    if absent:
        bg, border, accent, badge, badge_color = "#f7f7f7", "#ececec", "#bdbdbd", L["badge_absent"], "#9e9e9e"
    elif flagged:
        bg, border, accent, badge, badge_color = "#fff8e1", "#ffe082", "#f9a825", L["badge_flagged"], "#e65100"
    else:
        bg, border, accent, badge, badge_color = "#f4f9f4", "#dbe9db", "#43a047", L["badge_ok"], "#2e7d32"

    if highlight == fname: border, accent = "#1e88e5", "#1e88e5"

    override_badge = f'<span style="font-size:11px;color:#6a1b9a;margin-left:6px;">{L["override_badge"]}</span>' if override else ""
    target_prefix = f'📍 ' if highlight == fname else ""

    # 1. 渲染卡片头部
    st.markdown(
        f'<div style="padding:10px 14px 4px 14px;margin-top:10px;border-radius:8px 8px 0 0;'
        f'background:{bg};border:1px solid {border};border-bottom:none;border-left:4px solid {accent};">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">'
        f'<span style="font-weight:600;color:#37474f;font-size:13px;">{target_prefix}{html.escape(label)}{override_badge}</span>'
        f'<span style="font-size:11px;color:{badge_color};white-space:nowrap;">{badge}</span>'
        f'</div></div>', unsafe_allow_html=True,
    )

    # 2. 渲染警告信息
    if flagged and vm:
        display_msg = MSG_MAPPING.get(vm, vm) if isinstance(vm, str) else vm.get("en", "")
        st.markdown(
            f'<div style="margin:0;padding:0 14px 6px 14px;background:{bg};border-left:1px solid {border};border-right:1px solid {border};font-size:12px;color:#e65100;">⚠ {html.escape(display_msg)}</div>',
            unsafe_allow_html=True)

    # 3. 强制注入 CSS，让文本框变得极其明显（白底蓝框）
    st.markdown("""
        <style>
        div[data-testid="stTextArea"] textarea {
            background-color: #ffffff !important; 
            border: 2px solid #1e88e5 !important; 
            border-radius: 0 0 8px 8px !important;
            color: #000000 !important;
            font-size: 15px !important;
            font-weight: 500 !important;
        }
        </style>
    """, unsafe_allow_html=True)

    # 4. 渲染输入框
    current = st.session_state.get(f"input_{fname}")
    if current is None:
        current = "" if value is None else str(value)

    st.text_area(
        label=f"edit_{fname}",
        value=current,
        key=f"input_{fname}",
        label_visibility="collapsed",
        placeholder="✏️ CLICK HERE TO EDIT..." if absent else "✏️ Edit here...",
        height=68
    )

    # 5. 渲染证据按钮
    if evidence:
        cols = st.columns(min(len(evidence), 3))
        for i, ev in enumerate(evidence):
            with cols[i % len(cols)]:
                st.button(f"▶ {ev['segment_id']}", key=f"ev_{fname}_{ev['segment_id']}",
                          type="primary" if ev["segment_id"] == active_sid else "secondary",
                          use_container_width=True, on_click=_select_evidence, args=(fname, ev["segment_id"]))