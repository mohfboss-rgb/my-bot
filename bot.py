import os
import json
import time
import asyncio
import threading
import requests
import websockets
from flask import Flask, request, render_template_string
import google.generativeai as genai
import yt_dlp

app = Flask(__name__)

# قراءة المتغيرات من إعدادات Render
BOT_USERNAME = os.environ.get("BOT_USERNAME", "")
BOT_PASSWORD = os.environ.get("BOT_PASSWORD", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "12345")
DEFAULT_ROOM = os.environ.get("MY_ROOM_ID", "")

# تهيئة الذكاء الاصطناعي Gemini
ai_model = None
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    ai_model = genai.GenerativeModel("gemini-1.5-flash")

# دالة تنظيف رقم الروم في حال تم إدخال رابط كامل
def clean_room_id(raw_id):
    val = str(raw_id).strip()
    if "room-" in val:
        val = val.split("room-")[-1].split("-")[0]
    return val

# قائمة الاشتراكات المفعلة (مقفلة ضد السرقة)
subscriptions = {}
if DEFAULT_ROOM:
    r_clean = clean_room_id(DEFAULT_ROOM)
    if r_clean:
        subscriptions[r_clean] = {
            "host": "الكل",
            "mods": [],
            "active": True
        }

bot_state = {
    "logged_in": False,
    "log": "جاري بدء التشغيل والاتصال...",
    "current_song": "لا يوجد",
    "connected_rooms": []
}

# دالة البحث عن الأغاني في يوتيوب
def search_youtube_song(query):
    ydl_opts = {
        "format": "bestaudio",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch1:{query}", download=False)
            entries = result.get("entries", [])
            if entries and len(entries) > 0:
                video = entries[0]
                return video.get("title", query), video.get("webpage_url", "")
        return None, None
    except Exception:
        return None, None

# دالة الرد الذكي
def ask_gemini(prompt):
    if not ai_model:
        return "مفتاح الذكاء الاصطناعي غير مضاف في الإعدادات."
    try:
        sys_msg = "أنت بوت ذكي ومشرف مساعد في غرفة دردشة IMVU. رد بالعربية باختصار شديد ولباقة (سطرين كحد أقصى): "
        res = ai_model.generate_content(sys_msg + prompt)
        return res.text.strip()
    except Exception:
        return "عذراً، حدث ضغط في النظام. حاول بعد قليل."

# التحقق من صلاحية الهوست والمشرفين والاشتراك
def is_authorized(room_id, sender_name):
    sub = subscriptions.get(str(room_id))
    if not sub or not sub.get("active"):
        return False
    if sub["host"] == "الكل" or not sub["host"]:
        return True
    allowed = [sub["host"].lower()] + [m.lower() for m in sub["mods"]]
    return sender_name.lower() in allowed

# عميل الاتصال الفعلي بلعبة IMVU
class SecureIMVUBot:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json"
        })
        self.cid = None
        self.sauce = None

    def login(self):
        if not BOT_USERNAME or not BOT_PASSWORD:
            bot_state["log"] = "خطأ: بيانات حساب البوت ناقصة في Render"
            return False
        try:
            resp = self.session.post(
                "https://imvu.com",
                json={"username": BOT_USERNAME, "password": BOT_PASSWORD},
                timeout=15
            )
            data = resp.json()
            if data.get("status") == "success":
                user_info = data["denormalized"][data["id"]]["data"]
                self.cid = user_info["user"]["id"]
                self.sauce = user_info["sauce"]
                bot_state["logged_in"] = True
                bot_state["log"] = f"تم تسجيل الدخول بنجاح (ID: {self.cid})"
                return True
            bot_state["log"] = f"فشل الدخول: {data.get('message', 'تحقق من بيانات الحساب')}"
            return False
        except Exception as e:
            bot_state["log"] = f"خطأ في الاتصال بالسيرفر: {e}"
            return False

    async def run_ws(self):
        if not self.login():
            return

        imq_url = "wss://://imvu.com"
        try:
            async with websockets.connect(imq_url) as ws:
                await ws.send(json.dumps({
                    "type": "imq_connect",
                    "user_id": str(self.cid),
                    "sauce": self.sauce
                }))
                await asyncio.sleep(1)

                joined = set()
                while True:
                    # الانضمام للغرف المفعلة فقط
                    for r_id, info in list(subscriptions.items()):
                        if info.get("active") and r_id not in joined:
                            ch = f"imvu:room:{r_id}"
                            await ws.send(json.dumps({"type": "imq_join", "channel": ch}))
                            joined.add(r_id)
                            bot_state["connected_rooms"] = list(joined)
                            await ws.send(json.dumps({
                                "type": "imq_send",
                                "channel": ch,
                                "message": "🛡️ تم تفعيل البوت الذكي المحمي! الأوامر متاحة للهوست والمشرفين."
                            }))

                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    except asyncio.TimeoutError:
                        continue

                    msg_data = json.loads(raw)
                    text = msg_data.get("message", "").strip()
                    sender_id = str(msg_data.get("user_id", ""))
                    sender_name = str(msg_data.get("username", sender_id))
                    channel = msg_data.get("channel", "")

                    if not text or sender_id == str(self.cid) or not channel.startswith("imvu:room:"):
                        continue

                    room_id = channel.replace("imvu:room:", "")

                    # رفض أي شخص غير مصرح له أو روم غير مشترك
                    if not is_authorized(room_id, sender_name):
                        continue

                    # أمر تشغيل الأغاني
                    if text.startswith("!شغل ") or text.startswith("!play "):
                        parts = text.split(" ", 1)
                        if len(parts) > 1 and parts[1].strip():
                            title, link = search_youtube_song(parts[1].strip())
                            if title:
                                bot_state["current_song"] = title
                                reply = f"🎶 تشغيل ({sender_name}): {title} | {link}"
                            else:
                                reply = "❌ لم أتمكن من العثور على الأغنية."
                            await ws.send(json.dumps({"type": "imq_send", "channel": channel, "message": reply}))

                    # أمر الذكاء الاصطناعي
                    elif text.startswith("!بوت ") or text.startswith("بوت "):
                        parts = text.split(" ", 1)
                        if len(parts) > 1 and parts[1].strip():
                            ai_ans = ask_gemini(parts[1].strip())
                            if ai_ans:
                                await ws.send(json.dumps({"type": "imq_send", "channel": channel, "message": ai_ans}))

        except Exception as e:
            bot_state["logged_in"] = False
            bot_state["connected_rooms"] = []
            bot_state["log"] = f"انقطع الاتصال، جاري إعادة المحاولة تلقائياً..."

def background_worker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot = SecureIMVUBot()
    while True:
        loop.run_until_complete(bot.run_ws())
        time.sleep(15)

threading.Thread(target=background_worker, daemon=True).start()

# واجهة لوحة التحكم
HTML_DASHBOARD = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>لوحة إدارة اشتراكات بوت IMVU</title>
    <style>
        body { font-family: Tahoma, sans-serif; background: #0f172a; color: #f8fafc; padding: 15px; text-align: center; }
        .box { background: #1e293b; border-radius: 12px; padding: 20px; max-width: 480px; margin: 15px auto; box-shadow: 0 4px 12px rgba(0,0,0,0.4); }
        input, button { width: 92%; padding: 11px; margin: 7px 0; border-radius: 8px; border: none; font-size: 15px; }
        input { background: #334155; color: white; }
        button { background: #2563eb; color: white; font-weight: bold; cursor: pointer; }
        .sub-item { background: #0f172a; padding: 10px; border-radius: 8px; margin: 8px 0; text-align: right; font-size: 14px; }
        .alert { color: #38bdf8; font-weight: bold; margin: 10px 0; }
    </style>
</head>
<body>
    <div class="box">
        <h2>🛡️ لوحة البوت المحمي (نظام الاشتراكات)</h2>
        <p>الحالة: <b>{{ state.log }}</b></p>
        <p>الغرف النشطة: <b>{{ state.connected_rooms | join(', ') or 'لا يوجد' }}</b></p>
        <p>الأغنية الحالية: <b>{{ state.current_song }}</b></p>
        {% if message %}<div class="alert">{{ message }}</div>{% endif %}
    </div>

    <div class="box">
        <h3>➕ تفعيل اشتراك روم جديد (للمالك فقط)</h3>
        <form method="POST" action="/manage_sub">
            <input type="password" name="secret" placeholder="كلمة سر المالك (ADMIN_SECRET)" required>
            <input type="text" name="room_id" placeholder="رقم الروم (Room ID)" required>
            <input type="text" name="host" placeholder="اسم الهوست (أو اكتب: الكل)" required>
            <input type="text" name="mods" placeholder="أسماء المشرفين مفصولة بفاصلة (اختياري)">
            <button type="submit" name="action" value="add">تفعيل الاشتراك ودخول البوت</button>
