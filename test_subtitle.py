# test_subtitle.py  — save this in your project root and run it
from services.subtitle_fetcher import get_subtitles

url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"  # "Me at the zoo" - short video

try:
    subs, duration, title = get_subtitles(url, lang='en')  # test with English first
    print(f"✅ Success! Got {len(subs)} subtitle lines")
    print(f"   Title: {title}")
    print(f"   Duration: {duration}s")
    print(f"   First line: {subs[0]}")
except Exception as e:
    print(f"❌ Error: {e}")