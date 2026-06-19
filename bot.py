# bot.py
from telegram.ext import Application
from config import BOT_TOKEN
from database.models import init_db
from handlers.start import start_handler, profile_handler, get_registration_handler
from handlers.payment import get_payment_handlers
from handlers.video_processor import handle_youtube_link
from telegram.ext import CommandHandler, MessageHandler, filters
# bot.py - Add better error handling
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import services.subtitle_fetcher as subtitle_fetcher

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    user_id = update.effective_user.id
    
    try:
        # Send "processing" message
        status_msg = await update.message.reply_text("⏳ Processing video...")
        
        # Try to get subtitles with better error handling
        try:
            segments, duration, title = subtitle_fetcher.get_subtitles(url)
            
            # Success - send the subtitles or summary
            await status_msg.edit_text(f"✅ Successfully downloaded subtitles for:\n📹 {title}")
            # ... process subtitles further
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error for user {user_id}: {error_msg}")
            
            # Send user-friendly error message
            await status_msg.edit_text(f"❌ Error:\n{error_msg}")
            
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ An unexpected error occurred. Please try again later.")

# ... rest of your bot code

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("profile", profile_handler))
    app.add_handler(get_registration_handler())

    for h in get_payment_handlers():
        app.add_handler(h)

    app.add_handler(MessageHandler(filters.Regex(r'(youtube\.com|youtu\.be)'), handle_youtube_link))

    app.run_polling()

if __name__ == '__main__':
    main()