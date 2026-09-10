from audio_cleaner import chunk_windows, format_timestamp_range


def test_formats_timestamp_range_as_minutes_and_seconds():
    assert format_timestamp_range(65.8, 130.1) == "[01:05 - 02:10]"


def test_chunk_windows_preserve_overlap_offsets():
    assert chunk_windows(1_500, chunk_ms=1_000, overlap_ms=200) == [(0, 1_000), (800, 1_500)]