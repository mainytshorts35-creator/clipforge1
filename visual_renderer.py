import os
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np

from config import AspectRatioEnum, CAPTION_STYLES, global_config, get_logger

logger = get_logger("ClipForge.VideoRenderer")


class RenderError(Exception):
    pass


def _ffmpeg():
    p = shutil.which("ffmpeg")
    if not p:
        raise RenderError(
            "FFmpeg was not found. Install FFmpeg; Streamlit deployments should include packages.txt."
        )
    return p


def _run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise RenderError((p.stderr or p.stdout or "Command failed")[-3000:])
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

        outdir = Path(output_dir)
        outdir.mkdir(parents=True, exist_ok=True)

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

                if path.exists():
                    return path

                mp4 = path.with_suffix(".mp4")
                if mp4.exists():
                    return mp4

                matches = sorted(
                    outdir.glob("downloaded_source.*"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )

                if matches:
                    return matches[0]

        except Exception as exc:
            raise RenderError(f"Video download failed: {exc}") from exc

        raise RenderError(
            "Download completed but the output video could not be found."
        )

    @staticmethod
    def _load_audio_with_ffmpeg(audio_path):
        """
        Decode any supported audio/video file into mono 16 kHz float32 PCM.

        This intentionally avoids Faster-Whisper/PyAV opening the source file
        directly, which prevents the `metadata_errors` incompatibility.
        """
        ffmpeg = _ffmpeg()

        cmd = [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(audio_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "s16le",
            "pipe:1",
        ]

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except Exception as exc:
            raise RenderError(
                f"Could not start FFmpeg audio decoding: {exc}"
            ) from exc

        if result.returncode != 0:
            error_text = result.stderr.decode(
                "utf-8", errors="replace"
            ).strip()

            raise RenderError(
                "FFmpeg could not decode the audio for transcription.\n"
                + error_text[-2000:]
            )

        if not result.stdout:
            raise RenderError("No audio data was found in the source.")

        # int16 PCM -> float32 [-1, 1]
        audio = np.frombuffer(
            result.stdout,
            dtype=np.int16
        ).astype(np.float32) / 32768.0

        if audio.size == 0:
            raise RenderError("The decoded audio is empty.")

        return audio

    def _transcribe(self, audio_path):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RenderError(
                "Faster-Whisper is missing. Install requirements.txt or disable captions."
            ) from exc

        if not os.path.exists(audio_path):
            raise RenderError(
                f"Audio file for transcription was not found: {audio_path}"
            )

        try:
            logger.info(
                "Loading Faster-Whisper model: %s",
                global_config.whisper.model_size,
            )

            model = WhisperModel(
                global_config.whisper.model_size,
                device=global_config.whisper.device,
                compute_type=global_config.whisper.compute_type,
            )

            logger.info("Decoding audio with FFmpeg for Whisper...")

            audio = self._load_audio_with_ffmpeg(audio_path)

            logger.info(
                "Transcribing %.2f seconds of audio...",
                len(audio) / 16000.0,
            )

            segments, info = model.transcribe(
                audio,
                word_timestamps=True,
                vad_filter=True,
                language="en",
                beam_size=5,
            )

            words = []

            for segment in segments:
                if not segment.words:
                    continue

                for word in segment.words:
                    if word.start is None or word.end is None:
                        continue

                    text = (word.word or "").strip()

                    if not text:
                        continue

                    words.append(
                        (
                            float(word.start),
                            float(word.end),
                            text,
                        )
                    )

            if not words:
                raise RenderError(
                    "Whisper did not detect any spoken words in the audio."
                )

            logger.info(
                "Transcription complete: %d words detected.",
                len(words),
            )

            return words

        except RenderError:
            raise

        except Exception as exc:
            error_text = str(exc)

            # Friendly message for the old PyAV incompatibility
            if "metadata_errors" in error_text:
                raise RenderError(
                    "Audio transcription hit a Faster-Whisper/PyAV "
                    "compatibility problem. Keep av==18.1.0 in requirements.txt "
                    "and redeploy the app."
                ) from exc

            raise RenderError(
                f"Audio transcription failed: {error_text}"
            ) from exc

    @staticmethod
    def _write_srt(words, path, max_words=3):
        if not words:
            raise RenderError(
                "No speech was detected, so captions could not be generated."
            )

        lines = []
        idx = 1
        i = 0

        while i < len(words):
            group = words[i:i + max_words]

            start = group[0][0]
            end = max(
                group[-1][1],
                group[0][0] + 0.25
            )

            txt = re.sub(
                r"\s+([,.;!?])",
                r"\1",
                " ".join(w[2] for w in group),
            ).strip()

            lines.extend(
                [
                    str(idx),
                    f"{_time_srt(start)} --> {_time_srt(end)}",
                    txt,
                    "",
                ]
            )

            idx += 1
            i += max_words

        Path(path).write_text(
            "\n".join(lines),
            encoding="utf-8",
        )

        return path

    def render(
        self,
        video_path,
        output_path,
        aspect=AspectRatioEnum.VERTICAL,
        voice_path=None,
        burn_captions=True,
        caption_style="Bold White",
        caption_position="Lower third",
        max_words=3,
        cover_old_captions=False,
        keep_source_audio=False,
    ):
        video_path = str(video_path)
        output_path = str(output_path)

        if not os.path.exists(video_path):
            raise RenderError("Source video file was not found.")

        if not isinstance(aspect, AspectRatioEnum):
            aspect = AspectRatioEnum.VERTICAL

        width = aspect.width
        height = aspect.height

        workdir = Path(global_config.paths.temp_dir)
        workdir.mkdir(
            parents=True,
            exist_ok=True,
        )

        srt_path = workdir / "generated_captions.srt"

        caption_source = (
            voice_path
            if voice_path and os.path.exists(voice_path)
            else video_path
        )

        # ---------------------------------------------------------
        # Generate captions
        # ---------------------------------------------------------
        if burn_captions:
            words = self._transcribe(caption_source)

            self._write_srt(
                words,
                srt_path,
                max_words=max(1, int(max_words)),
            )

        # ---------------------------------------------------------
        # Video filters
        # ---------------------------------------------------------
        filters = [
            f"scale={width}:{height}:force_original_aspect_ratio=increase",
            f"crop={width}:{height}",
        ]

        if cover_old_captions:
            filters.append(
                "drawbox="
                "x=0:"
                "y=ih*0.80:"
                "w=iw:"
                "h=ih*0.20:"
                "color=black@0.88:"
                "t=fill"
            )

        if burn_captions:
            style = CAPTION_STYLES.get(
                caption_style,
                CAPTION_STYLES["Bold White"],
            )

            vertical = {
                "Lower third": 1450,
                "Center": 900,
                "Upper third": 400,
            }.get(
                caption_position,
                1450,
            )

            escaped = (
                str(srt_path)
                .replace("\\", "/")
                .replace(":", r"\:")
                .replace("'", r"\'")
            )

            subtitle_filter = (
                f"subtitles='{escaped}':"
                "force_style="
                "'FontName=Arial,"
                "FontSize=20,"
                f"PrimaryColour={style['primary']},"
                f"OutlineColour={style['outline']},"
                "BorderStyle=1,"
                "Outline=3,"
                "Shadow=1,"
                "Alignment=2,"
                f"MarginV={max(40, height - vertical)}'"
            )

            filters.append(subtitle_filter)

        vf = ",".join(filters)

        # ---------------------------------------------------------
        # FFmpeg command
        # ---------------------------------------------------------
        cmd = [
            _ffmpeg(),
            "-y",
            "-i",
            video_path,
        ]

        if voice_path and os.path.exists(voice_path):
            cmd += [
                "-i",
                str(voice_path),
            ]

            if keep_source_audio:
                filter_complex = (
                    "[0:a]volume=0.18[src];"
                    "[1:a]volume=1.0[vo];"
                    "[src][vo]"
                    "amix=inputs=2:"
                    "duration=first:"
                    "dropout_transition=2[a]"
                )

                cmd += [
                    "-filter_complex",
                    filter_complex,
                    "-map",
                    "0:v:0",
                    "-map",
                    "[a]",
                ]

            else:
                cmd += [
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                ]

        else:
            cmd += [
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
            ]

        cmd += [
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "21",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-shortest",
            output_path,
        ]

        logger.info("Rendering final video...")

        _run(cmd)

        if (
            not os.path.exists(output_path)
            or os.path.getsize(output_path) < 1000
        ):
            raise RenderError(
                "FFmpeg finished without producing a valid output file."
            )

        logger.info(
            "Render complete: %s",
            output_path,
        )

        return output_path
