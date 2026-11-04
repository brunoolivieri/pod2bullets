"""Audio fixtures generator for offline and fast unit testing."""

from pathlib import Path

import av
import numpy as np
import soundfile as sf


def create_synthetic_wav(
    file_path: Path,
    duration_seconds: float = 2.0,
    sample_rate: int = 16000,
    frequency: float = 440.0,
) -> Path:
    """Generate a pure tone mono WAV file."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    t = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)
    # Generate 440Hz sine wave, float32 normalized between -1.0 and 1.0
    audio_data = (0.5 * np.sin(2 * np.pi * frequency * t)).astype(np.float32)
    sf.write(str(file_path), audio_data, sample_rate, format="WAV", subtype="PCM_16")
    return file_path


def create_synthetic_mp3(
    file_path: Path,
    duration_seconds: float = 2.0,
    sample_rate: int = 16000,
) -> Path:
    """Generate a mono MP3 file using PyAV."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    container = av.open(str(file_path), mode="w", format="mp3")
    stream = container.add_stream("mp3", rate=sample_rate, layout="mono")

    # Generate audio frames
    t = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)
    audio_data = (0.5 * np.sin(2 * np.pi * 300.0 * t)).astype(np.float32)

    # 1152 samples per frame for mp3
    frame_size = 1152
    for i in range(0, len(audio_data), frame_size):
        chunk = audio_data[i : i + frame_size]
        if len(chunk) < frame_size:
            chunk = np.pad(chunk, (0, frame_size - len(chunk)))
        # Reshape to (channels, samples)
        raw_frame = chunk.reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(raw_frame, format="flt", layout="mono")
        frame.sample_rate = sample_rate
        for packet in stream.encode(frame):
            container.mux(packet)

    for packet in stream.encode(None):
        container.mux(packet)
    container.close()
    return file_path


def generate_sample_rss_xml(
    podcast_title: str,
    episodes: list[dict],
    base_url: str = "http://localhost:8000",
) -> str:
    """Generate a clean podcast RSS 2.0 XML string."""
    items_xml = []
    for ep in episodes:
        items_xml.append(f"""
        <item>
            <title>{ep.get("title", "Episode Title")}</title>
            <guid>{ep.get("guid", ep.get("title"))}</guid>
            <pubDate>{ep.get("pub_date", "Wed, 04 Nov 2026 12:00:00 GMT")}</pubDate>
            <description>{ep.get("description", "Episode description")}</description>
            <enclosure url="{base_url}/audio/{ep.get("audio_filename", "audio.mp3")}" length="{ep.get("length", 1024)}" type="audio/mpeg" />
            <itunes:duration>{ep.get("duration", "00:02:00")}</itunes:duration>
        </item>
        """)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
    <channel>
        <title>{podcast_title}</title>
        <link>{base_url}</link>
        <description>Sample Podcast for testing</description>
        <language>pt-BR</language>
        {"".join(items_xml)}
    </channel>
</rss>
"""
