import os
import re
import time
import asyncio
import html
import logging
from datetime import timezone, timedelta
from urllib.parse import quote
from dotenv import load_dotenv
from telethon import TelegramClient, events, utils
from telethon.tl.types import User, Channel
from telethon.sessions import StringSession

# ---- خادم الويب لإبقاء البوت حياً 24/7 (متوافق مع Render) ----
from flask import Flask
from threading import Thread

app = Flask(__name__)
logging.getLogger('werkzeug').setLevel(logging.ERROR)


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
# --------------------------------------------------------------------

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
STRING_SESSION = os.getenv("STRING_SESSION", "")

# استخدام StringSession لتفادي مشاكل الحظر وجلسات الحساب
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

TEST_GROUP = "testorders1"

# قائمة القروبات المحدثة (بدون تكرار)
ALLOWED_GROUPS = [
    "Testorders1",       # قروب الاختبار
    "taxijazan",
    "taxijazan1",
    "Jazan_Taxi",
    "JazanTrans",
    "jiuzin_jazan",
    "manadibbknk",
    "jazandraivers007",
    "JazanShift",
    "mkjhpo",
    "JazanRoute",
    "mhndq121",
    "SamtaTaxi",
    "Jazan09",
    "ba2rq",
    "JazanTaxi",
    "DeliveryJazan",
    "JazanWagon",
    "Azoz6612",
    "JazanTax",
    "hhbsjg",
    "JazanMover",
    "JazanZoom",
    "JU_Naqil",
    "jaz0iii",
    "DarbSabya",
    "DarbJazan",
    "taxi_jizan",
    "DarbSamtah"
]

CUSTOMER_INTENT_KEYWORDS = [
    r"\bابغى\b", r"\bابغا\b", r"\bابي\b", r"\bأبي\b", r"\bاحتاج\b", r"\bأحتاج\b",
    r"\bمطلوب\b", r"\bمحتاج\b", r"\bمين\b", r"\bاحد\b", r"\bأحد\b",
    r"\bفاضي\b", r"\bفاطي\b", r"\bتوصيله\b", r"\bتوصيلة\b", r"\bتوصيل\b",
    r"\bسيارة\b", r"\bسياره\b", r"\bمشوار\b", r"\bمشاوير\b", r"\bمندوب\b",
]

CUSTOMER_PHRASES = [
    "احد يوصل", "أحد يوصل", "احد يوصلني", "يوصلني", "يوصل لي", "محتاجه",
    "وصل لي", "ابي احد", "أبي احد", "ابي مندوب", "أبي مندوب", "ابغى مندوب",
    "ابغا مندوب", "محتاج مندوب", "مين فاضي", "من فاضي", "من يوصل", "مين يوصل",
    "مين يوصلني", "محتاجة", "ابي مشوار", "ابغى مشوار", "ابغى سواق", "يوصل"
]

DRIVER_EXCLUDE_KEYWORDS = [
    "يوجد لدينا", "لدينا توصيل", "خدمات توصيل", "شهري", "دوام شهري", "نوفر لكم",
    "متاح الان", "متاح الآن", "متواجد في", "متواجد الان", "مندوب صامطة", "مندوب جازان",
    "نوصل", "نقدم خدمة", "للتواصل واتس", "عبر الواتس", "على الواتس",
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
    return any(re.search(kw, text_clean) for kw in CUSTOMER_INTENT_KEYWORDS)


# ---------------- أدوات التنسيق (HTML & RTL) ----------------
MARK_CHOICE = os.getenv("RTL_MARK", "ALM").upper()
RLM = "\u061C" if MARK_CHOICE == "ALM" else "\u200F"

USE_BLOCKQUOTE = os.getenv("USE_BLOCKQUOTE", "1") == "1"

FILLER = "\u2800"
QUOTE_MIN_WIDTH = 34
SEPARATOR = "━" * 18
MAX_TEXT_LEN = 1500
AUTO_REPLY_TEXT = "السلام عليكم، حصلتم ولا لسا؟! إذا باقي أنا بتمم معاك"


def rtl(line=""):
    return f"{RLM}{line}" if line else ""


# ---------------- استخراج الوقت والمسار والوسوم ----------------
RIYADH_TZ = timezone(timedelta(hours=3))


def format_time(dt):
    if dt is None:
        return ""
    local = dt.astimezone(RIYADH_TZ)
    hour12 = local.hour % 12 or 12
    suffix = "ص" if local.hour < 12 else "م"
    return f"{hour12:02d}:{local.minute:02d} {suffix}"


_ROUTE_RE = re.compile(
    r"من\s+(?P<a>[^\n،,.؟?]{2,30}?)\s+(?:(?:الى|إلى|لين)\s+|ل(?=[ء-ي]))(?P<b>[^\n،,.؟?]{2,30})"
)
_ROUTE_STOP_RE = re.compile(
    r"\s+(?:الساعة|الان|الآن|الحين|بكرة|بكره|اليوم|الليلة|بعد|قبل|وابي|و\s?ابي|ابغى|ابي|ب\s?\d|السعر|بسعر)(?!\w)|\s+\d"
)


def _clean_place(value):
    value = _ROUTE_STOP_RE.split(value.strip(), maxsplit=1)[0]
    return value.strip(" -:،,.")


def extract_route(text):
    for line in text.splitlines():
        m = _ROUTE_RE.search(line)
        if not m:
            continue
        origin = _clean_place(m.group("a"))
        destination = _clean_place(m.group("b"))
        if len(origin) >= 2 and len(destination) >= 2:
            return origin, destination
    return None


# تخصيص الوسوم الذكية
URGENT_WORDS = ["عاجل", "ضروري", "مستعجل", "حالا", "حالاً", "الان", "الآن", "الحين", "بسرعة", "فورا", "فوراً"]
AIRPORT_WORDS = ["مطار"]
UNIVERSITY_WORDS = ["جامعة", "جامعه"]
HOSPITAL_WORDS = ["مستشفى", "المستشفي", "المستوصف", "مستوصف"]
CAFE_WORDS = ["كوفي", "كوفيه", "كافيه", "كافي"]
RESTAURANT_WORDS = ["مطعم", "المطعم", "بوفية", "البوفية"]
MARKET_WORDS = ["سوق", "السوق", "مول", "المول"]
GROCERY_WORDS = ["بقالة", "البقالة", "سوبرماركت"]
BEACH_WORDS = ["بحر", "البحر", "كورنيش", "الشاطئ", "شاطئ"]

TAG_RULES = [
    ("🔥", URGENT_WORDS),
    ("✈️", AIRPORT_WORDS),
    ("🎓", UNIVERSITY_WORDS),
    ("🏥", HOSPITAL_WORDS),
    ("☕", CAFE_WORDS),
    ("🍽️", RESTAURANT_WORDS),
    ("🛍️", MARKET_WORDS),
    ("🛒", GROCERY_WORDS),
    ("🌊", BEACH_WORDS),
]


def _has_word(text, words):
    pattern = r"(?<!\w)(?:و)?(?:ال|لل|ب|ل)?(?:" + "|".join(map(re.escape, words)) + r")(?!\w)"
    return re.search(pattern, text) is not None


def build_tags(text):
    return " ".join(emoji for emoji, words in TAG_RULES if _has_word(text, words))


def build_quote(text):
    text = text.strip()
    if len(text) > MAX_TEXT_LEN:
        text = text[:MAX_TEXT_LEN] + "…"
    
    safe_text = html.escape(text)
    
    if USE_BLOCKQUOTE:
        return f"<blockquote>{safe_text}</blockquote>"
    else:
        return f"<code>{safe_text}</code>"


# ---------------- معالجة الرسائل واستماع الأحداث ----------------
@client.on(events.NewMessage(chats=ALLOWED_GROUPS))
async def handle_new_message(event):
    message_text = event.raw_text
    
    # فحص ما إذا كان الطلب حقيقياً وصادراً عن عميل
    if not is_real_customer_request(message_text):
        return

    # استخراج مسار الرحلة (من وإلى)
    route = extract_route(message_text)
    route_text = ""
    if route:
        origin, destination = route
        route_text = f"\n{SEPARATOR}\n📍 من: {origin}\n🏁 إلى: {destination}"

    tags = build_tags(message_text)
    req_time = format_time(event.date)
    quote_text = build_quote(message_text)
    
    chat = await event.get_chat()
    chat_title = getattr(chat, 'title', 'قروب عام')
    
    # إنشاء رابط تفاعلي للرسالة الأصلية
    message_link = f"https://t.me/{chat.username}/{event.id}" if getattr(chat, 'username', None) else ""
    
    # بناء هيكل الرسالة النهائية المرسلة لدردشة التوجيه
    final_message = (
        f"{rtl(f'🚨 طلب جديد {tags}')}\n"
        f"{rtl(f'⏰ الوقت: {req_time}')}\n"
        f"{rtl(f'👥 المصدر: {chat_title}')}\n"
        f"{quote_text}"
        f"{route_text}"
    )
    
    if message_link:
        final_message += f"\n\n🔗 <a href='{message_link}'>رابط الرسالة الأصلية</a>"

    try:
        await client.send_message(
            int(TARGET_CHAT_ID) if TARGET_CHAT_ID.lstrip('-').isdigit() else TARGET_CHAT_ID,
            final_message,
            parse_mode='html'
        )
    except Exception as e:
        logging.error(f"Failed to forward message: {e}")


# ---------------- التشغيل الرئيسي للبوت وخادم الويب ----------------
if __name__ == '__main__':
    # تشغيل خادم الويب لأجل Render في الخلفية
    keep_alive()
    
    try:
        print("Starting Telegram Userbot...")
        client.start()
        client.run_until_disconnected()
    except Exception as e:
        print(f"Telegram Bot Error: {e}")
