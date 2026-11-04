"""Audio normalization and decoding to 16kHz mono float32 using PyAV."""

from pathlib import Path

import av
import numpy as np

TARGET_SAMPLE_RATE = 16000


def load_audio_to_pcm16_mono(audio_path: Path) -> tuple[np.ndarray, float]:
    """Decode any audio format (mp3, m4a, ogg, wav) to mono 16kHz float32 numpy array.

    Returns:
        (audio_array, duration_seconds)
    """
    if not audio_path.exists():
        raise FileNotFoundError(f"Arquivo de áudio não encontrado: {audio_path}")

    container = av.open(str(audio_path))
    audio_stream = next((s for s in container.streams if s.type == "audio"), None)
    if not audio_stream:
        container.close()
        raise ValueError(f"Nenhum stream de áudio encontrado em {audio_path}")

    # Resampler to 16kHz mono float32
    resampler = av.AudioResampler(
        format="flt",
        layout="mono",
        rate=TARGET_SAMPLE_RATE,
    )

    chunks = []
    for frame in container.decode(audio_stream):
        resampled_frames = resampler.resample(frame)
        if resampled_frames:
            for rf in resampled_frames:
                # Convert to numpy array
                arr = rf.to_ndarray()
                chunks.append(arr.flatten())

    container.close()

    if not chunks:
        return np.zeros(0, dtype=np.float32), 0.0

    audio_data = np.concatenate(chunks).astype(np.float32)
    duration = float(len(audio_data)) / TARGET_SAMPLE_RATE
    return audio_data, duration
