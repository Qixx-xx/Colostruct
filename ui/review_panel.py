# ui/review_panel.py
import streamlit as st
from ui import common


def render():
    common.render_header("review")
    payload = st.session_state.payload
    if not payload:
        st.warning(common.L["status_info"])
        if st.button(common.L["btn_return_upload"]):
            st.session_state.page = "upload"
            st.rerun()
        return

    active_sid = st.session_state.active_segment
    highlight = st.session_state.highlight_field
    col_left, col_right = st.columns([4.5, 5.5])

    # ================== 左栏 ==================
    with col_left:
        st.subheader(common.L["review_left"])

        tracks = []
        if payload["diagnosis"]["status"] == "success": tracks.append(("Diagnosis", payload["diagnosis"]["data"]))
        if payload["macro"]["status"] == "success": tracks.append(("Macro", payload["macro"]["data"]))
        if payload["micro"]["status"] == "success": tracks.append(("Micro", payload["micro"]["data"]))

        if not tracks:
            st.warning("No audio timelines available.")
        else:
            tabs = st.tabs([f"🎧 {name}" for name, _ in tracks])

            for tab, (name, data) in zip(tabs, tracks):
                with tab:
                    module_segments = common.hydrate_evidence(data.get("clean_segments", []))
                    duration = max([s["end"] for s in module_segments] + [60.0]) + 10.0
                    audio_id = f"audio-{name.lower()}"

                    common.render_timeline(module_segments, active_sid, duration, common.L["timeline_hint"],
                                           data.get("audio_url", ""), audio_id)

                    if active_sid:
                        seg = next((s for s in module_segments if s["segment_id"] == active_sid), None)
                        if seg:
                            st.caption(common.L["active_segment"].format(seg["segment_id"], seg["start"], seg["end"]))
                            for q in seg["quotes"]: st.markdown(f"> {q}")
                        st.button(common.L["clear_highlight"], key=f"clear_hl_{name}", on_click=common._clear_highlight)

                    with st.container(height=250, border=True):
                        for seg in module_segments:
                            cols = st.columns([2, 3, 1])
                            cols[0].button(f"⏱ {seg['segment_id']}", key=f"seg_{name}_{seg['segment_id']}",
                                           type="primary" if seg["segment_id"] == active_sid else "secondary",
                                           use_container_width=True, on_click=common._select_segment,
                                           args=(seg["segment_id"],))
                            cols[1].caption(f"**{seg['start']:.1f}s – {seg['end']:.1f}s**  \n{seg.get('text', '')}")
                            cols[2].caption(f"{len(st.session_state.seg_to_fields.get(seg['segment_id'], []))} f")

        if any(payload[k]["status"] == "failed" for k in ["diagnosis", "macro", "micro"]):
            st.error(f"❌ {common.L['service_failed']} (Partial service failure)")

    # ================== 右栏 ==================
    with col_right:
        st.subheader(common.L["review_right"])

        with st.container(height=650, border=True):
            st.markdown("## 🩺 Diagnosis")
            if payload["diagnosis"]["status"] == "not_uploaded":
                st.error(common.L["not_uploaded"])
            elif payload["diagnosis"]["status"] == "failed":
                st.error(f"🚨 {common.L['service_failed']}")
            else:
                override_map = {o["field_name"]: o for o in payload["diagnosis"]["data"].get("override_logs") or []}
                for fname, fd in payload["diagnosis"]["data"]["fields"].items():
                    common.render_field_card(fname, fd, active_sid, highlight, override_map.get(fname))

            st.divider()

            st.markdown("## 🔬 Pathological Section")
            st.markdown("#### Macro")
            if payload["macro"]["status"] == "not_uploaded":
                st.error(common.L["not_uploaded"])
                st.text_area("Macro", value=common.L["not_uploaded"], disabled=True, label_visibility="collapsed")
            elif payload["macro"]["status"] == "failed":
                st.error(f"🚨 {common.L['service_failed']}")
                st.text_area("Macro", value=common.L["service_failed"], disabled=True, label_visibility="collapsed")
            else:
                cur_macro = st.session_state.get("input_macro_text", payload["macro"]["data"].get("text", ""))
                st.text_area("Macro", value=cur_macro, key="input_macro_text", height=150)

            st.markdown("#### Micro")
            if payload["micro"]["status"] == "not_uploaded":
                st.error(common.L["not_uploaded"])
                st.text_area("Micro", value=common.L["not_uploaded"], disabled=True, label_visibility="collapsed")
            elif payload["micro"]["status"] == "failed":
                st.error(f"🚨 {common.L['service_failed']}")
                st.text_area("Micro", value=common.L["service_failed"], disabled=True, label_visibility="collapsed")
            else:
                cur_micro = st.session_state.get("input_micro_text", payload["micro"]["data"].get("text", ""))
                st.text_area("Micro", value=cur_micro, key="input_micro_text", height=150)

        st.write("")
        st.subheader(common.L["confirm_title"])

        has_error = False
        if any(payload[k]["status"] == "failed" for k in ["diagnosis", "macro", "micro"]): has_error = True
        if payload["diagnosis"]["status"] == "success" and payload["diagnosis"]["data"].get(
            "has_block"): has_error = True

        confirm = st.checkbox(common.L["chk_confirm"])
        if st.button(common.L["btn_export"], type="primary", use_container_width=True):
            if not confirm:
                st.error(common.L["err_not_confirm"])
            elif has_error:
                st.error(common.L["err_validation"])
            else:
                st.session_state.page = "export"
                st.rerun()

        st.markdown("---")
        if st.button(common.L["btn_return_upload"], use_container_width=True):
            st.session_state.page = "upload"
            common._clear_highlight()
            st.rerun()