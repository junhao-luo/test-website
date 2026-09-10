# Task 3 Report — Transcription & Timestamp Validation

Summary:
- The frontend is responsible for producing locally-monotonic timestamps across emitted events (local monotonicity belongs to the audio capture/encoder/JS component).
- The Python service (`final_event_to_segment`) performs defensive validation only: it checks that session IDs are present, timestamps are provided, are finite numbers, are non-negative, and that `end >= start`. It does not enforce cross-event monotonicity or sequence ordering.

Rationale:
- Monotonic timestamp production is a runtime concern tied to the environment that captures and emits events (latency, buffering, and clock drift). The ledger ruling delegates that responsibility to the frontend.
- The backend's role is to validate and canonicalize the values it receives. Tests verify these defensive checks (blank session ID, missing timestamps, negative or non-finite values, and invalid ranges).

Location of validation code: `realtime_session.py` (`final_event_to_segment` and `_validated_timestamp`).

Tests updated to cover these validations: `tests/test_realtime_session.py`.
