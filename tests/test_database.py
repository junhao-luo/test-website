from dataclasses import dataclass, field
from unittest.mock import patch

import pytest
import sys
import types

# Provide a minimal fake pypdf module so importing database.py during tests
# does not require the real dependency. Individual tests patch PdfReader.
if "pypdf" not in sys.modules:
    fake_pypdf = types.ModuleType("pypdf")
    class PdfReader:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("PdfReader should be patched in tests")
    fake_pypdf.PdfReader = PdfReader
    sys.modules["pypdf"] = fake_pypdf

from database import Course, CourseRegistry, DEFAULT_COURSES, LectureDatabase
from transcription_service import TranscriptSegment


class FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class FakePdfReader:
    def __init__(self, texts: list[str]) -> None:
        self.pages = [FakePage(text) for text in texts]


@dataclass
class FakeCollection:
    rows: dict[str, tuple[str, dict]] = field(default_factory=dict)
    last_where: dict | None = None

    def upsert(self, *, ids, documents, metadatas) -> None:
        self.rows.update(dict(zip(ids, zip(documents, metadatas))))

    def query(self, *, where, **_kwargs):
        self.last_where = where
        values = [value for value in self.rows.values() if value[1]["course_id"] == where["course_id"]]
        return {
            "documents": [[value[0] for value in values]],
            "metadatas": [[value[1] for value in values]],
            "distances": [[0.0] * len(values)],
        }

    def get(self, *, where, include):
        values = [(row_id, value) for row_id, value in self.rows.items() if value[1]["course_id"] == where["course_id"]]
        return {
            "ids": [row_id for row_id, _value in values],
            "metadatas": [metadata for _row_id, (_document, metadata) in values],
        }

    def update(self, *, ids, metadatas):
        for row_id, metadata in zip(ids, metadatas):
            document, _old_metadata = self.rows[row_id]
            self.rows[row_id] = (document, metadata)


def make_database(tmp_path, collection: FakeCollection | None = None) -> LectureDatabase:
    return LectureDatabase(collection or FakeCollection(), CourseRegistry(tmp_path / "courses.json"))


def test_registry_seeds_courses_and_preserves_additions(tmp_path):
    registry = CourseRegistry(tmp_path / "courses.json")

    assert [course.course_id for course in registry.list_courses()] == [
        course.course_id for course in DEFAULT_COURSES
    ]
    registry.add_course(Course("ai_math_2", "AI基礎數學(二)", "", "First Year / Semester 2"))

    assert len(CourseRegistry(tmp_path / "courses.json").list_courses()) == 8


def test_registry_rejects_duplicates_and_hides_archived_courses(tmp_path):
    registry = CourseRegistry(tmp_path / "courses.json")

    with pytest.raises(ValueError, match="already exists"):
        registry.add_course(DEFAULT_COURSES[0])

    registry.update_course(
        "pe_1",
        name_zh="體育(一)",
        name_en="Physical Education I",
        term="First Year / Semester 1",
        archived=True,
    )

    assert "pe_1" not in [course.course_id for course in registry.list_courses()]


def test_indexes_explained_live_segment_and_filters_by_course(tmp_path):
    collection = FakeCollection()
    database = make_database(tmp_path, collection)
    segment = TranscriptSegment("session:evt", 3, 5, "[00:03 - 00:05]", "遞迴", "Recursion", "A function calls itself.")

    database.index_transcript("intro_cs", "2026-09-10", [segment])
    database.index_transcript(
        "ai_math_1",
        "2026-09-10",
        [TranscriptSegment("session:other", 8, 9, "[00:08 - 00:09]", "矩陣", "Matrix", "A rectangular array.")],
    )
    results = database.retrieve("intro_cs", "What is recursion?")

    assert results[0].document == "Traditional Chinese: 遞迴\nEnglish: Recursion\nExplanation: A function calls itself."
    assert results[0].metadata == {
        "course_id": "intro_cs",
        "course_name_zh": "電腦科學概論",
        "date": "2026-09-10",
        "type": "audio_transcript",
        "timestamp": "[00:03 - 00:05]",
        "page": 0,
    }
    assert results[0].distance == 0.0
    assert all(result.metadata["course_id"] == "intro_cs" for result in results)
    assert collection.last_where == {"course_id": "intro_cs"}


def test_pdf_indexing_creates_one_slide_document_per_nonempty_page(tmp_path):
    database = make_database(tmp_path)

    with patch("database.PdfReader", return_value=FakePdfReader(["Vectors", "   ", "Matrices"])):
        indexed = database.index_pdf("ai_math_1", "2026-09-10", tmp_path / "slides.pdf")

    assert indexed == 2
    assert database.collection.rows == {
        "ai_math_1:2026-09-10:slide:1": (
            "Vectors",
            {
                "course_id": "ai_math_1",
                "course_name_zh": "AI基礎數學(一)",
                "date": "2026-09-10",
                "type": "slide_material",
                "timestamp": "",
                "page": 1,
            },
        ),
        "ai_math_1:2026-09-10:slide:3": (
            "Matrices",
            {
                "course_id": "ai_math_1",
                "course_name_zh": "AI基礎數學(一)",
                "date": "2026-09-10",
                "type": "slide_material",
                "timestamp": "",
                "page": 3,
            },
        ),
    }


def test_create_lecture_database_uses_chromadb_persistentclient_and_embedding(monkeypatch):
    import sys
    import types

    # return a sentinel embedding function from the factory
    sentinel_embedding = object()
    monkeypatch.setattr("database.create_openai_embedding_function", lambda api_key: sentinel_embedding)

    recorded = {}

    class FakeClient:
        def __init__(self, path: str):
            recorded["path"] = path

        def get_or_create_collection(self, **kwargs):
            recorded.update(kwargs)
            return object()

    fake_mod = types.ModuleType("chromadb")
    fake_mod.PersistentClient = FakeClient

    monkeypatch.setitem(sys.modules, "chromadb", fake_mod)

    # Import inside test to use patched sys.modules
    from database import create_lecture_database

    # Call factory which will import our fake chromadb
    create_lecture_database(api_key="DUMMY")

    assert recorded.get("path") == "./chroma_db"
    # embedding_function should be passed through to get_or_create_collection
    assert recorded.get("embedding_function") is sentinel_embedding


def test_index_transcript_creates_deterministic_audio_id(tmp_path):
    collection = FakeCollection()
    database = make_database(tmp_path, collection)
    segment = TranscriptSegment("session:evt", 3, 5, "[00:03 - 00:05]", "遞迴", "Recursion", "A function calls itself.")

    database.index_transcript("intro_cs", "2026-09-10", [segment])

    assert "intro_cs:2026-09-10:audio:session:evt" in collection.rows


def test_refresh_course_metadata_updates_matching_rows_after_rename(tmp_path):
    collection = FakeCollection()
    database = make_database(tmp_path, collection)
    segment = TranscriptSegment("session:evt", 3, 5, "[00:03 - 00:05]", "遞迴", "Recursion", "A function calls itself.")
    database.index_transcript("intro_cs", "2026-09-10", [segment])

    database.update_course("intro_cs", name_zh="新的電腦科學", name_en="Introduction to CS", term="First Year / Semester 1", archived=False)

    assert collection.rows["intro_cs:2026-09-10:audio:session:evt"][1]["course_name_zh"] == "新的電腦科學"