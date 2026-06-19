# database/db.py
import sqlite3
from datetime import datetime
import json

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
    if not user or not user.get('is_vip'):
        return False
    if user.get('vip_expires'):
        return datetime.fromisoformat(user['vip_expires']) > datetime.now()
    return False

def save_video_data(video_id, url, title, duration, segments_data):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO videos (video_id, url, title, duration, total_segments, processed_at) VALUES (?,?,?,?,?,?)",
        (video_id, url, title, duration, len(segments_data), datetime.now().isoformat())
    )
    
    for seg in segments_data:
        c.execute(
            "INSERT INTO segments (video_id, segment_index, start_time, end_time) VALUES (?,?,?,?)",
            (video_id, seg['index'], seg['start'], seg['end'])
        )
        seg_id = c.lastrowid
        
        for w in seg['words']:
            c.execute(
                "INSERT INTO words (segment_id, word, level, translation, example_sentences, example_translations) VALUES (?,?,?,?,?,?)",
                (seg_id, w['word'], w.get('level', ''), w['translation'], json.dumps(w['examples']), json.dumps(w['example_translations']))
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

    result_segments = []
    for seg in segments:
        c.execute("SELECT * FROM words WHERE segment_id=?", (seg['id'],))
        words = c.fetchall()
        result_segments.append({
            'index': seg['segment_index'],
            'start': seg['start_time'],
            'end': seg['end_time'],
            'words': [{
                'word': w['word'],
                'level': w['level'],  # Added level field here
                'translation': w['translation'],
                'examples': json.loads(w['example_sentences']),
                'example_translations': json.loads(w['example_translations'])
            } for w in words]
        })
    conn.close()
    return {'video_id': video_id, 'segments': result_segments}