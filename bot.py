# bot.py
import logging
import re
import asyncio
import os
import tempfile
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import TimedOut, NetworkError
from services import subtitle_fetcher
import sqlite3

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot token
BOT_TOKEN = "8798006836:AAHwa8V8UrEGELqiQRvBDjv0CqnV7ISSzbk"

# Database setup
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, 
                  username TEXT, 
                  language TEXT DEFAULT 'am',
                  premium INTEGER DEFAULT 0,
                  registered_date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_progress
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  video_id TEXT,
                  words_learned TEXT,
                  timestamp TEXT)''')
    conn.commit()
    conn.close()

init_db()

# User data cache
user_data = {}
processing_tasks = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    # Register user
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (user_id, username, registered_date) VALUES (?, ?, ?)',
              (user_id, user.username or 'unknown', datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    keyboard = [
        [InlineKeyboardButton("🇪🇹 German → Amharic", callback_data="lang_am")],
        [InlineKeyboardButton("🇬🇧 German → English", callback_data="lang_en")],
        [InlineKeyboardButton("🇫🇷 German → French", callback_data="lang_fr")],
        [InlineKeyboardButton("🇪🇸 German → Spanish", callback_data="lang_es")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome = f"""
👋 Hallo {user.first_name}!

🇩🇪 Welcome to German Language Learning Bot!

🎯 **How it works:**
1. Send me a YouTube video link
2. I extract subtitles and find important words
3. Each 2-minute segment → 20 important words with translations
4. Learn vocabulary from real German content!

📌 Example: https://youtu.be/DZTTca7DBTk

**Choose your target language:**
"""
    await update.message.reply_text(welcome, reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if query.data.startswith("lang_"):
        lang = query.data.split("_")[1]
        
        # Update user language preference
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute('UPDATE users SET language = ? WHERE user_id = ?', (lang, user_id))
        conn.commit()
        conn.close()
        
        lang_names = {'am': 'Amharic', 'en': 'English', 'fr': 'French', 'es': 'Spanish'}
        await query.edit_message_text(
            f"✅ Language set to {lang_names.get(lang, lang)}!\n\n"
            "Now send me a YouTube URL to start learning!"
        )

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    user_id = update.effective_user.id
    
    # Check if it's a YouTube URL
    youtube_patterns = [
        r'(?:youtube\.com\/watch\?v=)', 
        r'(?:youtu\.be\/)', 
        r'(?:youtube\.com\/shorts\/)', 
        r'(?:youtube\.com\/embed\/)'
    ]
    
    if not any(re.search(pattern, url) for pattern in youtube_patterns):
        await update.message.reply_text(
            "❌ Please send a valid YouTube URL.\n"
            "Example: https://youtu.be/DZTTca7DBTk"
        )
        return
    
    # Get user language preference
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT language FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    target_lang = result[0] if result else 'am'
    
    # Send processing message
    status_msg = await update.message.reply_text(
        "⏳ **Processing your video...**\n"
        "▸ Fetching subtitles\n"
        "▸ Extracting important words\n"
        "▸ Translating to your language\n\n"
        "⏱️ This may take 30-60 seconds...",
        parse_mode='Markdown'
    )
    
    try:
        # Get subtitles - NOW RETURNS 5 VALUES including used_lang
        segments, duration, title, video_id, used_lang = subtitle_fetcher.get_subtitles(url)
        
        # ========== ADD THE LANGUAGE CHECK HERE ==========
        # Show which language was used if not German
        if used_lang != 'de':
            await status_msg.edit_text(
                f"⚠️ No German subtitles found. Using {used_lang.upper()} subtitles instead.\n\n"
                "⏳ Processing your video...",
                parse_mode='Markdown'
            )
        # ========== END OF LANGUAGE CHECK ==========
        
        if not segments:
            await status_msg.edit_text("❌ No subtitles found for this video.")
            return
        
        # Process in background
        task = asyncio.create_task(
            process_video(update, context, status_msg, segments, duration, title, video_id, target_lang)
        )
        
        if user_id not in processing_tasks:
            processing_tasks[user_id] = []
        processing_tasks[user_id].append(task)
        
    except Exception as e:
        error_msg = str(e)
        # Clean up error message for user
        if "Requested format is not available" in error_msg:
            error_msg = "YouTube format error. Please try a different video."
        elif "429" in error_msg:
            error_msg = "YouTube rate limit reached. Please wait a few minutes and try again."
        elif "Timed out" in error_msg or "ConnectTimeout" in error_msg:
            error_msg = "Connection timed out. Please check your internet and try again."
        
        await status_msg.edit_text(f"❌ Error: {error_msg[:200]}")

async def process_video(update, context, status_msg, segments, duration, title, video_id, target_lang):
    """Process video in background and send results."""
    try:
        # Update progress
        await status_msg.edit_text(
            "🔄 **Processing video...**\n"
            "▸ ✅ Subtitles fetched\n"
            "▸ 🔍 Extracting important words...",
            parse_mode='Markdown'
        )
        
        # Extract important words
        words_data = subtitle_fetcher.extract_important_words(
            segments, 
            words_per_segment=20
        )
        
        if not words_data:
            await status_msg.edit_text(
                "❌ Could not extract words from this video.\n"
                "Try a different video."
            )
            return
        
        total_words = sum(len(chunk['words']) for chunk in words_data)
        total_segments = len(words_data)
        
        await status_msg.edit_text(
            f"🔄 **Processing video...**\n"
            f"▸ ✅ Subtitles fetched\n"
            f"▸ ✅ Extracted {total_words} important words\n"
            f"▸ 🌍 Translating to target language...",
            parse_mode='Markdown'
        )
        
        # Translate
        translated_data = subtitle_fetcher.translate_words(words_data, target_lang)
        
        # Format and send results
        response = f"📹 **{title[:60]}**\n"
        response += f"⏱️ Duration: {duration // 60} minutes\n"
        response += f"📊 Found {total_words} important words in {total_segments} segments\n\n"
        
        # Send first 3 segments with words
        for i, chunk in enumerate(translated_data[:3]):
            minutes = int(chunk['segment_start'] // 60)
            seconds = int(chunk['segment_start'] % 60)
            response += f"**⏰ [{minutes:02d}:{seconds:02d}] Important Words:**\n"
            
            for word in chunk['words'][:10]:
                response += f"• **{word['original']}** → {word['translation']}\n"
                
                if word['contexts']:
                    ctx = word['contexts'][0]
                    response += f"  💬 _{ctx['original'][:60]}..._\n"
                    response += f"  📝 _{ctx['translated'][:60]}..._\n"
            
            response += "\n"
        
        # Send main message
        await status_msg.edit_text(
            response[:4000],
            parse_mode='Markdown'
        )
        
        # Send full word list as file
        full_content = f"📚 Vocabulary: {title}\n\n"
        full_content += f"Total words: {total_words}\n"
        full_content += f"Segments: {total_segments}\n\n"
        full_content += "=" * 50 + "\n\n"
        
        for chunk in translated_data:
            minutes = int(chunk['segment_start'] // 60)
            seconds = int(chunk['segment_start'] % 60)
            full_content += f"⏰ [{minutes:02d}:{seconds:02d}] - {len(chunk['words'])} words\n"
            full_content += "-" * 40 + "\n"
            
            for word in chunk['words']:
                full_content += f"📖 {word['original']} → {word['translation']}\n"
                full_content += f"📊 Frequency: {word['frequency']}\n"
                
                for ctx in word['contexts'][:2]:
                    full_content += f"  💬 {ctx['original']}\n"
                    full_content += f"  📝 {ctx['translated']}\n"
                full_content += "\n"
            
            full_content += "=" * 50 + "\n\n"
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write(full_content)
            f.flush()
            with open(f.name, 'rb') as file:
                await update.message.reply_document(
                    document=file,
                    filename=f"{title[:30]}_vocabulary.txt",
                    caption=f"📄 Full vocabulary list ({total_words} words)"
                )
        os.unlink(f.name)
        
        # Send success message
        await update.message.reply_text(
            f"✅ **Processing Complete!**\n\n"
            f"📚 {total_words} words extracted\n"
            f"📹 From: {title[:50]}\n"
            f"⏱️ Total time: ~{duration // 60} minutes\n\n"
            f"💡 Use /help for more features",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error processing video: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Error processing video: {str(e)[:200]}")

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user profile."""
    user_id = update.effective_user.id
    
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT username, language, premium, registered_date FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    
    if result:
        username, language, premium, reg_date = result
        lang_names = {'am': 'Amharic', 'en': 'English', 'fr': 'French', 'es': 'Spanish'}
        
        profile = f"👤 **Your Profile**\n\n"
        profile += f"Username: @{username or 'Not set'}\n"
        profile += f"Language: {lang_names.get(language, language)}\n"
        profile += f"Premium: {'✅ Active' if premium else '❌ Free'}\n"
        profile += f"Registered: {reg_date[:10] if reg_date else 'Unknown'}\n\n"
        
        if not premium:
            profile += "🔓 **Upgrade to Premium:**\n"
            profile += "• Unlimited videos per day\n"
            profile += "• Advanced AI word selection\n"
            profile += "• Custom vocabulary lists\n"
            profile += "• Priority processing\n"
        
        await update.message.reply_text(profile, parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Profile not found. Use /start to register.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🤖 **German Language Learning Bot**

**How to use:**
1. Send a YouTube URL
2. Bot extracts 20 important words per 2 minutes
3. Get translations and example sentences

**Commands:**
/start - Register and set language
/profile - View your profile
/help - Show this help
/set_lang - Change target language

**Features:**
• 🎯 Smart word extraction
• 🌍 Multi-language support
• 📚 Vocabulary export
• 📊 Progress tracking
• 💰 Premium features

**Language Support:**
🇩🇪 German → 🇪🇹 Amharic
🇩🇪 German → 🇬🇧 English
🇩🇪 German → 🇫🇷 French
🇩🇪 German → 🇪🇸 Spanish
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def set_lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🇪🇹 Amharic", callback_data="lang_am")],
        [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton("🇫🇷 French", callback_data="lang_fr")],
        [InlineKeyboardButton("🇪🇸 Spanish", callback_data="lang_es")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select your target language:", reply_markup=reply_markup)

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Unknown command. Use /help for available commands.")

def main():
    """Start the bot."""
    # Create application with timeout settings
    app = Application.builder() \
        .token(BOT_TOKEN) \
        .connect_timeout(30.0) \
        .read_timeout(30.0) \
        .write_timeout(30.0) \
        .build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("set_lang", set_lang_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    print("🤖 Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()