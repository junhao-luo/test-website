from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openai import OpenAI

from transcription_service import TranscriptSegment


class TranslationAlignmentError(ValueError):
    pass


TRANSLATION_EXPLANATION_PROMPT = (
    """
You are a precise translation assistant. Receive a JSON object with keys
`id` and `text` (Traditional Chinese). Return a single JSON object with
keys: `id` (must match the input), `translation` (a concise, formal English
translation, preserving formulas and code exactly), and `explanation` (one or
two sentences in clear English explaining the technical meaning). When the
source contains technical Chinese terms, keep the original Chinese term in
parentheses the first time and provide a meaningful English technical
equivalent. Do not invent new formulas; preserve code blocks and inline
math exactly. Output only a valid JSON object — no surrounding commentary.
Respond in formal English.
"""
)


def translate_and_explain(client: "OpenAI", segment: TranscriptSegment) -> TranscriptSegment:
    user_payload = json.dumps({"id": segment.segment_id, "text": segment.original_zh}, ensure_ascii=False)

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": TRANSLATION_EXPLANATION_PROMPT},
            {"role": "user", "content": user_payload},
        ],
    )

    # Extract the model content and parse JSON
    content = "{}"
    try:
        content = response.choices[0].message.content or "{}"
    except Exception:
        # Defensive fallback if structure differs
        raise TranslationAlignmentError("Model response missing expected message content")

    try:
        payload = json.loads(content)
    except Exception:
        raise TranslationAlignmentError("Model returned invalid JSON")

    # Validate identifier alignment
    if payload.get("id") != segment.segment_id:
        raise TranslationAlignmentError("Response identifier does not match segment id")

    translation = payload.get("translation")
    explanation = payload.get("explanation")

    if not isinstance(translation, str) or not translation.strip():
        raise TranslationAlignmentError("Translation missing or empty")

    if not isinstance(explanation, str):
        raise TranslationAlignmentError("Explanation missing or invalid")

    return replace(segment, translation_en=translation.strip(), explanation_en=explanation.strip())
