from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from openai import OpenAI


from audio_cleaner import AudioChunk, format_timestamp_range


@dataclass(frozen=True)
class TranscriptSegment:
    segment_id: str
    start_seconds: float
    end_seconds: float
    timestamp: str
    original_zh: str
    translation_en: str
    explanation_en: str = ""


def normalize_whisper_segments(raw_segments: list[dict], chunk_index: int, offset_ms: int) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    offset_seconds = offset_ms / 1000
    for i, s in enumerate(raw_segments):
        text = (s.get("text") or "").strip()
        if not text:
            continue
        start = float(s.get("start", 0.0)) + offset_seconds
        end = float(s.get("end", 0.0)) + offset_seconds
        timestamp = format_timestamp_range(start, end)
        segments.append(
            TranscriptSegment(
                segment_id=f"chunk-{chunk_index}-segment-{i}",
                start_seconds=start,
                end_seconds=end,
                timestamp=timestamp,
                original_zh=text,
                translation_en="",
                explanation_en="",
            )
        )
    return segments


def transcribe_chunk(client: OpenAI, chunk: AudioChunk) -> list[TranscriptSegment]:
    with chunk.path.open("rb") as audio_file:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    return normalize_whisper_segments(list(response.segments), chunk.index, chunk.offset_ms)
