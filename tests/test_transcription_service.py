from pathlib import Path
from types import SimpleNamespace

from audio_cleaner import AudioChunk
from transcription_service import normalize_whisper_segments, transcribe_chunk


def test_normalizes_whisper_segments_with_chunk_offset():
    segments = normalize_whisper_segments(
        [{"start": 2.0, "end": 5.0, "text": "遞迴"}],
        chunk_index=1,
        offset_ms=60_000,
    )

    assert segments[0].segment_id == "chunk-1-segment-0"
    assert segments[0].timestamp == "[01:02 - 01:05]"
    assert segments[0].explanation_en == ""


def test_transcribe_chunk_requests_verbose_segment_timestamps(tmp_path):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(segments=[{"start": 0, "end": 1, "text": "矩陣"}])

    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
    path = Path(tmp_path / "chunk.mp3")
    path.write_bytes(b"audio")

    # Call the function under test first, then assert the wrong response_format
    assert transcribe_chunk(client, AudioChunk(path, 0, 0, 1))[0].original_zh == "矩陣"

    # Ensure the request uses verbose JSON and passed a readable file object
    assert calls[0]["response_format"] == "verbose_json"
    assert hasattr(calls[0]["file"], "name")
    assert calls[0]["file"].name == str(path)
    assert calls[0]["model"] == "whisper-1"
    assert calls[0]["timestamp_granularities"] == ["segment"]


def test_normalize_strips_and_skips_blank_segments():
    raw = [
        {"start": 0, "end": 1, "text": "   "},
        {"start": 1, "end": 2, "text": "你好"},
        {"start": 2, "end": 3, "text": ""},
    ]

    segments = normalize_whisper_segments(raw, chunk_index=0, offset_ms=0)

    # Only the non-blank entry should survive and its ID should reflect the
    # original list index (1).
    assert len(segments) == 1
    assert segments[0].segment_id == "chunk-0-segment-1"
    assert segments[0].original_zh == "你好"