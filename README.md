# Bilingual Lecture Companion

This local Streamlit app captures Mandarin lecture speech from the browser, shows
finalized source text with an English translation and explanation, and supports
course-scoped retrieval from indexed lecture material.

## Requirements

- Python 3.11 or newer
- Node.js and npm for the live microphone component
- FFmpeg available on `PATH`
- Google Chrome or Microsoft Edge for live microphone capture
- An OpenAI API key

## Setup

Create and activate a Python environment from the repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the Python dependencies:

```powershell
python -m pip install -r requirements.txt
```

Install FFmpeg using your operating system's package manager or the official
distribution, then add the directory containing `ffmpeg.exe` to `PATH`. Open a
new terminal and verify it is available:

```powershell
ffmpeg -version
```

Build the browser component:

```powershell
cd live_mic_component/frontend
npm install
npm run build
cd ../..
```

## Credentials

Configure `OPENAI_API_KEY` in the server environment before starting Streamlit.
For PowerShell:

```powershell
$env:OPENAI_API_KEY = "your-key"
```

Streamlit secrets are also supported by adding the key to
`.streamlit/secrets.toml`:

```toml
OPENAI_API_KEY = "your-key"
```

Never put the API key in frontend code, source control, browser storage, or
client-visible configuration. The server uses the key to request a short-lived
ephemeral Realtime client secret; only that ephemeral secret is sent to the
browser.

## Run

From the repository root:

```powershell
streamlit run app.py
```

Open the displayed local URL in supported Chrome or Edge. When prompted,
allow microphone access for the local site. Start a live session, speak a
Mandarin sentence, confirm that the partial caption is transient and that the
finalized Chinese text, English translation, and explanation remain visible,
then select **Stop live session**. Successful finalized segments are indexed
only when the session stops; failed translations remain available for retry and
are not indexed.

## Persistent data and backups

The app keeps the course registry in `course_registry.json` and the persistent
Chroma database in `chroma_db`. Back up both locations before moving the app to
another machine or changing deployment storage. Do not back up raw microphone
audio: the live flow does not persist it.

## Manual live smoke test

With `OPENAI_API_KEY` configured:

1. Start the app with `streamlit run app.py` in Chrome or Edge.
2. Grant microphone permission, choose a course and lecture date, and start a live session.
3. Speak Mandarin and verify a transient caption appears, followed by an immutable source transcript with English translation and explanation.
4. Stop the session and verify the successful segment is indexed.
5. Ask a course-scoped chat question and verify the answer cites the date and audio timestamp, for example `[Date: 2026-09-10 | Audio Timestamp: 00:03]`.
6. Confirm a failed translation can be retried and is excluded from indexing until it succeeds.