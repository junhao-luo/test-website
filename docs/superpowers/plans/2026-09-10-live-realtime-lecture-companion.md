# Live Realtime Bilingual Lecture Companion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Streamlit lecture companion with browser-microphone Realtime transcription, automatic English translation and explanation, and course-scoped, cited retrieval.

**Architecture:** A small, independently testable Python service layer owns OpenAI credentials, Realtime client-secret creation, finalized segment normalization, translation, and Chroma persistence. A custom Streamlit component owns browser microphone permission and the Realtime WebRTC connection; it emits partial and finalized transcript events. `app.py` coordinates the component, locks the active course/date during capture, translates finalized segments, and indexes only successful translations after Stop.

**Tech Stack:** Python 3.11+, Streamlit, OpenAI Python SDK, ChromaDB, pydub/FFmpeg, NumPy, noisereduce, pypdf, pytest, TypeScript, Vite, and the Streamlit component protocol.

**Spec:** [docs/superpowers/specs/2026-09-10-live-realtime-lecture-companion-design.md](../specs/2026-09-10-live-realtime-lecture-companion-design.md)

## Global Constraints

- Read `OPENAI_API_KEY` from the environment before `st.secrets["OPENAI_API_KEY"]`.
- Never expose `OPENAI_API_KEY` to the browser; mint a short-lived Realtime client secret locally.
- Configure Realtime for Mandarin transcription with server voice-activity detection; persist only finalized speech turns.
- Render partial captions transiently; finalized source text, translation, and explanation are immutable.
- Persist no raw microphone audio.
- Store Chroma data with `chromadb.PersistentClient(path="./chroma_db")`.
- Metadata must contain `course_id`, `course_name_zh`, `date`, `type`, `timestamp`, and `page`.
- Every retrieval call must include `where={"course_id": selected_course_id}`.
- Do not make live OpenAI calls in automated tests.
- Do not commit changes unless the user explicitly asks for a commit.

---

## File Structure

- `requirements.txt`: pinned Python dependencies, including a current OpenAI SDK supporting client-secret creation.
- `audio_cleaner.py`: existing file-audio normalization and upload chunking; retain its public API.
- `transcription_service.py`: file-upload Whisper normalization and batch English translation.
- `realtime_session.py`: Realtime client-secret request, transcript event normalization, and duplicate suppression.
- `translation_service.py`: identifier-validated finalized-segment translation and explanation.
- `database.py`: registry plus Chroma document indexing, PDF extraction, and strict course-scoped retrieval.
- `app.py`: API-key resolution, Streamlit app, live session state machine, ingestion, and cited tutor chat.
- `live_mic_component/__init__.py`: declared component wrapper and typed event boundary.
- `live_mic_component/frontend/`: Vite/TypeScript browser component that captures the mic and maintains WebRTC.
- `tests/test_audio_cleaner.py`: existing audio helper coverage.
- `tests/test_transcription_service.py`: Whisper and translation alignment coverage.
- `tests/test_realtime_session.py`: client-secret, event, timestamp, and duplicate behavior.
- `tests/test_translation_service.py`: translation/explanation validation coverage.
- `tests/test_database.py`: registry, metadata, PDF, and course-filtered Chroma coverage.
- `tests/test_app_helpers.py`: credentials, session state, final-segment indexing, and citation coverage.
- `README.md`: setup, FFmpeg, API key, and live microphone smoke-test instructions.

### Task 1: Establish Shared Transcript Types And File Transcription

**Files:**
- Create: `transcription_service.py`
- Modify: `tests/test_transcription_service.py`

**Interfaces:**
- Produces: `TranscriptSegment(segment_id: str, start_seconds: float, end_seconds: float, timestamp: str, original_zh: str, translation_en: str, explanation_en: str = "")`.
- Produces: `normalize_whisper_segments(raw_segments: list[dict], chunk_index: int, offset_ms: int) -> list[TranscriptSegment]`.
- Produces: `transcribe_chunk(client: OpenAI, chunk: AudioChunk) -> list[TranscriptSegment]`.

- [ ] **Step 1: Extend the failing normalization test**

```python
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

    assert transcribe_chunk(client, AudioChunk(path, 0, 0, 1))[0].original_zh == "矩陣"
    assert calls[0]["model"] == "whisper-1"
    assert calls[0]["timestamp_granularities"] == ["segment"]
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `pytest tests/test_transcription_service.py -v`

Expected: FAIL because `transcription_service.py` does not exist.

- [ ] **Step 3: Implement the shared segment and Whisper boundary**

```python
@dataclass(frozen=True)
class TranscriptSegment:
    segment_id: str
    start_seconds: float
    end_seconds: float
    timestamp: str
    original_zh: str
    translation_en: str
    explanation_en: str = ""


def transcribe_chunk(client: OpenAI, chunk: AudioChunk) -> list[TranscriptSegment]:
    with chunk.path.open("rb") as audio_file:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    return normalize_whisper_segments(list(response.segments), chunk.index, chunk.offset_ms)
```

Use `format_timestamp_range` from `audio_cleaner.py`, add `offset_ms / 1000` to every source time, strip blank Whisper text, and skip blank segments.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `pytest tests/test_transcription_service.py -v`

Expected: PASS.

- [ ] **Step 5: Inspect this slice without committing**

Run: `git diff -- transcription_service.py tests/test_transcription_service.py`

Expected: Only the reusable segment type, Whisper adapter, and its tests are changed.

### Task 2: Add Final-Segment Translation And Explanation

**Files:**
- Create: `translation_service.py`
- Create: `tests/test_translation_service.py`

**Interfaces:**
- Consumes: `TranscriptSegment` from `transcription_service.py`.
- Produces: `translate_and_explain(client: OpenAI, segment: TranscriptSegment) -> TranscriptSegment`.
- Produces: `TranslationAlignmentError(ValueError)` for blank, missing, duplicate, or mismatched identifiers.

- [ ] **Step 1: Write failing validation tests**

```python
import json
from types import SimpleNamespace

import pytest

from transcription_service import TranscriptSegment
from translation_service import TranslationAlignmentError, translate_and_explain


def source() -> TranscriptSegment:
    return TranscriptSegment("live-7", 3, 5, "[00:03 - 00:05]", "遞迴", "")


def client_for(payload):
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_kwargs: response)))


def test_translates_and_explains_a_final_segment():
    result = translate_and_explain(client_for({"id": "live-7", "translation": "Recursion", "explanation": "A function calls itself."}), source())

    assert result.translation_en == "Recursion"
    assert result.explanation_en == "A function calls itself."


def test_rejects_misaligned_model_response():
    with pytest.raises(TranslationAlignmentError, match="identifier"):
        translate_and_explain(client_for({"id": "other", "translation": "Recursion", "explanation": ""}), source())
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `pytest tests/test_translation_service.py -v`

Expected: FAIL because `translation_service.py` does not exist.

- [ ] **Step 3: Implement one-call structured translation**

```python
def translate_and_explain(client: OpenAI, segment: TranscriptSegment) -> TranscriptSegment:
    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": TRANSLATION_EXPLANATION_PROMPT},
            {"role": "user", "content": json.dumps({"id": segment.segment_id, "text": segment.original_zh}, ensure_ascii=False)},
        ],
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    if payload.get("id") != segment.segment_id or not isinstance(payload.get("translation"), str) or not isinstance(payload.get("explanation"), str):
        raise TranslationAlignmentError("Response identifier or required text is invalid")
    return replace(segment, translation_en=payload["translation"].strip(), explanation_en=payload["explanation"].strip())
```

Make the system prompt require formal English, preservation of formulas/code, and Traditional Chinese terms alongside meaningful English technical equivalents. Reject empty translations.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `pytest tests/test_translation_service.py -v`

Expected: PASS.

- [ ] **Step 5: Inspect this slice without committing**

Run: `git diff -- translation_service.py tests/test_translation_service.py`

Expected: Only final-segment translation/explanation and its validation tests are changed.

### Task 3: Build the Realtime Credential And Event Service

**Files:**
- Create: `realtime_session.py`
- Create: `tests/test_realtime_session.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `LiveTranscriptEvent(event_id: str, kind: Literal["partial_transcript", "final_transcript"], text: str, start_seconds: float | None, end_seconds: float | None)`.
- Produces: `create_realtime_client_secret(api_key: str, http_post: Callable[..., Any]) -> str`.
- Produces: `FinalEventDeduplicator.accept(event: LiveTranscriptEvent) -> bool`.
- Produces: `final_event_to_segment(event: LiveTranscriptEvent, session_id: str) -> TranscriptSegment`.

- [ ] **Step 1: Write failing Realtime boundary tests**

```python
from types import SimpleNamespace

from realtime_session import FinalEventDeduplicator, LiveTranscriptEvent, create_realtime_client_secret, final_event_to_segment


def test_requests_a_mandarin_vad_transcription_client_secret():
    calls = []

    def post(url, *, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"client_secret": {"value": "ephemeral"}})

    assert create_realtime_client_secret("server-key", post) == "ephemeral"
    assert calls[0][1]["Authorization"] == "Bearer server-key"
    assert calls[0][2]["session"]["audio"]["input"]["transcription"]["language"] == "zh"
    assert calls[0][2]["session"]["audio"]["input"]["turn_detection"]["type"] == "server_vad"


def test_final_events_are_deduplicated_and_get_a_timestamp():
    event = LiveTranscriptEvent("evt-1", "final_transcript", "矩陣", 62, 65)
    deduplicator = FinalEventDeduplicator()

    assert deduplicator.accept(event) is True
    assert deduplicator.accept(event) is False
    assert final_event_to_segment(event, "session-1").timestamp == "[01:02 - 01:05]"
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `pytest tests/test_realtime_session.py -v`

Expected: FAIL because `realtime_session.py` does not exist.

- [ ] **Step 3: Implement secret creation, validation, and event conversion**

```python
REALTIME_CLIENT_SECRETS_URL = "https://api.openai.com/v1/realtime/client_secrets"


def create_realtime_client_secret(api_key: str, http_post: Callable[..., Any]) -> str:
    response = http_post(
        REALTIME_CLIENT_SECRETS_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"session": {"type": "transcription", "audio": {"input": {"transcription": {"model": "gpt-4o-transcribe", "language": "zh"}, "turn_detection": {"type": "server_vad"}}}}},
        timeout=15,
    )
    response.raise_for_status()
    secret = response.json().get("client_secret", {}).get("value")
    if not isinstance(secret, str) or not secret.strip():
        raise ValueError("Realtime client secret response was invalid")
    return secret
```

Require `requests` in `requirements.txt`. `final_event_to_segment` rejects partial events, blank text, missing/negative timestamps, and inverted ranges; it creates `f"{session_id}:{event.event_id}"` IDs and uses `format_timestamp_range`.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `pytest tests/test_realtime_session.py -v`

Expected: PASS.

- [ ] **Step 5: Inspect this slice without committing**

Run: `git diff -- requirements.txt realtime_session.py tests/test_realtime_session.py`

Expected: Only Realtime service dependencies, code, and tests are changed.

### Task 4: Complete Chroma Indexing And Course-Isolated Retrieval

**Files:**
- Modify: `database.py`
- Modify: `tests/test_database.py`

**Interfaces:**
- Produces: `RetrievedDocument(document: str, metadata: dict[str, Any], distance: float)`.
- Produces: `LectureDatabase(collection: Any, registry: CourseRegistry)` with `index_transcript(course_id: str, lecture_date: str, segments: list[TranscriptSegment]) -> None`, `index_pdf(course_id: str, lecture_date: str, pdf_path: Path) -> int`, and `retrieve(course_id: str, question: str, limit: int = 8) -> list[RetrievedDocument]`.

- [ ] **Step 1: Write failing live-segment metadata and retrieval tests**

```python
from dataclasses import dataclass, field

from database import CourseRegistry, LectureDatabase
from transcription_service import TranscriptSegment


@dataclass
class FakeCollection:
    rows: dict = field(default_factory=dict)
    last_where: dict | None = None

    def upsert(self, *, ids, documents, metadatas):
        self.rows.update(dict(zip(ids, zip(documents, metadatas))))

    def query(self, *, where, **_kwargs):
        self.last_where = where
        values = [value for value in self.rows.values() if value[1]["course_id"] == where["course_id"]]
        return {"documents": [[value[0] for value in values]], "metadatas": [[value[1] for value in values]], "distances": [[0.0] * len(values)]}


def test_indexes_explained_live_segment_and_filters_by_course(tmp_path):
    collection = FakeCollection()
    database = LectureDatabase(collection, CourseRegistry(tmp_path / "courses.json"))
    segment = TranscriptSegment("session:evt", 3, 5, "[00:03 - 00:05]", "遞迴", "Recursion", "A function calls itself.")

    database.index_transcript("intro_cs", "2026-09-10", [segment])
    results = database.retrieve("intro_cs", "What is recursion?")

    assert "Explanation: A function calls itself." in results[0].document
    assert results[0].metadata["timestamp"] == "[00:03 - 00:05]"
    assert collection.last_where == {"course_id": "intro_cs"}
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `pytest tests/test_database.py -v`

Expected: FAIL because the Chroma document interfaces are not implemented.

- [ ] **Step 3: Implement deterministic document storage and retrieval**

```python
def index_transcript(self, course_id: str, lecture_date: str, segments: list[TranscriptSegment]) -> None:
    course = self.registry.get_course(course_id)
    self.collection.upsert(
        ids=[f"{course_id}:{lecture_date}:audio:{segment.segment_id}" for segment in segments],
        documents=[f"Traditional Chinese: {segment.original_zh}\nEnglish: {segment.translation_en}\nExplanation: {segment.explanation_en}" for segment in segments],
        metadatas=[self._metadata(course, lecture_date, "audio_transcript", segment.timestamp, 0) for segment in segments],
    )
```

Create the persistent Chroma client and an OpenAI `text-embedding-3-small` adapter in an application factory. Add page-level PDF extraction. Map the Chroma query response to `RetrievedDocument`, using the exact `where={"course_id": course_id}` filter.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `pytest tests/test_database.py -v`

Expected: PASS.

- [ ] **Step 5: Inspect this slice without committing**

Run: `git diff -- database.py tests/test_database.py`

Expected: Only course registry-compatible indexing, extraction, retrieval, and tests are changed.

### Task 5: Create the Browser Realtime Microphone Component

**Files:**
- Create: `live_mic_component/__init__.py`
- Create: `live_mic_component/frontend/package.json`
- Create: `live_mic_component/frontend/tsconfig.json`
- Create: `live_mic_component/frontend/index.html`
- Create: `live_mic_component/frontend/src/main.ts`
- Create: `live_mic_component/frontend/src/main.test.ts`

**Interfaces:**
- Produces: `live_mic_component(client_secret: str | None, command: str, key: str) -> dict[str, object] | None`.
- Produces browser events shaped as `{ "type": "session_started" | "partial_transcript" | "final_transcript" | "session_error" | "session_stopped", "event_id": string, "text": string, "start_seconds": number | null, "end_seconds": number | null, "message": string | null }`.

- [ ] **Step 1: Write failing browser event-adapter tests**

```typescript
import { eventForTranscript, eventForError } from "./main";

test("maps partial and completed Realtime transcript events", () => {
  expect(eventForTranscript({ type: "conversation.item.input_audio_transcription.delta", item_id: "item-1", delta: "矩" })).toMatchObject({
    type: "partial_transcript", event_id: "item-1", text: "矩",
  });
  expect(eventForTranscript({ type: "conversation.item.input_audio_transcription.completed", item_id: "item-1", transcript: "矩陣", audio_start_ms: 2000, audio_end_ms: 3500 })).toEqual({
    type: "final_transcript", event_id: "item-1", text: "矩陣", start_seconds: 2, end_seconds: 3.5,
  });
});

test("converts browser errors to safe component events", () => {
  expect(eventForError(new Error("Permission denied"))).toEqual({ type: "session_error", message: "Permission denied" });
});
```

- [ ] **Step 2: Run the frontend test and verify it fails**

Run: `npm test --prefix live_mic_component/frontend -- --run`

Expected: FAIL because the frontend project does not exist.

- [ ] **Step 3: Implement the component wrapper and frontend**

In `__init__.py`, call `components.declare_component("live_mic_component", path=str(FRONTEND_BUILD_PATH))` and return the component value only after verifying it is a mapping with a string `type`.

In `main.ts`, use the Streamlit component API to receive `client_secret` and `command`. On `start`, call `navigator.mediaDevices.getUserMedia({ audio: true })`, create a WebRTC peer connection, send the local microphone track, exchange SDP with the current OpenAI Realtime WebRTC endpoint using the ephemeral credential, and listen on the data channel for transcription events. Use `Streamlit.setComponentValue(...)` to emit the normalized events. On `stop`, close audio tracks, data channel, and peer connection, then emit `session_stopped`. Never log or render the client secret.

Export pure `eventForTranscript` and `eventForError` functions for Vitest. Set component height deterministically and call `Streamlit.setFrameHeight` after state changes.

- [ ] **Step 4: Run the frontend test and build the bundle**

Run: `npm test --prefix live_mic_component/frontend -- --run; npm run build --prefix live_mic_component/frontend`

Expected: PASS and a deployable `frontend/dist` bundle is produced.

- [ ] **Step 5: Inspect this slice without committing**

Run: `git diff -- live_mic_component`

Expected: The component has no server API key, and its event contract matches this task exactly.

### Task 6: Implement Live Session State And Streamlit Integration

**Files:**
- Create: `app.py`
- Create: `tests/test_app_helpers.py`

**Interfaces:**
- Produces: `get_openai_api_key(environment: Mapping[str, str], secrets: Mapping[str, str]) -> str | None`.
- Produces: `LiveSessionState(session_id: str, course_id: str, lecture_date: str, status: Literal["inactive", "connecting", "recording", "stopping", "failed"], partial_text: str, finalized: list[TranscriptSegment], failed: dict[str, str], seen_events: set[str])`.
- Produces: `handle_live_event(state: LiveSessionState, event: LiveTranscriptEvent, openai_client: OpenAI) -> LiveSessionState`.
- Produces: `stop_and_index_live_session(state: LiveSessionState, database: LectureDatabase) -> int`.

- [ ] **Step 1: Write failing session-state and indexing tests**

```python
from dataclasses import replace
from types import SimpleNamespace

from app import LiveSessionState, handle_live_event, stop_and_index_live_session
from realtime_session import LiveTranscriptEvent
from transcription_service import TranscriptSegment


def test_final_event_is_translated_once_and_partial_text_is_cleared(monkeypatch):
    state = LiveSessionState("s1", "intro_cs", "2026-09-10", "recording", "in progress", [], {}, set())
    event = LiveTranscriptEvent("evt-1", "final_transcript", "遞迴", 3, 5)
    monkeypatch.setattr("app.final_event_to_segment", lambda *_args: TranscriptSegment("s1:evt-1", 3, 5, "[00:03 - 00:05]", "遞迴", ""))
    monkeypatch.setattr("app.translate_and_explain", lambda _client, segment: replace(segment, translation_en="Recursion", explanation_en="A function calls itself."))

    updated = handle_live_event(state, event, SimpleNamespace())

    assert updated.partial_text == ""
    assert [segment.segment_id for segment in updated.finalized] == ["s1:evt-1"]
    assert handle_live_event(updated, event, SimpleNamespace()).finalized == updated.finalized


def test_stop_indexes_only_successfully_translated_segments():
    ready = TranscriptSegment("s1:ready", 0, 1, "[00:00 - 00:01]", "原文", "Translation", "Explanation")
    database = SimpleNamespace(calls=[], index_transcript=lambda *args: database.calls.append(args))
    state = LiveSessionState("s1", "intro_cs", "2026-09-10", "stopping", "", [ready], {"s1:failed": "retry needed"}, set())

    assert stop_and_index_live_session(state, database) == 1
    assert database.calls == [("intro_cs", "2026-09-10", [ready])]
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `pytest tests/test_app_helpers.py -v`

Expected: FAIL because `app.py` does not exist.

- [ ] **Step 3: Implement pure session helpers and the Streamlit app**

```python
def handle_live_event(state: LiveSessionState, event: LiveTranscriptEvent, openai_client: OpenAI) -> LiveSessionState:
    if event.kind == "partial_transcript":
        return replace(state, partial_text=event.text)
    if event.event_id in state.seen_events:
        return state
    segment = final_event_to_segment(event, state.session_id)
    try:
        translated = translate_and_explain(openai_client, segment)
    except TranslationAlignmentError as error:
        return replace(state, partial_text="", seen_events=state.seen_events | {event.event_id}, failed={**state.failed, segment.segment_id: str(error)})
    return replace(state, partial_text="", seen_events=state.seen_events | {event.event_id}, finalized=[*state.finalized, translated])
```

Use `st.session_state` for a single `LiveSessionState`. Begin capture only after API-key resolution and client-secret creation succeeds. Lock the course selector and date control unless state is `inactive` or `failed`. Render a transient partial-caption region, finalized Chinese/English/explanation rows, a retry action for failed identifiers, and a Stop action. Only index on Stop, through `stop_and_index_live_session`; leave failed segments visible but excluded. Retain existing file/PDF ingestion and course-scoped chat in the same app entry point.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `pytest tests/test_app_helpers.py -v`

Expected: PASS.

- [ ] **Step 5: Run the full Python suite**

Run: `pytest -v`

Expected: PASS with no network calls.

### Task 7: Document Setup And Perform End-to-End Validation

**Files:**
- Create: `README.md`
- Modify: `tests/test_app_helpers.py`

**Interfaces:**
- Produces: local installation and supported-browser instructions for the executable Streamlit application.

- [ ] **Step 1: Write the failing documentation test**

```python
from pathlib import Path


def test_readme_documents_live_microphone_requirements():
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "OPENAI_API_KEY" in readme
    assert "FFmpeg" in readme
    assert "streamlit run app.py" in readme
    assert "microphone" in readme.lower()
    assert "chroma_db" in readme
```

- [ ] **Step 2: Run the documentation test and verify it fails**

Run: `pytest tests/test_app_helpers.py::test_readme_documents_live_microphone_requirements -v`

Expected: FAIL because `README.md` does not exist.

- [ ] **Step 3: Write the concise local-run documentation**

Document Python environment creation, `pip install -r requirements.txt`, `npm install` and `npm run build` for the component, FFmpeg installation/PATH, environment-based API-key setup, `streamlit run app.py`, Chrome/Edge microphone permission, ephemeral credential safety, and backup locations for `course_registry.json` and `chroma_db`.

- [ ] **Step 4: Run final automated validation**

Run: `pytest -v; npm test --prefix live_mic_component/frontend -- --run; npm run build --prefix live_mic_component/frontend; git diff --check`

Expected: All Python/frontend tests and component build pass; `git diff --check` reports no whitespace errors.

- [ ] **Step 5: Run the manual live smoke test without committing**

Run: `streamlit run app.py`

Expected: With `OPENAI_API_KEY` configured, the browser can grant microphone access, a Mandarin utterance displays a transient caption then an immutable Chinese transcript with English translation/explanation, Stop indexes the successful segment, and course-scoped chat retrieves it with `[Date: YYYY-MM-DD | Audio Timestamp: MM:SS]`.

Run: `git status --short`

Expected: Only the planned application, test, frontend component, documentation, and specification files are modified or untracked.

## Plan Self-Review

- **Spec coverage:** Tasks 3 and 5 enforce the ephemeral-credential and browser Realtime boundary; Tasks 2 and 6 implement automatic explanation, retry, and immutable final segments; Task 4 implements course-isolated persistence/retrieval; Task 7 validates the actual microphone workflow.
- **Placeholder scan:** No task uses deferred implementation markers or unspecified test coverage.
- **Type consistency:** `TranscriptSegment` is the common durable record from file ingestion, Realtime final events, translation, Chroma indexing, and session state. `LiveTranscriptEvent` remains the transient component protocol type.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-10-live-realtime-lecture-companion.md`.

Two execution options:

1. **Subagent-Driven (recommended):** Dispatch a fresh subagent per task and review between tasks.
2. **Inline Execution:** Execute tasks in this session using `executing-plans`, with checkpoints for review.