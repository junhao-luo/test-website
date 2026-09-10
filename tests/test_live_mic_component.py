from collections.abc import Mapping

import pytest

import live_mic_component


def test_live_mic_component_returns_none_when_browser_has_not_emitted_yet(monkeypatch):
    monkeypatch.setattr(live_mic_component, "_component_func", lambda **_kwargs: None)

    assert live_mic_component.live_mic_component(None, "idle", "mic") is None


def test_live_mic_component_returns_only_mapping_payloads_with_string_type(monkeypatch):
    monkeypatch.setattr(
        live_mic_component,
        "_component_func",
        lambda **_kwargs: {
            "type": "final_transcript",
            "event_id": "item-1",
            "text": "矩陣",
            "start_seconds": 2.0,
            "end_seconds": 3.5,
            "message": None,
        },
    )

    payload = live_mic_component.live_mic_component("secret", "start", "mic")

    assert isinstance(payload, Mapping)
    assert payload["type"] == "final_transcript"


def test_live_mic_component_accepts_event_batches_with_valid_events(monkeypatch):
    monkeypatch.setattr(
        live_mic_component,
        "_component_func",
        lambda **_kwargs: {
            "type": "event_batch",
            "events": [{"type": "partial_transcript", "event_id": "item-1"}],
        },
    )

    assert live_mic_component.live_mic_component("secret", "start", "mic")["type"] == "event_batch"


def test_live_mic_component_rejects_malformed_event_batches(monkeypatch):
    monkeypatch.setattr(
        live_mic_component,
        "_component_func",
        lambda **_kwargs: {"type": "event_batch", "events": [{"type": 7}]},
    )

    with pytest.raises(ValueError, match="event"):
        live_mic_component.live_mic_component("secret", "start", "mic")


@pytest.mark.parametrize("browser_value", [[], {"type": 7}, "final_transcript"])
def test_live_mic_component_rejects_malformed_component_payloads(monkeypatch, browser_value):
    monkeypatch.setattr(live_mic_component, "_component_func", lambda **_kwargs: browser_value)

    with pytest.raises(ValueError, match="mapping"):
        live_mic_component.live_mic_component("secret", "start", "mic")