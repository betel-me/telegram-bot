# bot.py
import logging
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    CallbackQueryHandler, ContextTypes,
)
from telegram import Update

from config import BOT_TOKEN
from database.models import init_db
from database.db import create_or_get_user
from handlers.start import start_handler, profile_handler, get_registration_handler
from handlers.payment import get_payment_handlers
from handlers.video_processor import handle_youtube_link, handle_segment_navigation

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def on_start_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Make sure every user who hits /start exists in the DB, then show the welcome message."""
    user = update.effective_user
    create_or_get_user(user.id, user.username, user.first_name)
    await start_handler(update, context)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 *German Vocabulary Bot*\n\n"
        "*How it works:*\n"
        "1\\. Send me a YouTube link with subtitles\n"
        "2\\. I split it into 2\\-minute segments\n"
        "3\\. Each segment gets a full translation \\+ 20 key vocabulary words\n\n"
        "*Commands:*\n"
        "/register \\- set up your profile \\(required\\)\n"
        "/profile \\- view your profile\n"
        "/vip \\- premium features and pricing\n"
        "/help \\- this message\n"
    )
    await update.message.reply_text(help_text, parse_mode='MarkdownV2')


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ Something went wrong processing that. Please try again."
            )
        except Exception:
            pass


def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # Core commands
    app.add_handler(CommandHandler("start", on_start_register))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("profile", profile_handler))
    app.add_handler(get_registration_handler())

    # Payments
    for h in get_payment_handlers():
        app.add_handler(h)

    # YouTube link -> AI translation pipeline (handlers/video_processor.py)
    app.add_handler(MessageHandler(
        filters.Regex(r'(youtube\.com|youtu\.be)'),
        handle_youtube_link
    ))

    # Segment navigation buttons (Next/Previous)
    app.add_handler(CallbackQueryHandler(handle_segment_navigation, pattern=r'^seg_'))

    app.add_error_handler(error_handler)

    logger.info("🤖 Bot is starting...")
    app.run_polling()


if __name__ == '__main__':
    main()