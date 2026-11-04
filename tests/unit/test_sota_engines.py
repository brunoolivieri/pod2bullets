"""Test SOTA engines initialization and mock transcription."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from pod2bullets.transcriber.faster_whisper_engine import FasterWhisperEngine
from pod2bullets.transcriber.onnx_asr_engine import OnnxAsrEngine


def test_faster_whisper_engine_mock(sample_wav: Path):
    engine = FasterWhisperEngine()

    mock_segment = MagicMock()
    mock_segment.start = 0.0
    mock_segment.end = 1.5
    mock_segment.text = "Texto transcrito com Whisper Turbo."

    mock_info = MagicMock()
    mock_info.language = "pt"

    with patch.object(engine, "_load_model") as mock_load:
        mock_instance = MagicMock()
        mock_instance.transcribe.return_value = ([mock_segment], mock_info)
        mock_load.return_value = mock_instance

        res = engine.transcribe(sample_wav)
        assert res.plain_text == "Texto transcrito com Whisper Turbo."
        assert len(res.segments) == 1
        assert res.language == "pt"


def test_onnx_asr_engine_mock(sample_wav: Path):
    engine = OnnxAsrEngine()

    with patch.object(engine, "_load_model") as mock_load:
        mock_instance = MagicMock()
        mock_instance.recognize.return_value = "Texto reconhecido pelo Parakeet NVIDIA."
        mock_load.return_value = mock_instance

        res = engine.transcribe(sample_wav)
        assert res.plain_text == "Texto reconhecido pelo Parakeet NVIDIA."
        assert len(res.segments) == 1
        assert res.engine_name == "onnx-asr"
