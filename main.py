import os
import re
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.custom import Button
from telethon.tl.types import User, Channel

# ---- إضافة خادم الويب لإبقاء البوت حياً 24/7 (متوافق مع Render) ----
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive and running!", 200

def run_web_server():
    # Render يعتمد على متغير البيئة PORT وغالباً ما يكون الافتراضي 10000
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.daemon = True
    t.start()
# -----------------------------------------------

# جلب بيانات الاعتماد من البيئة (Environment Variables) بدون قيم افتراضية حساسة
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

# قائمة القروبات المسموح بالالتقاط منها حصراً (بواسطة المعرف Username)
ALLOWED_GROUPS = [
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

# الكلمات المفتاحية والعبارات الخاصة بطلبات العملاء
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

# العبارات المخصصة لاستبعاد إعلانات السائقين والمندوبين
DRIVER_EXCLUDE_KEYWORDS = [
    "يوجد لدينا", "لدينا توصيل", "خدمات توصيل", "شهري", "دوام شهري", "نوفر لكم",
    "متاح الان", "متاح الآن", "متواجد في", "متواجد الان", "مندوب صامطة", "مندوب جازان",
    "نوصل", "نقدم خدمة", "للتواصل واتس", "عبر الواتس", "على الواتس"
]

DESTINATION_PATTERNS = [
    r"(?:إلى|الي|لـ|ل|اتجاه|رايح)\s+([\w\s]+)",
    r"(?:من\s+[\w\s]+\s+(?:إلى|الي|لـ|ل)\s+([\w\s]+))",
    r"(?:لمخطط|مخطط)\s*([\w\d\s]+)",
    r"\b(صبيا|أبو عريش|ابو عريش|صامطة|صامطه|جيزان|جازان|أحد المسارحة|احد المسارحه|الدرب|بيش|العارضة|العارضه)\b"
]

def extract_destination(text):
    for pattern in DESTINATION_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            dest = match.group(1).strip() if match.groups() else match.group(0).strip()
            dest = re.sub(r'^(إلى|الي|لـ|ل)\s*', '', dest)
            return dest
    return "وجهة غير محددة"

def is_real_customer_request(text):
    text_clean = text.lower().strip()

    # 1. حظر حاسم لأي رسالة تحتوي على معرف تلجرام (@username)
    if re.search(r'@[a-zA-Z0-9_]+', text_clean):
        return False

    # 2. حظر حاسم لأي رسالة تحتوي على رقم جوال (05x أو +9665x أو 9665x)
    if re.search(r'(?:05|\+?9665)\d{8}', text_clean):
        return False

    # 3. استبعاد العبارات الصريحة لإعلانات السائقين والمناديب
    for exclude_term in DRIVER_EXCLUDE_KEYWORDS:
        if exclude_term in text_clean:
            return False

    # 4. قبول الطلب إذا احتوى على عبارات العملاء المتداولة
    for phrase in CUSTOMER_PHRASES:
        if phrase in text_clean:
            return True

    # 5. قبول الطلب إذا احتوى على كلمة مفتاحية تعبر عن نية ورغبة العميل
    has_intent = any(re.search(kw, text_clean) for kw in CUSTOMER_INTENT_KEYWORDS)
    if has_intent:
        return True

    return False

# حصر المراقبة على القائمة المحددة فقط عبر chats=ALLOWED_GROUPS
@client.on(events.NewMessage(chats=ALLOWED_GROUPS))
async def handle_new_message(event):
    if event.is_private or event.out:
        return
    text = event.message.message
    if not text or not is_real_customer_request(text):
        return

    sender = await event.get_sender()
    chat = await event.get_chat()

    # تحديد الاسم بحسب نوع كائن المرسل بأمان (User أم Channel)
    if isinstance(sender, User):
        sender_name = f"{sender.first_name or ''} {sender.last_name or ''}".strip() or "عميل"
    elif isinstance(sender, Channel):
        sender_name = getattr(sender, 'title', 'قناة/مجموعة')
    else:
        sender_name = "عميل"

    group_title = getattr(chat, 'title', 'قروب توصيل')
    destination = extract_destination(text)

    # ضبط روابط التلجرام المتوافقة مع الآيفون (iOS) والأندرويد
    sender_id = getattr(sender, 'id', event.sender_id)
    username = getattr(sender, 'username', None)

    if username:
        user_link = f"https://t.me/{username}"
    else:
        user_link = f"tg://user?id={sender_id}"

    message_link = f"https://t.me/c/{chat.id}/{event.message.id}" if getattr(chat, 'id', None) else ""

    notification_text = (
        f"🚖 **طلب مشوار إلى {destination}**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 **العميل:** [{sender_name}]({user_link})\n"
        f"📍 **المصدر:** {group_title}\n\n"
        f"💬 **نص الطلب:**\n"
        f"> {text}\n"
    )

    # التنسيق الجديد للأزرار حسب طلبك
    buttons = [
        [Button.inline("⚡ إرسال رسالة آلياً للعميل", data=f"send_pm:{sender_id}")],
        [
            Button.url("💬 محادثة العميل", user_link),
            Button.url("👥 فتح الرسالة", message_link) if message_link else Button.url("👥 القروب", user_link)
        ]
    ]

    try:
        target_peer = int(TARGET_CHAT_ID) if TARGET_CHAT_ID.lstrip('-').isdigit() else TARGET_CHAT_ID
        await client.send_message(target_peer, notification_text, buttons=buttons, link_preview=False)
    except Exception as e:
        print(f"Error sending notification: {e}")

@client.on(events.CallbackQuery(data=re.compile(br"send_pm:(\d+)")))
async def handle_auto_reply_click(event):
    user_id = int(event.pattern_match.group(1))

    natural_message = (
        "السلام عليكم\n\n"
        "حصلتم ولا لسسسى ..!\n\n"
        "اذا باقي انا بتمم معاك"
    )

    try:
        await client.send_message(user_id, natural_message)
        await event.answer("✅ تم إرسال الرسالة بنجاح!", alert=True)

        await event.edit(buttons=[
            [Button.inline("✅ تم التواصل مع العميل", data="done")],
            [Button.url("💬 محادثة العميل", f"tg://user?id={user_id}")]
        ])
    except Exception as e:
        await event.answer(f"❌ تعذر الإرسال بسبب الخصوصية: {e}", alert=True)

async def main():
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError(
            "userbot_session.session exists but is not authorized; "
            "a Telegram login is required."
        )

    print(
        "🚀 Userbot running with iOS-compatible links and restricted groups setup...",
        flush=True,
    )
    await client.run_until_disconnected()

if __name__ == "__main__":
    try:
        # تشغيل خادم الويب في الخلفية لمنع توقف الخدمة واستجابة UptimeRobot
        keep_alive()

        asyncio.run(main())
    except KeyboardInterrupt:
        pass
