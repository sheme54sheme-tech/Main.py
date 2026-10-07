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

# ---- Web server to keep the bot alive 24/7 (Render compatible) ----
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

client = TelegramClient('userbot_session', API_ID, API_HASH)

TEST_GROUP = "testorders1"

# Groups allowed for capturing requests
ALLOWED_GROUPS = [
    "Testorders1",       # test group (captures everything)
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
    "jazandraivers007",
]

# NOTE: the very common word "من" was removed: it matches almost every Arabic
# sentence and caused false positives.
CUSTOMER_INTENT_KEYWORDS = [
    r"\bابغى\b", r"\bابغا\b", r"\bابي\b", r"\bأبي\b", r"\bاحتاج\b", r"\bأحتاج\b",
    r"\bمطلوب\b", r"\bمحتاج\b", r"\bمين\b", r"\bاحد\b", r"\bأحد\b",
    r"\bفاضي\b", r"\bفاطي\b", r"\bتوصيله\b", r"\bتوصيلة\b", r"\bتوصيل\b",
    r"\bسيارة\b", r"\bسياره\b", r"\bمشوار\b", r"\bمشاوير\b", r"\bمندوب\b",
]

# NOTE: the bare word "يوصل" was removed from this list: as a substring match it
# also fired on driver ads such as "يوصلك". Specific phrases are safer.
CUSTOMER_PHRASES = [
    "احد يوصل", "أحد يوصل", "احد يوصلني", "يوصلني", "يوصل لي", "محتاجه",
    "وصل لي", "ابي احد", "أبي احد", "ابي مندوب", "أبي مندوب", "ابغى مندوب",
    "ابغا مندوب", "محتاج مندوب", "مين فاضي", "من فاضي", "من يوصل", "مين يوصل",
    "مين يوصلني", "محتاجة", "ابي مشوار", "ابغى مشوار", "ابغى سواق",
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


# ---------------- Formatting helpers ----------------
# Direction mark placed at the start of every line.
#   "\u200F" = RLM (Right-to-Left Mark)
#   "\u061C" = ALM (Arabic Letter Mark), treated as a strong Arabic letter and
#              handled better by some Telegram clients. Switch with the env var.
MARK_CHOICE = os.getenv("RTL_MARK", "ALM").upper()
RLM = "\u061C" if MARK_CHOICE == "ALM" else "\u200F"

# True  -> use Telegram's <blockquote> for the request text
# False -> use plain lines prefixed with a bar, always right-aligned
USE_BLOCKQUOTE = os.getenv("USE_BLOCKQUOTE", "1") == "1"

FILLER = "\u2800"         # Invisible braille blank, used to widen the quote box
QUOTE_MIN_WIDTH = 34      # Increase if the quote box is still narrow, 0 to disable
SEPARATOR = "━" * 18      # Short enough to never wrap into a second line
MAX_TEXT_LEN = 1500       # Keep the whole notification under Telegram's 4096 limit
AUTO_REPLY_TEXT = "السلام عليكم، حصلتم ولا لسا؟! إذا باقي أنا بتمم معاك"

# Set to True temporarily to print what Telethon actually sends
DEBUG_FORMAT = os.getenv("DEBUG_FORMAT", "0") == "1"


def rtl(line=""):
    """Prefix a line with the direction mark (empty lines stay empty)."""
    return f"{RLM}{line}" if line else ""


# ---------------- Extra features: time / route / tags ----------------
RIYADH_TZ = timezone(timedelta(hours=3))   # Saudi Arabia has no daylight saving


def format_time(dt):
    """Message time in Riyadh time, 12-hour format with ص/م."""
    if dt is None:
        return ""
    local = dt.astimezone(RIYADH_TZ)
    hour12 = local.hour % 12 or 12
    suffix = "ص" if local.hour < 12 else "م"
    return f"{hour12:02d}:{local.minute:02d} {suffix}"


# "من X الى Y"  (also: إلى / لين / لـ attached to the destination)
_ROUTE_RE = re.compile(
    r"من\s+(?P<a>[^\n،,.؟?]{2,30}?)\s+(?:(?:الى|إلى|لين)\s+|ل(?=[ء-ي]))(?P<b>[^\n،,.؟?]{2,30})"
)
# Words/numbers that mark the end of a place name (time, urgency, extra request)
_ROUTE_STOP_RE = re.compile(
    r"\s+(?:الساعة|الان|الآن|الحين|بكرة|بكره|اليوم|الليلة|بعد|قبل|وابي|و\s?ابي|ابغى|ابي|ب\s?\d|السعر|بسعر)(?!\w)|\s+\d"
)


def _clean_place(value):
    value = _ROUTE_STOP_RE.split(value.strip(), maxsplit=1)[0]
    return value.strip(" -:،,.")


def extract_route(text):
    """Best-effort 'from X to Y' extraction. Returns (origin, destination) or None."""
    for line in text.splitlines():
        m = _ROUTE_RE.search(line)
        if not m:
            continue
        origin = _clean_place(m.group("a"))
        destination = _clean_place(m.group("b"))
        if len(origin) >= 2 and len(destination) >= 2:
            return origin, destination
    return None


# ---- Tag rules: emoji -> words that trigger it ----
# To add a new word: put it in the matching list.
# To add a new tag: add a new (emoji, [words]) line to TAG_RULES.
# Prefixes like ال / لل / ب / ل / و are handled automatically.
URGENT_WORDS = ["عاجل", "ضروري", "مستعجل", "حالا", "حالاً", "الان", "الآن", "الحين", "بسرعة", "فورا", "فوراً"]
AIRPORT_WORDS = ["مطار"]
UNIVERSITY_WORDS = ["جامعة", "جامعه"]
HOSPITAL_WORDS = ["مستشفى", "مستشفي"]
CAFE_WORDS = ["كوفي", "كوفيه", "كافيه", "كافي"]
RESTAURANT_WORDS = ["مطعم"]

TAG_RULES = [
    ("🔥", URGENT_WORDS),
    ("✈️", AIRPORT_WORDS),
    ("🎓", UNIVERSITY_WORDS),
    ("🏥", HOSPITAL_WORDS),
    ("☕", CAFE_WORDS),
    ("🍽️", RESTAURANT_WORDS),
]


def _has_word(text, words):
    pattern = r"(?<!\w)(?:و)?(?:ال|لل|ب|ل)?(?:" + "|".join(map(re.escape, words)) + r")(?!\w)"
    return re.search(pattern, text) is not None


def build_tags(text):
    return " ".join(emoji for emoji, words in TAG_RULES if _has_word(text, words))


def build_quote(text):
    """Build the request text: every line RTL, escaped, optionally widened."""
    text = text.strip()
    if len(text) > MAX_TEXT_LEN:
        text = text[:MAX_TEXT_LEN] + "…"
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return RLM

    if not USE_BLOCKQUOTE:
        return "\n".join(f"{RLM}┃ {html.escape(ln)}" for ln in lines)

    longest = max(range(len(lines)), key=lambda i: len(lines[i]))
    out = []
    for i, ln in enumerate(lines):
        piece = RLM + html.escape(ln)
        if i == longest and len(ln) < QUOTE_MIN_WIDTH:
            piece += RLM + FILLER * (QUOTE_MIN_WIDTH - len(ln))
        out.append(piece)
    return "\n".join(out)


def link(url, label):
    return f'<a href="{html.escape(url, quote=True)}">{label}</a>'


def build_notification(sender_name, group_title, text, pm_link, user_link,
                       message_link, time_str="", route=None, tags=""):
    quote_part = build_quote(text)
    if USE_BLOCKQUOTE:
        quote_part = f"<blockquote>{quote_part}</blockquote>"

    title = "🚗 طلب مشوار جديد" + (f" {tags}" if tags else "")
    lines = [
        rtl(f"<b>{title}</b>"),
        rtl(SEPARATOR),
        rtl(f"<b>👤 العميل:</b> {html.escape(sender_name or 'غير معروف')}"),
        rtl(f"<b>📍 المصدر:</b> {html.escape(group_title or 'غير معروف')}"),
    ]
    if time_str:
        lines.append(rtl(f"<b>🕒 الوقت:</b> {html.escape(time_str)}"))
    if route:
        lines.append(rtl(f"<b>🟢 من:</b> {html.escape(route[0])}"))
        lines.append(rtl(f"<b>🏁 إلى:</b> {html.escape(route[1])}"))
    lines += [
        "",
        rtl("<b>📝 نص الطلب:</b>"),
        quote_part,
        "",
        rtl("<b>🔗 روابط سريعة للتفاعل:</b>"),
    ]
    if pm_link:
        lines.append(rtl(f"⚡ {link(pm_link, 'إرسال رسالة جاهزة للعميل')}"))
    if user_link:
        lines.append(rtl(f"💬 {link(user_link, 'محادثة العميل مباشرة')}"))
    if message_link:
        lines.append(rtl(f"👥 {link(message_link, 'فتح الرسالة الأصلية في القروب')}"))
    return "\n".join(lines)


# Simple duplicate protection (same sender + same text within 10 minutes)
_recent = {}
DEDUPE_SECONDS = 600


def is_duplicate(sender_id, text):
    now = time.time()
    for k in [k for k, t in _recent.items() if now - t > DEDUPE_SECONDS]:
        del _recent[k]
    key = (sender_id, re.sub(r"\s+", " ", text.strip().lower()))
    if key in _recent:
        return True
    _recent[key] = now
    return False


# ---------------- Main handler ----------------
async def handle_new_message(event):
    if event.out:
        return
    text = event.message.message
    if not text:
        return

    chat = await event.get_chat()
    group_username = (getattr(chat, 'username', '') or '').lower()

    # Test group skips filtering for free testing
    if group_username != TEST_GROUP:
        if not is_real_customer_request(text):
            return

    sender = await event.get_sender()
    sender_id = getattr(sender, 'id', None) or event.sender_id

    if group_username != TEST_GROUP and is_duplicate(sender_id, text):
        return

    if isinstance(sender, User):
        sender_name = f"{sender.first_name or ''} {sender.last_name or ''}".strip() or "عميل"
    elif isinstance(sender, Channel):
        sender_name = getattr(sender, 'title', None) or 'قناة/مجموعة'
    else:
        sender_name = "عميل"

    group_title = getattr(chat, 'title', None) or 'قروب توصيل'
    username = getattr(sender, 'username', None)

    # Links
    if username:
        user_link = f"https://t.me/{username}"
        pm_link = f"https://t.me/{username}?text={quote(AUTO_REPLY_TEXT)}"
    elif sender_id:
        # Works only if this account already knows the user.
        # "tg://msg?to=" is not a supported link, so no prefilled-message link here.
        user_link = f"tg://user?id={sender_id}"
        pm_link = None
    else:
        user_link = None
        pm_link = None

    if group_username:
        message_link = f"https://t.me/{group_username}/{event.message.id}"
    else:
        message_link = f"https://t.me/c/{chat.id}/{event.message.id}"

    notification_text = build_notification(
        sender_name, group_title, text, pm_link, user_link, message_link,
        time_str=format_time(event.message.date),
        route=extract_route(text),
        tags=build_tags(text),
    )

    if DEBUG_FORMAT:
        from telethon.extensions import html as tl_html
        parsed, ents = tl_html.parse(notification_text)
        print("first chars:", [hex(ord(c)) for c in parsed[:6]], flush=True)
        print("entities:", ents[:5], flush=True)

    try:
        target_peer = int(TARGET_CHAT_ID) if TARGET_CHAT_ID.lstrip('-').isdigit() else TARGET_CHAT_ID
        await client.send_message(
            target_peer, notification_text, link_preview=False, parse_mode='html'
        )
    except Exception as e:
        print(f"Error sending notification: {e}", flush=True)


async def resolve_groups():
    """Resolve groups one by one so a single bad username can't crash the bot."""
    ids = []
    for name in ALLOWED_GROUPS:
        try:
            entity = await client.get_input_entity(name)
            ids.append(utils.get_peer_id(entity))
        except Exception as e:
            print(f"⚠️ Skipping '{name}': {e}", flush=True)
    return ids


async def main():
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError(
            "userbot_session.session exists but is not authorized; "
            "a Telegram login is required."
        )

    group_ids = await resolve_groups()
    if not group_ids:
        raise RuntimeError("None of the ALLOWED_GROUPS could be resolved.")
    client.add_event_handler(handle_new_message, events.NewMessage(chats=group_ids))

    print(f"🚀 Userbot running (mark={MARK_CHOICE}, blockquote={USE_BLOCKQUOTE}), "
          f"watching {len(group_ids)} groups", flush=True)
    await client.run_until_disconnected()


if __name__ == "__main__":
    try:
        keep_alive()
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
