from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Callable, Literal

from audio_cleaner import format_timestamp_range
from transcription_service import TranscriptSegment


REALTIME_CLIENT_SECRETS_URL = "https://api.openai.com/v1/realtime/client_secrets"


@dataclass(frozen=True)
class LiveTranscriptEvent:
    event_id: str
    kind: Literal["partial_transcript", "final_transcript"]
    text: str
    start_seconds: float | None
    end_seconds: float | None


def create_realtime_client_secret(api_key: str, http_post: Callable[..., Any]) -> str:
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("API key is required to create a realtime client secret")

    response = http_post(
        REALTIME_CLIENT_SECRETS_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "session": {
                "type": "transcription",
                "audio": {
                    "input": {
                        "transcription": {
                            "model": "gpt-4o-transcribe",
                            "language": "zh",
                        },
                        "turn_detection": {
                            "type": "server_vad",
                        },
                    }
                },
            }
        },
        timeout=15,
    )
    response.raise_for_status()

    payload = response.json()
    secret = payload.get("client_secret", {}).get("value")
    if not isinstance(secret, str) or not secret.strip():
        raise ValueError("Realtime client secret response was invalid")
    return secret.strip()


class FinalEventDeduplicator:
    def __init__(self) -> None:
        self._seen_event_ids: set[str] = set()

    def accept(self, event: LiveTranscriptEvent) -> bool:
        if event.kind != "final_transcript":
            return True
        if event.event_id in self._seen_event_ids:
            return False
        self._seen_event_ids.add(event.event_id)
        return True


def final_event_to_segment(event: LiveTranscriptEvent, session_id: str) -> TranscriptSegment:
    if event.kind != "final_transcript":
        raise ValueError("Only final transcript events can be converted")

    text = event.text.strip()
    if not text:
        raise ValueError("Final transcript text cannot be blank")

    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Session ID is required")

    start_seconds = _validated_timestamp(event.start_seconds, "start")
    end_seconds = _validated_timestamp(event.end_seconds, "end")

    if end_seconds < start_seconds:
        raise ValueError("Final transcript time range is invalid")

    return TranscriptSegment(
        segment_id=f"{session_id}:{event.event_id}",
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        timestamp=format_timestamp_range(start_seconds, end_seconds),
        original_zh=text,
        translation_en="",
        explanation_en="",
    )


def _validated_timestamp(value: float | None, label: str) -> float:
    if value is None:
        raise ValueError("Final transcript timestamps are required")

    timestamp = float(value)
    if not isfinite(timestamp):
        raise ValueError("Final transcript timestamps must be finite numbers")
    if timestamp < 0:
        raise ValueError(f"Final transcript {label} time cannot be negative")
    return timestamp