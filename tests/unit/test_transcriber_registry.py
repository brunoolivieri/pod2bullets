"""Test audio normalization and ModelRegistry."""

from pathlib import Path

import numpy as np

from pod2bullets.transcriber.audio import load_audio_to_pcm16_mono
from pod2bullets.transcriber.fake_engine import FakeTranscriberEngine
from pod2bullets.transcriber.registry import ModelRegistry


def test_load_audio_to_pcm16_wav(sample_wav: Path):
    audio, duration = load_audio_to_pcm16_mono(sample_wav)
    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    assert len(audio) > 0
    assert 1.4 <= duration <= 1.6


def test_load_audio_to_pcm16_mp3(sample_mp3: Path):
    audio, duration = load_audio_to_pcm16_mono(sample_mp3)
    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    assert len(audio) > 0
    assert 1.4 <= duration <= 1.6


def test_model_registry(tmp_path: Path):
    registry = ModelRegistry(models_dir=tmp_path / "models")
    models = registry.list_models()
    assert len(models) >= 2
    model_ids = [m.id for m in models]
    assert "whisper-large-v3-turbo" in model_ids
    assert "parakeet-tdt-0.6b-v3" in model_ids

    # Fake engine execution
    fake = registry.get_engine("fake-engine")
    assert isinstance(fake, FakeTranscriberEngine)
    assert fake.is_available()
