"""Persistent course catalog and ChromaDB lecture storage."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from transcription_service import TranscriptSegment


@dataclass(frozen=True)
class Course:
    course_id: str
    name_zh: str
    name_en: str
    term: str
    archived: bool = False


DEFAULT_COURSES = (
    Course("pe_1", "體育(一)", "Physical Education I", "First Year / Semester 1"),
    Course("chinese_expression_1", "中文思辨與表達(一)", "Chinese Critical Thinking and Expression I", "First Year / Semester 1"),
    Course("college_english_1", "大學基礎英文(一)", "College Basic English I", "First Year / Semester 1"),
    Course("intro_cs", "電腦科學概論", "Introduction to Computer Science", "First Year / Semester 1"),
    Course("industry_ai_seminar", "產業科技創新與AI應用專題", "Industrial Tech Innovation & AI Applications Seminar", "First Year / Semester 1"),
    Course("ai_math_1", "AI基礎數學(一)", "Foundations of AI Mathematics I", "First Year / Semester 1"),
    Course("programming_1", "基礎程式設計(一)", "Fundamental Programming I", "First Year / Semester 1"),
)


@dataclass(frozen=True)
class RetrievedDocument:
    document: str
    metadata: dict[str, Any]
    distance: float


class CourseRegistry:
    def __init__(self, path: Path | str = "course_registry.json") -> None:
        self.path = Path(path)
        if not self.path.exists():
            self._write(list(DEFAULT_COURSES))

    def list_courses(self, include_archived: bool = False) -> list[Course]:
        courses = self._read()
        return courses if include_archived else [course for course in courses if not course.archived]

    def get_course(self, course_id: str) -> Course:
        for course in self._read():
            if course.course_id == course_id:
                return course
        raise ValueError(f"Unknown course ID: {course_id}")

    def add_course(self, course: Course) -> Course:
        self._validate(course)
        courses = self._read()
        if any(item.course_id == course.course_id for item in courses):
            raise ValueError(f"Course ID already exists: {course.course_id}")
        courses.append(course)
        self._write(courses)
        return course

    def update_course(self, course_id: str, *, name_zh: str, name_en: str, term: str, archived: bool) -> Course:
        updated = Course(course_id, name_zh.strip(), name_en.strip(), term.strip(), archived)
        self._validate(updated)
        courses = self._read()
        for index, course in enumerate(courses):
            if course.course_id == course_id:
                courses[index] = updated
                self._write(courses)
                return updated
        raise ValueError(f"Unknown course ID: {course_id}")

    def _read(self) -> list[Course]:
        return [Course(**record) for record in json.loads(self.path.read_text(encoding="utf-8"))]

    def _write(self, courses: list[Course]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary_path.write_text(json.dumps([asdict(course) for course in courses], ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_path.replace(self.path)

    @staticmethod
    def _validate(course: Course) -> None:
        if not course.course_id.strip() or not course.name_zh.strip() or not course.term.strip():
            raise ValueError("Course ID, Traditional Chinese name, and term are required")


class LectureDatabase:
    def __init__(self, collection: Any, registry: CourseRegistry) -> None:
        self.collection = collection
        self.registry = registry

    def index_transcript(self, course_id: str, lecture_date: str, segments: list[TranscriptSegment]) -> None:
        if not segments:
            return

        course = self.registry.get_course(course_id)
        self.collection.upsert(
            ids=[f"{course_id}:{lecture_date}:audio:{segment.segment_id}" for segment in segments],
            documents=[self._transcript_document(segment) for segment in segments],
            metadatas=[self._metadata(course, lecture_date, "audio_transcript", segment.timestamp, 0) for segment in segments],
        )

    def refresh_course_name_metadata(self, course_id: str, course_name_zh: str) -> None:
        self.registry.get_course(course_id)
        records = self.collection.get(where={"course_id": course_id}, include=["metadatas"])
        ids = records.get("ids", [])
        metadatas = records.get("metadatas", [])
        if ids:
            self.collection.update(
                ids=ids,
                metadatas=[{**metadata, "course_name_zh": course_name_zh} for metadata in metadatas],
            )

    def update_course(self, course_id: str, *, name_zh: str, name_en: str, term: str, archived: bool) -> Course:
        course = self.registry.update_course(
            course_id,
            name_zh=name_zh,
            name_en=name_en,
            term=term,
            archived=archived,
        )
        self.refresh_course_name_metadata(course_id, course.name_zh)
        return course

    def index_pdf(self, course_id: str, lecture_date: str, pdf_path: Path) -> int:
        course = self.registry.get_course(course_id)
        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []

        for page_number, page in enumerate(PdfReader(pdf_path).pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            ids.append(f"{course_id}:{lecture_date}:slide:{page_number}")
            documents.append(text)
            metadatas.append(self._metadata(course, lecture_date, "slide_material", "", page_number))

        if ids:
            self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

        return len(ids)

    def retrieve(self, course_id: str, question: str, limit: int = 8) -> list[RetrievedDocument]:
        self.registry.get_course(course_id)
        result = self.collection.query(
            query_texts=[question],
            n_results=limit,
            where={"course_id": course_id},
            include=["documents", "metadatas", "distances"],
        )

        documents = result.get("documents", [[]])
        metadatas = result.get("metadatas", [[]])
        distances = result.get("distances", [[]])

        return [
            RetrievedDocument(document=document, metadata=metadata, distance=float(distance))
            for document, metadata, distance in zip(documents[0], metadatas[0], distances[0])
        ]

    @staticmethod
    def _transcript_document(segment: TranscriptSegment) -> str:
        return (
            f"Traditional Chinese: {segment.original_zh}\n"
            f"English: {segment.translation_en}\n"
            f"Explanation: {segment.explanation_en}"
        )

    @staticmethod
    def _metadata(course: Course, lecture_date: str, document_type: str, timestamp: str, page: int) -> dict[str, Any]:
        return {
            "course_id": course.course_id,
            "course_name_zh": course.name_zh,
            "date": lecture_date,
            "type": document_type,
            "timestamp": timestamp,
            "page": page,
        }


def create_openai_embedding_function(api_key: str, model_name: str = "text-embedding-3-small") -> Any:
    from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

    return OpenAIEmbeddingFunction(api_key=api_key, model_name=model_name)


def create_persistent_chroma_collection(
    *,
    path: Path | str = "./chroma_db",
    collection_name: str = "lecture_materials",
    embedding_function: Any | None = None,
) -> Any:
    import chromadb

    collection_options = {"name": collection_name}
    if embedding_function is not None:
        collection_options["embedding_function"] = embedding_function

    client = chromadb.PersistentClient(path=str(path))
    return client.get_or_create_collection(**collection_options)


def create_lecture_database(
    *,
    registry_path: Path | str = "course_registry.json",
    chroma_path: Path | str = "./chroma_db",
    collection_name: str = "lecture_materials",
    api_key: str | None = None,
) -> LectureDatabase:
    embedding_function = create_openai_embedding_function(api_key) if api_key else None
    collection = create_persistent_chroma_collection(
        path=chroma_path,
        collection_name=collection_name,
        embedding_function=embedding_function,
    )
    return LectureDatabase(collection, CourseRegistry(registry_path))