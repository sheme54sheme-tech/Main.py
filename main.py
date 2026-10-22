import os
import re
import time
import asyncio
import html
import logging
from difflib import SequenceMatcher
from datetime import timezone, timedelta
from urllib.parse import quote
from dotenv import load_dotenv
from telethon import TelegramClient, events, utils
from telethon.tl.types import User, Channel
from telethon.sessions import StringSession

# مكتبة للاتصال بالذكاء الاصطناعي (خفيفة وسريعة)
import openai

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

# إعداد مفتاح الذكاء الاصطناعي (يدعم OpenAI, Groq, DeepSeek وغيرها المتوافقة مع OpenAI)
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.openai.v1") # يمكن تغييره لـ Groq أو غيره
USE_AI_FILTER = os.getenv("USE_AI_FILTER", "0") == "1" # تفعيل/تعطيل الذكاء الاصطناعي عبر المتغيرات

if AI_API_KEY:
    openai.api_key = AI_API_KEY
    if AI_BASE_URL and "openai.com" not in AI_BASE_URL:
        openai.api_base = AI_BASE_URL

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


# ======================================================================
#  أدوات تطبيع النص العربي (تُستخدم في الكشف وفي منع التكرار)
# ======================================================================
_DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u0640]")
_NON_WORD_RE = re.compile(r"[^\w\s]", re.UNICODE)
_DIGITS_TABLE = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def _letters(text):
    text = text.lower().translate(_DIGITS_TABLE)
    text = _DIACRITICS_RE.sub("", text)
    text = re.sub(r"[أإآٱ]", "ا", text)
    text = (text.replace("ة", "ه").replace("ى", "ي")
                .replace("ئ", "ي").replace("ؤ", "و"))
    return re.sub(r"(.)\1{2,}", r"\1", text)


def normalize_text(text):
    text = _NON_WORD_RE.sub(" ", _letters(text))
    return re.sub(r"\s+", " ", text).strip()


def _kw(words, prefix=True, suffix=False):
    alts = "|".join(
        re.escape(_letters(w)) for w in sorted(set(words), key=len, reverse=True)
    )
    pre = r"(?:و|ف)?(?:ال|لل|ل|ب)?" if prefix else ""
    suf = r"\w*" if suffix else ""
    return rf"(?<!\w)(?:{pre})(?:{alts}){suf}(?!\w)"


# ======================================================================
#  كشف طلبات العملاء الحقيقية (نظام نقاط + ذكاء اصطناعي اختياري)
# ======================================================================
FILTER_REQUESTS = os.getenv("FILTER_REQUESTS", "1") == "1"
DETECTION_DEBUG = os.getenv("DETECTION_DEBUG", "0") == "1"
MIN_REQUEST_SCORE = int(os.getenv("MIN_REQUEST_SCORE", "3"))

ASK_WORDS = [
    "ابي", "ابغى", "ابغا", "ابا", "ابى", "ابغاه", "ابغاها", "ابيه", "بغيت", "ابغيت",
    "احتاج", "احتاجها", "محتاج", "محتاجه", "محتاجة", "محتاجين", "نحتاج",
    "نبغى", "نبي", "نبغا", "ودي", "وددت", "اريد", "نريد", "مطلوب",
]

SERVICE_WORDS = [
    "توصيل", "توصيله", "توصيلة", "مشوار", "سواق", "سائق", "سايق", "كابتن", "مندوب",
    "سياره", "سيارة", "تكسي", "تاكسي", "ليموزين", "وانيت", "ونيت", "شاحنه", "دباب",
    "دينا", "نقل", "رحله", "رحلة",
]

GO_VERBS = ["اروح", "اوصل", "اسافر", "اطلع", "انزل", "اذهب", "ارجع", "اجي", "اودي", "اوديه", "يمرني", "يجيني", "يشيلني"]

QUESTION_WORDS = [
    "مين", "منو", "منهو", "احد", "حد", "اي واحد", "اي حد",
    "فيه احد", "في احد", "فيه حد", "في حد",
]

WHO_ACTIONS = [
    "يوصل", "يوصلني", "يوصلنا", "فاضي", "فاضيه", "فاضية", "متاح", "متفرغ", "يقدر", "يروح",
    "يجيب", "يشتري", "يشيل", "يودي", "يوديني", "يودينا", "ياخذني", "ياخذنا", "يمرني", "يجيني",
    "ينقل", "متوفر", "موجود", "قريب", "يمر لنا", "يمرنا",
]

STRONG_PHRASES = [
    "مين يوصلني", "مين يوصلنا", "مين فاضي", "مين فاضية", "من فاضي", "مين متاح", "مين موجود",
    "مين يقدر", "مين يروح", "مين يمرني", "مين يمرنا", "مين يمر لنا", "مين يجيني", "مين يوديني", 
    "مين يودينا", "مين ياخذني", "مين ياخذنا", "مين يطلعنا", "مين يمشينا", "مين يجيب لي", "مين يشتري لي",
    "احد فاضي", "احد يوصلني", "احد يوصلنا", "احد يمرني", "احد يمرنا", "احد يجيني", "احد يوديني",
    "في احد فاضي", "في احد يوصلني", "في احد يوصلنا", "فيه احد يمرنا", "حد فاضي", "حد يوصلني",
    "ابي مشوار", "ابغى مشوار", "ابغا مشوار", "ابي توصيله", "ابغى توصيلة", "محتاج مشوار", "محتاجة مشوار",
    "ابي احد يوصلني", "ابغى احد يوصلني", "ابغا احد يوصلني", "محتاج احد يوصلني", "محتاجة احد يوصلنا",
    "ابي احد يمرني", "ابغى احد يمرني", "محتاج احد يمرني", "محتاجة احد يمرنا", "ابي احد يجيني",
    "ابغى احد يجيني", "محتاج احد يجيني", "محتاجة احد يجيني", "ودي بمشوار", "ودي احد يوصلني",
    "احتاج مشوار", "احتاج توصيلة", "احتاج احد يوصلني", "ادور على مشوار", "ابحث عن توصيلة",
    "محتاجين مشوار", "محتاجين توصيلة", "محتاجين احد يوصلنا", "محتاجين احد يمرنا",
    "نبي مشوار", "نبغى مشوار", "نبغا مشوار", "نبي احد يوصلنا", "نبغى احد يوصلنا", "نبغى احد يمرنا",
    "نحتاج مشوار", "نحتاج توصيلة", "نحتاج احد يوصلنا", "نحتاج احد يمرنا", "ودي احد يوصلنا",
    "ناوين نروح", "طالعين مشوار", "مين يودينا المطار", "ابي احد يوديني المطار", "ابغى المطار"
]

TIME_WORDS = [
    "الساعه", "الساعة", "الحين", "الان", "الآن", "حاليا", "فورا", "حالا", "عاجل", "ضروري", "مستعجل", "بسرعه",
    "بكره", "بكرا", "اليوم", "الليله", "الفجر", "الصبح", "صباحا", "مساء",
]
PRICE_WORDS = ["كم", "بكم", "بكام", "سعر", "السعر", "اجره", "الاجره", "الحساب", "تكلفه", "التكلفه"]
PASSENGER_CARGO_WORDS = [
    "شخص", "اشخاص", "شخصين", "راكب", "ركاب", "راكبين", "عائله", "عيله", "اسره",
    "حريم", "نساء", "بنات", "بنت", "اطفال", "طفل", "شنطه", "شنط", "عفش", "اثاث",
    "طرد", "طرود", "شحنه", "غرض", "اغراض", "طلبيه", "بضاعه", "مستندات", "اوراق",
]
PLACE_WORDS = [
    "مطار", "جامعه", "جامعة", "كليه", "مستشفي", "مستشفى", "مستوصف", "سوق", "مول", "كورنيش",
    "شاطي", "محطه", "ميناء", "فندق", "مطعم", "كوفي", "كافيه", "بقاله", "صيدليه", "مدرسه",
]
CITY_WORDS = [
    "جازان", "جيزان", "صبيا", "صامطه", "صامطة", "ابو عريش", "ابوعريش", "المسارحه", "احد المسارحه",
    "فيفا", "ضمد", "بيش", "العارضه", "الدرب", "الريث", "فرسان", "الحرث", "العيدابي",
    "هروب", "الطوال", "الشقيق", "ابها", "خميس مشيط", "نجران", "جده", "مكه", "الرياض",
]

AD_STEM_WORDS = ["نوصل", "نوفر", "نقدم", "نخدم", "نستقبل", "نلبي", "نضمن", "خدماتن", "خدمتن"]
AD_PHRASES = [
    "لدينا", "تواصل معنا", "للتواصل", "للحجز", "للاستفسار", "للطلب",
    "واتس", "واتساب", "وتساب", "whatsapp", "تحت امركم", "بخدمتكم", "في خدمتكم",
    "اسعارنا", "اسعار مناسبه", "اسعار مميزه", "اسعار منافسه",
    "عروض", "عرض خاص", "خصم", "خصومات", "اشتراك", "اشتراكات", "شهري",
    "24 ساعه", "على مدار الساعه", "اعلان", "للايجار", "للبيع", "ايجار",
    "توظيف", "وظيفه", "وظايف", "سجل معنا", "رابط التسجيل", "مضمون",
    "انا مندوب", "أنا مندوب", "انا سواق", "أنا سواق", "انا كابتن", "التواصل واتس"
]

AD_WEAK_WORDS = ["متاح", "متوفر", "متواجد", "جاهز", "جاهزين", "موجود", "حياكم", "حياك"]
PLURAL_AD_WORDS = ["مشاوير", "توصيلات", "مناديب", "مندوبين", "سواقين", "سايقين", "سيارات", "كباتن", "رحلات"]

JOB_HEAD_WORDS = ["مطلوب", "مطلوبين", "نطلب", "نحتاج", "وظيفه"]
JOB_ROLE_WORDS = ["سائق", "سايق", "سواق", "مندوب", "كابتن", "موظف", "عامل"]
JOB_QUALIFIER_WORDS = ["راتب", "براتب", "دوام", "توظيف", "وظيفه", "للعمل", "عمل معنا", "شركه", "مؤسسه"]

_ASK = _kw(ASK_WORDS)
_SERVICE = _kw(SERVICE_WORDS)

ASK_RE = re.compile(_ASK)
SERVICE_RE = re.compile(_SERVICE)
ASK_SERVICE_RE = re.compile(rf"{_ASK}\s+(?:\S+\s+){{0,3}}?{_SERVICE}")
ASK_GO_RE = re.compile(rf"{_ASK}\s+(?:\S+\s+)?{_kw(GO_VERBS, prefix=False)}")
WHO_RE = re.compile(rf"{_kw(QUESTION_WORDS, prefix=False)}\s+(?:\S+\s+){{0,2}}?{_kw(WHO_ACTIONS, suffix=True)}")
WHO_FROM_RE = re.compile(rf"(?<!\w)من\s+{_kw(['يوصل', 'فاضي', 'متاح', 'يقدر', 'يروح', 'يجيب', 'يشتري', 'يودي', 'عنده', 'متفرغ', 'يمرني', 'يجيني'], prefix=False, suffix=True)}")
_QW = _kw(QUESTION_WORDS, prefix=False)
WHO_LOC_RE = re.compile(rf"{_QW}(?!\s+(?:ال)?(?:مسارحه|رفيده))\s+(?:\S+\s+){{0,2}}?{_kw(PLACE_WORDS + CITY_WORDS)}")
WHO_ALONE_RE = re.compile(rf"^{_QW}(?:\s+(?:هنا|قريب|حولي|موجود|متواجد|فاضي))?$")
WHO_REV_RE = re.compile(rf"{_kw(['فاضي', 'فاضيه', 'متاح', 'متفرغ'], prefix=False)}\s+{_kw(['احد', 'حد', 'مين'], prefix=False)}")
STRONG_RE = re.compile(_kw(STRONG_PHRASES, prefix=False))

ROUTE_RE_N = re.compile(r"(?<!\w)من\s+\S+(?:\s+\S+){0,3}?\s+(?:الي|لين|ل\S{2,})")
DEST_RE_N = re.compile(r"(?<!\w)(?:الي|لين|لحد)\s+\S{2,}")
TIME_RE = re.compile(_kw(TIME_WORDS, prefix=False) + r"|(?<!\w)بعد\s+(?:\d+|ساعه|ساعتين|نص|ربع)")
PRICE_RE = re.compile(_kw(PRICE_WORDS, prefix=False))
PASSENGER_RE = re.compile(_kw(PASSENGER_CARGO_WORDS))
PLACE_RE = re.compile(_kw(PLACE_WORDS + CITY_WORDS))

AD_STEM_RE = re.compile(_kw(AD_STEM_WORDS, prefix=False, suffix=True))
AD_PHRASE_RE = re.compile(_kw(AD_PHRASES, prefix=False))
AD_WEAK_RE = re.compile(_kw(AD_WEAK_WORDS))
PLURAL_AD_RE = re.compile(_kw(PLURAL_AD_WORDS))

DRIVER_SELF_RE = re.compile(rf"(?<!\w)(?:انا|اني|احنا)\s+{_kw(['مندوب', 'سواق', 'سايق', 'سائق', 'كابتن', 'متاح', 'فاضي', 'متواجد', 'جاهز', 'موجود'], prefix=True, suffix=True)}")
DRIVER_SOLICIT_RE = re.compile(r"(?<!\w)مين\s+(?:يبي|يبغي|يبغا|يحتاج|يريد|محتاج|ودها)\w*")
DRIVER_SECOND_PERSON_RE = re.compile(r"(?<!\w)(?:تبي|تبغي|تبغا|تبون|تبغون|تحتاج|تحتاجون)\s+(?:\S+\s+){0,2}?" + _kw(["مشوار", "توصيله", "توصيل", "سياره", "مندوب", "سواق", "سايق"]))
JOB_RE = re.compile(rf"{_kw(JOB_HEAD_WORDS)}\s+(?:\S+\s+)?{_kw(JOB_ROLE_WORDS)}")
JOB_QUALIFIER_RE = re.compile(_kw(JOB_QUALIFIER_WORDS))

_LINK_RE = re.compile(r"@[A-Za-z0-9_]{3,}|t\.me/|https?://|www\.", re.IGNORECASE)
_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50]")

_HARD_REJECTS = [
    ("ad-stem", AD_STEM_RE),
    ("ad-phrase", AD_PHRASE_RE),
    ("driver-self", DRIVER_SELF_RE),
    ("driver-solicit", DRIVER_SOLICIT_RE),
    ("driver-second-person", DRIVER_SECOND_PERSON_RE),
]


def _has_phone(text):
    t = text.translate(_DIGITS_TABLE)
    t = re.sub(r"(?<=\d)[\s\-.]+(?=\d)", "", t)
    return re.search(r"(?<!\d)(?:\+?966|00966|0)?5\d{8}(?!\d)", t) is not None


# ---- وظيفة الذكاء الاصطناعي الإضافية (اختيارية وتعمل بتوافق تام) ----
def ai_verify_request(text):
    """
    تستიدم الذكاء الاصطناعي لتحليل النص والتحقق مما إذا كان طلب عميل حقيقي.
    ترجع True إذا كان طلباً حقيقياً، و False إذا كان إعلاناً أو غير مهم.
    """
    if not USE_AI_FILTER or not AI_API_KEY:
        return None # معطلة، يتم الاعتماد على النظام العادي
    
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo", # أو أي نموذج سريع واقتصادي مثل groq/llama3
            messages=[
                {
                    "role": "system", 
                    "content": "أنت مساعد ذكي لتصفية رسائل قروبات التوصيل والمشاوير في السعودية. مهمتك تحديد ما إذا كانت الرسالة الواردة هي 'طلب عميل حقيقي' يبحث عن توصيل/مشوار/أغراض، وليست 'إعلاناً' من سائق أو مندوب يعرض خدماته. أجب بكلمة واحدة فقط: YES (إذا كان طلب عميل) أو NO (إذا كان إعلان أو غير ذلك)."
                },
                {"role": "user", "content": text}
            ],
            max_tokens=5,
            temperature=0.0
        }
        answer = response.choices[0].message.content.strip().upper()
        return "YES" in answer
    except Exception as e:
        logging.error(f"AI Filter Error: {e}")
        return None


def classify_request(text):
    raw = text or ""
    norm = normalize_text(raw)
    if not norm:
        return False, 0, ["empty"]

    if _LINK_RE.search(raw):
        return False, 0, ["reject:link-or-handle"]
    for label, rx in _HARD_REJECTS:
        if rx.search(norm):
            return False, 0, [f"reject:{label}"]
    if JOB_RE.search(norm) and JOB_QUALIFIER_RE.search(norm):
        return False, 0, ["reject:job-ad"]

    # فحص الذكاء الاصطناعي الاختياري إذا كان مفَعّلاً
    if USE_AI_FILTER and AI_API_KEY:
        ai_res = ai_verify_request(raw)
        if ai_res is False:
            return False, 0, ["reject:ai-classified-as-ad"]
        elif ai_res is True:
            return True, 10, ["approve:ai-verified-customer"]

    score = 0
    reasons = []

    def add(points, label):
        nonlocal score
        score += points
        reasons.append(f"{points:+d} {label}")

    has_strong = bool(STRONG_RE.search(norm))
    has_ask = bool(ASK_RE.search(norm))
    has_who = bool(
        WHO_RE.search(norm) or WHO_FROM_RE.search(norm) or WHO_REV_RE.search(norm)
        or WHO_LOC_RE.search(norm) or WHO_ALONE_RE.match(norm)
    )

    if has_strong:
        add(5, "strong-phrase-matched")
    if has_who:
        add(4, "who-asks")
    if ASK_SERVICE_RE.search(norm):
        add(4, "ask+service")
    if ASK_GO_RE.search(norm):
        add(3, "ask+go")
    if has_ask:
        add(2, "ask")
    if SERVICE_RE.search(norm):
        add(1, "service")

    if ROUTE_RE_N.search(norm):
        add(2, "route")
    elif DEST_RE_N.search(norm):
        add(1, "destination")
    if PLACE_RE.search(norm):
        add(1, "place")
    if TIME_RE.search(norm):
        add(1, "time")
    if PRICE_RE.search(norm):
        add(1, "price")
    if PASSENGER_RE.search(norm):
        add(1, "passengers/cargo")

    if not (has_ask or has_who or has_strong) and AD_WEAK_RE.search(norm):
        add(-4, "availability-wording")
    if PLURAL_AD_RE.search(norm):
        add(-3, "plural-ad-wording")
    if _has_phone(raw):
        add(-3, "phone-number-in-ad")
    if len(_EMOJI_RE.findall(raw)) >= 5:
        add(-2, "emoji-heavy")

    return score >= MIN_REQUEST_SCORE, score, reasons


def is_real_customer_request(text):
    ok, score, reasons = classify_request(text)
    if DETECTION_DEBUG:
        logging.info(f"[detect] ok={ok} score={score} reasons={reasons} text={text[:80]!r}")
    return ok


# ======================================================================
#  منع تكرار الطلب في عدة قروبات
# ======================================================================
DEDUP_WINDOW = int(os.getenv("DEDUP_WINDOW_SECONDS", "1800"))
SIMILARITY_THRESHOLD = float(os.getenv("DEDUP_SIMILARITY", "0.88"))

_recent_by_sender = {}
_last_cleanup = 0.0


def _cleanup_recent(now):
    global _last_cleanup
    if now - _last_cleanup < 60:
        return
    _last_cleanup = now
    for key in list(_recent_by_sender):
        kept = [e for e in _recent_by_sender[key] if now - e[1] <= DEDUP_WINDOW]
        if kept:
            _recent_by_sender[key] = kept
        else:
            del _recent_by_sender[key]


def is_duplicate_request(sender_id, text):
    if DEDUP_WINDOW <= 0:
        return False
    now = time.monotonic()
    norm = normalize_text(text)
    _cleanup_recent(now)

    entries = _recent_by_sender.setdefault(sender_id or "anon", [])
    for entry in entries:
        if now - entry[1] > DEDUP_WINDOW:
            continue
        old = entry[0]
        same = old == norm
        similar = (
            not same
            and len(norm) >= 15
            and len(old) >= 15
            and SequenceMatcher(None, old, norm).ratio() >= SIMILARITY_THRESHOLD
        )
        if same or similar:
            entry[1] = now
            return True

    entries.append([norm, now])
    return False


# ---------------- أدوات التنسيق (HTML & RTL) ----------------
MARK_CHOICE = os.getenv("RTL_MARK", "ALM").upper()
RLM = "\u061C" if MARK_CHOICE == "ALM" else "\u200F"
USE_BLOCKQUOTE = os.getenv("USE_BLOCKQUOTE", "1") == "1"
MAX_TEXT_LEN = 1500
AUTO_REPLY_TEXT = "السلام عليكم، حصلتم ولا لسا؟! إذا باقي أنا بتمم معاك"

RIYADH_TZ = timezone(timedelta(hours=3))


def format_time(dt):
    if dt is None:
        return ""
    local = dt.astimezone(RIYADH_TZ)
    hour12 = local.hour % 12 or 12
    suffix = "ص" if local.hour < 12 else "م"
    return f"{hour12:02d}:{local.minute:02d} {suffix}"


_ROUTE_RE = re.compile(r"من\s+(?P<a>[^\n،,.؟?]{2,30}?)\s+(?:(?:الى|إلى|لين)\s+|ل(?=[ء-ي]))(?P<b>[^\n،,.؟?]{2,30})")
_ROUTE_STOP_RE = re.compile(r"\s+(?:الساعة|الان|الآن|الحين|بكرة|بكره|اليوم|الليلة|بعد|قبل|وابي|و\s?ابي|ابغى|ابي|ب\s?\d|السعر|بسعر)(?!\w)|\s+\d")


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


URGENT_WORDS = ["عاجل", "ضروري", "مستعجل", "حالا", "حالاً", "الان", "الآن", "الحين", "بسرعة", "فورا"]
AIRPORT_WORDS = ["مطار"]
UNIVERSITY_WORDS = ["جامعة", "جامعه"]
HOSPITAL_WORDS = ["مستشفى", "المستشفي", "مستوصف"]
CAFE_WORDS = ["كوفي", "كافيه", "كافي"]
RESTAURANT_WORDS = ["مطعم", "المطعم"]
MARKET_WORDS = ["سوق", "السوق", "مول"]
GROCERY_WORDS = ["بقالة", "البقالة", "سوبرماركت"]
BEACH_WORDS = ["بحر", "البحر", "كورنيش", "شاطئ"]

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

    if not message_text or not message_text.strip():
        return

    if FILTER_REQUESTS and not is_real_customer_request(message_text):
        return

    if is_duplicate_request(event.sender_id, message_text):
        logging.info(f"Duplicate request skipped (sender={event.sender_id})")
        return

    route = extract_route(message_text)
    route_text = ""
    if route:
        origin, destination = route
        route_text = f"\n📍 <b>من:</b> {origin}\n🏁 <b>إلى:</b> {destination}"

    tags = build_tags(message_text)
    req_time = format_time(event.date)
    quote_text = build_quote(message_text)

    chat = await event.get_chat()
    sender = await event.get_sender()

    chat_title = getattr(chat, 'title', 'قروب عام')

    sender_name = "عميل"
    if sender:
        first = getattr(sender, 'first_name', '') or ''
        last = getattr(sender, 'last_name', '') or ''
        sender_name = html.escape(f"{first} {last}".strip() or "عميل")

    direct_chat_link = ""
    auto_reply_link = ""
    encoded_reply = quote(AUTO_REPLY_TEXT)

    if sender and getattr(sender, 'username', None):
        username = sender.username
        direct_chat_link = f"https://t.me/{username}"
        auto_reply_link = f"https://t.me/{username}?text={encoded_reply}"
    elif sender:
        direct_chat_link = f"tg://user?id={sender.id}"
        auto_reply_link = f"tg://user?id={sender.id}"

    message_link = ""
    if getattr(chat, 'username', None):
        message_link = f"https://t.me/{chat.username}/{event.id}"

    final_message = (
        f"🚗 <b>طلب مشوار جديد</b> {tags}\n"
        f"──────────────────\n"
        f"👤 <b>العميل:</b> {sender_name}\n"
        f"📍 <b>المصدر:</b> {html.escape(chat_title)}\n"
        f"⏰ <b>الوقت:</b> {req_time}\n"
        f"{route_text}\n\n"
        f"📝 <b>نص الطلب:</b>\n"
        f"{quote_text}\n\n"
        f"🔗 <b>روابط السريعة للتفاعل:</b>\n"
    )

    if direct_chat_link:
        final_message += f"💬 <a href='{direct_chat_link}'>محادثة العميل مباشرة</a>\n"
    if auto_reply_link:
        final_message += f"📩 <a href='{auto_reply_link}'>إرسال رد جاهز للعميل</a>\n"
    if message_link:
        final_message += f"👁️ <a href='{message_link}'>عرض الرسالة في القروب الأصلي</a>\n"

    try:
        await client.send_message(
            int(TARGET_CHAT_ID) if TARGET_CHAT_ID.lstrip('-').isdigit() else TARGET_CHAT_ID,
            final_message,
            parse_mode='html',
            link_preview=False
        )
    except Exception as e:
        logging.error(f"Failed to forward message: {e}")


# ---------------- التشغيل الرئيسي للبوت وخادم الويب ----------------
if __name__ == '__main__':
    keep_alive()

    try:
        print("Starting Telegram Userbot...")
        client.start()
        client.run_until_disconnected()
    except Exception as e:
        print(f"Telegram Bot Error: {e}")
