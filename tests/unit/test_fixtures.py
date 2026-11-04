"""Test offline audio fixtures and RSS XML generation."""

from pathlib import Path

import av
import feedparser


def test_synthetic_wav_creation(sample_wav: Path):
    assert sample_wav.exists()
    assert sample_wav.stat().st_size > 0
    with av.open(str(sample_wav)) as container:
        stream = next(s for s in container.streams if s.type == "audio")
        assert stream.sample_rate == 16000
        assert stream.channels == 1


def test_synthetic_mp3_creation(sample_mp3: Path):
    assert sample_mp3.exists()
    assert sample_mp3.stat().st_size > 0
    with av.open(str(sample_mp3)) as container:
        stream = next(s for s in container.streams if s.type == "audio")
        assert stream.sample_rate == 16000
        assert stream.channels == 1


def test_sample_rss_parsing(sample_rss_content: str):
    parsed = feedparser.parse(sample_rss_content)
    assert parsed.feed.title == "Podcast de Teste"
    assert len(parsed.entries) == 2
    ep1 = parsed.entries[0]
    assert ep1.title == "Episódio 1 - O Início"
    assert len(ep1.enclosures) == 1
    assert ep1.enclosures[0].href.endswith("ep001.mp3")
