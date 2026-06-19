# test_single_video.py
import services.subtitle_fetcher as sf
import logging

logging.basicConfig(level=logging.INFO)

url = "https://youtu.be/DZTTca7DBTk?si=OPg2DFS8XddV78Vs"
try:
    segments, duration, title = sf.get_subtitles(url, 'de')
    print(f"✅ Success! Title: {title}")
    print(f"Duration: {duration} seconds")
    print(f"Number of segments: {len(segments)}")
    print(f"First segment: {segments[0] if segments else 'None'}")
except Exception as e:
    print(f"❌ Error: {e}")