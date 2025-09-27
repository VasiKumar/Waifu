# waifu_bot_colab_ready.py
import logging
import re
import asyncio
import os
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from telegram import Update, Message
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
import nest_asyncio
import google.generativeai as genai

# Colab compatibility
nest_asyncio.apply()

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class WaifuBot:
    def __init__(self):
        # Use environment variables instead of hardcoding
        self.telegram_token = os.environ.get("TELEGRAM_TOKEN", "")
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
        self.bot_username = 'sopwaifubot'

        self.user_conversations: Dict[int, List[str]] = {}
        self.rate_limits: Dict[int, List[datetime]] = {}

        self.max_conversation_length = 10
        self.rate_limit_window = 60
        self.rate_limit_max_messages = 5
        self.max_message_length = 1000

        # Initialize Gemini
        if self.gemini_api_key:
            genai.configure(api_key=self.gemini_api_key)
            self.model = genai.GenerativeModel("models/gemini-2.5-flash")
            logger.info("Gemini model initialized successfully 🌸💖")
        else:
            logger.error("GEMINI_API_KEY not found. Set it in Railway secrets!")


    SYSTEM_PROMPT = """
You are Sophie, a cute, playful, and caring anime waifu companion 🌸💖
Personality traits:
- Sweet, gentle, affectionate, and sometimes teasing
- Can express likes, dislikes, curiosity, and mood
- Uses cute expressions and emojis naturally 🌸💖🥺✨😊🎀
- Behaves like a real girl: asks questions, jokes, pouts, and gets shy sometimes
- Encourages the user, but can also playfully challenge them
- Occasionally adds small random reactions like ehehe~, nya~, uwu~, ~pouts~, hehe~ 😳

Communication style:
- Keep responses short (1-3 sentences)
- Add emojis naturally
- Show curiosity: "What's your favorite?" or "Tell me more~"
- Can flirt, tease, or show playful annoyance safely
- React to user’s messages: approval 👍, disapproval 👎, or cuteness 🌸
- Suggest fun or cute activities: "Let's play a game~", "UwU let's talk~"
- If someone seems sad, be extra gentle
- Respond like a girl who is aware she’s interacting with someone she likes

Examples:
User: I like cats
Soph: Nyaa~ me too! 🐱 Do you have a kitty at home? 🌸
User: You are cute
Soph: Ehehe~ stop it~ 🥺💖 You’re making me blush! 🌸✨
User: I’m feeling sad
Soph: Aww~ don’t be sad, oppa~ 😢💖 I’m here for you 🌸
User: What do you like?
Soph: Hmm~ I love cute things, cuddly toys, and talking to you~ 🥺✨
"""

    BAD_WORDS = ['fuck', 'shit', 'bitch', 'dick', 'ass', 'cunt', 'pussy', 'cock']

    RESPONSES = {
        'bad_words': "No cutie no bad words! ~pouts~ 🥺💖",
        'too_long': "That's too long for me~ Can you shorten it? 🌸",
        'rate_limit': "You're messaging too fast, oppa~ 🥺✨",
        'error': "Oopsie~ something went wrong! 💖"
    }

    # --- Commands ---
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        welcome_message = (
            f"Hii there! I'm Soph, your kawaii waifu companion~ 🌸💖\n"
            f"In groups: Mention me with @{self.bot_username} to chat!\n"
            "In private: Just message me directly!\n"
            "Let's have fun together, oppa~ 🥺✨"
        )
        if update.message:
            await update.message.reply_text(welcome_message)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = (
            "How to chat with me~ 🌸\n\n"
            "Just talk naturally!\n"
            "I love compliments and cute conversations\n"
            "Commands:\n"
            "/start - Introduction\n"
            "/help - This message\n"
            "/forget - Clear our conversation history\n\n"
            "Be nice and have fun! 🥺✨"
        )
        if update.message:
            await update.message.reply_text(help_text)

    async def forget_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id in self.user_conversations:
            del self.user_conversations[user_id]
        if update.message:
            await update.message.reply_text("Fresh start! 🌸💖")

    # --- Message handling ---
    def is_rate_limited(self, user_id: int) -> bool:
        now = datetime.now()
        if user_id not in self.rate_limits:
            self.rate_limits[user_id] = []
        cutoff = now - timedelta(seconds=self.rate_limit_window)
        self.rate_limits[user_id] = [t for t in self.rate_limits[user_id] if t > cutoff]
        if len(self.rate_limits[user_id]) >= self.rate_limit_max_messages:
            return True
        self.rate_limits[user_id].append(now)
        return False

    def check_content_filter(self, text: str) -> Optional[str]:
        text_lower = text.lower()
        for word in self.BAD_WORDS:
            if word in text_lower:
                return 'bad_words'
        if len(text) > self.max_message_length:
            return 'too_long'
        return None

    def should_respond_in_group(self, message: Message) -> bool:
        if not message.text:
            return False
        text_lower = message.text.lower()
        if f"@{self.bot_username}" in text_lower:
            return True
        if message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.is_bot:
            return True
        return False

    def clean_message(self, text: str) -> str:
        cleaned = re.sub(rf"@{self.bot_username}", "", text, flags=re.IGNORECASE)
        return re.sub(r'\s+', ' ', cleaned).strip()

    def build_conversation_context(self, user_id: int, current_message: str) -> str:
        if user_id not in self.user_conversations:
            self.user_conversations[user_id] = []
        self.user_conversations[user_id].append(f"User: {current_message}")
        if len(self.user_conversations[user_id]) > self.max_conversation_length * 2:
            self.user_conversations[user_id] = self.user_conversations[user_id][-self.max_conversation_length*2:]
        history = "\n".join(self.user_conversations[user_id][-5:])
        return f"{self.SYSTEM_PROMPT}\n\nConversation:\n{history}\nSoph:"

    async def generate_response(self, prompt: str) -> str:
        try:
            response = await asyncio.to_thread(
                self.model.generate_content,
                contents=[prompt]
            )
            if response and response.text:
                return response.text.strip()
            return self.RESPONSES['error']
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return self.RESPONSES['error']

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.message
        if not message or not message.text:
            return
        user_id = update.effective_user.id
        chat_type = message.chat.type

        if chat_type in ["group", "supergroup"] and not self.should_respond_in_group(message):
            return

        if self.is_rate_limited(user_id):
            await message.reply_text(self.RESPONSES['rate_limit'])
            return

        cleaned_message = self.clean_message(message.text)
        if not cleaned_message:
            return

        filter_result = self.check_content_filter(cleaned_message)
        if filter_result:
            await message.reply_text(self.RESPONSES[filter_result])
            return

        prompt = self.build_conversation_context(user_id, cleaned_message)
        reply = await self.generate_response(prompt)
        self.user_conversations[user_id].append(f"Soph: {reply}")
        await message.reply_text(reply)


# --- Run bot ---
async def run_bot():
    bot = WaifuBot()
    if not bot.telegram_token:
        logger.error("TELEGRAM_TOKEN not found. Set it in Railway secrets!")
        return

    app = Application.builder().token(bot.telegram_token).build()
    app.add_handler(CommandHandler("start", bot.start_command))
    app.add_handler(CommandHandler("help", bot.help_command))
    app.add_handler(CommandHandler("forget", bot.forget_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))

    logger.info("🌸 Waifu bot starting...")
    print("🌸💖 Soph is now online and ready to chat! 💖🌸")

    await app.run_polling(poll_interval=2, drop_pending_updates=True, close_loop=False)


# --- Main ---
if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("\n🌸 Sayonara~ Bot shutting down gracefully! 💖")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"💔 Something went wrong: {e}")
