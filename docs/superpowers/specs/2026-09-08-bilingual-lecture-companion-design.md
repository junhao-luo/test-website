# Bilingual Academic Lecture Companion Design

## Purpose

Provide a local Streamlit application for an international student at Feng Chia University to preserve, translate, search, and discuss lecture materials across their degree. The application processes Mandarin classroom audio and teacher PDFs, retains source-specific citations, and searches only the currently selected course.

## Scope

The first release is a synchronous local application. The browser remains open during ingestion and displays stage-level progress. ChromaDB data persists under `./chroma_db`; uploaded source files are staged temporarily and removed after processing. The application does not implement authentication, multi-user sharing, cloud storage, background workers, or a custom recording interface.

## Course Roster

The application seeds the following First Year, Semester 1 roster on its first run:

| Course ID | Course name (Traditional Chinese) | English name |
| --- | --- | --- |
| `pe_1` | `體育(一)` | Physical Education I |
| `chinese_expression_1` | `中文思辨與表達(一)` | Chinese Critical Thinking and Expression I |
| `college_english_1` | `大學基礎英文(一)` | College Basic English I |
| `intro_cs` | `電腦科學概論` | Introduction to Computer Science |
| `industry_ai_seminar` | `產業科技創新與AI應用專題` | Industrial Tech Innovation & AI Applications Seminar |
| `ai_math_1` | `AI基礎數學(一)` | Foundations of AI Mathematics I |
| `programming_1` | `基礎程式設計(一)` | Fundamental Programming I |

Courses are stored in a persistent local registry at `./course_registry.json`. Each record contains a stable `course_id`, Traditional Chinese name, optional English name, and editable term label such as `First Year / Semester 1`. The sidebar offers course-management controls to add a course or edit its display names and term label for future semesters.

`course_id` is generated from a user-supplied or normalized title when a course is created and remains immutable after materials are indexed. This protects Chroma partitions and avoids orphaned lecture records. The course manager can archive a course to remove it from the default selector without deleting its semester history; archived courses remain recoverable through the manager.

## Components

### `audio_cleaner.py`

This module accepts uploaded `.mp3`, `.m4a`, and `.wav` lecture audio and requires FFmpeg through pydub. It performs these operations in order:

1. Load the recording and convert it to mono, 16,000 Hz audio.
2. Convert samples to a NumPy signal and apply `noisereduce` spectral gating.
3. Rebuild an audio segment and export a 32 kbps MP3 derivative.
4. Split the compressed derivative when it exceeds the OpenAI 25 MB request limit. Chunks are 12 minutes with a two-second overlap and retain their original start offset in milliseconds.

Returned chunk objects contain a file path, sequential chunk index, start offset, and duration. Segment timestamps from Whisper are adjusted by the chunk offset before persistence. The two-second overlap can yield duplicate nearby text, which retrieval tolerates through semantic ranking and stable per-segment identifiers.

### `transcription_service.py`

The service accepts a cleaned chunk and an injected OpenAI client. It calls `whisper-1` with `response_format="verbose_json"` and segment timestamp granularity. It normalizes each segment into a structured record with absolute start/end seconds and a `[MM:SS - MM:SS]` timestamp.

Translation requests batch sequential segments to GPT-4o. The system instructions require formal technical English, retain Traditional Chinese terminology beside its English equivalent where meaningful, preserve formulas and code, and return every segment against its source identifier. The service rejects missing, duplicate, or mismatched segment identifiers rather than indexing an unreliable alignment.

### `database.py`

The database module creates `chromadb.PersistentClient(path="./chroma_db")` and a single named collection. It uses OpenAI `text-embedding-3-small` through an embedding adapter. The module reads and maintains the persistent course registry, validates each selected active course, builds deterministic record IDs, upserts documents, extracts PDF text page by page with `pypdf`, and retrieves semantic matches.

All stored records include these metadata fields:

| Field | Transcript value | PDF value |
| --- | --- | --- |
| `course_id` | stable registry ID | stable registry ID |
| `course_name_zh` | registry title | registry title |
| `date` | selected `YYYY-MM-DD` | selected `YYYY-MM-DD` |
| `type` | `audio_transcript` | `slide_material` |
| `timestamp` | `[MM:SS - MM:SS]` | empty string |
| `page` | `0` | one-based page number |

Retrieval always passes `where={"course_id": selected_course_id}`. It returns documents and citation-ready metadata across every indexed date for that course. A count operation reports distinct indexed lecture dates for the active course. On a course rename, the registry is updated and existing Chroma records for that `course_id` are updated to keep `course_name_zh` metadata accurate.

### `app.py`

The Streamlit layer contains no audio or vector-store implementation. Its sidebar provides the course selector, course-management controls, date picker, audio uploader, PDF uploader, and `Process & Index Lecture Materials` action. The selector labels each course with its term and Traditional Chinese title, prioritizes active courses, and allows semester history to be selected through the manager. The action stages uploads, runs cleaning, transcription, translation, PDF extraction, and indexing with progress updates, then removes temporary source files in a `finally` block.

The main canvas presents the active course and indexed-session count, followed by course-scoped persisted-in-session chat messages. A contextual chat input asks questions across the selected course's full semester. For a question, the app retrieves course-filtered context, formats the source metadata, and asks GPT-4o to answer as a patient academic tutor. The system prompt requires citations in exactly one of these forms:

- `[Date: YYYY-MM-DD | Audio Timestamp: MM:SS]`
- `[Date: YYYY-MM-DD | Slide Page X]`

The application accepts an API key from `OPENAI_API_KEY` in the environment first, then `st.secrets["OPENAI_API_KEY"]`. It displays a configuration error before any network or embedding operation when neither value is available.

## Data Flow

1. The user selects an active registered course and lecture date, then uploads optional audio and/or PDF materials.
2. Audio is normalized, denoised, compressed, and chunked where required.
3. Each chunk is transcribed, translated, timestamp-adjusted, and converted to transcript documents.
4. Each PDF is extracted into page-level slide documents.
5. The database validates metadata, creates embeddings, and upserts all resulting documents.
6. A course-scoped question retrieves relevant documents from all available dates, then GPT-4o composes a cited answer from that evidence.

## Consistency And Failure Handling

- Inputs with unsupported extensions, unavailable FFmpeg, unreadable media, blank PDFs, missing credentials, failed API calls, and malformed model payloads result in clear Streamlit errors.
- A processing failure prevents the affected material from being indexed. The UI reports the failing stage and leaves existing indexed records unchanged.
- Deterministic IDs are based on course ID, date, material type, and the segment or page identity. Reprocessing the same source identity upserts it rather than duplicating it.
- The registry seeds only when absent, preserving additions, edits, and archives across restarts. Duplicate course IDs are rejected; IDs cannot be changed after indexed records exist.
- Course display-name edits update matching Chroma metadata; archiving never deletes vectors or their retrieval history.
- Transcript and translation records must maintain one-to-one source identifiers. Alignment failures are errors, not best-effort inserts.
- The Chroma path is relative to the application working directory and must be backed up for semester retention.

## Tests And Validation

Unit tests will cover:

- timestamp formatting and chunk-offset adjustment;
- chunk threshold behavior and overlap metadata;
- course roster validation and strictly filtered retrieval;
- persistent registry seeding, additions, edits, and archiving behavior;
- metadata construction and deterministic identifiers;
- PDF page extraction behavior;
- translation response alignment validation;
- citation formatting and credential resolution priority.

Tests inject or mock the OpenAI and Chroma boundaries. They do not make live API calls. A documented manual smoke test runs the Streamlit app with a configured API key and representative audio/PDF inputs.