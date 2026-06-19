# services/word_extractor.py
import re
from collections import Counter

STOPWORDS_DE = {
    'der','die','das','und','ist','ich','du','er','sie','es','wir','ihr',
    'ein','eine','einen','einem','einer','zu','von','mit','auf','für','nicht','auch',
    'als','am','im','in','dem','den','des','sich','wie','war','sind','waren',
    'aber','oder','so','an','um','aus','nach','bei','noch','nur','schon',
    'wenn','was','wird','wurde','haben','hat','sein','kann','muss','soll',
    'mich','mir','dich','dir','uns','euch','ihm','ihn','ihre','sein','seine',
    'da','dann','doch','denn','ja','nein','ganz','sehr','mehr','also'
}

# Load a German frequency list (CEFR-tagged). Format: word -> rank (lower = more common/basic)
# Download from: https://github.com/hermitdave/FrequencyWords (CC-BY-SA)
_FREQ_CACHE = None

def load_frequency_list(path='data/de_50k.txt'):
    global _FREQ_CACHE
    if _FREQ_CACHE is not None:
        return _FREQ_CACHE

    freq = {}
    try:
        with open(path, encoding='utf-8') as f:
            for rank, line in enumerate(f):
                word = line.split()[0].lower()
                freq[word] = rank
    except FileNotFoundError:
        pass  # fallback: no frequency data available

    _FREQ_CACHE = freq
    return freq


def get_cefr_level(rank):
    """Rough mapping of frequency rank to CEFR level"""
    if rank < 500: return 'A1'
    if rank < 1500: return 'A2'
    if rank < 3000: return 'B1'
    if rank < 6000: return 'B2'
    if rank < 12000: return 'C1'
    return 'C2'


def lemmatize_simple(word):
    """Very basic German lemmatization - strip common inflections.
    For production, use spaCy with de_core_news_sm model."""
    # Remove plural/case endings (simplified)
    suffixes = ['en', 'er', 'es', 'em', 'e', 'n', 's']
    for suf in suffixes:
        if word.endswith(suf) and len(word) - len(suf) > 3:
            base = word[:-len(suf)]
            return base
    return word


def extract_keywords(text, top_n=20, user_level='B1', use_frequency_filter=True):
    words = re.findall(r'\b[a-zA-ZäöüÄÖÜß]+\b', text)

    # Keep original casing for nouns (German capitalizes nouns - useful signal)
    word_info = []
    for w in words:
        lw = w.lower()
        if lw in STOPWORDS_DE or len(lw) < 3:
            continue
        word_info.append({'original': w, 'lower': lw, 'is_noun_like': w[0].isupper()})

    freq_counter = Counter(w['lower'] for w in word_info)

    if use_frequency_filter:
        freq_list = load_frequency_list()
        level_max_rank = {'A1': 1500, 'A2': 3000, 'B1': 6000, 'B2': 12000, 'C1': 20000, 'C2': 999999}
        max_rank = level_max_rank.get(user_level, 6000)

        scored = []
        for word, count in freq_counter.items():
            rank = freq_list.get(word, 999999)
            # Score: prefer words within learner's level range, weighted by frequency in video
            if rank == 999999:
                # Unknown word - might be advanced/proper noun, give moderate priority
                relevance = count * 0.5
            elif rank <= max_rank:
                relevance = count * (1.0 - rank / max_rank * 0.3)  # slight boost to lower-rank (easier) words
            else:
                # Word is harder than learner's level - lower priority but not excluded
                relevance = count * 0.3

            scored.append((word, relevance, get_cefr_level(rank)))

        scored.sort(key=lambda x: -x[1])
        return [{'word': w, 'level': lvl} for w, _, lvl in scored[:top_n]]
    else:
        most_common = freq_counter.most_common(top_n)
        return [{'word': w, 'level': 'unknown'} for w, _ in most_common]


def find_example_sentences(word, lines, max_examples=3):
    examples = []
    seen = set()
    for line in lines:
        if word.lower() in line.lower() and line not in seen:
            examples.append(line)
            seen.add(line)
            if len(examples) >= max_examples:
                break
    return examples