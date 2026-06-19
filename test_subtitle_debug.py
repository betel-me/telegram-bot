# test_subtitle_debug.py  — save in project root
import yt_dlp
import os

url = input("Paste YouTube URL: ").strip()

ydl_opts = {
    'skip_download': True,
    'writesubtitles': True,
    'writeautomaticsub': True,
    'subtitleslangs': ['de'],   # Download German subtitles
    'subtitlesformat': 'vtt',
    'quiet': False,              # show full output
    'outtmpl': '/tmp/test_video',
    # 'impersonate': 'chrome',   # Comment out temporarily - causing error
}

# Try without impersonate first
with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    # Download the subtitles
    info = ydl.extract_info(url, download=True)
    
    print("\n=== AVAILABLE SUBTITLES ===")
    subs = info.get('subtitles', {})
    auto_subs = info.get('automatic_captions', {})
    
    print(f"Manual subtitles: {list(subs.keys()) or 'None'}")
    print(f"Auto-generated:   {list(auto_subs.keys()) or 'None'}")

# Check if subtitle file was actually downloaded
print("\n=== CHECKING DOWNLOADED FILES ===")
for f in os.listdir('/tmp'):
    if 'test_video' in f or 'de' in f:
        print(f"Found: {f}")