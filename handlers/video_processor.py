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

        user_level = user.get('cefr_level', 'B1')
        target_lang = user.get('target_lang', 'de')    # language being learned
        native_lang = user.get('native_lang', 'am')     # language to translate into

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

        await status_msg.edit_text(f"📊 Found {total_segments} segments. Selecting key vocabulary...")

        # --- Step 1: extract smart vocabulary per segment (free, local, no network) ---
        segment_word_lists = []
        all_words_to_translate = []
        all_sentences_to_translate = []
        all_full_sentences = []  # every line of dialogue, for full transcript translation

        for seg in segments:
            lines = seg['lines']
            full_text = ' '.join(lines)

            keyword_results = extract_keywords(full_text, top_n=20, user_level=user_level)

            seg_words = []
            for kw in keyword_results:
                word = kw['word']
                level = kw.get('level', '')
                examples = find_example_sentences(word, lines, max_examples=2)

                seg_words.append({'word': word, 'level': level, 'examples': examples})
                all_words_to_translate.append(word)
                all_sentences_to_translate.extend(examples)

            all_full_sentences.extend(lines)
            segment_word_lists.append((seg, seg_words, lines))

        # --- Step 2: translate everything in big concurrent batches (free Google Translate) ---
        unique_word_count = len(set(all_words_to_translate))
        await status_msg.edit_text(
            f"🌍 Translating {unique_word_count} key words and the full transcript "
            f"({total_segments} segments)... this is free and runs in parallel."
        )

        word_translations = await asyncio.to_thread(
            translate_batch, all_words_to_translate, used_lang, native_lang
        )
        sentence_translations = await asyncio.to_thread(
            translate_batch, all_sentences_to_translate, used_lang, native_lang
        )
        full_line_translations = await asyncio.to_thread(
            translate_batch, all_full_sentences, used_lang, native_lang
        )

        # --- Step 3: assemble final segment data (no more network calls) ---
        all_segment_data = []
        for idx, (seg, seg_words, lines) in enumerate(segment_word_lists):
            final_words = []
            for w in seg_words:
                translation = word_translations.get(w['word'], w['word'])
                example_translations = [
                    sentence_translations.get(ex, ex) for ex in w['examples']
                ]
                final_words.append({
                    'word': w['word'],
                    'level': w['level'],
                    'meaning': translation,
                    'examples': w['examples'],
                    'example_translations': example_translations,
                })

            translation_pairs = [
                {'source': line, 'target': full_line_translations.get(line, line)}
                for line in lines
            ]

            all_segment_data.append({
                'index': idx,
                'start': seg['start'],
                'end': seg['end'],
                'translation': translation_pairs,
                'vocabulary': final_words,
            })

        await status_msg.edit_text("💾 Saving...")
        save_video_data(video_id, url, title, duration, all_segment_data)

        await status_msg.edit_text(f"✅ Done! {total_segments} segments ready.")
        await send_results({'video_id': video_id, 'title': title, 'segments': all_segment_data}, user_id, context)

    except Exception as e:
        logger.error(f"process_video failed: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Error: {str(e)}")


async def send_results(video_data, user_id, context):
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

    row = []
    if current_index > 0:
        row.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"seg_{video_id}_{current_index - 1}"))
    if current_index < total_segments - 1:
        row.append(InlineKeyboardButton("➡️ Next Segment", callback_data=f"seg_{video_id}_{current_index + 1}"))
    return InlineKeyboardMarkup([row]) if row else None


async def handle_segment_navigation(update, context):
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
            lines.append(pair.get('source', ''))
            lines.append(pair.get('target', ''))
            lines.append("")

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
        level_tag = f" <code>{v.get('level','')}</code>" if v.get('level') else ""
        text += f"{i}. <b>{v.get('word','')}</b>{level_tag} → {v.get('meaning','')}\n"
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