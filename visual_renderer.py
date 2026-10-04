import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

from config import AspectRatioEnum, CAPTION_STYLES, global_config, get_logger

logger = get_logger("ClipForge.VideoRenderer")

class RenderError(Exception):
    pass

def _ffmpeg():
    p = shutil.which("ffmpeg")
    if not p:
        raise RenderError("FFmpeg was not found. Install FFmpeg; Streamlit deployments should include packages.txt.")
    return p

def _run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise RenderError((p.stderr or p.stdout or "FFmpeg failed")[-3000:])
    return p

def _time_srt(seconds):
    ms = max(0, int(seconds * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, milli = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{milli:03}"

class VideoRenderer:
    @staticmethod
    def download_video(url, output_dir):
        try:
            import yt_dlp
        except ImportError as exc:
            raise RenderError("yt-dlp is not installed.") from exc
        outdir = Path(output_dir); outdir.mkdir(parents=True, exist_ok=True)
        opts = {
            "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
            "outtmpl": str(outdir / "downloaded_source.%(ext)s"),
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                path = Path(ydl.prepare_filename(info))
                if path.exists(): return path
                mp4 = path.with_suffix(".mp4")
                if mp4.exists(): return mp4
                matches = sorted(outdir.glob("downloaded_source.*"), key=lambda p: p.stat().st_mtime, reverse=True)
                if matches: return matches[0]
        except Exception as exc:
            raise RenderError(f"Video download failed: {exc}") from exc
        raise RenderError("Download completed but the output video could not be found.")

    def _transcribe(self, audio_path):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RenderError("Faster-Whisper is missing. Install requirements.txt or disable captions.") from exc
        try:
            model = WhisperModel(global_config.whisper.model_size, device="cpu",
                                 compute_type=global_config.whisper.compute_type)
            segments, _ = model.transcribe(str(audio_path), word_timestamps=True, vad_filter=True)
            return [(float(w.start), float(w.end), w.word.strip())
                    for seg in segments for w in (seg.words or []) if w.word.strip()]
        except Exception as exc:
            raise RenderError(f"Audio transcription failed: {exc}") from exc

    @staticmethod
    def _write_srt(words, path, max_words=3):
        if not words: raise RenderError("No speech was detected, so captions could not be generated.")
        lines, idx, i = [], 1, 0
        while i < len(words):
            group = words[i:i + max_words]
            start, end = group[0][0], max(group[-1][1], group[0][0] + 0.25)
            txt = re.sub(r"\s+([,.;!?])", r"\1", " ".join(w[2] for w in group)).strip()
            lines.extend([str(idx), f"{_time_srt(start)} --> {_time_srt(end)}", txt, ""])
            idx += 1; i += max_words
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        return path

    def render(self, video_path, output_path, aspect=AspectRatioEnum.VERTICAL, voice_path=None,
               burn_captions=True, caption_style="Bold White", caption_position="Lower third",
               max_words=3, cover_old_captions=False, keep_source_audio=False):
        video_path, output_path = str(video_path), str(output_path)
        if not os.path.exists(video_path): raise RenderError("Source video file was not found.")
        if not isinstance(aspect, AspectRatioEnum): aspect = AspectRatioEnum.VERTICAL
        width, height = aspect.width, aspect.height
        workdir = Path(global_config.paths.temp_dir)
        workdir.mkdir(parents=True, exist_ok=True)
        srt_path = workdir / "generated_captions.srt"
        caption_source = voice_path or video_path

        if burn_captions:
            words = self._transcribe(caption_source)
            self._write_srt(words, srt_path, max_words=max(1, int(max_words)))

        # Fit/crop to selected canvas; optional mask covers old text near the bottom.
        filters = [f"scale={width}:{height}:force_original_aspect_ratio=increase",
                   f"crop={width}:{height}"]
        if cover_old_captions:
            filters.append(f"drawbox=x=0:y=ih*0.80:w=iw:h=ih*0.20:color=black@0.88:t=fill")
        if burn_captions:
            style = CAPTION_STYLES.get(caption_style, CAPTION_STYLES["Bold White"])
            vertical = {"Lower third": 1450, "Center": 900, "Upper third": 400}.get(caption_position, 1450)
            # subtitles filter renders text safely after normalizing path separators.
            escaped = str(srt_path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
            filters.append(f"subtitles='{escaped}':force_style='FontName=Arial,FontSize=20,PrimaryColour={style['primary']},OutlineColour={style['outline']},BorderStyle=1,Outline=3,Shadow=1,Alignment=2,MarginV={max(40, height-vertical)}'")
        vf = ",".join(filters)

        cmd = [_ffmpeg(), "-y", "-i", video_path]
        if voice_path and os.path.exists(voice_path):
            cmd += ["-i", str(voice_path)]
            if keep_source_audio:
                fc = "[0:a]volume=0.18[src];[1:a]volume=1.0[vo];[src][vo]amix=inputs=2:duration=first:dropout_transition=2[a]"
                cmd += ["-filter_complex", fc, "-map", "0:v:0", "-map", "[a]"]
            else:
                cmd += ["-map", "0:v:0", "-map", "1:a:0"]
        else:
            cmd += ["-map", "0:v:0", "-map", "0:a?"]
        cmd += ["-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                "-shortest", output_path]
        _run(cmd)
        if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
            raise RenderError("FFmpeg finished without producing a valid output file.")
        return output_path
