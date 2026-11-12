import os
import re
import time
import asyncio
import html
import logging
from difflib import SequenceMatcher
from datetime import timezone, timedelta
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# ---- خادم الويب لإبقاء البوت حياً 24/7 ----
from flask import Flask
from threading import Thread

app = Flask(__name__)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

@app.route('/')
def home():
    return "Both UserBot Catchers are alive and running!", 200

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.daemon = True
    t.start()
# --------------------------------------------------------------------

load_dotenv()

API_ID_1 = int(os.getenv("TELEGRAM_API_ID", "30891622"))
API_HASH_1 = os.getenv("TELEGRAM_API_HASH", "cf380ef18f4a06e651338496ff72c851")
TARGET_CHAT_ID = os.getenv("TELEGRAM_TARGET_CHAT_ID", "-1004382902175")
STRING_SESSION_1 = os.getenv("STRING_SESSION", "").strip()

API_ID_2 = 39121133
API_HASH_2 = "12b31138fd1b526e0c02b776b1c09936"
# وضعنا الجلسة الثانية هنا مباشرة لضمان قراءتها 100% دون أخطاء
STRING_SESSION_2 = "N8mxqrGGnyGxek5hME3t8sryEv80emzN3d8Vz2IpMa5sVpxInGRv0SQmHPQwgMIJn3EH"

# إنشاء العملاء بشكل آمن تماماً
client1 = TelegramClient(StringSession(STRING_SESSION_1), API_ID_1, API_HASH_1) if STRING_SESSION_1 else None
client2 = TelegramClient(StringSession(STRING_SESSION_2), API_ID_2, API_HASH_2) if STRING_SESSION_2 else None

ALLOWED_GROUPS = [
    "Testorders1", "taxijazan", "taxijazan1", "Jazan_Taxi", "JazanTrans",
    "jiuzin_jazan", "manadibbknk", "jazandraivers007", "JazanShift", "mkjhpo",
    "JazanRoute", "mhndq121", "SamtaTaxi", "Jazan09", "ba2rq", "JazanTaxi",
    "DeliveryJazan", "JazanWagon", "Azoz6612", "JazanTax", "hhbsjg",
    "JazanMover", "JazanZoom", "JU_Naqil", "jaz0iii", "DarbSabya",
    "DarbJazan", "taxi_jizan", "DarbSamtah"
]

_DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u0640]")
_NON_WORD_RE = re.compile(r"[^\w\s]", re.UNICODE)
_DIGITS_TABLE = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

def _letters(text):
    text = text.lower().translate(_DIGITS_TABLE)
    text = _DIACRITICS_RE.sub("", text)
    text = re.sub(r"[أإآٱ]", "ا", text)
    return re.sub(r"(.)\1{2,}", r"\1", text.replace("ة", "ه").replace("ى", "ي").replace("ئ", "ي").replace("ؤ", "و"))

def normalize_text(text):
    return re.sub(r"\s+", " ", _NON_WORD_RE.sub(" ", _letters(text))).strip()

def _kw(words, prefix=True, suffix=False):
    alts = "|".join(re.escape(_letters(w)) for w in sorted(set(words), key=len, reverse=True))
    pre = r"(?:و|ف)?(?:ال|لل|ل|ب)?" if prefix else ""
    return rf"(?<!\w){pre}(?:{alts})\w*(?!\w)" if suffix else rf"(?<!\w){pre}(?:{alts})(?!\w)"

FILTER_REQUESTS = os.getenv("FILTER_REQUESTS", "1") == "1"
MIN_REQUEST_SCORE = int(os.getenv("MIN_REQUEST_SCORE", "3"))

ASK_WORDS = ["ابي", "ابغى", "ابغا", "ابا", "ابى", "ابغاه", "ابغاها", "ابيه", "بغيت", "احتاج", "محتاج", "محتاجه", "محتاجة", "نحتاج", "نبغى", "نبي", "ودي", "اريد", "مطلوب"]
SERVICE_WORDS = ["توصيل", "توصيله", "توصيلة", "مشوار", "سواق", "سائق", "سايق", "كابتن", "مندوب", "سياره", "سيارة", "تكسي", "تاكسي", "ليموزين", "نقل", "رحله", "رحلة"]
STRONG_PHRASES = ["مين يوصلني", "مين يوصلنا", "مين فاضي", "مين فاضية", "مين متاح", "مين يقدر", "مين يمرني", "ابي مشوار", "ابغى مشوار", "محتاج مشوار", "احتاج مشوار", "نبي مشوار"]

ASK_RE = re.compile(_kw(ASK_WORDS))
SERVICE_RE = re.compile(_kw(SERVICE_WORDS))
STRONG_RE = re.compile(_kw(STRONG_PHRASES, prefix=False))

def is_real_customer_request(text):
    raw = text or ""
    norm = normalize_text(raw)
    if not norm: return False
    score = 0
    if STRONG_RE.search(norm): score += 5
    if ASK_RE.search(norm): score += 2
    if SERVICE_RE.search(norm): score += 1
    return score >= MIN_REQUEST_SCORE

_recent_by_sender = {}
def is_duplicate_request(sender_id, text):
    now = time.monotonic()
    norm = normalize_text(text)
    entries = _recent_by_sender.setdefault(sender_id or "anon", [])
    for entry in entries:
        if now - entry[1] <= 1800 and (entry[0] == norm or SequenceMatcher(None, entry[0], norm).ratio() >= 0.88):
            entry[1] = now
            return True
    entries.append([norm, now])
    return False

RIYADH_TZ = timezone(timedelta(hours=3))
def format_time(dt):
    if dt is None: return ""
    local = dt.astimezone(RIYADH_TZ)
    return f"{local.hour % 12 or 12:02d}:{local.minute:02d} {'ص' if local.hour < 12 else 'م'}"

async def process_incoming_message(event, client_label):
    message_text = event.raw_text
    if not message_text or not message_text.strip(): return
    if FILTER_REQUESTS and not is_real_customer_request(message_text): return
    if is_duplicate_request(event.sender_id, message_text): return

    chat = await event.get_chat()
    sender = await event.get_sender()
    chat_title = getattr(chat, 'title', 'قروب عام')
    sender_name = html.escape(f"{getattr(sender, 'first_name', '')} {getattr(sender, 'last_name', '')}".strip() or "عميل")

    direct_chat_link = f"https://t.me/{sender.username}" if sender and getattr(sender, 'username', None) else f"tg://user?id={sender.id}" if sender else ""
    
    final_message = (
        f"🚗 <b>طلب مشوار جديد ({client_label})</b>\n"
        f"──────────────────\n"
        f"👤 <b>العميل:</b> {sender_name}\n"
        f"📍 <b>المصدر:</b> {html.escape(chat_title)}\n"
        f"⏰ <b>الوقت:</b> {format_time(event.date)}\n\n"
        f"📝 <b>نص الطلب:</b>\n<blockquote>{html.escape(message_text[:1500])}</blockquote>\n\n"
    )
    if direct_chat_link:
        final_message += f"💬 <a href='{direct_chat_link}'>محادثة العميل مباشرة</a>\n"

    try:
        target = int(TARGET_CHAT_ID) if TARGET_CHAT_ID.lstrip('-').isdigit() else TARGET_CHAT_ID
        if client1:
            await client1.send_message(target, final_message, parse_mode='html', link_preview=False)
        elif client2:
            await client2.send_message(target, final_message, parse_mode='html', link_preview=False)
    except Exception as e:
        logging.error(f"Failed to forward message: {e}")

if client1:
    @client1.on(events.NewMessage(chats=ALLOWED_GROUPS))
    async def handle_client1(event): await process_incoming_message(event, "محمد دويري")

if client2:
    @client2.on(events.NewMessage(chats=ALLOWED_GROUPS))
    async def handle_client2(event): await process_incoming_message(event, "الحساب الثاني")

async def main():
    keep_alive()
    print("Starting Telegram Userbot(s)...")
    
    clients_to_run = []
    if client1: clients_to_run.append(client1.start())
    if client2: clients_to_run.append(client2.start())
    
    if clients_to_run:
        await asyncio.gather(*clients_to_run)
        print("Userbots are running successfully.")
    
    disconnects = []
    if client1: disconnects.append(client1.run_until_disconnected())
    if client2: disconnects.append(client2.run_until_disconnected())
        
    if disconnects:
        await asyncio.gather(*disconnects)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Telegram Bot Error: {e}")
