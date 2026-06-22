# services/word_extractor.py
import re
import os
import logging
from collections import Counter

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Aggressive stopword list - covers pronouns, articles, conjunctions, modal/aux verbs,
# fillers, and the junk that was leaking through before (ist, war, sich, mich, etc.)
GERMAN_STOPWORDS = {
    # articles
    'der', 'die', 'das', 'den', 'dem', 'des', 'ein', 'eine', 'einen', 'einem', 'einer', 'eines',
    # personal pronouns
    'ich', 'du', 'er', 'sie', 'es', 'wir', 'ihr', 'mich', 'dich', 'ihn', 'uns', 'euch',
    'mir', 'dir', 'ihm', 'ihnen', 'man',
    # possessives
    'mein', 'meine', 'meinen', 'meinem', 'meiner', 'meins',
    'dein', 'deine', 'deinen', 'deinem', 'deiner',
    'sein', 'seine', 'seinen', 'seinem', 'seiner',
    'unser', 'unsere', 'unseren', 'unserem', 'unserer',
    'euer', 'eure', 'euren', 'eurem', 'eurer',
    'ihre', 'ihren', 'ihrem', 'ihrer',
    # conjunctions / connectors
    'und', 'oder', 'aber', 'denn', 'sondern', 'doch', 'weil', 'dass', 'ob', 'wenn',
    'als', 'wie', 'während', 'bevor', 'nachdem', 'seit', 'bis', 'seitdem', 'also',
    # prepositions
    'zu', 'von', 'mit', 'für', 'auf', 'bei', 'aus', 'nach', 'in', 'an', 'über',
    'unter', 'neben', 'zwischen', 'vor', 'hinter', 'ohne', 'durch', 'gegen', 'um',
    # negation / quantity / filler adverbs
    'nicht', 'kein', 'keine', 'keinen', 'keinem', 'keiner', 'ja', 'nein', 'vielleicht',
    'bitte', 'danke', 'gern', 'gerne', 'sehr', 'so', 'auch', 'nur', 'noch', 'schon',
    'wohl', 'eigentlich', 'gar', 'fast', 'etwa', 'viel', 'wenig', 'ganz', 'halb',
    'genau', 'immer', 'nie', 'manchmal', 'oft', 'selten', 'irgendwie', 'einfach',
    'halt', 'mal', 'dann', 'jetzt', 'hier', 'da', 'dort',
    # question words
    'was', 'wo', 'wer', 'wann', 'warum', 'wozu', 'weshalb',
    'welcher', 'welche', 'welches', 'welchen', 'welchem',
    # to be / to have / modal verbs (all forms) -- the junk that was leaking through
    'ist', 'sind', 'war', 'waren', 'bin', 'bist', 'seid', 'sei', 'wäre', 'wären',
    'hat', 'habe', 'hast', 'habt', 'haben', 'hatte', 'hatten', 'hättest', 'hätte',
    'wird', 'werden', 'wurde', 'wurden', 'würde', 'würden',
    'kann', 'kannst', 'können', 'könnt', 'konnte', 'konnten', 'könnte',
    'muss', 'musst', 'müssen', 'müsst', 'musste', 'mussten',
    'soll', 'sollst', 'sollen', 'sollt', 'sollte', 'sollten',
    'darf', 'darfst', 'dürfen', 'dürft', 'durfte', 'durften',
    'will', 'willst', 'wollen', 'wollt', 'wollte', 'wollten',
    'mag', 'magst', 'mögen', 'mögt', 'mochte', 'mochten',
    # reflexive
    'sich', 'mich', 'dich',
    # other very common filler
    'noch', 'echt', 'krass', 'also', 'naja', 'ähm', 'äh', 'okay', 'ok',
}

_FREQ_CACHE = None


def load_frequency_list(path=None):
    """German word frequency list (lower rank = more common).
    Source: hermitdave/FrequencyWords. Returns {} if file is missing
    (extraction still works, just without CEFR-level tagging)."""
    global _FREQ_CACHE
    if _FREQ_CACHE is not None:
        return _FREQ_CACHE

    if path is None:
        path = os.path.join(DATA_DIR, "de_50k.txt")

    freq = {}
    try:
        with open(path, encoding='utf-8') as f:
            for rank, line in enumerate(f):
                parts = line.split()
                if parts:
                    freq[parts[0].lower()] = rank
    except FileNotFoundError:
        logger.warning(
            f"Frequency list not found at {path}. "
            "Run scripts/download_frequency_lists.py for CEFR-level tagging. "
            "Falling back to plain frequency ranking."
        )

    _FREQ_CACHE = freq
    return freq


def get_cefr_level(rank):
    if rank < 500:
        return 'A1'
    if rank < 1500:
        return 'A2'
    if rank < 3000:
        return 'B1'
    if rank < 6000:
        return 'B2'
    if rank < 12000:
        return 'C1'
    return 'C2'


def extract_keywords(text, top_n=20, user_level='B1'):
    """
    Returns a list of {'word': str, 'level': str} in ORDER OF FIRST APPEARANCE
    in the text (not by frequency) -- matches what the user actually wants:
    a vocabulary list that follows the video's narrative order.
    """
    words_in_order = re.findall(r'\b[a-zA-ZäöüßÄÖÜ]+\b', text)

    freq_list = load_frequency_list()
    level_max_rank = {'A1': 1500, 'A2': 3000, 'B1': 6000, 'B2': 12000, 'C1': 20000, 'C2': 999999}
    max_rank = level_max_rank.get(user_level, 6000)

    seen = set()
    candidates = []  # (word_lower, original_word, first_index)

    for idx, w in enumerate(words_in_order):
        lw = w.lower()
        if lw in GERMAN_STOPWORDS or len(lw) < 3:
            continue
        if lw in seen:
            continue
        seen.add(lw)
        candidates.append((lw, w, idx))

    # Score: prefer words near/below the learner's level (real vocabulary, not noise),
    # but don't hard-exclude harder words -- just deprioritize them.
    scored = []
    for lw, original, idx in candidates:
        rank = freq_list.get(lw, 999999)
        if rank == 999999:
            score = 0.5  # unknown to frequency list -- could be a proper noun or rare/advanced word
        elif rank <= max_rank:
            score = 1.0 - (rank / max_rank) * 0.3
        else:
            score = 0.3
        scored.append((lw, original, idx, score, rank))

    # Take the highest-scoring N, then RE-SORT by appearance order for final output
    top = sorted(scored, key=lambda x: -x[3])[:top_n]
    top_in_order = sorted(top, key=lambda x: x[2])

    return [
        {'word': original, 'level': get_cefr_level(rank)}
        for lw, original, idx, score, rank in top_in_order
    ]


def find_example_sentences(word, lines, max_examples=2):
    """Find up to max_examples lines containing the word (whole-word match)."""
    pattern = re.compile(r'\b' + re.escape(word.lower()) + r'\b')
    examples = []
    seen = set()
    for line in lines:
        if pattern.search(line.lower()) and line not in seen:
            examples.append(line)
            seen.add(line)
            if len(examples) >= max_examples:
                break
    return examples