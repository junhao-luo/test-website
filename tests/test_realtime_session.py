from types import SimpleNamespace

import pytest

from realtime_session import (
    FinalEventDeduplicator,
    LiveTranscriptEvent,
    create_realtime_client_secret,
    final_event_to_segment,
)


def test_requests_a_mandarin_vad_transcription_client_secret():
    calls = []

    def post(url, *, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"client_secret": {"value": "ephemeral"}},
        )

    assert create_realtime_client_secret("server-key", post) == "ephemeral"
    assert calls[0][0].endswith("/v1/realtime/client_secrets")
    assert calls[0][1]["Authorization"] == "Bearer server-key"
    assert calls[0][2]["session"]["type"] == "transcription"
    assert calls[0][2]["session"]["audio"]["input"]["transcription"]["model"] == "gpt-4o-transcribe"
    assert calls[0][2]["session"]["audio"]["input"]["transcription"]["language"] == "zh"
    assert calls[0][2]["session"]["audio"]["input"]["turn_detection"]["type"] == "server_vad"
    assert calls[0][3] == 15


def test_rejects_invalid_client_secret_response():
    def post(_url, *, headers, json, timeout):
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"client_secret": {"value": "   "}},
        )

    with pytest.raises(ValueError, match="client secret"):
        create_realtime_client_secret("server-key", post)


def test_final_events_are_deduplicated_and_get_a_timestamp():
    event = LiveTranscriptEvent("evt-1", "final_transcript", "矩陣", 62, 65)
    deduplicator = FinalEventDeduplicator()

    assert deduplicator.accept(event) is True
    assert deduplicator.accept(event) is False

    segment = final_event_to_segment(event, "session-1")

    assert segment.segment_id == "session-1:evt-1"
    assert segment.original_zh == "矩陣"
    assert segment.translation_en == ""
    assert segment.explanation_en == ""
    assert segment.timestamp == "[01:02 - 01:05]"


@pytest.mark.parametrize(
    ("event", "message"),
    [
        (LiveTranscriptEvent("evt-1", "partial_transcript", "矩", None, None), "final"),
        (LiveTranscriptEvent("evt-1", "final_transcript", "   ", 1, 2), "blank"),
        (LiveTranscriptEvent("evt-1", "final_transcript", "矩陣", None, 2), "timestamps"),
        (LiveTranscriptEvent("evt-1", "final_transcript", "矩陣", -1, 2), "negative"),
        (LiveTranscriptEvent("evt-1", "final_transcript", "矩陣", 3, 2), "range"),
    ],
)
def test_rejects_invalid_final_event_data(event, message):
    with pytest.raises(ValueError, match=message):
        final_event_to_segment(event, "session-1")


def test_rejects_blank_session_id():
    event = LiveTranscriptEvent("evt-1", "final_transcript", "矩陣", 1, 2)
    with pytest.raises(ValueError, match="Session ID"):
        final_event_to_segment(event, "   ")


@pytest.mark.parametrize("start,end", [(float("nan"), 2.0), (1.0, float("nan")), (float("inf"), 2.0), (1.0, float("inf"))])
def test_rejects_non_finite_timestamps(start, end):
    event = LiveTranscriptEvent("evt-1", "final_transcript", "矩陣", start, end)
    with pytest.raises(ValueError, match="finite"):
        final_event_to_segment(event, "session-1")