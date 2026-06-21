# database/db.py
import sqlite3
import json
from datetime import datetime

DB_PATH = 'bot.db'


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_or_get_user(user_id, username, first_name):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        c.execute(
            "INSERT INTO users (user_id, username, first_name, created_at) VALUES (?,?,?,?)",
            (user_id, username, first_name, datetime.now().isoformat())
        )
        conn.commit()
        c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        row = c.fetchone()
    conn.close()
    return dict(row)


def update_user_field(user_id, field, value):
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"UPDATE users SET {field}=? WHERE user_id=?", (value, user_id))
    conn.commit()
    conn.close()


def get_user(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def is_vip(user_id):
    user = get_user(user_id)
    if not user or not user['is_vip']:
        return False
    if user['vip_expires']:
        return datetime.fromisoformat(user['vip_expires']) > datetime.now()
    return False


def save_video_data(video_id, url, title, duration, segments_data):
    """
    segments_data: list of dicts with keys:
        index, start, end, translation (list of {source,target}), vocabulary (list of {word,meaning})
    Cache key is video_id alone for now -- if you support multiple target/native
    language pairs per video, prefix video_id with the language pair before calling this.
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO videos (video_id, url, title, duration, total_segments, processed_at) "
        "VALUES (?,?,?,?,?,?)",
        (video_id, url, title, duration, len(segments_data), datetime.now().isoformat())
    )

    # Clear old segments for this video (in case of reprocessing)
    c.execute("DELETE FROM segments WHERE video_id=?", (video_id,))

    for seg in segments_data:
        c.execute(
            "INSERT INTO segments (video_id, segment_index, start_time, end_time, translation_json, vocabulary_json) "
            "VALUES (?,?,?,?,?,?)",
            (
                video_id,
                seg['index'],
                seg['start'],
                seg['end'],
                json.dumps(seg.get('translation', [])),
                json.dumps(seg.get('vocabulary', [])),
            )
        )

    conn.commit()
    conn.close()


def get_cached_video(video_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM videos WHERE video_id=?", (video_id,))
    video = c.fetchone()
    if not video:
        conn.close()
        return None

    c.execute("SELECT * FROM segments WHERE video_id=? ORDER BY segment_index", (video_id,))
    segments = c.fetchall()
    conn.close()

    result_segments = []
    for seg in segments:
        result_segments.append({
            'index': seg['segment_index'],
            'start': seg['start_time'],
            'end': seg['end_time'],
            'translation': json.loads(seg['translation_json']) if seg['translation_json'] else [],
            'vocabulary': json.loads(seg['vocabulary_json']) if seg['vocabulary_json'] else [],
        })

    return {
        'video_id': video_id,
        'title': video['title'],
        'segments': result_segments,
    }