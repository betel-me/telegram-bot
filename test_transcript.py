# test_transcript.py
from youtube_transcript_api import YouTubeTranscriptApi

video_id = "DZTTca7DBTk"

try:
    ytt_api = YouTubeTranscriptApi()
    transcript_list = ytt_api.list(video_id)

    print("Available transcripts:")
    for t in transcript_list:
        print(f"  - {t.language_code} (auto-generated: {t.is_generated})")

    transcript = transcript_list.find_transcript(['de'])
    fetched = transcript.fetch()

    print(f"\n✅ Got {len(fetched)} subtitle entries")
    print(fetched[0])  # FetchedTranscriptSnippet object

except Exception as e:
    print(f"❌ Error: {type(e).__name__}: {e}")