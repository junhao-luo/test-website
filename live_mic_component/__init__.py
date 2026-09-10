from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

try:
    import streamlit.components.v1 as components
except ModuleNotFoundError:
    components = None


FRONTEND_BUILD_PATH = Path(__file__).resolve().parent / "frontend" / "dist"


def _missing_component(**_kwargs: Any) -> None:
    return None


try:
    if components is None:
        raise ModuleNotFoundError
    _component_func = components.declare_component("live_mic_component", path=str(FRONTEND_BUILD_PATH))
except Exception:
    _component_func = _missing_component


def live_mic_component(client_secret: str | None, command: str, key: str) -> dict[str, object] | None:
    value = _component_func(client_secret=client_secret, command=command, key=key, default=None)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("Component value must be a mapping with a string type")

    event_type = value.get("type")
    if not isinstance(event_type, str):
        raise ValueError("Component value must be a mapping with a string type")

    if event_type == "event_batch":
        events = value.get("events")
        if not isinstance(events, list):
            raise ValueError("event_batch must contain a list of events")
        for event in events:
            if not isinstance(event, Mapping) or not isinstance(event.get("type"), str) or not isinstance(event.get("event_id"), str):
                raise ValueError("event_batch events must be mappings with string type and event_id")

    return dict(value)


__all__ = ["live_mic_component"]