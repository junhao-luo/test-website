# Supabase Student Dashboard And Cloud Sync Design

## Purpose

Expand the local bilingual lecture companion into a cloud-backed student workspace. The application will provide authenticated student profiles, an overview dashboard, course add/drop management, lecture file management, profile and lecture-material photos, and synchronization of lecture data with Supabase.

## Scope

The first cloud release uses Supabase as the system of record for user-owned application data while retaining the existing local Chroma database as a retrieval cache during migration. It supports one student account per user, authenticated browser sessions, secure per-user data access, course enrollment history, file metadata and storage, profile photos, lecture photos, OCR/indexing hooks, and sync status.

The release does not implement institutional SSO, multi-student sharing, instructor accounts, public course catalogs, collaborative editing, payment features, or automatic deletion of historical lecture material when a course is dropped.

## Cloud Architecture

### Supabase services

- **Auth** manages email/password or magic-link authentication and browser sessions.
- **Postgres** stores profiles, courses, enrollments, lecture sessions, transcript segments, files, photo metadata, and sync records.
- **Storage** stores profile photos, lecture photos, PDFs, and optional uploaded audio in private buckets.
- **Row-level security** requires every user-owned row to be reachable through `auth.uid()` ownership or an enrollment relationship.

The browser receives only the Supabase project URL and publishable/anon key. The server retains `OPENAI_API_KEY` and any privileged Supabase service-role credential. Service-role access is never sent to the browser.

### Data model

The initial migration creates:

- `profiles`: `id` equal to `auth.users.id`, display name, student ID, program, year, avatar path, timezone, language preference, created/updated timestamps.
- `courses`: stable course ID, Traditional Chinese name, English name, term, archived flag, created/updated timestamps.
- `enrollments`: user ID, course ID, status (`active`, `dropped`, `completed`), enrolled/dropped timestamps, unique user/course constraint.
- `lecture_sessions`: user ID, course ID, lecture date, source (`live`, `upload`, `photo`), processing status, created/updated timestamps.
- `transcript_segments`: user ID, lecture session ID, stable segment ID, start/end seconds, timestamp, Traditional Chinese text, English translation, explanation, sync version, unique session/segment constraint.
- `files`: user ID, course ID, lecture session ID nullable, storage path, filename, media type, byte size, processing status, OCR text nullable, created/updated timestamps.
- `photos`: user ID, course ID nullable, kind (`profile`, `lecture_material`), storage path, width/height, OCR status, created timestamp.
- `sync_events`: user ID, entity type, entity ID, operation, client version, server status, error text nullable, created timestamp.

Dropped courses retain enrollments, lecture sessions, transcript segments, files, and photos. Default course selectors show only active enrollments; history views can show dropped or completed courses.

### Storage layout

Use private buckets with paths scoped by authenticated user ID:

```text
profiles/{user_id}/avatar/{file_id}
users/{user_id}/courses/{course_id}/files/{file_id}/{filename}
users/{user_id}/courses/{course_id}/photos/{photo_id}
users/{user_id}/sessions/{session_id}/audio/{file_id}
```

Storage policies must require the first path segment to equal `auth.uid()`. Database file/photo rows are deleted or marked deleted before storage objects are removed. UI deletion is explicit and must not remove a course's historical transcript automatically.

## Security And Privacy

- Every table has RLS enabled.
- Profile rows are readable and writable only by the matching authenticated user.
- Enrollment, lecture, transcript, file, photo, and sync rows are readable only where `user_id = auth.uid()`.
- Course joins used by a user must be enforced through that user's enrollment or ownership relation.
- Storage object read/write policies enforce the user-scoped path.
- OpenAI calls remain server-side; browser code never receives the OpenAI API key.
- Profile and lecture photos are private by default and are never exposed through public URLs.
- Raw live microphone audio remains non-persistent unless the user explicitly uploads an audio file.
- Delete actions require an explicit confirmation and write an audit-ready sync event.

## Application Layers

### `cloud_store.py`

Owns Supabase client creation, authenticated-user checks, CRUD for profile/courses/enrollments/files/photos, signed download URLs, and sync operations. It accepts an injected client for tests and never reads browser tokens from arbitrary request fields.

### `supabase/migrations/`

Contains the SQL schema, indexes, RLS policies, storage bucket/policies, and updated-at triggers. Migrations are the source of truth; the Python app does not create tables at runtime.

### `app.py`

Adds authentication gating, dashboard navigation, profile settings, course enrollment actions, file/photo controls, and cloud/local sync status. The live Realtime flow keeps the selected authenticated user and active enrollment attached to each lecture session. Successful finalized segments are written to Supabase first, then upserted into local Chroma as a retrieval cache.

### Dashboard views

- **Overview**: active course count, next lecture date, recent sessions, unprocessed files/photos, and sync status.
- **Courses**: active/history tabs, add course, drop course, restore enrollment, and course detail navigation.
- **Course detail**: live session start, transcript history, files, photos, OCR state, and course-scoped chat.
- **Files**: upload, rename, filter by course/type/status, preview/download through signed URLs, retry processing, and delete.
- **Profile**: display name, student ID, program, year, language preference, timezone, and profile photo capture/upload.
- **Settings**: account/session actions, sync controls, local cache location, processing preferences, and privacy/delete controls.

## Photo Workflows

### Profile photo

The profile view uses browser camera capture when available and accepts an image upload fallback. The client resizes/compresses the image before upload, writes a private Storage object, updates `profiles.avatar_path`, and displays it through a short-lived signed URL.

### Lecture-material photo

The course detail view captures or uploads whiteboard, slide, or handwritten-note photos. Each photo is attached to the selected course and optionally a lecture session. Processing extracts OCR text, stores the result in `files` or `photos`, and creates a searchable document with course/user metadata. OCR failure keeps the original photo and exposes retry status.

No photo is added to a public bucket. Camera permission denial falls back to file upload and does not block the rest of the dashboard.

## Sync And Offline Behavior

Supabase is authoritative for authenticated records. The local registry and Chroma data remain a cache for compatibility with the current application. Each write uses an idempotent stable ID and records a `sync_event`. Reads show cached content immediately when present, then refresh from Supabase. Failed writes remain in a retryable state with an actionable error.

Live transcript flow:

1. Authenticate the user and verify active enrollment.
2. Create a Supabase `lecture_session`.
3. Receive finalized Realtime segments and translate/explain them server-side.
4. Upsert each successful segment to Supabase with its stable segment ID.
5. Upsert the same segment into local Chroma with the existing required metadata.
6. On Stop, mark the session complete only after pending segment writes settle.

If Supabase is unavailable, the app keeps local finalized segments visible, marks the session sync-pending, and does not claim cloud persistence succeeded. A later retry reconciles by stable session/segment IDs.

## Testing And Validation

- Migration tests verify table constraints, indexes, RLS ownership, enrollment access, and private storage policies.
- `cloud_store.py` tests use an injected fake Supabase client and never call a real project.
- App tests cover unauthenticated gating, profile updates, add/drop/restore course transitions, file/photo CRUD, signed URL use, sync retry, and cloud-first live segment persistence.
- Browser tests cover login state, camera permission denial fallback, profile photo capture, lecture photo capture, file upload, dashboard navigation, and logout.
- A manual smoke test uses a disposable Supabase project: create account, complete profile, add/drop a course, capture both photo types, upload a PDF, run a live session, verify cloud rows/storage objects, reload, and confirm course-scoped chat still cites the lecture.

## Deployment

Deployment configuration will be added through the repository's gstack deployment workflow after the hosting provider and production URL are known. Required production secrets are Supabase URL, Supabase publishable key, Supabase service-role key where server-side operations require it, and `OPENAI_API_KEY`. Secrets are configured in the hosting platform, never committed to the repository.