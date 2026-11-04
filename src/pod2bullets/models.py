"""Domain data models and schemas."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class EpisodeStatus(str, Enum):
    AVAILABLE = "available"  # Metadata synced from RSS, audio NOT downloaded
    QUEUED_DOWNLOAD = "queued_download"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"  # Audio file saved locally
    QUEUED_TRANSCRIPTION = "queued_transcription"
    TRANSCRIBING = "transcribing"
    COMPLETED = "completed"  # Audio downloaded and transcribed (.txt ready)
    FAILED = "failed"


class JobType(str, Enum):
    DOWNLOAD = "download"
    TRANSCRIBE = "transcribe"
    DOWNLOAD_AND_TRANSCRIBE = "download_and_transcribe"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SubscriptionList(BaseModel):
    id: Optional[int] = None
    name: str
    slug: str
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PodcastFeed(BaseModel):
    id: Optional[int] = None
    title: str
    slug: str
    rss_url: str
    site_url: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Episode(BaseModel):
    id: Optional[int] = None
    feed_id: int
    guid: str
    title: str
    slug: str
    published_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    audio_url: str
    audio_ext: str = "mp3"
    image_url: Optional[str] = None
    summary: Optional[str] = None
    status: EpisodeStatus = EpisodeStatus.AVAILABLE
    local_audio_path: Optional[str] = None
    file_size_bytes: Optional[int] = None
    sha256: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Transcript(BaseModel):
    id: Optional[int] = None
    episode_id: int
    model_id: str
    engine_name: str
    language: Optional[str] = "pt"
    plain_text_path: str
    meta_json_path: Optional[str] = None
    char_count: int = 0
    word_count: int = 0
    duration_proc_seconds: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Job(BaseModel):
    id: Optional[int] = None
    job_type: JobType
    status: JobStatus = JobStatus.PENDING
    episode_id: int
    model_id: Optional[str] = None
    progress_percent: float = 0.0
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
