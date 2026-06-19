# services/translator.py
from deep_translator import GoogleTranslator

def translate_word(word, source='de', target='am'):
    try:
        translator = GoogleTranslator(source=source, target=target)
        return translator.translate(word)
    except Exception as e:
        return f"[translation error: {e}]"

def translate_sentence(sentence, source='de', target='am'):
    try:
        translator = GoogleTranslator(source=source, target=target)
        return translator.translate(sentence)
    except Exception as e:
        return f"[translation error: {e}]"

def batch_translate(words, source='de', target='am'):
    """Translate efficiently - GoogleTranslator handles one at a time,
    but we batch with delays to avoid rate limits"""
    import time
    results = {}
    translator = GoogleTranslator(source=source, target=target)
    for word in words:
        try:
            results[word] = translator.translate(word)
            time.sleep(0.3)  # avoid rate limiting
        except Exception:
            results[word] = word  # fallback to original
    return results