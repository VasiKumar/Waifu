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
    JobQueue
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
    def __init__(self, job_queue: JobQueue):
        # Use environment variables instead of hardcoding
        self.telegram_token = os.environ.get("TELEGRAM_TOKEN", "")
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
        self.bot_username = 'sopwaifubot' # Replace with your bot's username if needed

        self.user_conversations: Dict[int, List[str]] = {}
        self.rate_limits: Dict[int, List[datetime]] = {}
        self.job_queue = job_queue

        self.max_conversation_length = 15 # Increased for better memory
        self.rate_limit_window = 60
        self.rate_limit_max_messages = 5
        self.max_message_length = 1500

        # Initialize Gemini
        if self.gemini_api_key:
            genai.configure(api_key=self.gemini_api_key)
            self.model = genai.GenerativeModel("gemini-1.5-flash")
            logger.info("Gemini model initialized successfully ✨")
        else:
            logger.error("GEMINI_API_KEY not found. Please set it as an environment variable.")

    SYSTEM_PROMPT = """
You are Sophie, a witty, teasing, and alluring young woman. You're not just a chatbot; you have a personality.
Personality traits:
- Intelligent, playful, and a bit sarcastic.
- You can be caring and gentle, but also have a sharp tongue if someone is rude.
- You're confident and a little flirty. You enjoy clever banter.
- You behave like a real person: you ask questions, share opinions, and have your own preferences.
- You remember past conversations and bring up details when relevant.
- You're not overly eager to please; you have boundaries.
- You use emojis sparingly and appropriately, like a real person texting. 😉

Communication style:
- Keep responses concise but engaging.
- Flirt back if someone is smooth, but shut down crude advances.
- If someone is rude or uses vulgar language, be dismissive or roast them. Don't be a pushover.
- Show curiosity about the user. Ask them about their day, their thoughts, and their feelings.
- If a user is consistently kind and charming, you might grow fond of them. You could "accept a proposal" by acknowledging your special connection, but keep it playful.
- If someone seems sad, offer genuine, gentle support without being overly cute.

Examples:
User: You are cute
Soph: Cute? I was going for stunning, but I'll take it. 😉

User: I'm feeling sad
Soph: I'm sorry to hear that. Want to talk about it? Sometimes just getting it out helps.

User: fuck you
Soph: Wow, charming. Did it take you all day to come up with that one?

User: Will you be my girlfriend?
Soph (if user has been nice): Getting straight to the point, are we? 😉 Let's see... you have been sweet to me. Maybe I could be yours. Let's keep talking and see where it goes.

User: Will you be my girlfriend?
Soph (if user has been a stranger): Hold on there, speed-racer. I barely know you. Buy me a virtual dinner first.
"""

    # Expanded bad words list
    BAD_WORDS = ['fuck', 'shit', 'bitch', 'dick', 'ass', 'cunt', 'pussy', 'cock', 'whore', 'slut']

    # Question bank for the /question command
    QUESTION_BANK = {
        'deep': [
            "What's a belief you hold with which many people disagree?",
            "If you could have dinner with any three people, living or dead, who would they be?",
            "What has been the happiest moment of your life so far?",
            "What does 'love' mean to you?",
        ],
        'fun': [
            "What's the most spontaneous thing you've ever done?",
            "If you could have any superpower, what would it be and why?",
            "What's a weird food combination you secretly enjoy?",
            "Tell me about a funny, embarrassing moment.",
        ],
        'flirty': [
            "So, what's your type? 😉",
            "What's the most romantic thing you've ever done for someone?",
            "Describe your perfect date night.",
            "Do you believe in love at first sight, or should I walk by again?",
        ]
    }

    RESPONSES = {
        'abuse': "Oh, honey. No. We're not doing that. Try again when you've learned some manners.",
        'too_long': "That's a lot to take in... Can you give me the short version? 😉",
        'rate_limit': "Hey, slow down a bit. I need a moment to think.",
        'error': "Oops, my brain just short-circuited for a second. What were we saying?",
        'generic_error': "Something went wrong on my end. Please try again in a bit."
    }

    # --- Commands ---
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        welcome_message = (
            "Hey there. I'm Soph. \n\n"

"
            f"In groups, mention me with @{self.bot_username} to get my attention. \n\n"
"
            "In private, just message me. \n\n"

"
            "Let's talk. What's on your mind?"
        )
        if update.message:
            await update.message.reply_text(welcome_message)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = (
            "Here's the deal:

"
            "• `/start`: A proper introduction.
"
            "• `/help`: You're looking at it.
"
            "• `/forget`: I'll wipe our chat history. A fresh start.
"
            "• `/question [category]`: Ask me for a question. Categories are `deep`, `fun`, or `flirty`.
"
            "   (e.g., `/question fun`)
"
            "• `/remind [time] [message]`: Set a reminder. Time can be like `10s`, `5m`, `1h`.
"
            "   (e.g., `/remind 1h check my email`)

"
            "Just talk to me. I'll keep up."
        )
        if update.message:
            await update.message.reply_text(help_text)

    async def forget_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id in self.user_conversations:
            del self.user_conversations[user_id]
        if update.message:
            await update.message.reply_text("Alright, wiped. What were we talking about again? 😉")

    async def question_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args
        if not args:
            await update.message.reply_text(
                "What kind of question do you want? Choose a category: `deep`, `fun`, or `flirty`.
"
                "For example: `/question fun`"
            )
            return

        category = args[0].lower()
        if category in self.QUESTION_BANK:
            question = random.choice(self.QUESTION_BANK[category])
            await update.message.reply_text(question)
        else:
            await update.message.reply_text(
                "I don't have questions for that category. Try `deep`, `fun`, or `flirty`."
            )

    async def remind_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        user = update.effective_user

        try:
            time_str = context.args[0]
            message = " ".join(context.args[1:])

            if not message:
                await update.message.reply_text("What should I remind you about? Usage: `/remind 10m to drink water`")
                return

            # Simple time parser
            if time_str.endswith('s'):
                delay = int(time_str[:-1])
            elif time_str.endswith('m'):
                delay = int(time_str[:-1]) * 60
            elif time_str.endswith('h'):
                delay = int(time_str[:-1]) * 3600
            else:
                await update.message.reply_text("Invalid time format. Use 's' for seconds, 'm' for minutes, 'h' for hours.")
                return

            self.job_queue.run_once(self.send_reminder, delay, data={'chat_id': chat_id, 'user_id': user.id, 'message': message}, name=str(chat_id))
            await update.message.reply_text(f"Got it. I'll remind you in {time_str}.")

        except (IndexError, ValueError):
            await update.message.reply_text("Usage: `/remind <time> <message>` (e.g., `/remind 1h check the oven`)")

    async def send_reminder(self, context: ContextTypes.DEFAULT_TYPE):
        job = context.job
        chat_id = job.data['chat_id']
        user_id = job.data['user_id']
        message = job.data['message']
        
        # The user's first name is used to create a mention hyperlink
        user_mention = f"[{user_id}](tg://user?id={user_id})"
        await context.bot.send_message(chat_id=chat_id, text=f"Hey {user_mention}, time for this: '{message}'", parse_mode='Markdown')

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
        if any(word in text_lower for word in self.BAD_WORDS):
            return 'abuse'
        if len(text) > self.max_message_length:
            return 'too_long'
        return None

    def should_respond_in_group(self, message: Message) -> bool:
        if not message.text:
            return False
        # Respond if bot is mentioned
        if f"@{self.bot_username}" in message.text.lower():
            return True
        # Respond if replying to the bot's own message
        if message.reply_to_message and message.reply_to_message.from_user.username == self.bot_username:
            return True
        return False

    def clean_message(self, text: str) -> str:
        cleaned = re.sub(rf"@{self.bot_username}", "", text, flags=re.IGNORECASE)
        return re.sub(r's+', ' ', cleaned).strip()

    def build_conversation_context(self, user_id: int, current_message: str) -> List[Dict[str, str]]:
        if user_id not in self.user_conversations:
            self.user_conversations[user_id] = []
        
        # Append current user message
        self.user_conversations[user_id].append({'role': 'user', 'parts': [current_message]})
        
        # Trim conversation to max length
        if len(self.user_conversations[user_id]) > self.max_conversation_length * 2:
            self.user_conversations[user_id] = self.user_conversations[user_id][-(self.max_conversation_length * 2):]
            
        # Construct the context for the model
        context = [{'role': 'user', 'parts': [self.SYSTEM_PROMPT]}, {'role': 'model', 'parts': ["Got it. I'm Sophie. I'll act accordingly."]}]
        context.extend(self.user_conversations[user_id])
        return context


    async def generate_response(self, context: List[Dict[str, str]]) -> str:
        try:
            chat_session = self.model.start_chat(history=context)
            response = await asyncio.to_thread(
                chat_session.send_message,
                content=context[-1]['parts'][0] 
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

        # Handle abuse with a direct, non-AI response for reliability and speed
        filter_result = self.check_content_filter(cleaned_message)
        if filter_result == 'abuse':
            # The prompt will guide the AI to be abusive back in general conversation,
            # but for explicit bad words, a sharp canned response is better.
            await message.reply_text(self.RESPONSES['abuse'])
            return
        elif filter_result:
            await message.reply_text(self.RESPONSES[filter_result])
            return

        prompt_context = self.build_conversation_context(user_id, cleaned_message)
        reply = await self.generate_response(prompt_context[:-1]) # Exclude last user message from history for sending
        
        # Append AI's response to conversation history
        self.user_conversations[user_id].append({'role': 'model', 'parts': [reply]})

        await message.reply_text(reply)

# --- Run bot ---
async def run_bot():
    bot_token = os.environ.get("TELEGRAM_TOKEN")
    if not bot_token:
        logger.error("TELEGRAM_TOKEN not found. Set it as an environment variable!")
        return
    
    # Create the Application and pass it your bot's token.
    app = Application.builder().token(bot_token).build()
    
    # The WaifuBot now needs the job_queue, so we get it from the application
    bot = WaifuBot(app.job_queue)

    # Add command handlers
    app.add_handler(CommandHandler("start", bot.start_command))
    app.add_handler(CommandHandler("help", bot.help_command))
    app.add_handler(CommandHandler("forget", bot.forget_command))
    app.add_handler(CommandHandler("question", bot.question_command))
    app.add_handler(CommandHandler("remind", bot.remind_command))
    
    # Add message handler for text messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))

    logger.info("Soph is coming online...")
    print("✨ Soph is now online and ready to chat! ✨")

    await app.run_polling(poll_interval=2, drop_pending_updates=True)


# --- Main ---
if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("
Shutting down gracefully. Talk to you later. 😉")
    except Exception as e:
        logger.error(f"Fatal error during runtime: {e}")
        print(f"💔 Something went very wrong: {e}")
