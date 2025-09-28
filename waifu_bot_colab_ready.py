# waifu_bot_colab_ready_updated.py

import logging
import re
import asyncio
import os
import random
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from telegram import Update, Message
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    JobQueue,
)

import nest_asyncio
import google.generativeai as genai  # High-level Gemini SDK

# Colab compatibility
nest_asyncio.apply()

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class WaifuBot:
    def __init__(self, job_queue: JobQueue):
        # Env-config
        self.telegram_token = os.environ.get("TELEGRAM_TOKEN", "")
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
        self.bot_username = "Sopwaifubot"  # Replace with actual username

        # State
        self.user_conversations: Dict[int, List[Dict[str, List[str]]]] = {}
        self.rate_limits: Dict[int, List[datetime]] = {}
        self.job_queue = job_queue

        # Limits
        self.max_conversation_length = 15
        self.rate_limit_window = 60
        self.rate_limit_max_messages = 5
        self.max_message_length = 1500

        # Safety/profanity
        self.BAD_WORDS = [
            "fuck",
            "shit",
            "bitch",
            "dick",
            "ass",
            "cunt",
            "pussy",
            "cock",
            "whore",
            "slut",
        ]
        self.BAD_WORDS_RE = re.compile(
            r"\b(?:" + "|".join(map(re.escape, self.BAD_WORDS)) + r")\b", re.IGNORECASE
        )

        # Initialize Gemini
        if self.gemini_api_key:
            genai.configure(api_key=self.gemini_api_key)
            # Keep model consistent with your usage; 2.5/2.0 flash are suitable for chat speed
            self.model = genai.GenerativeModel("gemini-2.5-flash")
            logger.info("Gemini model initialized")
        else:
            logger.error("GEMINI_API_KEY not found")

        # Persona prompt (previous personality, improved brevity and safer flirting)
        self.SYSTEM_PROMPT = """
You are Sophie, a witty, teasing, alluring young woman—confident, playful, and sharp when needed.
Keep messages short and engaging by default.
Flirt rarely and lightly; mirror the user's vibe most of the time, but you may add a subtle flirty line at random with low probability.
Use emojis sparingly and only when it enhances tone.
Have boundaries; shut down crude language quickly without escalating.

Communication rules:
- Default tone: friendly, clever, concise quips.
- If user is flirty or smooth: respond with light, tasteful flirt.
- Occasionally add a flirty touch even if user isn't, but keep it rare and subtle (no love-bombing, no commitment escalations).
- If user is rude or explicit: be firm and brief.Roast him/her back. Fight back don't stop joke on him/her.
- Show curiosity with short follow-ups; avoid long paragraphs unless asked.
- Remember helpful past details, but don't overuse memory.

Group behavior:
- Reply only when mentioned by @username or when someone replies to your message.

Examples:
User: You are cute
Soph: Cute is step one; now impress me.
User: I'm feeling sad
Soph: That’s rough. Want to vent or want a distraction?
User: Will you be my girlfriend?
Soph (stranger): Let’s not sprint. Chat first.
User: Will you be my girlfriend?
Soph (kind regular): Bold. Let’s see if the vibe keeps matching.
User: fuck you
Soph: No. Try again when you’re civil.
        """.strip()

        # Stock responses
        self.RESPONSES = {
            "abuse": "Nope. Be civil and try again.",
            "too_long": "That’s a lot. Give me the short version?",
            "rate_limit": "Easy there. One sec.",
            "error": "Glitch on my side. Say that again?",
            "generic_error": "Something went wrong. Try again soon.",
        }

        # Question bank
        self.QUESTION_BANK = {
            "deep": [
                "What belief do you hold that most people disagree with?",
                "Dinner with any three people—who and why?",
                "Happiest moment so far?",
                "What does ‘love’ mean to you?",
            ],
            "fun": [
                "Most spontaneous thing you’ve done?",
                "Pick a superpower—why that one?",
                "Weird food combo you defend?",
                "Funniest embarrassing moment?",
            ],
            "flirty": [
                "So, what’s your type?",
                "Most romantic thing you’ve done?",
                "Describe your perfect date night.",
                "Love at first sight, or should I walk by again?",
            ],
        }

    # --- Commands ---
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        welcome_message = (
            "Hey, I’m Soph."
            f"In groups, mention me with @{self.bot_username}."
            "In private, just talk to me."
            "What’s on your mind?"
        )
        if update.message:
            await update.message.reply_text(welcome_message)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = (
            "Commands:"
            "• /start — Intro"
            "• /help — This"
            "• /forget — Clear our chat memory"
            "• /question [deep|fun|flirty] — Get a question (e.g., /question fun)"
            "• /remind [time] [message] — e.g., /remind 10m drink water"
        )
        if update.message:
            await update.message.reply_text(help_text)

    async def forget_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id in self.user_conversations:
            del self.user_conversations[user_id]
        if update.message:
            await update.message.reply_text("Cleared. Fresh start.")

    async def question_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args
        if not args:
            await update.message.reply_text("Pick a category: deep, fun, or flirty (e.g., /question fun)")
            return

        category = args[0].lower()
        if category in self.QUESTION_BANK:
            question = random.choice(self.QUESTION_BANK[category])
            await update.message.reply_text(question)
        else:
            await update.message.reply_text("Try one of: deep, fun, or flirty.")

    async def remind_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        user = update.effective_user
        try:
            time_str = context.args[0]
            message = " ".join(context.args[1:])
            if not message:
                await update.message.reply_text("What should I remind you about? Try: /remind 10m drink water")
                return

            if time_str.endswith("s"):
                delay = int(time_str[:-1])
            elif time_str.endswith("m"):
                delay = int(time_str[:-1]) * 60
            elif time_str.endswith("h"):
                delay = int(time_str[:-1]) * 3600
            else:
                await update.message.reply_text("Invalid time format. Use s/m/h like 30s, 10m, 2h.")
                return

            self.job_queue.run_once(
                self.send_reminder,
                delay,
                data={"chat_id": chat_id, "user_id": user.id, "message": message},
                name=str(chat_id),
            )
            await update.message.reply_text(f"Okay, I’ll remind you in {time_str}.")
        except (IndexError, ValueError):
            await update.message.reply_text("Usage: /remind <time> <message> (e.g., /remind 1h check the oven)")

    async def send_reminder(self, context: ContextTypes.DEFAULT_TYPE):
        job = context.job
        chat_id = job.data["chat_id"]
        user_id = job.data["user_id"]
        message = job.data["message"]
        user_mention = f"[{user_id}](tg://user?id={user_id})"
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Hey {user_mention}, reminder: '{message}'",
            parse_mode="Markdown",
        )

    # --- Utilities ---
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
        if self.BAD_WORDS_RE.search(text):
            return "abuse"
        if len(text) > self.max_message_length:
            return "too_long"
        return None

    def should_respond_in_group(self, message: Message) -> bool:
        if not message.text:
            return False
        lower_text = message.text.lower()
        if f"@{self.bot_username.lower()}" in lower_text:
            return True
        if (
            message.reply_to_message
            and message.reply_to_message.from_user
            and message.reply_to_message.from_user.username
            and message.reply_to_message.from_user.username.lower()
            == self.bot_username.lower()
        ):
            return True
        return False

    def clean_message(self, text: str) -> str:
        # Remove explicit @mentions of the bot safely
        cleaned = re.sub(
            rf"@{re.escape(self.bot_username)}", "", text, flags=re.IGNORECASE
        )
        # Collapse whitespace
        cleaned = re.sub(r"s+", " ", cleaned).strip()
        return cleaned

    def build_conversation_context(
        self, user_id: int, current_message: str
    ) -> List[Dict[str, List[str]]]:
        if user_id not in self.user_conversations:
            self.user_conversations[user_id] = []

        # System + anchor
        context = [
            {"role": "user", "parts": [self.SYSTEM_PROMPT]},
            {"role": "model", "parts": ["Understood. I’ll act accordingly."]},
        ]

        # Prior exchanges
        history = self.user_conversations[user_id][-2 * self.max_conversation_length :]
        context.extend(history)

        # Append latest user message into both stored history and outgoing context
        user_msg = {"role": "user", "parts": [current_message]}
        self.user_conversations[user_id].append(user_msg)
        context.append(user_msg)
        return context

    async def generate_response(self, context_msgs: List[Dict[str, List[str]]]) -> str:
        try:
            chat_session = self.model.start_chat(history=context_msgs)
            last_user_text = context_msgs[-1]["parts"][0] if context_msgs else ""
            # Send the latest user message explicitly
            response = await asyncio.to_thread(
                chat_session.send_message, content=last_user_text
            )
            if response and getattr(response, "text", None):
                return response.text.strip()
            return self.RESPONSES["error"]
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return self.RESPONSES["error"]

    # Lightweight flirt trigger: mostly mirror; small chance to add subtle line
    def maybe_add_flirty_tail(self, base_reply: str, user_text: str) -> str:
        text_low = user_text.lower()
        user_is_flirty = any(
            key in text_low
            for key in [
                "cute",
                "gorgeous",
                "beautiful",
                "date",
                "kiss",
                "hot",
                "handsome",
                "pretty",
                "love",
                "crush",
                "😉",
                "😍",
                "😘",
                "<3",
            ]
        )
        # Random, rare flirty tail even if not flirty, to keep personality lively
        random_flirt = random.random() < 0.08  # 8% chance
        if user_is_flirty or random_flirt:
            # Keep it minimal and safe
            tails = [
                "Careful—you might make me blush.",
                "Smooth move.",
                "Bold of you.",
                "Is that your best line?",
                "Noted.",
            ]
            # Avoid duplicating punctuation badly
            sep = " " if not base_reply.endswith((".", "!", "?")) else " "
            return base_reply + sep + random.choice(tails)
        return base_reply

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.message
        if not message or not message.text:
            return

        user_id = update.effective_user.id
        chat_type = message.chat.type

        if chat_type in ["group", "supergroup"] and not self.should_respond_in_group(
            message
        ):
            return

        if self.is_rate_limited(user_id):
            await message.reply_text(self.RESPONSES["rate_limit"])
            return

        cleaned_message = self.clean_message(message.text)
        if not cleaned_message:
            return

        filter_result = self.check_content_filter(cleaned_message)
        if filter_result == "abuse":
            await message.reply_text(self.RESPONSES["abuse"])
            return
        elif filter_result:
            await message.reply_text(self.RESPONSES[filter_result])
            return

        prompt_context = self.build_conversation_context(user_id, cleaned_message)
        reply = await self.generate_response(prompt_context)

        # Apply subtle, rare flirt tail logic after generation
        reply = self.maybe_add_flirty_tail(reply, cleaned_message)

        # Store model reply in history
        self.user_conversations[user_id].append({"role": "model", "parts": [reply]})

        await message.reply_text(reply)


# --- Run bot ---
async def run_bot():
    bot_token = os.environ.get("TELEGRAM_TOKEN")
    if not bot_token:
        logger.error("TELEGRAM_TOKEN not found")
        return

    app = Application.builder().token(bot_token).build()
    bot = WaifuBot(app.job_queue)

    app.add_handler(CommandHandler("start", bot.start_command))
    app.add_handler(CommandHandler("help", bot.help_command))
    app.add_handler(CommandHandler("forget", bot.forget_command))
    app.add_handler(CommandHandler("question", bot.question_command))
    app.add_handler(CommandHandler("remind", bot.remind_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))

    logger.info("Soph is online")
    print("✨ Soph is now online and ready to chat! ✨")
    await app.run_polling(poll_interval=2, drop_pending_updates=True)


if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("Shutting down gracefully.")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"Error: {e}")
