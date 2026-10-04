"""Expressive, free-first narration using Edge TTS.

This module uses provider voices and delivery controls, not unauthorized cloning.
Edge TTS is an online service; voice availability can change by region/provider.
"""
import asyncio
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Dict, Optional

from config import GlobalConfig, global_config, get_logger

logger = get_logger("ClipForge.VoiceSynthesis")


class VoiceSynthesisError(Exception):
    """Raised when narration generation or conversion fails."""


@dataclass(frozen=True)
class VoicePersona:
    key: str
    display_name: str
    voice_id: str
    description: str
    rate: str = "+0%"
    pitch: str = "+0Hz"
    volume: str = "+0%"


# These are general provider voices, not impersonations of named creators.
BUILTIN_SPEAKERS: Dict[str, VoicePersona] = {
    "andrew_story": VoicePersona("andrew_story", "Andrew · Casual storyteller", "en-US-AndrewNeural", "Conversational, friendly, natural pacing", "+0%", "+0Hz"),
    "brian_facts": VoicePersona("brian_facts", "Brian · Viral facts", "en-US-BrianNeural", "Confident, punchy facts and countdowns", "+8%", "+0Hz"),
    "guy_hype": VoicePersona("guy_hype", "Guy · Hype / sports", "en-US-GuyNeural", "Lively sports and action narration", "+10%", "+2Hz"),
    "christopher_doc": VoicePersona("christopher_doc", "Christopher · Documentary", "en-US-ChristopherNeural", "Steady, lower-key documentary delivery", "-4%", "-2Hz"),
    "ava_bright": VoicePersona("ava_bright", "Ava · Bright conversational", "en-US-AvaNeural", "Upbeat, clear and approachable", "+3%", "+1Hz"),
    "jenny_fun": VoicePersona("jenny_fun", "Jenny · Playful commentary", "en-US-JennyNeural", "Bright, casual commentary", "+5%", "+2Hz"),
    "aria_clean": VoicePersona("aria_clean", "Aria · Clear explainer", "en-US-AriaNeural", "Clear, balanced explainer voice", "+0%", "+0Hz"),
    "sonia_uk": VoicePersona("sonia_uk", "Sonia · British storyteller", "en-GB-SoniaNeural", "Natural British English delivery", "+2%", "+0Hz"),
}


class VoiceSynthesisManager:
    def __init__(self, config: Optional[GlobalConfig] = None):
        self.cfg = config or global_config

    def generate_narration(
        self,
        text_script: str,
        primary_speaker_key="andrew_story",
        output_wav_path="output_speech.mp3",
        output_format=None,
        delivery_style=None,
        rate_adjustment=0,
        pitch_adjustment=0,
    ) -> str:
        if not text_script or not text_script.strip():
            raise VoiceSynthesisError("Please enter a narration script.")
        try:
            import edge_tts
        except ImportError as exc:
            raise VoiceSynthesisError("edge-tts is missing. Add edge-tts to requirements.txt.") from exc

        persona = BUILTIN_SPEAKERS.get(primary_speaker_key, BUILTIN_SPEAKERS["andrew_story"])
        output_path = os.path.abspath(output_wav_path)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        fmt = (output_format or ("mp3" if output_path.lower().endswith(".mp3") else "wav")).lower()
        if fmt not in ("mp3", "wav"):
            raise VoiceSynthesisError("Output format must be MP3 or WAV.")
        temp_mp3 = output_path if fmt == "mp3" else output_path + ".tmp.mp3"

        # Small rate/pitch controls let creators tune delivery without pretending to
        # provide emotion synthesis the underlying voice does not expose.
        rate_base = int(persona.rate.replace("%", "").replace("+", ""))
        pitch_base = int(persona.pitch.replace("Hz", "").replace("+", ""))
        rate = max(-30, min(30, rate_base + int(rate_adjustment)))
        pitch = max(-10, min(10, pitch_base + int(pitch_adjustment)))
        rate_arg = f"{rate:+d}%"
        pitch_arg = f"{pitch:+d}Hz"
        text = text_script.strip()

        voices_to_try = list(dict.fromkeys([
            persona.voice_id, "en-US-AndrewNeural", "en-US-GuyNeural", "en-US-AriaNeural"
        ]))
        errors = []

        async def synthesize_voice(voice_id):
            last_error = None
            for attempt in range(3):
                try:
                    if os.path.exists(temp_mp3):
                        os.remove(temp_mp3)
                    comm = edge_tts.Communicate(text, voice_id, rate=rate_arg, pitch=pitch_arg, volume=persona.volume)
                    await comm.save(temp_mp3)
                    if not os.path.isfile(temp_mp3) or os.path.getsize(temp_mp3) < 100:
                        raise RuntimeError("The speech service returned an empty audio file.")
                    return voice_id
                except Exception as exc:
                    last_error = exc
                    logger.warning("TTS attempt %s for %s failed: %s", attempt + 1, voice_id, exc)
                    if attempt < 2:
                        await asyncio.sleep(1 + attempt * 2)
            raise RuntimeError(f"{voice_id}: {last_error}")

        async def run_all():
            for voice_id in voices_to_try:
                try:
                    return await synthesize_voice(voice_id)
                except Exception as exc:
                    errors.append(str(exc))
            raise VoiceSynthesisError(
                "Speech generation failed for the selected and fallback voices. "
                "Check deployment logs and internet access. Details: " + " | ".join(errors[-4:])
            )

        result, failure = {}, {}
        def runner():
            try:
                result["voice"] = asyncio.run(run_all())
            except Exception as exc:
                failure["error"] = exc
        thread = threading.Thread(target=runner)
        thread.start()
        thread.join()

        if "error" in failure:
            try:
                if os.path.exists(temp_mp3): os.remove(temp_mp3)
            except OSError:
                pass
            exc = failure["error"]
            if isinstance(exc, VoiceSynthesisError):
                raise exc
            raise VoiceSynthesisError(f"Speech generation failed: {exc}") from exc

        if fmt == "wav":
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                raise VoiceSynthesisError("FFmpeg is required for WAV output. Choose MP3 or install FFmpeg.")
            proc = subprocess.run(
                [ffmpeg, "-y", "-i", temp_mp3, "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", output_path],
                capture_output=True, text=True, timeout=120,
            )
            if proc.returncode:
                raise VoiceSynthesisError("Audio conversion failed: " + (proc.stderr or "")[-1500:])
            try: os.remove(temp_mp3)
            except OSError: pass

        if not os.path.isfile(output_path) or os.path.getsize(output_path) < 100:
            raise VoiceSynthesisError("Speech generation finished without a valid output file.")
        logger.info("Narration generated with %s (%s, rate=%s, pitch=%s)", result.get("voice"), delivery_style or "custom", rate_arg, pitch_arg)
        return output_path

    @staticmethod
    def estimate_speaking_duration(text, words_per_minute=165):
        words = len((text or "").split())
        return max(1.0, words * 60.0 / max(1, words_per_minute)) if words else 0.0
