# services/subtitle_fetcher.py
import yt_dlp
import re
import time
import os
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_subtitles(youtube_url, lang='de'):
    try:
        video_id = extract_video_id(youtube_url)
        if not video_id or video_id == 'unknown':
            raise Exception(f"Could not extract video ID from URL: {youtube_url}")
        
        output_path = f'/tmp/{video_id}'
        
        logger.info(f"Fetching subtitles for video: {video_id}")

        # First: check what subtitles are actually available
        available = check_available_subtitles(youtube_url)
        logger.info(f"Available subtitles: manual={available['manual']}, auto={available['auto']}")
        
        # Build language fallback list
        lang_variants = [lang, f'{lang}-{lang.upper()}']
        
        manual_available = [l for l in lang_variants if l in available['manual']]
        auto_available = [l for l in available['auto'] if l.startswith(lang)]
        
        if not manual_available and not auto_available:
            available_list = available['manual'] + available['auto'][:5]
            raise Exception(
                f"No {lang.upper()} subtitles found for this video.\n"
                f"Available languages: {available_list or 'none found'}\n"
                "Try a different video or change your target language in /profile."
            )

        # Pick best available language code
        best_lang = manual_available[0] if manual_available else auto_available[0]
        logger.info(f"Best language match: {best_lang}")

        ydl_opts = {
            'skip_download': True,
            'writesubtitles': bool(manual_available),
            'writeautomaticsub': bool(auto_available) and not manual_available,
            'subtitleslangs': [best_lang],
            'subtitlesformat': 'vtt',
            'quiet': False,
            'no_warnings': False,
            'outtmpl': output_path,
            'sleep_interval': 5,
            'max_sleep_interval': 10,
            'sleep_interval_requests': 2,
            'verbose': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'source_address': '0.0.0.0',
            'extractor_args': {
                'youtube': {
                    'skip': ['dash', 'hls'],
                    'player_client': ['android'],
                }
            }
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                logger.info("Starting download...")
                info = ydl.extract_info(youtube_url, download=True)
                video_id = info.get('id', video_id)
                duration = info.get('duration', 0)
                title = info.get('title', 'Unknown Title')
                logger.info(f"Download complete: {title}")
            except yt_dlp.utils.DownloadError as e:
                error_msg = str(e)
                if '429' in error_msg:
                    raise Exception(
                        "YouTube rate limit hit (429). Please wait 10-15 minutes and try again.\n"
                        "Tip: Add cookies.txt file to bypass rate limiting."
                    )
                elif '400' in error_msg:
                    raise Exception(
                        "YouTube returned a 400 error. This could be due to:\n"
                        "• The video doesn't have subtitles\n"
                        "• YouTube is blocking the request\n"
                        "• Try using a different video or try again later"
                    )
                elif 'Unable to download video subtitles' in error_msg:
                    raise Exception(
                        f"Failed to download subtitles. The video may not have subtitles available.\n"
                        f"Technical details: {error_msg[:200]}"
                    )
                else:
                    raise Exception(f"YouTube download error: {error_msg[:200]}")

        # Find the downloaded subtitle file
        sub_path = None
        possible = [
            f'{output_path}.{best_lang}.vtt',
            f'{output_path}.{lang}.vtt',
            f'{output_path}.en.vtt',
        ]
        
        # Also scan /tmp for any matching file
        try:
            for f in os.listdir('/tmp'):
                if video_id in f and f.endswith('.vtt'):
                    possible.append(f'/tmp/{f}')
        except Exception as e:
            logger.warning(f"Could not scan /tmp directory: {e}")

        for path in possible:
            if os.path.exists(path):
                sub_path = path
                logger.info(f"Found subtitle file: {path}")
                break

        if not sub_path:
            # Try to find any .vtt file in /tmp with the video_id
            try:
                tmp_files = [f for f in os.listdir('/tmp') if video_id in f]
                logger.error(f"Files in /tmp with video_id: {tmp_files}")
                raise Exception(
                    f"Subtitle file not found after download.\n"
                    f"Files in /tmp with video_id: {tmp_files or 'none found'}\n"
                    f"Tried paths: {possible}"
                )
            except Exception as e:
                if "Subtitle file not found" in str(e):
                    raise
                raise Exception(f"Error finding subtitle file: {e}")

        # Parse the VTT file
        try:
            segments = parse_vtt(sub_path)
            if not segments:
                raise Exception("Subtitle file was downloaded but contains no segments")
            return segments, duration, title
        except Exception as e:
            raise Exception(f"Error parsing subtitle file: {e}")

    except Exception as e:
        logger.error(f"Error in get_subtitles: {e}", exc_info=True)
        raise


def check_available_subtitles(youtube_url):
    """Return dict of available manual and auto subtitle language codes."""
    ydl_opts = {
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'extractor_args': {
            'youtube': {
                'player_client': ['android'],
            }
        }
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(youtube_url, download=False)
            return {
                'manual': list(info.get('subtitles', {}).keys()),
                'auto': list(info.get('automatic_captions', {}).keys()),
            }
        except Exception as e:
            logger.error(f"Error checking available subtitles: {e}")
            return {'manual': [], 'auto': []}


def parse_vtt(path):
    """Simplified VTT parser that handles most common formats"""
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    segments = []
    lines = content.split('\n')
    current_text = []
    current_start = None
    current_end = None
    
    for line in lines:
        line = line.strip()
        
        # Skip header lines
        if line.startswith('WEBVTT') or line.startswith('Kind:') or line.startswith('Language:'):
            continue
        
        # Check for timestamp line
        if '-->' in line:
            # Save previous segment
            if current_start is not None and current_text:
                text = ' '.join(current_text).strip()
                text = re.sub(r'<[^>]+>', '', text)  # Remove HTML tags
                text = re.sub(r'\s+', ' ', text)      # Normalize spaces
                if text:
                    try:
                        start = time_to_seconds(current_start)
                        # Fix: Use current_end if available, otherwise default to start + 5 seconds
                        if current_end:
                            end = time_to_seconds(current_end)
                        else:
                            end = start + 5.0  # Default 5 second duration
                        segments.append({
                            'start': start,
                            'end': end,
                            'text': text
                        })
                    except Exception as e:
                        print(f"Warning: Could not parse timestamps: {e}")
            
            # Start new segment
            try:
                parts = line.split('-->')
                current_start = parts[0].strip()
                current_end = parts[1].strip() if len(parts) > 1 else None
                current_text = []
            except:
                current_start = None
                current_end = None
                current_text = []
        elif line and not line.isdigit():  # Skip cue numbers
            # Add text to current segment
            if current_start is not None:
                current_text.append(line)
    
    # Save the last segment
    if current_start is not None and current_text:
        text = ' '.join(current_text).strip()
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text)
        if text:
            try:
                start = time_to_seconds(current_start)
                if current_end:
                    end = time_to_seconds(current_end)
                else:
                    end = start + 5.0
                segments.append({
                    'start': start,
                    'end': end,
                    'text': text
                })
            except:
                pass
    
    print(f"Parsed {len(segments)} subtitle segments")
    if segments:
        print(f"First segment: {segments[0]}")
    else:
        print("WARNING: No segments parsed! Checking file content...")
        print(content[:500])
    
    return segments


def time_to_seconds(t):
    """Convert timestamp to seconds with robust error handling"""
    t = t.strip()
    try:
        if '.' in t:
            # Has milliseconds
            parts = t.split(':')
            if len(parts) == 3:
                h, m, s = parts
                return int(h) * 3600 + int(m) * 60 + float(s)
            elif len(parts) == 2:
                m, s = parts
                return int(m) * 60 + float(s)
        else:
            # No milliseconds
            parts = t.split(':')
            if len(parts) == 3:
                h, m, s = parts
                return int(h) * 3600 + int(m) * 60 + int(s)
            elif len(parts) == 2:
                m, s = parts
                return int(m) * 60 + int(s)
            else:
                return int(t)
    except Exception as e:
        print(f"Error parsing time '{t}': {e}")
        return 0


def extract_video_id(url):
    """Extract YouTube video ID from various URL formats"""
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
    
    # Try to find any 11-character ID in the URL
    match = re.search(r'([0-9A-Za-z_-]{11})', url)
    if match:
        return match.group(1)
    
    return 'unknown'