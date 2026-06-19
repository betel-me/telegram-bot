# database/models.py
import sqlite3
from datetime import datetime

def init_db():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        target_lang TEXT DEFAULT 'de',
        native_lang TEXT DEFAULT 'am',
        is_vip BOOLEAN DEFAULT 0,
        vip_expires TEXT,
        bio TEXT,
        profile_complete BOOLEAN DEFAULT 0,
        created_at TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS videos (
        video_id TEXT PRIMARY KEY,
        url TEXT,
        title TEXT,
        duration INTEGER,
        total_segments INTEGER,
        processed_at TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS segments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id TEXT,
        segment_index INTEGER,
        start_time INTEGER,
        end_time INTEGER,
        FOREIGN KEY (video_id) REFERENCES videos(video_id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS words (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        segment_id INTEGER,
        word TEXT,
        translation TEXT,
        example_sentences TEXT,
        example_translations TEXT,
        FOREIGN KEY (segment_id) REFERENCES segments(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS user_progress (
        user_id INTEGER,
        video_id TEXT,
        words_learned INTEGER DEFAULT 0,
        last_segment INTEGER DEFAULT 0,
        completed BOOLEAN DEFAULT 0,
        PRIMARY KEY (user_id, video_id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        currency TEXT,
        status TEXT,
        provider_payment_id TEXT,
        created_at TEXT
    )''')
    
    existing_cols = [row[1] for row in c.execute("PRAGMA table_info(users)").fetchall()]
    if 'photo_file_id' not in existing_cols:
        c.execute("ALTER TABLE users ADD COLUMN photo_file_id TEXT")
    
    # Add level column to words table
    existing_words_cols = [row[1] for row in c.execute("PRAGMA table_info(words)").fetchall()]
    if 'level' not in existing_words_cols:
        c.execute("ALTER TABLE words ADD COLUMN level TEXT")
    
    # Add cefr_level column to users table
    existing_user_cols = [row[1] for row in c.execute("PRAGMA table_info(users)").fetchall()]
    if 'cefr_level' not in existing_user_cols:
        c.execute("ALTER TABLE users ADD COLUMN cefr_level TEXT DEFAULT 'B1'")
    
    conn.commit()
    conn.close()