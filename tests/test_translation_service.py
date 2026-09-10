import json
from types import SimpleNamespace

import pytest

from transcription_service import TranscriptSegment
from translation_service import TranslationAlignmentError, translate_and_explain


def source() -> TranscriptSegment:
    return TranscriptSegment("live-7", 3, 5, "[00:03 - 00:05]", "遞迴", "")


def client_for(payload):
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])

    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return response

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), calls


def test_translates_and_explains_a_final_segment():
    src = source()
    client, calls = client_for({"id": "live-7", "translation": "Recursion", "explanation": "A function calls itself."})

    result = translate_and_explain(client, src)

    assert result.translation_en == "Recursion"
    assert result.explanation_en == "A function calls itself."

    # Preserve source metadata
    assert result.segment_id == src.segment_id
    assert result.start_seconds == src.start_seconds
    assert result.end_seconds == src.end_seconds
    assert result.timestamp == src.timestamp
    assert result.original_zh == src.original_zh

    # Assert the model was called exactly once and recorded the kwargs
    assert len(calls) == 1
    req = calls[0]
    assert req.get("model") == "gpt-4o"
    assert req.get("response_format") == {"type": "json_object"}

    messages = req.get("messages")
    assert isinstance(messages, list)
    user_msg = next((m for m in messages if m.get("role") == "user"), None)
    assert user_msg is not None
    payload = json.loads(user_msg.get("content"))
    assert payload.get("id") == src.segment_id
    assert payload.get("text") == src.original_zh


def test_rejects_misaligned_model_response():
    with pytest.raises(TranslationAlignmentError, match="identifier"):
        client, calls = client_for({"id": "other", "translation": "Recursion", "explanation": ""})
        translate_and_explain(
            client,
            source(),
        )
