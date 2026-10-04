from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import logging
import os
import shutil

def get_logger(name):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return logging.getLogger(name)

class AspectRatioEnum(Enum):
    VERTICAL = ("Vertical 9:16 (Shorts)", 1080, 1920)
    SQUARE = ("Square 1:1", 1080, 1080)
    LANDSCAPE = ("Landscape 16:9", 1920, 1080)
    @property
    def label(self): return self.value[0]
    @property
    def width(self): return self.value[1]
    @property
    def height(self): return self.value[2]
    def __str__(self): return self.label

class CaptionStyleEnum(Enum):
    BOLD_WHITE = "Bold White"
    HORMOZI_GOLD = "Gold Highlight"
    CLEAN = "Clean White"

CAPTION_STYLES = {
    "Bold White": {"primary": "&H00FFFFFF", "highlight": "&H0000D7FF", "outline": "&H00000000"},
    "Gold Highlight": {"primary": "&H00FFFFFF", "highlight": "&H0000D7FF", "outline": "&H00000000"},
    "Clean White": {"primary": "&H00FFFFFF", "highlight": "&H00FFFFFF", "outline": "&H00000000"},
}

@dataclass
class PathConfig:
    base_dir: Path = field(default_factory=lambda: Path(os.getenv("CLIPFORGE_HOME", Path.cwd() / "clipforge_data")))
    def __post_init__(self):
        self.workspace_dir = self.base_dir / "workspace"
        self.temp_dir = self.workspace_dir / "temp"
        self.export_dir = self.workspace_dir / "exports"
        self.font_path = None
        for p in (self.base_dir, self.workspace_dir, self.temp_dir, self.export_dir):
            p.mkdir(parents=True, exist_ok=True)

@dataclass
class Credentials:
    openai_api_key: str = ""
    elevenlabs_api_key: str = ""

@dataclass
class AudioProcessingConfig:
    sample_rate: int = 44100
    voice_gain_db: float = 2.0
    bgm_gain_db: float = -14.0

@dataclass
class WhisperModelConfig:
    model_size: str = "base"
    compute_type: str = "int8"
    device: str = "cpu"

@dataclass
class SafetyGuardrails:
    strict_mode: bool = True
    excluded_keywords: list = field(default_factory=lambda: ["non-consensual", "private information"])

@dataclass
class GlobalConfig:
    paths: PathConfig = field(default_factory=PathConfig)
    credentials: Credentials = field(default_factory=Credentials)
    audio: AudioProcessingConfig = field(default_factory=AudioProcessingConfig)
    whisper: WhisperModelConfig = field(default_factory=WhisperModelConfig)
    safety: SafetyGuardrails = field(default_factory=SafetyGuardrails)
    def update_api_keys(self, openai_key="", elevenlabs_key=""):
        self.credentials.openai_api_key = openai_key or ""
        self.credentials.elevenlabs_api_key = elevenlabs_key or ""

global_config = GlobalConfig()

class EnvironmentValidator:
    @staticmethod
    def run_full_diagnostics(paths):
        return {
            "ffmpeg_installed": bool(shutil.which("ffmpeg")),
            "ffmpeg_path": shutil.which("ffmpeg") or "Not found",
            "workspace_ready": all(p.exists() for p in (paths.workspace_dir, paths.temp_dir, paths.export_dir)),
        }
