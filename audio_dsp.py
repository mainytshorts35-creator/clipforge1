import shutil
import subprocess
from pathlib import Path
from config import AudioProcessingConfig, global_config, get_logger

logger = get_logger("ClipForge.AudioDSP")

class AudioProcessingError(Exception):
    pass

def _ffmpeg():
    path = shutil.which("ffmpeg")
    if not path:
        raise AudioProcessingError("FFmpeg is required. Install it and ensure it is on PATH.")
    return path

def _run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise AudioProcessingError((p.stderr or p.stdout or "FFmpeg operation failed")[-2500:])
    return p

class VocalMasteringProcessor:
    def __init__(self, config=None):
        self.config = config or global_config.audio
    def process_voice_chain(self, input_path, output_path):
        _run([_ffmpeg(), "-y", "-i", str(input_path), "-af",
              "highpass=f=80,lowpass=f=15000,acompressor=threshold=0.125:ratio=3:attack=10:release=80,alimiter=limit=0.95",
              "-ar", str(self.config.sample_rate), "-ac", "1", str(output_path)])
        return str(output_path)

class SidechainMusicDucker:
    def __init__(self, config=None):
        self.config = config or global_config.audio
    def mix_bgm_with_sidechain(self, vocal_path, bgm_path, output_path, bgm_ducking_gain_db=-15.0):
        # Sidechain compression attenuates music while speech is active; looping music fills longer clips.
        filt = f"[1:a]volume={bgm_ducking_gain_db}dB[bg];[bg][0:a]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=350[duck];[0:a][duck]amix=inputs=2:duration=first:normalize=0[mix]"
        _run([_ffmpeg(), "-y", "-i", str(vocal_path), "-stream_loop", "-1", "-i", str(bgm_path),
              "-filter_complex", filt, "-map", "[mix]", "-c:a", "pcm_s16le", str(output_path)])
        return str(output_path)
