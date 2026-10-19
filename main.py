import os
import asyncio
from flask import Flask
from telethon import TelegramClient
from telethon.sessions import StringSession

# إعداد تطبيق الفلاسك (Flask) للحفاظ على عمل البوت على Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running successfully!"

# قراءة البيانات المعتمدة من متغيرات البيئة في Render
API_ID = int(os.environ.get('TELEGRAM_API_ID', 0))
API_HASH = os.environ.get('TELEGRAM_API_HASH', '')
STRING_SESSION = os.environ.get('STRING_SESSION', '')

# تهيئة عميل تيليجرام باستخدام الـ StringSession لمنع أي تعارض في الملفات المحلية
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

async def main():
    # بدء تشغيل العميل
    await client.start()
    print("Telegram client started successfully!")
    
    # ضع هنا المهام أو الأكواد الخاصة بالبوت الخاص بك
    # مثال: await client.send_message('me', 'Bot is online!')

    # الابتعاد عن إغلاق السيرفر وجعل البوت يعمل بشكل مستمر
    await client.run_until_disconnected()

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    import threading
    # تشغيل خادم الفلاسك في خلفية منفصلة لضمان استجابة المنصة
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # تشغيل نظام تيليجرام المتزامن
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped.")
