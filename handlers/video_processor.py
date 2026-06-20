# handlers/video_processor.py
import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes
from services.subtitle_fetcher import get_subtitles
from services.segment_processor import split_into_segments
from services.word_extractor import extract_keywords, find_example_sentences
from services.translator import translate_batch
from database.db import save_video_data, get_cached_video, get_user

logger = logging.getLogger(__name__)


async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    user_id = update.effective_user.id

    msg = await update.message.reply_text("🔄 Processing video... this may take a minute.")

    asyncio.create_task(process_video(url, user_id, update, context, msg))


async def process_video(url, user_id, update, context, status_msg):
    try:
        video_id = extract_video_id(url)

        # Check cache first
        cached = get_cached_video(video_id)
        if cached:
            await status_msg.edit_text("✅ Found cached version! Sending segments...")
            await send_segments_to_user(cached, user_id, context)
            return

        # --- User profile ---
        user = get_user(user_id)
        if not user or not user.get('profile_complete'):
            await status_msg.edit_text(
                "⚠️ Please complete /register first so I know your target and native language."
            )
            return

        user_level = user.get('cefr_level', 'B1')
        target_lang = user.get('target_lang', 'de')
        native_lang = user.get('native_lang', 'am')

        # --- Fetch subtitles ---
        await status_msg.edit_text("📥 Fetching subtitles...")
        subtitles, duration, title, returned_video_id, used_lang = await asyncio.to_thread(
            get_subtitles, url, target_lang
        )

        if not subtitles:
            await status_msg.edit_text(f"❌ No {target_lang.upper()} subtitles found for this video.")
            return

        # --- Split into 2-minute segments ---
        await status_msg.edit_text("✂️ Splitting into 2-minute segments...")
        segments = split_into_segments(subtitles, segment_length=120)
        total_segments = len(segments)
        await status_msg.edit_text(f"📊 Found {total_segments} segments. Extracting words...")

        # --- Step 1: extract keywords + example sentences for ALL segments first (no network calls yet) ---
        segment_word_lists = []  # list of (segment, [{'word','level','examples'}])
        all_words_to_translate = []
        all_sentences_to_translate = []

        for seg in segments:
            full_text = ' '.join(seg['lines'])
            keyword_results = extract_keywords(full_text, top_n=20, user_level=user_level)

            seg_words = []
            for kw in keyword_results:
                word = kw['word']
                level = kw.get('level', '')
                # 2 examples instead of 3 -- cuts translation volume ~30% with minimal learning loss
                examples = find_example_sentences(word, seg['lines'], max_examples=2)

                seg_words.append({
                    'word': word,
                    'level': level,
                    'examples': examples,
                })

                all_words_to_translate.append(word)
                all_sentences_to_translate.extend(examples)

            segment_word_lists.append((seg, seg_words))

        # --- Step 2: translate everything in two big concurrent batches (NOT one call at a time) ---
        await status_msg.edit_text(
            f"🌍 Translating {len(set(all_words_to_translate))} unique words "
            f"and {len(set(all_sentences_to_translate))} sentences..."
        )

        word_translations = await asyncio.to_thread(
            translate_batch, all_words_to_translate, used_lang, native_lang
        )
        sentence_translations = await asyncio.to_thread(
            translate_batch, all_sentences_to_translate, used_lang, native_lang
        )

        # --- Step 3: assemble final segment data using the translation lookups (no more network calls) ---
        all_segment_data = []
        for idx, (seg, seg_words) in enumerate(segment_word_lists):
            final_words = []
            for w in seg_words:
                translation = word_translations.get(w['word'], w['word'])
                example_translations = [
                    sentence_translations.get(ex, ex) for ex in w['examples']
                ]
                final_words.append({
                    'word': w['word'],
                    'level': w['level'],
                    'translation': translation,
                    'examples': w['examples'],
                    'example_translations': example_translations,
                })

            all_segment_data.append({
                'index': idx,
                'start': seg['start'],
                'end': seg['end'],
                'words': final_words,
            })

        # --- Save & send ---
        await status_msg.edit_text("💾 Saving...")
        save_video_data(video_id, url, title, duration, all_segment_data)

        await status_msg.edit_text(f"✅ Done! {total_segments} segments ready.")
        await send_segments_to_user(
            {'video_id': video_id, 'segments': all_segment_data}, user_id, context
        )

    except Exception as e:
        logger.error(f"process_video failed: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Error: {str(e)}")


async def send_segments_to_user(video_data, user_id, context):
    """Send first segment, with buttons to navigate"""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    segments = video_data['segments']
    seg = segments[0]

    text = format_segment(seg)

    keyboard = []
    if len(segments) > 1:
        keyboard.append([InlineKeyboardButton("➡️ Next Segment", callback_data=f"seg_{video_data['video_id']}_1")])

    await context.bot.send_message(
        chat_id=user_id,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        parse_mode='HTML'
    )


def format_segment(seg):
    mins_start = seg['start'] // 60
    mins_end = seg['end'] // 60

    text = f"<b>📚 Segment {seg['index']+1} ({mins_start}-{mins_end} min)</b>\n\n"

    for w in seg['words'][:20]:
        level_tag = f" <code>{w.get('level', '')}</code>" if w.get('level') else ""
        text += f"🔹 <b>{w['word']}</b>{level_tag} → {w['translation']}\n"
        if w['examples']:
            text += f"   <i>Source:</i> {w['examples'][0]}\n"
            text += f"   <i>Translation:</i> {w['example_translations'][0]}\n"
        text += "\n"

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