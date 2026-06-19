# handlers/start.py
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters
from database.db import create_or_get_user, update_user_field, get_user

# Conversation states
LANG_TARGET, LANG_NATIVE, LEVEL, BIO, PHOTO = range(5)

LANGUAGES = {
    'de': '🇩🇪 German', 'en': '🇬🇧 English', 'am': '🇪🇹 Amharic',
    'fr': '🇫🇷 French', 'es': '🇪🇸 Spanish', 'ar': '🇸🇦 Arabic'
}

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_or_get_user(user.id, user.username, user.first_name)

    text = (
        f"👋 Welcome {user.first_name}!\n\n"
        "📺 Send me a YouTube link with subtitles, and I'll extract key vocabulary "
        "with translations for language learning.\n\n"
        "📝 Use /register to set up your profile (required for vocabulary translation "
        "and community features).\n"
        "💎 Use /vip to learn about premium features.\n"
        "👤 Use /profile to view/edit your profile."
    )
    await update.message.reply_text(text)


async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton(name)] for name in LANGUAGES.values()]
    await update.message.reply_text(
        "🎯 Which language are you LEARNING (target language)?",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return LANG_TARGET


async def register_target_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    selected = update.message.text
    code = next((k for k, v in LANGUAGES.items() if v == selected), 'de')
    context.user_data['target_lang'] = code

    keyboard = [[KeyboardButton(name)] for name in LANGUAGES.values()]
    await update.message.reply_text(
        "🗣 What is your NATIVE language (for translations)?",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return LANG_NATIVE


async def register_native_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    selected = update.message.text
    code = next((k for k, v in LANGUAGES.items() if v == selected), 'am')
    context.user_data['native_lang'] = code

    keyboard = [[KeyboardButton(lvl)] for lvl in ['A1', 'A2', 'B1', 'B2', 'C1']]
    await update.message.reply_text(
        "📈 What's your current level in the language you're learning?",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return LEVEL


async def register_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['cefr_level'] = update.message.text.strip().upper()
    await update.message.reply_text(
        "✍️ Write a short bio (e.g., 'B1 German learner, love movies & football'):",
        reply_markup=None
    )
    return BIO


async def register_bio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['bio'] = update.message.text
    await update.message.reply_text(
        "📷 Send a profile photo (or type /skip):"
    )
    return PHOTO


async def register_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
        update_user_field(user_id, 'photo_file_id', photo_file_id)

    update_user_field(user_id, 'target_lang', context.user_data['target_lang'])
    update_user_field(user_id, 'native_lang', context.user_data['native_lang'])
    update_user_field(user_id, 'cefr_level', context.user_data['cefr_level'])
    update_user_field(user_id, 'bio', context.user_data['bio'])
    update_user_field(user_id, 'profile_complete', 1)

    target = LANGUAGES.get(context.user_data['target_lang'])
    native = LANGUAGES.get(context.user_data['native_lang'])
    level = context.user_data['cefr_level']

    await update.message.reply_text(
        f"✅ Profile complete!\n\n"
        f"Learning: {target}\n"
        f"Native: {native}\n"
        f"Level: {level}\n"
        f"Bio: {context.user_data['bio']}\n\n"
        "Now send me a YouTube link to get started! 🎬",
        reply_markup=None
    )
    return ConversationHandler.END


async def register_skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await register_photo(update, context)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Registration cancelled.")
    return ConversationHandler.END


def get_registration_handler():
    return ConversationHandler(
        entry_points=[CommandHandler('register', register_start)],
        states={
            LANG_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_target_lang)],
            LANG_NATIVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_native_lang)],
            LEVEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_level)],
            BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_bio)],
            PHOTO: [
                MessageHandler(filters.PHOTO, register_photo),
                CommandHandler('skip', register_skip_photo)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )


async def profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or not user['profile_complete']:
        await update.message.reply_text("⚠️ You haven't completed registration. Use /register first.")
        return

    vip_status = "💎 VIP" if user['is_vip'] else "🆓 Free"
    target = LANGUAGES.get(user['target_lang'], user['target_lang'])
    native = LANGUAGES.get(user['native_lang'], user['native_lang'])
    level = user.get('cefr_level', 'Not set')

    text = (
        f"👤 <b>Your Profile</b>\n\n"
        f"Status: {vip_status}\n"
        f"Learning: {target}\n"
        f"Native: {native}\n"
        f"Level: {level}\n"
        f"Bio: {user['bio']}\n"
    )

    if user.get('photo_file_id'):
        await update.message.reply_photo(photo=user['photo_file_id'], caption=text, parse_mode='HTML')
    else:
        await update.message.reply_text(text, parse_mode='HTML')