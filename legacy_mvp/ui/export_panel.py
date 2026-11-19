# ui/export_panel.py
import streamlit as st
import html
from ui import common


def render():
    common.render_header("export")
    payload = st.session_state.payload
    if not payload:
        st.warning(common.L["status_info"])
        if st.button(common.L["btn_return_upload"]):
            st.session_state.page = "upload"
            st.rerun()
        return

    def get_field_val(fname, fd):
        edited = st.session_state.get(f"input_{fname}")
        if edited is not None and str(edited).strip(): return str(edited).strip()
        if fd.get("value") is not None: return str(fd["value"])
        return common.L["ph_not_mentioned"]

    col_left, col_right = st.columns([3, 7])
    md_content = f"# {common.L['doc_title']}\n\n"

    md_content += "## 🩺 Diagnosis\n\n"
    if payload["diagnosis"]["status"] == "not_uploaded":
        md_content += f"*{common.L['not_uploaded']}*\n\n"
    elif payload["diagnosis"]["status"] == "failed":
        md_content += f"*[Error: {common.L['service_failed']}]*\n\n"
    else:
        for fname, fd in payload["diagnosis"]["data"]["fields"].items():
            label = common.FIELD_LABELS.get(fname, fname)
            md_content += f"### {label}\n{get_field_val(fname, fd)}\n\n"

    md_content += "## 🔬 Pathological Section\n\n"

    md_content += "### Macro\n"
    if payload["macro"]["status"] == "not_uploaded":
        md_content += f"*{common.L['not_uploaded']}*\n\n"
    elif payload["macro"]["status"] == "failed":
        md_content += f"*[Error: {common.L['service_failed']}]*\n\n"
    else:
        md_content += f"{st.session_state.get('input_macro_text', payload['macro']['data'].get('text', ''))}\n\n"

    md_content += "### Micro\n"
    if payload["micro"]["status"] == "not_uploaded":
        md_content += f"*{common.L['not_uploaded']}*\n\n"
    elif payload["micro"]["status"] == "failed":
        md_content += f"*[Error: {common.L['service_failed']}]*\n\n"
    else:
        md_content += f"{st.session_state.get('input_micro_text', payload['micro']['data'].get('text', ''))}\n\n"

    with col_left:
        with st.container(border=True):
            st.subheader(common.L["export_left"])
            st.success(common.L["export_ready"])
            st.success(common.L["export_confirmed"])
            st.write(common.L["export_fmt"])

            st.download_button(label=common.L["btn_download"], data=md_content, file_name="clinical_report.md",
                               mime="text/markdown", type="primary", use_container_width=True)
            if st.button(common.L["btn_return_edit"], use_container_width=True):
                st.session_state.page = "review"
                st.rerun()

    with st.container(border=True):
        st.subheader(common.L["export_right"])
        css_watermark = f"""
        <style>
        .watermark-bg {{
            background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' version='1.1' height='100px' width='250px'><text transform='translate(20, 60) rotate(-25)' fill='rgba(200, 200, 200, 0.2)' font-size='24'>{common.L['watermark']}</text></svg>");
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
        html_preview += f'<h1 class="md-h1">{common.L["doc_title"]}</h1>'

        html_preview += '<h2 class="md-h2">🩺 Diagnosis</h2>'
        if payload["diagnosis"]["status"] == "not_uploaded":
            html_preview += f'<p class="md-p" style="color:red;">{common.L["not_uploaded"]}</p>'
        elif payload["diagnosis"]["status"] == "failed":
            html_preview += f'<p class="md-p" style="color:red;">[Error: {common.L["service_failed"]}]</p>'
        else:
            for fname, fd in payload["diagnosis"]["data"]["fields"].items():
                label = common.FIELD_LABELS.get(fname, fname)
                html_preview += f'<h3 class="md-h3">{html.escape(label)}</h3>'
                html_preview += f'<p class="md-p">{html.escape(get_field_val(fname, fd))}</p>'

        html_preview += '<h2 class="md-h2">🔬 Pathological Section</h2>'

        html_preview += '<h3 class="md-h3">Macro</h3>'
        if payload["macro"]["status"] == "not_uploaded":
            html_preview += f'<p class="md-p" style="color:red;">{common.L["not_uploaded"]}</p>'
        elif payload["macro"]["status"] == "failed":
            html_preview += f'<p class="md-p" style="color:red;">[Error: {common.L["service_failed"]}]</p>'
        else:
            html_preview += f'<p class="md-p">{html.escape(st.session_state.get("input_macro_text", payload["macro"]["data"].get("text", "")))}</p>'

        html_preview += '<h3 class="md-h3">Micro</h3>'
        if payload["micro"]["status"] == "not_uploaded":
            html_preview += f'<p class="md-p" style="color:red;">{common.L["not_uploaded"]}</p>'
        elif payload["micro"]["status"] == "failed":
            html_preview += f'<p class="md-p" style="color:red;">[Error: {common.L["service_failed"]}]</p>'
        else:
            html_preview += f'<p class="md-p">{html.escape(st.session_state.get("input_micro_text", payload["micro"]["data"].get("text", "")))}</p>'

        html_preview += "</div>"
        st.markdown(html_preview, unsafe_allow_html=True)

    st.info(common.L["export_note"])