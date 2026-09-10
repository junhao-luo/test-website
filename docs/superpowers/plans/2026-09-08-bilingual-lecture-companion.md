# Bilingual Academic Lecture Companion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Streamlit application that processes Mandarin lecture audio and PDFs into course-isolated, semester-long RAG conversations with cited English answers.

**Architecture:** `audio_cleaner.py`, `transcription_service.py`, and `database.py` are independently testable service modules. `app.py` orchestrates those modules, keeps UI state isolated from processing logic, and sends only selected-course context to GPT-4o. A JSON registry persists editable courses while ChromaDB persists lecture documents and embeddings.

**Tech Stack:** Python 3.11+, Streamlit, OpenAI Python SDK, ChromaDB, pydub and FFmpeg, NumPy, noisereduce, pypdf, pytest.

**Spec:** [docs/superpowers/specs/2026-09-08-bilingual-lecture-companion-design.md](../specs/2026-09-08-bilingual-lecture-companion-design.md)

## Global Constraints

- Read `OPENAI_API_KEY` from the environment before `st.secrets["OPENAI_API_KEY"]`.
- Seed the supplied seven First Year, Semester 1 courses only when `./course_registry.json` is absent.
- Store ChromaDB data using `chromadb.PersistentClient(path="./chroma_db")`.
- Embed with `text-embedding-3-small`, transcribe with `whisper-1`, and generate translations and answers with `gpt-4o`.
- Audio must be mono, 16,000 Hz, noise-reduced, and exported as 32 kbps MP3 before transcription.
- Split cleaned payloads larger than 25 MB into 12-minute chunks with a 2-second overlap and preserve absolute timestamps.
- Every vector must include `course_id`, `course_name_zh`, `date`, `type`, `timestamp`, and `page` metadata.
- Retrieval must use `where={"course_id": selected_course_id}` without exception.
- Do not commit changes unless the user explicitly asks for a commit.

---

## File Structure

- `requirements.txt`: Fully pinned runtime and test dependencies.
- `audio_cleaner.py`: Media normalization, noise reduction, compression, and chunk creation.
- `transcription_service.py`: Whisper transcription, time formatting, translation validation, and GPT-4o calls.
- `database.py`: Course registry persistence, Chroma setup, PDF extraction, metadata validation, indexing, and retrieval.
- `app.py`: Streamlit course manager, ingestion orchestration, and cited chat interface.
- `tests/test_audio_cleaner.py`: Unit coverage for audio timing and chunk logic.
- `tests/test_transcription_service.py`: Unit coverage for timestamps and translation alignment.
- `tests/test_database.py`: Unit coverage for course management, metadata, extraction, and course isolation.
- `tests/test_app_helpers.py`: Unit coverage for credentials and citation helpers.

### Task 1: Project Foundation And Course Registry

**Files:**
- Create: `requirements.txt`
- Create: `database.py`
- Create: `tests/test_database.py`

**Interfaces:**
- Produces: `Course` dataclass with `course_id: str`, `name_zh: str`, `name_en: str`, `term: str`, `archived: bool`.
- Produces: `CourseRegistry(path: Path)` with `list_courses(include_archived: bool = False) -> list[Course]`, `add_course(course: Course) -> Course`, `update_course(course_id: str, *, name_zh: str, name_en: str, term: str, archived: bool) -> Course`.
- Produces: `DEFAULT_COURSES: tuple[Course, ...]` containing the required seven First Year, Semester 1 courses with their exact IDs and Chinese names.

- [ ] **Step 1: Write the failing registry tests**

```python
import pytest

from database import Course, CourseRegistry, DEFAULT_COURSES


def test_registry_seeds_first_year_semester_one_courses_once(tmp_path):
    registry = CourseRegistry(tmp_path / "courses.json")

    courses = registry.list_courses()

    assert [(course.course_id, course.name_zh) for course in courses] == [
        (course.course_id, course.name_zh) for course in DEFAULT_COURSES
    ]
    registry.add_course(Course("ai_math_2", "AI基礎數學(二)", "", "First Year / Semester 2"))
    assert len(CourseRegistry(tmp_path / "courses.json").list_courses()) == 8


def test_registry_rejects_duplicate_id_and_archives_course(tmp_path):
    registry = CourseRegistry(tmp_path / "courses.json")

    with pytest.raises(ValueError, match="already exists"):
        registry.add_course(DEFAULT_COURSES[0])

    archived = registry.update_course("pe_1", name_zh="體育(一)", name_en="Physical Education I", term="First Year / Semester 1", archived=True)

    assert archived.archived is True
    assert "pe_1" not in [course.course_id for course in registry.list_courses()]
```

- [ ] **Step 2: Run the registry tests to verify they fail**

Run: `pytest tests/test_database.py -v`

Expected: FAIL because `database` is not yet available.

- [ ] **Step 3: Add pinned dependencies and minimal registry implementation**

Create `requirements.txt` with:

```text
chromadb==0.6.3
noisereduce==3.0.3
numpy==2.2.3
openai==1.66.3
pydub==0.25.1
pypdf==5.2.0
pytest==8.3.4
streamlit==1.42.0
```

Implement JSON serialization with `dataclasses.asdict`. When the registry path does not exist, write `DEFAULT_COURSES` atomically. Reject a blank ID/name and duplicate IDs. `list_courses()` excludes archived records by default; `update_course()` changes display fields and archive state but never changes the ID.

```python
@dataclass(frozen=True)
class Course:
    course_id: str
    name_zh: str
    name_en: str
    term: str
    archived: bool = False
```

- [ ] **Step 4: Run the registry tests to verify they pass**

Run: `pytest tests/test_database.py -v`

Expected: PASS.

- [ ] **Step 5: Inspect the working tree without committing**

Run: `git diff -- requirements.txt database.py tests/test_database.py`

Expected: Only the dependency manifest, course registry, and its tests are changed.

### Task 2: Audio Normalization And Chunking

**Files:**
- Create: `audio_cleaner.py`
- Create: `tests/test_audio_cleaner.py`

**Interfaces:**
- Produces: `AudioChunk(path: Path, index: int, offset_ms: int, duration_ms: int)`.
- Produces: `format_timestamp_range(start_seconds: float, end_seconds: float) -> str`.
- Produces: `split_audio_for_upload(audio: AudioSegment, output_dir: Path, max_bytes: int = 25 * 1024 * 1024, chunk_ms: int = 720_000, overlap_ms: int = 2_000) -> list[AudioChunk]`.
- Produces: `clean_audio(source_path: Path, output_dir: Path) -> list[AudioChunk]`.

- [ ] **Step 1: Write failing timestamp and chunk-offset tests**

```python
from pydub import AudioSegment

from audio_cleaner import format_timestamp_range, split_audio_for_upload


def test_formats_absolute_timestamp_range():
    assert format_timestamp_range(65.2, 130.8) == "[01:05 - 02:10]"


def test_chunking_preserves_offsets_and_two_second_overlap(tmp_path):
    audio = AudioSegment.silent(duration=1_500, frame_rate=16_000)

    chunks = split_audio_for_upload(audio, tmp_path, max_bytes=1, chunk_ms=1_000, overlap_ms=200)

    assert [(chunk.index, chunk.offset_ms, chunk.duration_ms) for chunk in chunks] == [
        (0, 0, 1_000),
        (1, 800, 700),
    ]
```

- [ ] **Step 2: Run the audio tests to verify they fail**

Run: `pytest tests/test_audio_cleaner.py -v`

Expected: FAIL because `audio_cleaner` is not yet available.

- [ ] **Step 3: Implement pure helpers and the audio pipeline**

Implement `format_timestamp_range` using rounded-down nonnegative seconds. Implement chunk boundaries as `[offset, min(offset + chunk_ms, len(audio))]` and advance by `chunk_ms - overlap_ms`. Export each chunk at `32k` bitrate when splitting. In `clean_audio`, load with `AudioSegment.from_file`, set one channel and 16,000 Hz, convert samples to normalized float32 NumPy data, call `noisereduce.reduce_noise`, reconstruct the segment at the original sample width, export a cleaned MP3, then call `split_audio_for_upload`.

```python
def clean_audio(source_path: Path, output_dir: Path) -> list[AudioChunk]:
    raw = AudioSegment.from_file(source_path).set_channels(1).set_frame_rate(16_000)
    cleaned = reduce_noise(audio_clip=to_float32(raw), sr=16_000)
    normalized = from_float32(cleaned, sample_width=raw.sample_width, frame_rate=16_000)
    return split_audio_for_upload(normalized, output_dir)
```

- [ ] **Step 4: Run the audio tests to verify they pass**

Run: `pytest tests/test_audio_cleaner.py -v`

Expected: PASS.

- [ ] **Step 5: Inspect the working tree without committing**

Run: `git diff -- audio_cleaner.py tests/test_audio_cleaner.py`

Expected: Only the audio module and its tests are changed.

### Task 3: Transcription, Timestamp Alignment, And Translation

**Files:**
- Create: `transcription_service.py`
- Create: `tests/test_transcription_service.py`

**Interfaces:**
- Consumes: `AudioChunk` from `audio_cleaner.py`.
- Produces: `TranscriptSegment(segment_id: str, start_seconds: float, end_seconds: float, timestamp: str, original_zh: str, translation_en: str)`.
- Produces: `transcribe_chunk(client: OpenAI, chunk: AudioChunk) -> list[TranscriptSegment]`.
- Produces: `translate_segments(client: OpenAI, segments: list[TranscriptSegment]) -> list[TranscriptSegment]`.

- [ ] **Step 1: Write failing alignment tests with a fake client**

```python
import json
from types import SimpleNamespace

import pytest

from audio_cleaner import AudioChunk
from transcription_service import TranscriptSegment, transcribe_chunk, translate_segments


class FakeWhisperClient:
    class audio:
        class transcriptions:
            @staticmethod
            def create(**_kwargs):
                return type("Response", (), {"segments": [{"start": 2.0, "end": 5.0, "text": "遞迴"}]})()


class FakeTranslationClient:
    def __init__(self, translations):
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"translations": translations})))])
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_kwargs: response))


def test_transcription_applies_chunk_offset_to_timestamps(tmp_path):
    chunk = AudioChunk(tmp_path / "chunk.mp3", 1, 60_000, 120_000)
    chunk.path.write_bytes(b"audio")

    segments = transcribe_chunk(FakeWhisperClient(), chunk)

    assert [(item.start_seconds, item.end_seconds, item.timestamp) for item in segments] == [
        (62.0, 65.0, "[01:02 - 01:05]")
    ]


def test_translation_rejects_missing_source_identifier():
    source = [TranscriptSegment("segment-0", 0, 1, "[00:00 - 00:01]", "遞迴", "")]

    with pytest.raises(ValueError, match="missing or unexpected"):
        translate_segments(FakeTranslationClient([{ "id": "other", "translation": "Recursion" }]), source)
```

- [ ] **Step 2: Run the transcription tests to verify they fail**

Run: `pytest tests/test_transcription_service.py -v`

Expected: FAIL because `transcription_service` is not yet available.

- [ ] **Step 3: Implement OpenAI boundary calls and response validation**

Open `chunk.path` in binary mode and call `client.audio.transcriptions.create(model="whisper-1", file=audio_file, response_format="verbose_json", timestamp_granularities=["segment"])`. Create segment IDs as `chunk-{chunk.index}-segment-{segment_index}`. Apply `chunk.offset_ms / 1000` to source times and format the absolute range with Task 2's helper.

Send GPT-4o one structured JSON request containing IDs and Traditional Chinese text. Its system message must retain Chinese technical terms beside English equivalents, preserve formal CS/math terminology, formulas, and code. Parse the returned JSON list, require each requested ID exactly once, and return new `TranscriptSegment` values in source order.

```python
def translate_segments(client: OpenAI, segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    payload = {"segments": [{"id": segment.segment_id, "text": segment.original_zh} for segment in segments]}
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
    )
    translations = parse_translation_response(response)
    return validate_and_merge(segments, translations)
```

- [ ] **Step 4: Run the transcription tests to verify they pass**

Run: `pytest tests/test_transcription_service.py -v`

Expected: PASS.

- [ ] **Step 5: Inspect the working tree without committing**

Run: `git diff -- transcription_service.py tests/test_transcription_service.py`

Expected: Only the transcription service and its tests are changed.

### Task 4: Chroma Documents, PDF Extraction, And Isolated Retrieval

**Files:**
- Modify: `database.py`
- Modify: `tests/test_database.py`

**Interfaces:**
- Consumes: `CourseRegistry` and `TranscriptSegment`.
- Produces: `LectureDatabase(client: chromadb.ClientAPI, embedding_function: EmbeddingFunction, registry: CourseRegistry)`.
- Produces: `index_transcript(course_id: str, date: str, segments: list[TranscriptSegment]) -> None`.
- Produces: `index_pdf(course_id: str, date: str, pdf_path: Path) -> int`.
- Produces: `retrieve(course_id: str, question: str, limit: int = 8) -> list[RetrievedDocument]`.
- Produces: `indexed_session_count(course_id: str) -> int`.

- [ ] **Step 1: Write failing database behavior tests**

```python
from dataclasses import dataclass


@dataclass
class FakeCollection:
    rows: dict[str, tuple[str, dict]]
    last_where: dict | None = None

    def upsert(self, ids, documents, metadatas):
        self.rows.update(zip(ids, zip(documents, metadatas)))

    def query(self, *, where, **_kwargs):
        self.last_where = where
        matching = [(identifier, value) for identifier, value in self.rows.items() if value[1]["course_id"] == where["course_id"]]
        return {"documents": [[value[0] for _, value in matching]], "metadatas": [[value[1] for _, value in matching]], "distances": [[0.0] * len(matching)]}


class FakeChromaClient:
    def __init__(self):
        self.collection = FakeCollection({})

    def get_or_create_collection(self, **_kwargs):
        return self.collection


def make_database(tmp_path):
    return LectureDatabase(FakeChromaClient(), embedding_function=None, registry=CourseRegistry(tmp_path / "courses.json"))


def segment(identifier, timestamp, translation):
    return TranscriptSegment(identifier, 3.0, 5.0, timestamp, "原文", translation)


def test_transcript_metadata_is_complete_and_retrieval_filters_by_course(tmp_path):
    database = make_database(tmp_path)
    database.index_transcript("intro_cs", "2026-09-08", [segment("s1", "[00:03 - 00:05]", "Stack")])
    database.index_transcript("ai_math_1", "2026-09-08", [segment("s2", "[00:03 - 00:05]", "Matrix")])

    results = database.retrieve("intro_cs", "What is a stack?")

    assert results[0].metadata == {
        "course_id": "intro_cs", "course_name_zh": "電腦科學概論",
        "date": "2026-09-08", "type": "audio_transcript",
        "timestamp": "[00:03 - 00:05]", "page": 0,
    }
    assert all(result.metadata["course_id"] == "intro_cs" for result in results)
    assert database.collection.last_where == {"course_id": "intro_cs"}


def test_pdf_indexing_creates_one_slide_document_per_nonempty_page(tmp_path):
    database = make_database(tmp_path)

    with patch("database.PdfReader", return_value=FakePdfReader(["Vectors", "Matrices"])):
        indexed = database.index_pdf("ai_math_1", "2026-09-08", tmp_path / "slides.pdf")

    assert indexed == 2
```

At the top of this test file, import `patch` from `unittest.mock`, `TranscriptSegment`, and the database interfaces. Define `FakePdfReader` with `pages` containing objects whose `extract_text()` returns the supplied string. Keep the collection fake in-memory so the test asserts `where={"course_id": "intro_cs"}` behavior without a Chroma server.

- [ ] **Step 2: Run the database tests to verify they fail**

Run: `pytest tests/test_database.py -v`

Expected: FAIL because indexing and retrieval methods are not implemented.

- [ ] **Step 3: Implement documents and Chroma persistence**

Create the collection from `chromadb.PersistentClient(path="./chroma_db")` with the injected OpenAI embedding adapter. Generate IDs as `"{course_id}:{date}:audio:{segment_id}"` and `"{course_id}:{date}:slide:{page}"`. Extract PDF text with `PdfReader(pdf_path).pages`, skip whitespace-only pages, and assign one-based page numbers. Build every metadata dictionary with all six required fields and use `collection.upsert`.

Implement retrieval with this exact call shape and map its response into typed results:

```python
result = self.collection.query(
    query_texts=[question],
    n_results=limit,
    where={"course_id": course_id},
    include=["documents", "metadatas", "distances"],
)
```

When a course display name changes, fetch records with the same course filter and call `collection.update` with rebuilt metadata that changes only `course_name_zh`.

- [ ] **Step 4: Run the database tests to verify they pass**

Run: `pytest tests/test_database.py -v`

Expected: PASS.

- [ ] **Step 5: Inspect the working tree without committing**

Run: `git diff -- database.py tests/test_database.py`

Expected: The database module contains only registry, PDF, indexing, and retrieval work specified here.

### Task 5: Streamlit Configuration And Citation Helpers

**Files:**
- Create: `app.py`
- Create: `tests/test_app_helpers.py`

**Interfaces:**
- Produces: `get_openai_api_key(environment: Mapping[str, str], secrets: Mapping[str, str]) -> str | None`.
- Produces: `format_source_context(results: list[RetrievedDocument]) -> str`.
- Produces: `ask_tutor(client: OpenAI, course_name: str, question: str, sources: list[RetrievedDocument]) -> str`.

- [ ] **Step 1: Write failing helper tests**

```python
from app import format_source_context, get_openai_api_key
from database import RetrievedDocument


def retrieved(document, metadata):
    return RetrievedDocument(document=document, metadata=metadata, distance=0.0)


def test_environment_key_takes_priority_over_streamlit_secret():
    assert get_openai_api_key({"OPENAI_API_KEY": "environment-key"}, {"OPENAI_API_KEY": "secret-key"}) == "environment-key"


def test_source_context_formats_audio_and_slide_citations():
    context = format_source_context([
        retrieved("Audio explanation", {"date": "2026-09-08", "type": "audio_transcript", "timestamp": "[03:05 - 03:16]", "page": 0}),
        retrieved("Slide bullet", {"date": "2026-09-08", "type": "slide_material", "timestamp": "", "page": 4}),
    ])

    assert "[Date: 2026-09-08 | Audio Timestamp: 03:05]" in context
    assert "[Date: 2026-09-08 | Slide Page 4]" in context
```

- [ ] **Step 2: Run the helper tests to verify they fail**

Run: `pytest tests/test_app_helpers.py -v`

Expected: FAIL because `app` is not yet available.

- [ ] **Step 3: Implement configuration and grounded-answer helpers**

Implement environment-first credential resolution. `format_source_context` must remove brackets and the end time from transcript metadata when creating the required `Audio Timestamp: MM:SS` citation. `ask_tutor` must give GPT-4o only formatted retrieved sources and a system message that requires thorough English explanations, explicit source citations, and an honest statement when the provided evidence is insufficient.

```python
def ask_tutor(client: OpenAI, course_name: str, question: str, sources: list[RetrievedDocument]) -> str:
    context = format_source_context(sources)
    response = client.chat.completions.create(model="gpt-4o", messages=[
        {"role": "system", "content": TUTOR_PROMPT},
        {"role": "user", "content": f"Course: {course_name}\nSources:\n{context}\nQuestion: {question}"},
    ])
    return response.choices[0].message.content or "I could not generate an answer from the available materials."
```

- [ ] **Step 4: Run the helper tests to verify they pass**

Run: `pytest tests/test_app_helpers.py -v`

Expected: PASS.

- [ ] **Step 5: Inspect the working tree without committing**

Run: `git diff -- app.py tests/test_app_helpers.py`

Expected: Only non-UI helpers and their tests are changed.

### Task 6: Streamlit Ingestion And Semester Chat Workflow

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app_helpers.py`

**Interfaces:**
- Consumes: every public interface from Tasks 1 through 5.
- Produces: `IngestionServices(clean_audio: Callable, transcribe_chunk: Callable, translate_segments: Callable, database: LectureDatabase)` for testable orchestration.
- Produces: `process_materials(services: IngestionServices, course_id: str, lecture_date: date, audio_file: bytes | None, pdf_file: bytes | None) -> None`.
- Produces: `render_app() -> None` and an executable Streamlit entry point.

- [ ] **Step 1: Write a failing orchestration test**

```python
from datetime import date
from types import SimpleNamespace

from app import process_materials


class FakeServices:
    def __init__(self, root):
        self.root = root
        self.translated_segment = TranscriptSegment("s1", 0, 1, "[00:00 - 00:01]", "原文", "Translation")
        self.database = SimpleNamespace(transcript_calls=[], pdf_calls=[], index_transcript=self._index_transcript, index_pdf=self._index_pdf)
        self.clean_audio = lambda source, _output: [AudioChunk(source, 0, 0, 1)]
        self.transcribe_chunk = lambda _chunk: [TranscriptSegment("s1", 0, 1, "[00:00 - 00:01]", "原文", "")]
        self.translate_segments = lambda _segments: [self.translated_segment]

    def _index_transcript(self, course_id, lecture_date, segments):
        self.database.transcript_calls.append((course_id, lecture_date, segments))

    def _index_pdf(self, course_id, lecture_date, _path):
        self.database.pdf_calls.append((course_id, lecture_date))

    def temp_directory_is_empty(self):
        return not list(self.root.iterdir())


def test_process_materials_indexes_audio_and_pdf_for_selected_course(tmp_path):
    services = FakeServices(tmp_path)

    process_materials(services, course_id="intro_cs", lecture_date=date(2026, 9, 8), audio_file=b"audio", pdf_file=b"pdf")

    assert services.database.transcript_calls == [("intro_cs", "2026-09-08", [services.translated_segment])]
    assert services.database.pdf_calls == [("intro_cs", "2026-09-08")]
    assert services.temp_directory_is_empty()
```

- [ ] **Step 2: Run the orchestration test to verify it fails**

Run: `pytest tests/test_app_helpers.py::test_process_materials_indexes_audio_and_pdf_for_selected_course -v`

Expected: FAIL because `process_materials` is not yet available.

- [ ] **Step 3: Implement the orchestration function and Streamlit UI**

Implement `process_materials` as a dependency-injected coordinator: stage upload bytes in `TemporaryDirectory`, call `clean_audio`, transcribe and translate every chunk, index one combined transcript list, then call `index_pdf`. Always clean the staging directory in `finally`; propagate a stage-specific exception that the UI renders with `st.error`.

In `render_app`, use `st.sidebar.selectbox` for active registry courses labelled `"{term} | {name_zh}"`; add an expander for add/edit/archive/unarchive forms. Render date picker, `.mp3/.m4a/.wav` uploader, PDF uploader, and the exact action label `Process & Index Lecture Materials`. Wrap the coordinator in `st.status` or stage-progress updates. Display active course, indexed-session count, session-state chat history, and `st.chat_input(f"Ask any question about {course.name_zh} across the whole semester...")`. On a question, call `retrieve` using the selected course ID, then `ask_tutor`, and append the answer to history.

```python
def render_app() -> None:
    course = select_active_course(registry)
    st.title(course.name_zh)
    if prompt := st.chat_input(f"Ask any question about {course.name_zh} across the whole semester..."):
        answer = ask_tutor(openai_client, course.name_zh, prompt, database.retrieve(course.course_id, prompt))
        append_chat_messages(prompt, answer)
```

- [ ] **Step 4: Run the orchestration test to verify it passes**

Run: `pytest tests/test_app_helpers.py -v`

Expected: PASS.

- [ ] **Step 5: Run the full automated suite and inspect the UI locally**

Run: `pytest -v`

Expected: PASS.

Run: `streamlit run app.py`

Expected: The browser opens a usable local app; without credentials it shows the configuration error, and the course manager displays all seven seeded First Year, Semester 1 courses.

### Task 7: Deployment Notes And Final Validation

**Files:**
- Create: `README.md`

**Interfaces:**
- Produces: local setup documentation consistent with the implemented entry point and storage paths.

- [ ] **Step 1: Write a failing documentation assertion**

```python
from pathlib import Path

def test_readme_documents_credentials_and_ffmpeg_requirement():
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "OPENAI_API_KEY" in readme
    assert "FFmpeg" in readme
    assert "streamlit run app.py" in readme
```

- [ ] **Step 2: Run the documentation assertion to verify it fails**

Run: `pytest tests/test_app_helpers.py::test_readme_documents_credentials_and_ffmpeg_requirement -v`

Expected: FAIL because `README.md` is not yet available.

- [ ] **Step 3: Write concise local-run documentation**

Document Python environment setup, `pip install -r requirements.txt`, FFmpeg installation and PATH requirement, both credential options, `streamlit run app.py`, persistent `chroma_db` and `course_registry.json` locations, and the warning to back up both before a new machine/deployment.

- [ ] **Step 4: Run the complete test suite**

Run: `pytest -v`

Expected: PASS.

- [ ] **Step 5: Inspect the final diff without committing**

Run: `git diff --check; git status --short`

Expected: No whitespace errors; only planned application, test, documentation, and specification files are uncommitted.