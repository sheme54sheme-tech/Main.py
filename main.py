import os
import re
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.custom import Button
from telethon.tl.types import User, Channel

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

client = TelegramClient('userbot_session', API_ID, API_HASH)

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

    # استثناء قروب التجربة من الفلترة للاختبار الحر
    if group_username != "Testorders1":
        if not is_real_customer_request(text):
            return

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

    user_link = f"https://t.me/{username}" if username else f"tg://user?id={sender_id}"
    message_link = f"https://t.me/c/{chat.id}/{event.message.id}" if getattr(chat, 'id', None) else user_link

    # تنسيق رسالة التنبيه كما كانت تعمل بنجاح تام
    notification_text = (
        f"🚗 **طلب مشوار جديد**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 **العميل:** {sender_name}\n"
        f"📍 **المصدر:** {group_title}\n\n"
        f"💬 **نص الطلب:**\n"
        f"> {text}\n"
    )

    # زر إرسال الرسالة الجاهزة آلياً بالتفاعل المباشر
    buttons = [
        [Button.inline("⚡ إرسال رسالة آلياً للعميل", data=f"send_ready_{sender_id}".encode())],
        [
            Button.url("💬 محادثة العميل", user_link),
            Button.url("👥 فتح الرسالة", message_link)
        ]
    ]

    try:
        target_peer = int(TARGET_CHAT_ID) if TARGET_CHAT_ID.lstrip('-').isdigit() else TARGET_CHAT_ID
        await client.send_message(target_peer, notification_text, buttons=buttons, link_preview=False)
    except Exception as e:
        print(f"Error sending notification: {e}")

# دالة الاستجابة للزر لتنفيذ إرسال الرسالة المطلوبة فوراً
@client.on(events.CallbackQuery(data=re.compile(br"send_ready_(-?\d+)")))
async def handle_send_ready_message(event):
    sender_id = int(event.pattern_match.group(1))

    ready_message = (
        "السلام عليكم\n\n"
        "حصلتم ولا لسسى!!\n\n"
        "اذا باقي انا بتمم معاك👍🏻"
    )

    try:
        await client.send_message(sender_id, ready_message)
        await event.answer("✅ تم إرسال الرسالة بنجاح!", alert=True)

        await event.edit(buttons=[
            [Button.inline("✅ تم التواصل مع العميل", data="done_sent")],
            [Button.url("💬 محادثة العميل", f"tg://user?id={sender_id}")]
        ])
    except Exception as e:
        await event.answer(f"❌ تعذر الإرسال: {e}", alert=True)

async def main():
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError(
            "userbot_session.session exists but is not authorized; "
            "a Telegram login is required."
        )

    print("🚀 Userbot running with functional auto-send button...", flush=True)
    await client.run_until_disconnected()

if __name__ == "__main__":
    try:
        keep_alive()
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
