# services/subtitle_fetcher.py
import re
import os
import logging
import requests
from collections import Counter
from deep_translator import GoogleTranslator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# German stopwords
GERMAN_STOPWORDS = {
    'der', 'die', 'das', 'den', 'dem', 'des', 'ein', 'eine', 'einen', 'einem', 'einer',
    'und', 'oder', 'aber', 'denn', 'sondern', 'doch', 'weil', 'dass', 'ob', 'wenn',
    'als', 'wie', 'während', 'bevor', 'nachdem', 'seit', 'bis', 'seitdem',
    'ich', 'du', 'er', 'sie', 'es', 'wir', 'ihr', 'Sie',
    'mir', 'dir', 'ihm', 'ihr', 'uns', 'euch', 'Ihnen',
    'mein', 'dein', 'sein', 'ihr', 'unser', 'euer', 'Ihr',
    'der', 'die', 'das', 'den', 'dem', 'des', 'ein', 'eine', 'einen', 'einem', 'einer',
    'zu', 'von', 'mit', 'für', 'auf', 'bei', 'aus', 'nach', 'in', 'an', 'über',
    'unter', 'neben', 'zwischen', 'vor', 'hinter', 'ohne', 'durch', 'gegen',
    'nicht', 'kein', 'keine', 'keinen', 'keinem', 'keiner',
    'ja', 'nein', 'vielleicht', 'bitte', 'danke', 'gern', 'gerne',
    'sehr', 'so', 'auch', 'nur', 'noch', 'schon', 'wohl', 'eigentlich',
    'gar', 'fast', 'etwa', 'viel', 'wenig', 'ganz', 'halb', 'genau',
    'immer', 'nie', 'manchmal', 'oft', 'selten', 'man', 'es', 'was', 'wie',
    'wo', 'wer', 'wann', 'warum', 'wozu', 'weshalb', 'welcher', 'welche', 'welches'
}


def get_subtitles(youtube_url, lang='de'):
    """Fetch subtitles from YouTube video."""
    try:
        video_id = extract_video_id(youtube_url)
        if not video_id or video_id == 'unknown':
            raise Exception(f"Could not extract video ID from URL: {youtube_url}")

        logger.info(f"Fetching subtitles for video: {video_id}")

        segments = None
        duration = 0
        title = "Unknown Title"
        used_lang = lang

        # METHOD 1: youtube_transcript_api — fastest & most reliable
        try:
            logger.info("Trying youtube_transcript_api...")
            from youtube_transcript_api import YouTubeTranscriptApi

            ytt_api = YouTubeTranscriptApi()
            transcript_list = ytt_api.list(video_id)

            try:
                transcript = transcript_list.find_transcript([lang])
                used_lang = lang
                logger.info(f"Found {lang} transcript")
            except Exception:
                try:
                    transcript = transcript_list.find_transcript(['en'])
                    used_lang = 'en'
                    logger.info("Found English transcript")
                except Exception:
                    transcript = next(iter(transcript_list))
                    used_lang = transcript.language_code
                    logger.info(f"Using {used_lang} transcript")

            fetched = transcript.fetch()

            # v1.0+ returns FetchedTranscriptSnippet objects, not dicts
            segments = []
            for item in fetched:
                segments.append({
                    'start': item.start,
                    'end': item.start + item.duration,
                    'text': item.text
                })

            # Try to get video title via a lightweight request
            try:
                response = requests.get(youtube_url, timeout=10)
                if response.status_code == 200:
                    title_match = re.search(r'<title>(.+?)</title>', response.text)
                    if title_match:
                        title = title_match.group(1).replace(' - YouTube', '')
            except Exception:
                pass

            if segments:
                logger.info(f"Successfully fetched {len(segments)} subtitle segments")
                return segments, duration, title, video_id, used_lang

        except ImportError:
            logger.warning("youtube_transcript_api not installed. Run: pip install youtube-transcript-api")
        except Exception as e:
            logger.warning(f"youtube_transcript_api failed: {e}")

        # METHOD 2 (fallback): yt-dlp subtitle download
        try:
            logger.info("Fallback: Trying yt-dlp...")
            import yt_dlp

            output_path = f'/tmp/{video_id}'
            ydl_opts = {
                'skip_download': True,
                'writesubtitles': True,
                'writeautomaticsub': True,
                'subtitleslangs': [lang, 'en'],
                'subtitlesformat': 'vtt',
                'quiet': True,
                'no_warnings': True,
                'outtmpl': output_path,
                'sleep_interval': 2,
                'max_sleep_interval': 5,
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'extractor_args': {
                    'youtube': {
                        'player_client': ['web'],
                    }
                }
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=True)
                duration = info.get('duration', 0)
                title = info.get('title', 'Unknown Title')

            # Find subtitle file
            for f in os.listdir('/tmp'):
                if video_id in f and f.endswith('.vtt'):
                    sub_path = f'/tmp/{f}'
                    segments = parse_vtt(sub_path)
                    if segments:
                        logger.info(f"Successfully fetched {len(segments)} subtitle segments")
                        return segments, duration, title, video_id, lang

        except ImportError:
            logger.warning("yt_dlp not installed. Run: pip install yt-dlp")
        except Exception as e:
            logger.warning(f"yt-dlp fallback failed: {e}")

        # If all methods failed
        raise Exception(
            "❌ Could not fetch subtitles for this video.\n\n"
            "Possible reasons:\n"
            "• The video doesn't have subtitles\n"
            "• YouTube is blocking the request\n"
            "• The video is age-restricted or private\n\n"
            "💡 Try a different video with captions enabled."
        )

    except Exception as e:
        logger.error(f"Error in get_subtitles: {e}", exc_info=True)
        raise


def parse_vtt(path):
    """Parse VTT file and return segments with timestamps."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        return parse_vtt_from_text(content)
    except:
        return []


def parse_vtt_from_text(content):
    """Parse VTT content directly from text."""
    segments = []
    lines = content.split('\n')
    current_text = []
    current_start = None
    current_end = None
    
    for line in lines:
        line = line.strip()
        
        if line.startswith('WEBVTT') or line.startswith('Kind:') or line.startswith('Language:'):
            continue
        
        if '-->' in line:
            if current_start is not None and current_text:
                text = ' '.join(current_text).strip()
                text = re.sub(r'<[^>]+>', '', text)
                text = re.sub(r'\s+', ' ', text)
                if text:
                    try:
                        start = time_to_seconds(current_start)
                        end = time_to_seconds(current_end) if current_end else start + 3.0
                        segments.append({
                            'start': start,
                            'end': end,
                            'text': text
                        })
                    except:
                        pass
            
            try:
                parts = line.split('-->')
                current_start = parts[0].strip()
                current_end = parts[1].strip() if len(parts) > 1 else None
                current_text = []
            except:
                current_start = None
                current_end = None
                current_text = []
        elif line and not line.isdigit():
            if current_start is not None:
                current_text.append(line)
    
    # Save last segment
    if current_start is not None and current_text:
        text = ' '.join(current_text).strip()
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text)
        if text:
            try:
                start = time_to_seconds(current_start)
                end = time_to_seconds(current_end) if current_end else start + 3.0
                segments.append({
                    'start': start,
                    'end': end,
                    'text': text
                })
            except:
                pass
    
    return segments


def time_to_seconds(t):
    """Convert timestamp to seconds."""
    t = t.strip()
    try:
        if '.' in t:
            parts = t.split(':')
            if len(parts) == 3:
                h, m, s = parts
                return int(h) * 3600 + int(m) * 60 + float(s)
            elif len(parts) == 2:
                m, s = parts
                return int(m) * 60 + float(s)
        else:
            parts = t.split(':')
            if len(parts) == 3:
                h, m, s = parts
                return int(h) * 3600 + int(m) * 60 + int(s)
            elif len(parts) == 2:
                m, s = parts
                return int(m) * 60 + int(s)
            else:
                return int(t)
    except:
        return 0


def extract_video_id(url):
    """Extract YouTube video ID."""
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11})(?:[?&]|$)',
        r'youtu\.be\/([0-9A-Za-z_-]{11})(?:[?&]|$)',
        r'youtube\.com\/shorts\/([0-9A-Za-z_-]{11})',
        r'youtube\.com\/embed\/([0-9A-Za-z_-]{11})'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return 'unknown'


def extract_important_words(segments, words_per_segment=20):
    """Extract important words from subtitles."""
    if not segments:
        return []
    
    chunk_duration = 120
    chunks = []
    current_chunk = []
    current_time = 0
    
    for segment in segments:
        if segment['start'] >= current_time + chunk_duration:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = [segment]
            current_time = segment['start']
        else:
            current_chunk.append(segment)
    
    if current_chunk:
        chunks.append(current_chunk)
    
    results = []
    for chunk in chunks:
        full_text = ' '.join([seg['text'] for seg in chunk])
        words = re.findall(r'\b[a-zA-ZäöüßÄÖÜ]+\b', full_text.lower())
        word_freq = Counter(words)
        
        important_words = []
        for word, count in word_freq.most_common(50):
            if word not in GERMAN_STOPWORDS and len(word) > 2:
                important_words.append({
                    'word': word,
                    'frequency': count,
                    'context': get_context(chunk, word)
                })
                if len(important_words) >= words_per_segment:
                    break
        
        if important_words:
            results.append({
                'segment_start': chunk[0]['start'],
                'segment_end': chunk[-1]['end'],
                'words': important_words
            })
    
    return results


def get_context(chunk, target_word):
    """Get sentences containing the target word from a chunk."""
    contexts = []
    for segment in chunk:
        text = segment['text']
        sentences = re.split(r'[.!?]', text)
        for sentence in sentences:
            if target_word in sentence.lower():
                contexts.append(sentence.strip())
                if len(contexts) >= 3:
                    break
        if len(contexts) >= 3:
            break
    return contexts


def translate_words(words_data, target_lang='am'):
    """Translate words and contexts to target language."""
    try:
        translator = GoogleTranslator(source='de', target=target_lang)
    except:
        return words_data
    
    translated_data = []
    
    for chunk in words_data:
        translated_chunk = {
            'segment_start': chunk['segment_start'],
            'segment_end': chunk['segment_end'],
            'words': []
        }
        
        for word_info in chunk['words']:
            try:
                translation = translator.translate(word_info['word'])
                
                translated_contexts = []
                for context in word_info['context']:
                    try:
                        ctx_trans = translator.translate(context)
                        translated_contexts.append({
                            'original': context,
                            'translated': ctx_trans if ctx_trans else context
                        })
                    except:
                        translated_contexts.append({
                            'original': context,
                            'translated': context
                        })
                
                translated_chunk['words'].append({
                    'original': word_info['word'],
                    'translation': translation if translation else word_info['word'],
                    'frequency': word_info['frequency'],
                    'contexts': translated_contexts
                })
            except:
                translated_chunk['words'].append({
                    'original': word_info['word'],
                    'translation': word_info['word'],
                    'frequency': word_info['frequency'],
                    'contexts': [
                        {'original': ctx, 'translated': ctx} 
                        for ctx in word_info['context']
                    ]
                })
        
        translated_data.append(translated_chunk)
    
    return translated_data