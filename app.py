import os
from pathlib import Path

import streamlit as st

from config import (
    global_config,
    EnvironmentValidator,
    AspectRatioEnum,
    CAPTION_STYLES,
)
from voice_synthesis import (
    VoiceSynthesisManager,
    BUILTIN_SPEAKERS,
    VoiceSynthesisError,
)
from visual_renderer import VideoRenderer, RenderError


st.set_page_config(
    page_title="ClipForge Studio",
    page_icon="🎬",
    layout="wide",
)


st.markdown(
    """
<style>
.block-container {
    padding-top: 1.6rem;
    max-width: 1450px;
}

.hero {
    padding: 1.25rem 1.5rem;
    border: 1px solid #30343b;
    border-radius: 18px;
    background: linear-gradient(120deg,#171a22,#24202d);
    margin-bottom: 1rem;
}

.hero h1 {
    margin: 0;
    font-size: 2.1rem;
}

.hero p {
    margin: .4rem 0 0 0;
    color: #b8beca;
}

div[data-testid="stMetric"] {
    border: 1px solid #30343b;
    padding: 12px;
    border-radius: 12px;
}
</style>

<div class="hero">
    <h1>🎬 ClipForge Studio</h1>
    <p>
        Creator workflow for clips, expressive narration,
        voice-synced captions and visual-beat timing.
    </p>
</div>
""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------
# SESSION STATE
# ---------------------------------------------------------

for key, default in {
    "video_path": "",
    "voice_path": "",
    "render_path": "",
    "script_text": "",
    "visual_beats": [],
}.items():
    st.session_state.setdefault(key, default)


# ---------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------

with st.sidebar:
    st.header("⚙️ Project settings")

    aspect = st.selectbox(
        "Output format",
        list(AspectRatioEnum),
        format_func=lambda x: x.label,
    )

    caption_style = st.selectbox(
        "Caption style",
        list(CAPTION_STYLES.keys()),
        index=0,
    )

    speaker_key = st.selectbox(
        "AI voice",
        list(BUILTIN_SPEAKERS.keys()),
        format_func=lambda k: BUILTIN_SPEAKERS[k].display_name,
    )

    st.caption(
        "Edge TTS voices are available without a paid API key; "
        "internet access is required."
    )

    with st.expander("System check"):
        diag = EnvironmentValidator.run_full_diagnostics(
            global_config.paths
        )

        st.write(
            "FFmpeg:",
            "Available" if diag["ffmpeg_installed"] else "Missing",
        )

        st.write(
            "Workspace:",
            "Ready" if diag["workspace_ready"] else "Not ready",
        )

        if not diag["ffmpeg_installed"]:
            st.warning(
                "Install FFmpeg or deploy with packages.txt included."
            )


# ---------------------------------------------------------
# TABS
# ---------------------------------------------------------

tab_source, tab_voice, tab_render, tab_help = st.tabs(
    [
        "1 · Source clip",
        "2 · Voiceover",
        "3 · Captions & export",
        "Help",
    ]
)


# =========================================================
# SOURCE TAB
# =========================================================

with tab_source:
    st.subheader("Bring in a clip")

    mode = st.radio(
        "Source",
        ["Upload a video", "YouTube URL"],
        horizontal=True,
    )

    source_path = None

    if mode == "Upload a video":

        uploaded = st.file_uploader(
            "Choose a video",
            type=[
                "mp4",
                "mov",
                "mkv",
                "webm",
            ],
        )

        if uploaded:
            suffix = Path(uploaded.name).suffix or ".mp4"

            saved = (
                Path(global_config.paths.temp_dir)
                / f"source{suffix}"
            )

            saved.write_bytes(uploaded.getbuffer())

            st.session_state.video_path = str(saved)

            # New video = reset old detected timing
            st.session_state.visual_beats = []

            source_path = str(saved)

    else:

        url = st.text_input(
            "Video URL",
            placeholder="https://www.youtube.com/watch?v=...",
        )

        if st.button(
            "Fetch video",
            type="primary",
        ):

            if not url.strip():

                st.warning(
                    "Paste a video URL first."
                )

            else:

                with st.spinner(
                    "Downloading video with yt-dlp…"
                ):

                    try:

                        path = VideoRenderer.download_video(
                            url.strip(),
                            global_config.paths.temp_dir,
                        )

                        st.session_state.video_path = str(
                            path
                        )

                        st.session_state.visual_beats = []

                        st.success(
                            "Video downloaded."
                        )

                    except Exception as exc:

                        st.error(
                            f"Could not download video: {exc}"
                        )

        source_path = (
            st.session_state.get("video_path")
            or None
        )

    source_path = (
        source_path
        or st.session_state.get("video_path")
        or None
    )

    if source_path and os.path.exists(source_path):

        st.session_state.video_path = source_path

        st.success(
            f"Source ready: {Path(source_path).name}"
        )

        st.video(source_path)

        st.caption(
            "Only use clips you own or have permission "
            "to edit and publish."
        )

        # -------------------------------------------------
        # Visual beat detection
        # -------------------------------------------------

        if st.button(
            "🎯 Detect visual beats",
            use_container_width=True,
        ):

            with st.spinner(
                "Scanning the clip for cuts and major motion changes…"
            ):

                try:

                    beats = VideoRenderer.detect_visual_beats(
                        source_path
                    )

                    st.session_state.visual_beats = beats

                    st.success(
                        f"Detected {len(beats)} visual beats."
                    )

                except RenderError as exc:

                    st.error(str(exc))

        beats = st.session_state.get(
            "visual_beats",
            [],
        )

        if beats:

            st.caption(
                "Visual beats detected:"
            )

            preview = beats[:12]

            st.write(
                ", ".join(
                    f"{beat:.1f}s"
                    for beat in preview
                )
            )

            if len(beats) > 12:

                st.caption(
                    f"Showing first 12 of {len(beats)} beats."
                )

    else:

        st.info(
            "Upload a clip or paste a video URL to begin."
        )


# =========================================================
# VOICE TAB
# =========================================================

with tab_voice:

    st.subheader("Create narration")

    st.caption(
        "Write your narration, then the renderer will "
        "align captions to the actual generated voice audio."
    )

    rate_adjustment = st.slider(
        "Speaking speed",
        min_value=-10,
        max_value=15,
        value=0,
        step=1,
        help="Higher values make the voice faster.",
    )

    pitch_adjustment = st.slider(
        "Voice pitch",
        min_value=-4,
        max_value=4,
        value=0,
        step=1,
        help="Small pitch adjustment supported by the selected voice.",
    )

    selected_voice = BUILTIN_SPEAKERS[
        speaker_key
    ]

    st.info(
        f"**{selected_voice.display_name}** — "
        f"{selected_voice.description}"
    )

    target_seconds = st.slider(
        "Target script length",
        min_value=10,
        max_value=60,
        value=19,
        step=1,
    )

    st.caption(
        f"For about {target_seconds} seconds, aim for roughly "
        f"{int(target_seconds * 2.6)}–"
        f"{int(target_seconds * 2.9)} words."
    )

    script = st.text_area(
        "Narration script",
        value=st.session_state.get(
            "script_text",
            "",
        ),
        height=220,
        placeholder=(
            "Example: He saw the opening for "
            "just a split second..."
        ),
        key="script_editor",
    )

    st.session_state.script_text = script

    words = (
        len(script.split())
        if script.strip()
        else 0
    )

    st.metric(
        "Estimated narration length",
        (
            f"{max(1, round(words / 2.75))} sec"
            if words
            else "0 sec"
        ),
        f"{words} words",
    )

    if st.button(
        "Generate AI voiceover",
        type="primary",
        disabled=not script.strip(),
    ):

        with st.spinner(
            "Generating narration…"
        ):

            try:

                out = (
                    Path(global_config.paths.temp_dir)
                    / "narration.mp3"
                )

                VoiceSynthesisManager().generate_narration(
                    script,
                    speaker_key,
                    str(out),
                    output_format="mp3",
                    delivery_style=selected_voice.key,
                    rate_adjustment=rate_adjustment,
                    pitch_adjustment=pitch_adjustment,
                )

                st.session_state.voice_path = str(
                    out
                )

                st.success(
                    "Voiceover generated."
                )

            except VoiceSynthesisError as exc:

                st.error(str(exc))

            except Exception as exc:

                st.error(
                    f"Voiceover failed: {exc}"
                )

    vp = st.session_state.get(
        "voice_path"
    )

    if vp and os.path.exists(vp):

        st.audio(vp)

        st.download_button(
            "Download voiceover",
            data=Path(vp).read_bytes(),
            file_name="voiceover.mp3",
            mime="audio/mpeg",
        )


# =========================================================
# RENDER TAB
# =========================================================

with tab_render:

    st.subheader(
        "Captions and final render"
    )

    st.write(
        "Captions are timed from the actual narration "
        "with Faster-Whisper. Visual-beat detection then "
        "adjusts caption breaks around cuts and major "
        "motion without using a paid AI vision service."
    )

    c1, c2 = st.columns(2)

    with c1:

        burn_captions = st.checkbox(
            "Add generated captions",
            value=True,
        )

        smart_timing = st.checkbox(
            "🎯 Smart voice + visual timing",
            value=True,
            help=(
                "Uses voice word timestamps plus local "
                "visual change detection to make caption "
                "changes feel synchronized with the action."
            ),
        )

        detect_beats = st.checkbox(
            "Detect visual beats automatically",
            value=True,
        )

        cover_old = st.checkbox(
            "Cover old captions near the bottom",
            value=False,
        )

        keep_source_audio = st.checkbox(
            "Keep source audio quietly under narration",
            value=False,
        )

    with c2:

        caption_position = st.selectbox(
            "Caption position",
            [
                "Lower third",
                "Center",
                "Upper third",
            ],
        )

        max_words = st.slider(
            "Maximum words per caption",
            min_value=1,
            max_value=6,
            value=3,
        )

        visual_sensitivity = st.slider(
            "Visual timing sensitivity",
            min_value=1,
            max_value=10,
            value=6,
            help=(
                "Higher detects smaller visual changes; "
                "lower only reacts to bigger changes."
            ),
        )

        output_name = st.text_input(
            "Export filename",
            value="my_short.mp4",
        )

    st.caption(
        "Visual timing is local frame-change detection, "
        "not semantic AI. Voice timestamps remain the "
        "source of truth for speech."
    )

    if st.button(
        "Render my Short",
        type="primary",
    ):

        vp = st.session_state.get(
            "video_path"
        )

        voice = st.session_state.get(
            "voice_path"
        )

        if not vp or not os.path.exists(vp):

            st.error(
                "Add a source video in the first tab."
            )

        else:

            out_name = Path(
                output_name
            ).name

            if not out_name.lower().endswith(
                ".mp4"
            ):
                out_name += ".mp4"

            output = (
                Path(global_config.paths.export_dir)
                / out_name
            )

            with st.spinner(
                "Rendering video. Larger clips may take a few minutes…"
            ):

                try:

                    renderer = VideoRenderer()

                    visual_beats = (
                        st.session_state.get(
                            "visual_beats",
                            [],
                        )
                    )

                    if (
                        smart_timing
                        and detect_beats
                    ):

                        visual_beats = (
                            renderer.detect_visual_beats(
                                vp,
                                sensitivity=visual_sensitivity,
                            )
                        )

                        st.session_state.visual_beats = (
                            visual_beats
                        )

                    renderer.render(
                        video_path=vp,
                        output_path=str(output),
                        aspect=aspect,
                        voice_path=(
                            voice
                            if voice
                            and os.path.exists(voice)
                            else None
                        ),
                        burn_captions=burn_captions,
                        caption_style=caption_style,
                        caption_position=caption_position,
                        max_words=max_words,
                        cover_old_captions=cover_old,
                        keep_source_audio=keep_source_audio,
                        visual_beats=visual_beats,
                        smart_caption_timing=smart_timing,
                    )

                    st.session_state.render_path = (
                        str(output)
                    )

                    st.success(
                        "Render complete."
                    )

                except RenderError as exc:

                    st.error(str(exc))

                except Exception as exc:

                    st.error(
                        f"Render failed: {exc}"
                    )

    rp = st.session_state.get(
        "render_path"
    )

    if rp and os.path.exists(rp):

        st.video(rp)

        st.download_button(
            "Download finished Short",
            data=Path(rp).read_bytes(),
            file_name=Path(rp).name,
            mime="video/mp4",
        )


# =========================================================
# HELP TAB
# =========================================================

with tab_help:

    st.subheader(
        "What this version does"
    )

    st.markdown(
        """
- Accepts uploaded clips and supported video URLs.
- Generates narration with free Edge TTS voices.
- Transcribes audio with Faster-Whisper through FFmpeg-decoded PCM.
- Avoids the PyAV `metadata_errors` problem.
- Times captions to the actual generated voice.
- Detects visual cuts and major motion locally.
- Uses visual beats to make caption changes feel connected to the action.
- Converts the source to vertical 9:16 or other supported canvas sizes.
- Exports MP4.

**Important limitations**

- Visual beat detection is not semantic AI.
- It detects frame changes, cuts and strong motion.
- It does not know that an object is specifically a punch, kick, car, person, etc.
- Perfectly removing burned-in captions requires video inpainting.
- The cover option masks the old caption area instead.
- Only use footage and music you have rights to publish.
"""
    )
