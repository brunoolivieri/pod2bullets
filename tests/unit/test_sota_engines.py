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


def test_faster_whisper_logs_5_percent_and_no_transcript_text(sample_wav: Path, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="pod2bullets.transcriber")
    engine = FasterWhisperEngine()

    segments = []
    for idx in range(10):
        seg = MagicMock()
        seg.start = float(idx) * 0.2
        seg.end = float(idx + 1) * 0.2
        seg.text = f"Frase secreta numero {idx} que nao deve aparecer no log."
        segments.append(seg)

    mock_info = MagicMock()
    mock_info.language = "pt"

    with patch.object(engine, "_load_model") as mock_load:
        mock_instance = MagicMock()
        mock_instance.transcribe.return_value = (segments, mock_info)
        mock_load.return_value = mock_instance

        res = engine.transcribe(sample_wav)
        assert "Frase secreta numero 0" in res.plain_text

    log_text = "\n".join(r.message for r in caplog.records)
    assert "Frase secreta numero" not in log_text
    assert "Progresso da transcrição" in log_text
    assert "10%" in log_text or "50%" in log_text or "100%" in log_text


def test_faster_whisper_auto_installs_when_missing(tmp_path: Path):
    engine = FasterWhisperEngine(model_id="whisper-small", models_dir=tmp_path / "models")
    assert not engine.is_available()

    with (
        patch("pod2bullets.transcriber.registry.ModelRegistry.install_model") as mock_install,
        patch("pod2bullets.transcriber.faster_whisper_engine.WhisperModel") as mock_whisper_cls,
    ):
        mock_install.return_value = tmp_path / "models" / "whisper-small"
        engine._load_model()
        mock_install.assert_called_once_with("whisper-small")
        mock_whisper_cls.assert_called_once()
