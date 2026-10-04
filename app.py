import os
import shutil
import tempfile
from pathlib import Path

import streamlit as st

from config import global_config, EnvironmentValidator, AspectRatioEnum, CAPTION_STYLES
from voice_synthesis import VoiceSynthesisManager, BUILTIN_SPEAKERS, VoiceSynthesisError
from visual_renderer import VideoRenderer, RenderError
from audio_dsp import VocalMasteringProcessor, SidechainMusicDucker

st.set_page_config(page_title="ClipForge Studio", page_icon="🎬", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 1.6rem; max-width: 1450px;}
.hero {padding: 1.25rem 1.5rem; border: 1px solid #30343b; border-radius: 18px;
       background: linear-gradient(120deg,#171a22,#24202d); margin-bottom: 1rem;}
.hero h1 {margin:0; font-size:2.1rem;}
.hero p {margin:.4rem 0 0 0; color:#b8beca;}
div[data-testid="stMetric"] {border:1px solid #30343b; padding:12px; border-radius:12px;}
</style>
<div class="hero"><h1>🎬 ClipForge Studio</h1>
<p>A free, creator-focused workflow for vertical clips, narration, captions and export.</p></div>
""", unsafe_allow_html=True)

for key, default in {
    "workspace": str(global_config.paths.workspace_dir),
    "video_path": "",
    "voice_path": "",
    "render_path": "",
}.items():
    st.session_state.setdefault(key, default)

with st.sidebar:
    st.header("⚙️ Project settings")
    aspect = st.selectbox("Output format", list(AspectRatioEnum), format_func=lambda x: x.label)
    caption_style = st.selectbox("Caption style", list(CAPTION_STYLES.keys()), index=0)
    speaker_key = st.selectbox(
        "AI voice",
        list(BUILTIN_SPEAKERS.keys()),
        format_func=lambda k: BUILTIN_SPEAKERS[k].display_name,
    )
    st.caption("Free online voices with delivery presets. Requires internet; availability may vary.")
    with st.expander("System check"):
        diag = EnvironmentValidator.run_full_diagnostics(global_config.paths)
        st.write("FFmpeg:", "Available" if diag["ffmpeg_installed"] else "Missing")
        st.write("Workspace:", "Ready" if diag["workspace_ready"] else "Not ready")
        if not diag["ffmpeg_installed"]:
            st.warning("Install FFmpeg or deploy with packages.txt included.")

tab_source, tab_voice, tab_render, tab_help = st.tabs(
    ["1 · Source clip", "2 · Voiceover", "3 · Captions & export", "Help"]
)

with tab_source:
    st.subheader("Bring in a clip")
    mode = st.radio("Source", ["Upload a video", "YouTube URL"], horizontal=True)
    source_path = None
    if mode == "Upload a video":
        uploaded = st.file_uploader("Choose a video", type=["mp4", "mov", "mkv", "webm"])
        if uploaded:
            suffix = Path(uploaded.name).suffix or ".mp4"
            saved = Path(global_config.paths.temp_dir) / f"source{suffix}"
            saved.write_bytes(uploaded.getbuffer())
            st.session_state.video_path = str(saved)
            source_path = str(saved)
    else:
        url = st.text_input("Video URL", placeholder="https://www.youtube.com/watch?v=...")
        if st.button("Fetch video", type="primary"):
            if not url.strip():
                st.warning("Paste a video URL first.")
            else:
                with st.spinner("Downloading video with yt-dlp…"):
                    try:
                        path = VideoRenderer.download_video(url.strip(), global_config.paths.temp_dir)
                        st.session_state.video_path = str(path)
                        st.success("Video downloaded.")
                    except Exception as e:
                        st.error(f"Could not download video: {e}")
        source_path = st.session_state.get("video_path") or None

    source_path = source_path or st.session_state.get("video_path") or None
    if source_path and os.path.exists(source_path):
        st.session_state.video_path = source_path
        st.success(f"Source ready: {Path(source_path).name}")
        st.video(source_path)
        st.caption("Only use clips you own or have permission to edit and publish.")
    else:
        st.info("Upload a clip or paste a video URL to begin.")

with tab_voice:
    st.subheader("Create narration")
    st.caption("Choose a delivery style in the sidebar, then tune energy with the controls below.")
    energy_col, pitch_col = st.columns(2)
    with energy_col:
        rate_adjustment = st.slider("Speaking energy / speed", min_value=-10, max_value=15, value=0, step=1, help="Adjusts speaking rate. Higher is faster; it does not create emotion by itself.")
    with pitch_col:
        pitch_adjustment = st.slider("Voice pitch", min_value=-4, max_value=4, value=0, step=1, help="Small pitch adjustment in semitones-like Hz steps supported by the provider.")
    selected_voice = BUILTIN_SPEAKERS[speaker_key]
    st.info(f"**{selected_voice.display_name}** — {selected_voice.description}")
    script = st.text_area(
        "Narration script",
        value=st.session_state.get("script_text", ""),
        height=220,
        placeholder="Write the voiceover for your Short here…",
        key="script_editor",
    )
    st.session_state.script_text = script
    words = len(script.split()) if script.strip() else 0
    st.metric("Estimated narration length", f"{max(1, round(words / 2.75)) if words else 0} sec", f"{words} words")
    if st.button("Generate AI voiceover", type="primary", disabled=not script.strip()):
        with st.spinner("Generating narration…"):
            try:
                out = Path(global_config.paths.temp_dir) / "narration.mp3"
                VoiceSynthesisManager().generate_narration(script, speaker_key, str(out), output_format="mp3", delivery_style=selected_voice.key, rate_adjustment=rate_adjustment, pitch_adjustment=pitch_adjustment)
                st.session_state.voice_path = str(out)
                st.success("Voiceover generated.")
            except VoiceSynthesisError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Voiceover failed: {e}")
    vp = st.session_state.get("voice_path")
    if vp and os.path.exists(vp):
        st.audio(vp)
        st.download_button("Download voiceover", data=Path(vp).read_bytes(), file_name="voiceover.mp3", mime="audio/mpeg")

with tab_render:
    st.subheader("Captions and final render")
    st.write("The app transcribes the narration or source audio, creates timed captions, formats the video vertically, and exports MP4.")
    c1, c2 = st.columns(2)
    with c1:
        burn_captions = st.checkbox("Add generated captions", value=True)
        cover_old = st.checkbox("Cover old captions near the bottom", value=False)
        keep_source_audio = st.checkbox("Keep source audio quietly under narration", value=False)
    with c2:
        caption_position = st.selectbox("Caption position", ["Lower third", "Center", "Upper third"])
        max_words = st.slider("Words per caption", min_value=1, max_value=6, value=3)
        output_name = st.text_input("Export filename", value="my_short.mp4")
    st.caption("Covering old captions hides a selected bottom strip; it does not reconstruct pixels behind burned-in text.")
    if st.button("Render my Short", type="primary"):
        vp = st.session_state.get("video_path")
        voice = st.session_state.get("voice_path")
        if not vp or not os.path.exists(vp):
            st.error("Add a source video in the first tab.")
        else:
            out_name = Path(output_name).name
            if not out_name.lower().endswith(".mp4"):
                out_name += ".mp4"
            output = Path(global_config.paths.export_dir) / out_name
            with st.spinner("Rendering video. Larger clips may take a few minutes…"):
                try:
                    renderer = VideoRenderer()
                    renderer.render(
                        video_path=vp,
                        output_path=str(output),
                        aspect=aspect,
                        voice_path=voice if voice and os.path.exists(voice) else None,
                        burn_captions=burn_captions,
                        caption_style=caption_style,
                        caption_position=caption_position,
                        max_words=max_words,
                        cover_old_captions=cover_old,
                        keep_source_audio=keep_source_audio,
                    )
                    st.session_state.render_path = str(output)
                    st.success("Render complete.")
                except RenderError as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"Render failed: {e}")
    rp = st.session_state.get("render_path")
    if rp and os.path.exists(rp):
        st.video(rp)
        st.download_button("Download finished Short", data=Path(rp).read_bytes(),
                           file_name=Path(rp).name, mime="video/mp4")

with tab_help:
    st.subheader("What this version does")
    st.markdown("""
- Accepts uploaded clips and supported video URLs.
- Generates narration with free online Edge TTS voices, delivery presets, and rate/pitch controls without a paid API key.
- Transcribes audio with Faster-Whisper when available and burns timed captions.
- Converts the source to a vertical 9:16 or landscape/square canvas.
- Can cover a bottom caption strip, duck source audio, and export MP4.
- Includes basic voice mastering and music ducking utilities in `audio_dsp.py`.

**Important limitations**
- Removing burned-in captions perfectly requires video inpainting; the included cover option masks the old text rather than restoring the background.
- YouTube downloading may be restricted by the source, region, or platform rules.
- Edge TTS requires internet access. Faster-Whisper may download a model on first use.
- Uploading to Streamlit Cloud is free within its current limits, but long renders can run out of memory or time.
- Use source footage and music only when you have the rights to publish them.
""")
