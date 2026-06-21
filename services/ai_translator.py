# services/ai_translator.py
"""
Replaces the old word-by-word / sentence-by-sentence Google Translate approach.

Instead: send the FULL text of one 2-minute segment to Claude in a single
request, and ask for:
  1. Sentence-by-sentence translation (source -> target language)
  2. A vocabulary table of the 20 most important words/phrases, in order
     of appearance, with target-language meanings.

This cuts a 30-minute video from ~1000+ network calls down to ~15 calls
(one per 2-minute segment), which is what makes it fast like Gemini.
"""

import asyncio
import json
import logging
import os
import httpx
from dotenv import load_dotenv

load_dotenv()  # ensure .env is loaded even if this module is imported before config.py

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"

LANGUAGE_NAMES = {
    'de': 'German', 'en': 'English', 'am': 'Amharic', 'fr': 'French',
    'es': 'Spanish', 'ar': 'Arabic', 'it': 'Italian', 'ru': 'Russian',
    'tr': 'Turkish', 'pt': 'Portuguese', 'zh': 'Chinese', 'ja': 'Japanese',
}


def _build_prompt(segment_text, source_lang, target_lang, words_per_segment=20):
    source_name = LANGUAGE_NAMES.get(source_lang, source_lang)
    target_name = LANGUAGE_NAMES.get(target_lang, target_lang)

    return f"""You are a language-learning assistant. Below is a transcript excerpt in {source_name}.

TASK 1 — Translate it sentence by sentence into {target_name}.
TASK 2 — Then extract the {words_per_segment} most important words or short phrases from the excerpt for a learner, in the ORDER they first appear in the text. For nouns in German, include the definite article (der/die/das). For verbs, give the infinitive. Give the {target_name} meaning for each.

Respond ONLY with valid JSON, no markdown fences, no commentary, in exactly this shape:
{{
  "translation": [
    {{"source": "...", "target": "..."}},
    ...
  ],
  "vocabulary": [
    {{"word": "...", "meaning": "..."}},
    ...
  ]
}}

TRANSCRIPT:
\"\"\"
{segment_text}
\"\"\"
"""


async def _call_claude(client, prompt, max_tokens=4000):
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to your .env file. "
            "Get a key from https://console.anthropic.com"
        )

    response = await client.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60.0,
    )
    if response.status_code >= 400:
        # Log the ACTUAL error body from Anthropic instead of swallowing it
        logger.error(f"Anthropic API error {response.status_code}: {response.text}")
    response.raise_for_status()
    data = response.json()

    text_parts = [block["text"] for block in data["content"] if block.get("type") == "text"]
    raw_text = "".join(text_parts).strip()

    # Strip accidental markdown fences if the model adds them
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.startswith("json"):
            raw_text = raw_text[4:].strip()

    return json.loads(raw_text)


async def process_segment_with_ai(segment_text, source_lang='de', target_lang='am', words_per_segment=20):
    """
    Single segment -> {translation: [...], vocabulary: [...]}
    """
    prompt = _build_prompt(segment_text, source_lang, target_lang, words_per_segment)

    async with httpx.AsyncClient() as client:
        try:
            result = await _call_claude(client, prompt)
            return result
        except json.JSONDecodeError as e:
            logger.error(f"AI returned non-JSON output: {e}")
            return {"translation": [], "vocabulary": []}
        except Exception as e:
            logger.error(f"AI segment processing failed: {type(e).__name__}: {e}", exc_info=True)
            return {"translation": [], "vocabulary": []}


async def process_all_segments(segments_text_list, source_lang='de', target_lang='am',
                                 words_per_segment=20, max_concurrent=5):
    """
    segments_text_list: list of plain text strings, one per 2-minute segment.
    Returns: list of {translation, vocabulary} dicts, same order/length as input.

    Runs up to `max_concurrent` segments in parallel so a 30-min video
    (≈15 segments) finishes in roughly the time of 3 sequential calls,
    not 15.
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def bounded_call(text):
        async with semaphore:
            return await process_segment_with_ai(text, source_lang, target_lang, words_per_segment)

    tasks = [bounded_call(text) for text in segments_text_list]
    results = await asyncio.gather(*tasks)
    return results