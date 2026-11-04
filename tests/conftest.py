"""Global pytest fixtures."""

from pathlib import Path

import pytest

from tests.fixtures.make_audio_fixtures import (
    create_synthetic_mp3,
    create_synthetic_wav,
    generate_sample_rss_xml,
)


@pytest.fixture
def tmp_audio_dir(tmp_path: Path) -> Path:
    audio_dir = tmp_path / "audio_fixtures"
    audio_dir.mkdir(parents=True, exist_ok=True)
    return audio_dir


@pytest.fixture
def sample_wav(tmp_audio_dir: Path) -> Path:
    wav_path = tmp_audio_dir / "sample.wav"
    return create_synthetic_wav(wav_path, duration_seconds=1.5)


@pytest.fixture
def sample_mp3(tmp_audio_dir: Path) -> Path:
    mp3_path = tmp_audio_dir / "sample.mp3"
    return create_synthetic_mp3(mp3_path, duration_seconds=1.5)


@pytest.fixture
def sample_rss_content() -> str:
    episodes = [
        {
            "title": "Episódio 1 - O Início",
            "guid": "ep-001",
            "pub_date": "Mon, 02 Nov 2026 10:00:00 GMT",
            "description": "Primeiro episódio de teste.",
            "audio_filename": "ep001.mp3",
            "length": 20480,
            "duration": "00:01:30",
        },
        {
            "title": "Episódio 2 - A Continuação",
            "guid": "ep-002",
            "pub_date": "Tue, 03 Nov 2026 10:00:00 GMT",
            "description": "Segundo episódio com muito conteúdo.",
            "audio_filename": "ep002.mp3",
            "length": 40960,
            "duration": "00:03:00",
        },
    ]
    return generate_sample_rss_xml("Podcast de Teste", episodes)
