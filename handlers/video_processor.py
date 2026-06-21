# handlers/video_processor.py
import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes
from services.subtitle_fetcher import get_subtitles
from services.segment_processor import split_into_segments
from services.ai_translator import process_all_segments
from database.db import save_video_data, get_cached_video, get_user

logger = logging.getLogger(__name__)


async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    user_id = update.effective_user.id

    msg = await update.message.reply_text("🔄 Processing video...")
    asyncio.create_task(process_video(url, user_id, update, context, msg))


async def process_video(url, user_id, update, context, status_msg):
    try:
        video_id = extract_video_id(url)

        cached = get_cached_video(video_id)
        if cached:
            await status_msg.edit_text("✅ Found cached version! Sending...")
            await send_results(cached, user_id, context)
            return

        user = get_user(user_id)
        if not user or not user.get('profile_complete'):
            await status_msg.edit_text("⚠️ Please complete /register first.")
            return

        target_lang = user.get('target_lang', 'de')   # language being learned
        native_lang = user.get('native_lang', 'am')    # language to translate into

        # --- Fetch subtitles ---
        await status_msg.edit_text("📥 Fetching subtitles...")
        subtitles, duration, title, returned_video_id, used_lang = await asyncio.to_thread(
            get_subtitles, url, target_lang
        )

        if not subtitles:
            await status_msg.edit_text(f"❌ No {target_lang.upper()} subtitles found for this video.")
            return

        # --- Split into 2-minute chunks ---
        segments = split_into_segments(subtitles, segment_length=120)
        total_segments = len(segments)
        segment_texts = [' '.join(seg['lines']) for seg in segments]

        await status_msg.edit_text(
            f"🤖 Translating {total_segments} segments with AI (running in parallel)..."
        )

        # --- ONE AI call per segment, up to 5 at once ---
        ai_results = await process_all_segments(
            segment_texts,
            source_lang=used_lang,
            target_lang=native_lang,
            words_per_segment=20,
            max_concurrent=5,
        )

        # --- Assemble final data ---
        all_segment_data = []
        for idx, (seg, ai_result) in enumerate(zip(segments, ai_results)):
            all_segment_data.append({
                'index': idx,
                'start': seg['start'],
                'end': seg['end'],
                'translation': ai_result.get('translation', []),
                'vocabulary': ai_result.get('vocabulary', []),
            })

        await status_msg.edit_text("💾 Saving...")
        save_video_data(video_id, url, title, duration, all_segment_data)

        await status_msg.edit_text(f"✅ Done! {total_segments} segments ready.")
        await send_results({'video_id': video_id, 'title': title, 'segments': all_segment_data}, user_id, context)

    except Exception as e:
        logger.error(f"process_video failed: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Error: {str(e)}")


async def send_results(video_data, user_id, context):
    """Send the original-language transcript + vocab as a downloadable file,
    plus the first segment inline with Next buttons."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    import io

    segments = video_data['segments']

    full_text = build_full_text_file(video_data)
    file_buffer = io.BytesIO(full_text.encode('utf-8'))
    file_buffer.name = f"{video_data.get('title', 'video')[:50]}.txt"

    await context.bot.send_document(
        chat_id=user_id,
        document=file_buffer,
        caption="📄 Full transcript + translation + vocabulary"
    )

    seg = segments[0]
    text = format_segment(seg)
    keyboard = build_nav_keyboard(video_data['video_id'], 0, len(segments))

    await context.bot.send_message(
        chat_id=user_id,
        text=text,
        reply_markup=keyboard,
        parse_mode='HTML'
    )


def build_nav_keyboard(video_id, current_index, total_segments):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    buttons = []
    row = []
    if current_index > 0:
        row.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"seg_{video_id}_{current_index - 1}"))
    if current_index < total_segments - 1:
        row.append(InlineKeyboardButton("➡️ Next Segment", callback_data=f"seg_{video_id}_{current_index + 1}"))
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons) if buttons else None


async def handle_segment_navigation(update, context):
    """Handles the Next/Previous segment inline button presses."""
    from database.db import get_cached_video

    query = update.callback_query
    await query.answer()

    try:
        _, video_id, index_str = query.data.split('_', 2)
        index = int(index_str)
    except (ValueError, IndexError):
        await query.edit_message_text("❌ Invalid navigation data.")
        return

    video_data = get_cached_video(video_id)
    if not video_data:
        await query.edit_message_text("❌ Video data not found. Please resend the link.")
        return

    segments = video_data['segments']
    if index < 0 or index >= len(segments):
        await query.edit_message_text("❌ Segment out of range.")
        return

    seg = segments[index]
    text = format_segment(seg)
    keyboard = build_nav_keyboard(video_id, index, len(segments))

    await query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')


def build_full_text_file(video_data):
    lines = [f"# {video_data.get('title', 'Video')}\n"]

    for seg in video_data['segments']:
        mins_start = seg['start'] // 60
        mins_end = seg['end'] // 60
        lines.append(f"\n## Segment {seg['index']+1} ({mins_start}-{mins_end} min)\n")

        lines.append("### Translation\n")
        for pair in seg['translation']:
            lines.append(f"{pair.get('source','')}")
            lines.append(f"{pair.get('target','')}\n")

        lines.append("### Vocabulary\n")
        lines.append("| # | Word | Meaning |")
        lines.append("|---|------|---------|")
        for i, v in enumerate(seg['vocabulary'], 1):
            lines.append(f"| {i} | {v.get('word','')} | {v.get('meaning','')} |")

    return '\n'.join(lines)


def format_segment(seg):
    mins_start = seg['start'] // 60
    mins_end = seg['end'] // 60
    text = f"<b>📚 Segment {seg['index']+1} ({mins_start}-{mins_end} min)</b>\n\n"
    text += "<b>Vocabulary:</b>\n"
    for i, v in enumerate(seg['vocabulary'][:20], 1):
        text += f"{i}. <b>{v.get('word','')}</b> → {v.get('meaning','')}\n"
    return text


def extract_video_id(url):
    import re
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'youtu\.be\/([0-9A-Za-z_-]{11})'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return url