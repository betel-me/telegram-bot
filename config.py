import os
from dotenv import load_dotenv

# Load variables from .env file (create this file yourself - see .env.example)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError(
        "BOT_TOKEN is not set. Create a .env file in the project root "
        "with: BOT_TOKEN=your_token_here\n"
        "Get a token from @BotFather on Telegram."
    )

# Optional: OpenAI/GPT key for smarter word extraction (Phase 4 - not required for MVP)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Free tier limits
FREE_DAILY_VIDEO_LIMIT = 2

# Default segment length for processing (seconds)
SEGMENT_LENGTH = 120

# Default words per segment
WORDS_PER_SEGMENT = 20