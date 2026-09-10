# Live Realtime Bilingual Lecture Companion Design

## Purpose

Extend the local Streamlit lecture companion so an international student can listen to a Mandarin lecture through the browser microphone and receive low-latency, automatically segmented Traditional Chinese transcription, English translation, and a brief academic explanation. Finalized segments remain available in the selected course's cited, semester-long RAG chat.

## Scope

The first live release is a single-user local application. It captures microphone audio in the browser, creates a short-lived OpenAI Realtime session through the local application, and displays partial captions followed by finalized, translated, and explained speech segments. The application continues to support audio/PDF ingestion, course management, Chroma persistence, and course-scoped chat from the prior design.

The release does not implement authentication, multi-user sharing, cloud storage, speaker diarization, background processing, or system-audio capture. It records only browser microphone input after explicit permission.

## Architecture

### Local application boundary

`app.py` remains the Streamlit orchestration layer. It resolves `OPENAI_API_KEY` from the environment before `st.secrets["OPENAI_API_KEY"]`, validates that a key exists before starting a live session, renders the selected-course UI, and owns the session's finalized records.

A local credential endpoint accepts no user-provided OpenAI credentials. It reads the server-side API key and creates an ephemeral Realtime client secret with the transcription configuration. It returns only the temporary credential to the browser component. The browser must never receive `OPENAI_API_KEY`.

### Browser microphone component

A custom Streamlit component owns microphone permission and the OpenAI Realtime WebRTC or WebSocket media connection. It establishes the connection with the ephemeral credential, streams microphone audio continuously, and sends structured events to Streamlit:

- `session_started` after Realtime confirms the session;
- `partial_transcript` for unstable in-progress captions;
- `final_transcript` when Realtime identifies a completed speech segment;
- `session_error` for denied permission, setup failure, disconnect, or unrecoverable API failure;
- `session_stopped` after the user stops capture and all pending final events are delivered.

The component renders no API key and does not persist raw microphone audio. The UI exposes Start and Stop controls and a connection state. It shows the partial caption in a dedicated transient region. Final segments append below it and never change after rendering.

### Realtime transcription

The credential endpoint configures the Realtime transcription session for Mandarin / Traditional Chinese capture and server voice-activity detection. OpenAI determines speech turns, so a pause finalizes one segment without a fixed client-side time window. The component forwards only final transcript events for durable processing.

Each final event is normalized as a `LiveTranscriptSegment` containing a stable session-local identifier, start/end time, `[MM:SS - MM:SS]` timestamp, original Traditional Chinese transcript, English translation, and explanation. The application assigns an identifier before translation and de-duplicates finalized events by that identifier to tolerate reconnect replay.

### Translation and explanation

For each final transcript, the local application calls `gpt-4o` once with structured JSON output. The response contains the source identifier, a formal English translation, and a concise explanation suitable for an international student. Instructions preserve formulas, code, and technical terms; meaningful Traditional Chinese terminology remains beside its English equivalent.

Only finalized Mandarin source text is translated and explained. A failed translation does not discard the final transcript: it is shown with an actionable error and can be retried. A response with a missing or mismatched identifier is rejected and never indexed.

### Persistence and retrieval

The selected active course and date are locked when a live session starts. Finalized, successfully translated segments remain in session state during capture. On Stop, the application uses the existing `LectureDatabase.index_transcript` path to upsert them into ChromaDB with deterministic IDs, standard transcript metadata, and their final timestamps.

The course registry and Chroma behavior are unchanged:

- Chroma uses `chromadb.PersistentClient(path="./chroma_db")`.
- Transcript metadata contains `course_id`, `course_name_zh`, `date`, `type`, `timestamp`, and `page`.
- Retrieval always includes `where={"course_id": selected_course_id}`.
- Cited chat searches all indexed dates for only the active course.

## User Flow

1. The user selects an active course and lecture date, then chooses `Start live session`.
2. The app validates local credentials and requests an ephemeral Realtime credential.
3. The browser requests microphone permission and opens the Realtime session.
4. A transient caption updates while speech is in progress.
5. When Realtime finalizes a speech turn, the UI appends the immutable Chinese transcript, English translation, and automatic explanation.
6. The user may stop the session. The app waits for pending final events, indexes all successfully translated segments under the locked course/date, and reports the indexed count.
7. Course-scoped chat can retrieve these newly indexed segments with the existing timestamp citation format.

## Failure Handling

- Missing OpenAI credentials block session start before an ephemeral credential is requested.
- Microphone permission denial leaves the session inactive and gives a clear browser-facing error.
- Credential creation, Realtime setup, and connection failures leave no partial documents indexed and allow the user to retry from an inactive state.
- A dropped connection retains already finalized segments in the UI. The user can reconnect as a new live session; duplicate finalized identifiers are ignored within each session.
- Translation failures retain the source transcript, display the failure, and exclude that item from indexing until a retry returns a valid identifier-aligned result.
- Stop waits for queued final transcripts and translation requests to settle. The selected course/date cannot be changed during this draining phase.
- Browser refresh ends the active capture. Finalized translated records already stored in Streamlit session state are indexed only if the Stop action completes; no raw audio is recoverable.

## Components And Interfaces

- `realtime_session.py`: creates ephemeral Realtime sessions, validates client-secret responses, maps Realtime final events to `LiveTranscriptSegment`, and de-duplicates event IDs.
- `translation_service.py`: translates and explains one finalized segment with identifier-validated structured GPT-4o output.
- `database.py`: accepts normalized live segments through the existing transcript indexing interface without a second vector schema.
- `app.py`: provides the credential endpoint, controls state transitions, locks course/date during capture, queues translation work, renders partial/final views, and indexes results on stop.
- `live_mic_component/`: custom frontend component that requests the mic, manages the Realtime media connection, and emits the defined events to Streamlit.

## Testing And Validation

Unit tests inject fakes at all OpenAI boundaries and do not make live calls. They cover ephemeral credential request formation and secret extraction, Realtime event parsing, duplicate final-event suppression, timestamp normalization, translation/explanation identifier validation, session state transitions, locked course/date behavior, translation retry, and indexing only successfully translated final segments.

The browser component has a mocked Realtime integration test for Start, partial transcript, final transcript, Stop, and error event handling. A manual smoke test runs Streamlit with a configured API key, grants microphone access in a supported browser, verifies a Mandarin speech turn appears as a final Chinese transcript with English translation/explanation, stops the session, and confirms that a course-scoped chat question retrieves it with an audio timestamp citation.