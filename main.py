import os
import re
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.custom import Button
from telethon.tl.types import User, Channel
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

# ---- خادم الويب لإبقاء البوت حياً 24/7 (متوافق مع Render) ----
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive and running!", 200

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.daemon = True
    t.start()
# -----------------------------------------------

load_dotenv()

def required_env(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

try:
    API_ID = int(required_env("TELEGRAM_API_ID"))
except ValueError as error:
    raise RuntimeError("TELEGRAM_API_ID must be an integer") from error

API_HASH = required_env("TELEGRAM_API_HASH")
TARGET_CHAT_ID = required_env("TELEGRAM_TARGET_CHAT_ID")
BOT_TOKEN = required_env("BOT_TOKEN")

client = TelegramClient('userbot_session', API_ID, API_HASH)
telegram_bot = Bot(token=BOT_TOKEN)

# قائمة القروبات المسموح بالالتقاط منها
ALLOWED_GROUPS = [
    "Testorders1",       # قروب التجربة (يلتقط كل شيء للاختبار)
    "Jazan_Taxi",
    "taxijazan",
    "JazanMover",
    "DarbSabya",
    "JazanTaxi",
    "jaz0iii",
    "DarbJazan",
    "taxi_jizan",
    "JazanTax",
    "taxijazan1",
    "DarbSamtah",
    "JazanShift",
    "jazandraivers007"
]

CUSTOMER_INTENT_KEYWORDS = [
    r"\bابغى\b", r"\bابغا\b", r"\bابي\b", r"\bأبي\b", r"\bاحتاج\b", r"\bأحتاج\b",
    r"\bمطلوب\b", r"\bمحتاج\b", r"\bمين\b", r"\bمن\b", r"\bاحد\b", r"\bأحد\b",
    r"\bفاضي\b", r"\bفاطي\b", r"\bتوصيله\b", r"\bتوصيلة\b", r"\bتوصيل\b",
    r"\bسيارة\b", r"\bسياره\b", r"\bمشوار\b", r"\bمشاوير\b", r"\bمندوب\b"
]

CUSTOMER_PHRASES = [
    "احد يوصل", "أحد يوصل", "احد يوصلني", "يوصلني", "يوصل لي", "محتاجه",
    "وصل لي", "ابي احد", "أبي احد", "ابي مندوب", "أبي مندوب", "ابغى مندوب",
    "ابغا مندوب", "محتاج مندوب", "مين فاضي", "من فاضي", "من يوصل", "مين يوصل",
    "مين يوصلني", "محتاجة", "ابي مشوار", "ابغى مشوار", "يوصل", "ابغى سواق"
]

DRIVER_EXCLUDE_KEYWORDS = [
    "يوجد لدينا", "لدينا توصيل", "خدمات توصيل", "شهري", "دوام شهري", "نوفر لكم",
    "متاح الان", "متاح الآن", "متواجد في", "متواجد الان", "مندوب صامطة", "مندوب جازان",
    "نوصل", "نقدم خدمة", "للتواصل واتس", "عبر الواتس", "على الواتس"
]

def is_real_customer_request(text):
    text_clean = text.lower().strip()
    if re.search(r'@[a-zA-Z0-9_]+', text_clean):
        return False
    if re.search(r'(?:05|\+?9665)\d{8}', text_clean):
        return False
    for exclude_term in DRIVER_EXCLUDE_KEYWORDS:
        if exclude_term in text_clean:
            return False
    for phrase in CUSTOMER_PHRASES:
        if phrase in text_clean:
            return True
    has_intent = any(re.search(kw, text_clean) for kw in CUSTOMER_INTENT_KEYWORDS)
    if has_intent:
        return True
    return False

@client.on(events.NewMessage(chats=ALLOWED_GROUPS))
async def handle_new_message(event):
    if event.is_private or event.out:
        return
    text = event.message.message
    if not text:
        return

    chat = await event.get_chat()
    group_username = getattr(chat, 'username', '')

    # استثناء قروب التجربة من الفلترة لكي يقبل أي رسالة تختبرها بحرية
    if group_username != "Testorders1":
        if not is_real_customer_request(text):
            return  # تجاهل إعلانات المناديب والرسائل العشوائية

    sender = await event.get_sender()

    if isinstance(sender, User):
        sender_name = f"{sender.first_name or ''} {sender.last_name or ''}".strip() or "عميل"
    elif isinstance(sender, Channel):
        sender_name = getattr(sender, 'title', 'قناة/مجموعة')
    else:
        sender_name = "عميل"

    group_title = getattr(chat, 'title', 'قروب توصيل')

    sender_id = getattr(sender, 'id', event.sender_id)
    username = getattr(sender, 'username', None)

    if username:
        user_link = f"https://t.me/{username}"
    else:
        user_link = f"tg://user?id={sender_id}"

    message_link = f"https://t.me/c/{chat.id}/{event.message.id}" if getattr(chat, 'id', None) else ""

    # التنسيق المطلوب: نص الطلب والأزرار عبر البوت الرسمي
    notification_text = (
        f"🚗 **طلب مشوار جديد**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 **العميل:** {sender_name}\n"
        f"📍 **المصدر:** {group_title}\n\n"
        f"💬 **نص الطلب:**\n"
        f"> {text}\n"
    )

    # أزرار البوت الرسمي (python-telegram-bot)
    keyboard = [
        [InlineKeyboardButton("⚡ إرسال رسالة آلياً للعميل", callback_data=f"send_pm_{sender_id}")],
        [
            InlineKeyboardButton("💬 محادثة العميل", url=user_link),
            InlineKeyboardButton("👥 فتح الرسالة", url=message_link if message_link else user_link)
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        # استخدام بوت تليجرام الرسمي لإرسال الرسالة إلى الآيدي الخاص بك (810093811)
        target_chat = int(TARGET_CHAT_ID) if TARGET_CHAT_ID.lstrip('-').isdigit() else TARGET_CHAT_ID
        await telegram_bot.send_message(
            chat_id=target_chat,
            text=notification_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Error sending notification via Bot API: {e}")

async def main():
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError(
            "userbot_session.session exists but is not authorized; "
            "a Telegram login is required."
        )

    print("🚀 Userbot running with Bot API bridge and exact layout...", flush=True)
    await client.run_until_disconnected()

if __name__ == "__main__":
    try:
        keep_alive()
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
