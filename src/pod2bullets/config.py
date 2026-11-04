"""Core configuration for pod2bullets."""

from pathlib import Path

from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    app_name: str = "pod2bullets"
    data_dir: Path = PROJECT_ROOT / "data"
    db_path: Path = PROJECT_ROOT / "data" / "db" / "pod2bullets.sqlite"
    models_dir: Path = PROJECT_ROOT / "data" / "models"
    podcasts_dir: Path = PROJECT_ROOT / "data" / "podcasts"
    tmp_dir: Path = PROJECT_ROOT / "data" / "tmp"

    # Models & Transcription
    default_model_id: str = "whisper-large-v3-turbo"
    device: str = "auto"  # "cuda", "cpu", or "auto"
    compute_type: str = "auto"  # "float16", "int8", "auto"

    # Server
    host: str = "127.0.0.1"
    port: int = 2121

    def init_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.podcasts_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
