"""Lecture audio normalization, spectral noise reduction, and safe upload chunking."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


OPENAI_MAX_BYTES = 25 * 1024 * 1024
DEFAULT_CHUNK_MS = 12 * 60 * 1000
DEFAULT_OVERLAP_MS = 2 * 1000


@dataclass(frozen=True)
class AudioChunk:
    path: Path
    index: int
    offset_ms: int
    duration_ms: int


def format_timestamp_range(start_seconds: float, end_seconds: float) -> str:
    def render(seconds: float) -> str:
        total = max(0, int(seconds))
        return f"{total // 60:02d}:{total % 60:02d}"

    return f"[{render(start_seconds)} - {render(end_seconds)}]"


def chunk_windows(total_ms: int, chunk_ms: int = DEFAULT_CHUNK_MS, overlap_ms: int = DEFAULT_OVERLAP_MS) -> list[tuple[int, int]]:
    if total_ms <= 0 or chunk_ms <= 0 or not 0 <= overlap_ms < chunk_ms:
        raise ValueError("Audio duration must be positive and overlap must be smaller than chunk size")
    windows: list[tuple[int, int]] = []
    offset = 0
    while offset < total_ms:
        end = min(offset + chunk_ms, total_ms)
        windows.append((offset, end))
        if end == total_ms:
            break
        offset += chunk_ms - overlap_ms
    return windows


def _denoise(audio):
    import numpy as np
    import noisereduce as nr
    from pydub import AudioSegment

    samples = np.array(audio.get_array_of_samples())
    scale = float(1 << (8 * audio.sample_width - 1))
    reduced = nr.reduce_noise(y=samples.astype(np.float32) / scale, sr=audio.frame_rate)
    restored = np.clip(reduced * scale, -scale, scale - 1).astype(samples.dtype)
    return AudioSegment(restored.tobytes(), frame_rate=audio.frame_rate, sample_width=audio.sample_width, channels=1)


def split_audio_for_upload(audio, output_dir: Path, max_bytes: int = OPENAI_MAX_BYTES, chunk_ms: int = DEFAULT_CHUNK_MS, overlap_ms: int = DEFAULT_OVERLAP_MS) -> list[AudioChunk]:
    output_dir.mkdir(parents=True, exist_ok=True)
    single_path = output_dir / "cleaned.mp3"
    audio.export(single_path, format="mp3", bitrate="32k")
    if single_path.stat().st_size <= max_bytes:
        return [AudioChunk(single_path, 0, 0, len(audio))]

    single_path.unlink()
    chunks = []
    for index, (start, end) in enumerate(chunk_windows(len(audio), chunk_ms, overlap_ms)):
        chunk_path = output_dir / f"cleaned_{index:03d}.mp3"
        audio[start:end].export(chunk_path, format="mp3", bitrate="32k")
        chunks.append(AudioChunk(chunk_path, index, start, end - start))
    return chunks


def clean_audio(source_path: Path, output_dir: Path) -> list[AudioChunk]:
    from pydub import AudioSegment

    normalized = AudioSegment.from_file(source_path).set_channels(1).set_frame_rate(16_000)
    return split_audio_for_upload(_denoise(normalized), output_dir)