# services/translator.py
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from deep_translator import GoogleTranslator

logger = logging.getLogger(__name__)

# In-memory cache so we never translate the same string twice in one run.
# (For cross-run caching, you can later back this with the DB - see note at bottom.)
_translation_cache = {}

MAX_WORKERS = 8  # concurrent translation requests


def _cache_key(text, source, target):
    return f"{source}:{target}:{text}"


def _translate_one(text, source, target):
    key = _cache_key(text, source, target)
    if key in _translation_cache:
        return text, _translation_cache[key]

    try:
        translator = GoogleTranslator(source=source, target=target)
        result = translator.translate(text)
        if not result:
            result = text
    except Exception as e:
        logger.warning(f"Translation failed for '{text[:30]}...': {e}")
        result = text

    _translation_cache[key] = result
    return text, result


def translate_word(word, source='de', target='am'):
    """Single word translation (kept for compatibility, used rarely now)."""
    _, result = _translate_one(word, source, target)
    return result


def translate_sentence(sentence, source='de', target='am'):
    """Single sentence translation (kept for compatibility)."""
    _, result = _translate_one(sentence, source, target)
    return result


def translate_batch(texts, source='de', target='am', max_workers=MAX_WORKERS):
    """
    Translate a list of strings concurrently.
    Returns a dict: {original_text: translated_text}
    Duplicate strings are only translated once (cache hit).
    """
    unique_texts = list(dict.fromkeys(texts))  # preserve order, dedupe
    results = {}

    # Serve what's already cached without spending a worker on it
    to_translate = []
    for t in unique_texts:
        key = _cache_key(t, source, target)
        if key in _translation_cache:
            results[t] = _translation_cache[key]
        else:
            to_translate.append(t)

    if not to_translate:
        return results

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_translate_one, text, source, target): text
            for text in to_translate
        }
        for future in as_completed(futures):
            original, translated = future.result()
            results[original] = translated

    return results