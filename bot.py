import os
import asyncio
import threading
from flask import Flask, request, render_template_string, redirect, url_for
import imvu
import yt_dlp
import google.generativeai as genai

USERNAME = os.environ.get("BOT_USERNAME")
PASSWORD = os.environ.get("BOT_PASSWORD")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
MY_ROOM_ID = os.environ.get("MY_ROOM_ID", "")
ALLOWED_ROOMS = os.environ.get("ALLOWED_ROOMS", "")
PAYMENT_INFO = os.environ.get("PAYMENT_INFO", "سعر الاشتراك: 5000 كريدت أو 5$ USDT. تواصل مع المالك لتفعيل رقم غرفتك.")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    system_instruction="أنت بوت ذكي وموسيقي في لعبة IMVU. رد باللهجة العربية الودودة والقصيرة (سطر أو سطرين كحد أقصى) وأجب على أي سؤال بذكاء."
)

client = imvu.Client()
app = Flask(__name__)

current_songs = {}
custom_replies = {}
welcome_enabled = True

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>لوحة تحكم البوت الذكي والموسيقي</title>
    <style>
        body { background-color: #0b0f19; color: #f8fafc; font-family: Tahoma, sans-serif; margin: 0; padding: 15px; text-align: center; }
        .container { max-width: 480px; margin: auto; }
        .box { background: #131b2e; border: 1px solid #1e293b; border-radius: 16px; padding: 20px; margin-bottom: 15px; box-shadow: 0 4px 20px rgba(0,0,0,0.4); }
        h2, h3 { margin-top: 0; color: #38bdf8; }
        input { width: 92%; padding: 12px; margin: 8px 0; border-radius: 10px; border: 1px solid #334155; background: #0f172a; color: white; text-align: center; font-size: 15px; }
        .btn { padding: 11px 18px; border: none; border-radius: 10px; font-weight: bold; cursor: pointer; font-size: 14px; margin: 5px; }
        .btn-green { background: linear-gradient(90deg, #10b981, #059669); color: white; width: 45%; }
        .btn-red { background: #ef4444; color: white; width: 45%; }
        .btn-blue { background: #3b82f6; color: white; }
        .btn-kick { background: #dc2626; color: white; padding: 6px 12px; border-radius: 8px; font-size: 12px; }
        .member-row { display: flex; justify-content: space-between; align-items: center; background: #0f172a; padding: 10px 15px; border-radius: 10px; margin-bottom: 8px; border: 1px solid #1e293b; }
        .song-box { background: #0f172a; padding: 12px; border-radius: 12px; border: 1px solid #10b981; color: #34d399; font-weight: bold; }
        .msg { background: #1e293b; color: #38bdf8; padding: 10px; border-radius: 10px; margin-bottom: 15px; font-weight: bold; }
        .cmd-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; text-align: right; font-size: 12px; }
        .cmd-item { background: #0f172a; padding: 10px; border-radius: 8px; border: 1px solid #1e293b; }
        .cmd-code { color: #38bdf8; font-weight: bold; display: block; margin-bottom: 4px; }
    </style>
</head>
<body>
<div class="container">
    {% if msg %}
        <div class="msg">{{ msg }}</div>
    {% endif %}

    <div class="box">
        <h2>🎵 لوحة تحكم البوت الذكي</h2>
        <p style="font-size: 13px; color: #94a3b8;">أدخل رقم غرفتك (Room ID) للتحكم الكامل وإدخال البوت</p>
        <form method="GET" action="/">
            <input type="text" name="room_id" value="{{ room_id }}" placeholder="رقم الغرفة (مثال: 350431027-27)" required>
            <br>
            <button type="submit" name="action" value="join" class="btn btn-green">إدخال البوت ✅</button>
            <button type="submit" name="action" value="leave" class="btn btn-red">مغادرة الروم ❌</button>
        </form>
        <p style="font-size: 11px; color: #fbbf24; margin-top: 10px;">⚠️ شرط هام: أعطِ حساب البوت رتبة Moderator في غرفتك قبل الدخول.</p>
    </div>

    {% if room_id and is_allowed %}
    <div class="box">
        <h3>🎶 الأغنية الشغالة حالياً</h3>
        <div class="song-box">
            {{ current_song }}
        </div>
        <form method="POST" action="/control" style="margin-top: 10px;">
            <input type="hidden" name="room_id" value="{{ room_id }}">
            <input type="text" name="song_query" placeholder="اكتب اسم أغنية لتشغيلها مباشرة...">
            <button type="submit" name="cmd" value="play" class="btn btn-green">!play تشغيل ▶️</button>
            <button type="submit" name="cmd" value="stop" class="btn btn-red">!stop إيقاف ⏹️</button>
        </form>
    </div>

    <div class="box">
        <h3>👥 المتواجدين في الروم ({{ members|length }})</h3>
        {% if members %}
            {% for m in members %}
            <div class="member-row">
                <div style="text-align: right;">
                    <strong>{{ m.name }}</strong><br>
                    <span style="font-size: 11px; color: #64748b;">ID: {{ m.id }}</span>
                </div>
                <form method="POST" action="/kick" style="margin: 0;">
                    <input type="hidden" name="room_id" value="{{ room_id }}">
                    <input type="hidden" name="target_name" value="{{ m.name }}">
                    <button type="submit" class="btn btn-kick">❌ طرد</button>
                </form>
            </div>
            {% endfor %}
        {% else %}
            <p style="font-size: 13px; color: #64748b;">البوت غير متصل بالغرفة حالياً أو لا يوجد أعضاء.</p>
        {% endif %}
    </div>

    <div class="box">
        <h3>💬 ردود تلقائية مخصصة</h3>
        <form method="POST" action="/add_reply">
            <input type="hidden" name="room_id" value="{{ room_id }}">
            <input type="text" name="trigger" placeholder="الكلمة المفتاحية (مثلاً: السلام عليكم)" required>
            <input type="text" name="reply" placeholder="رد البوت (استخدم {user} لاسم الشخص)" required>
            <button type="submit" class="btn btn-blue">+ إضافة رد</button>
        </form>
        {% for k, v in replies.items() %}
            <div style="font-size: 12px; background: #0f172a; padding: 8px; border-radius: 8px; margin-top: 5px;">
                <strong>{{ k }}</strong> ⬅️ {{ v }}
            </div>
        {% endfor %}
    </div>
    {% endif %}

    <div class="box">
        <h3>📋 أوامر البوت في الدردشة</h3>
        <div class="cmd-grid">
            <div class="cmd-item"><span class="cmd-code">!شغل [اسم الأغنية]</span>البحث وتشغيل الأغنية فوراً</div>
            <div class="cmd-item"><span class="cmd-code">!وقف</span>إيقاف الموسيقى الحالية</div>
            <div class="cmd-item"><span class="cmd-code">يا بوت [سؤالك]</span>سؤال الذكاء الاصطناعي عن أي شيء</div>
            <div class="cmd-item"><span class="cmd-code">!طرد [الاسم]</span>طرد شخص من الغرفة (للمشرفين)</div>
        </div>
    </div>

    <div class="box" style="border-color: #3b82f6;">
        <h3>💳 تفعيل الاشتراك والدفع</h3>
        <p style="font-size: 13px; color: #cbd5e1;">{{ payment_info }}</p>
    </div>
</div>
</body>
</html>
"""

def check_allowed(room_id):
    if not room_id:
        return False
    allowed = [r.strip() for r in ALLOWED_ROOMS.split(",") if r.strip()]
    if MY_ROOM_ID:
        allowed.append(MY_ROOM_ID.strip())
    return room_id.strip() in allowed

@app.route("/", methods=["GET"])
def index():
    room_id = request.args.get("room_id", MY_ROOM_ID).strip()
    action = request.args.get("action")
    msg = request.args.get("msg", "")
    is_allowed = check_allowed(room_id)

    if action and room_id:
        if not is_allowed:
            msg = "❌ هذه الغرفة غير مفعلة! ادفع الاشتراك أولاً ثم أرسل رقم غرفتك للمالك."
        elif action == "join":
            asyncio.run_coroutine_threadsafe(join_room_task(room_id), client.loop)
            msg = f"✅ تم إرسال البوت إلى الغرفة {room_id} بنجاح!"
        elif action == "leave":
            asyncio.run_coroutine_threadsafe(leave_room_task(room_id), client.loop)
            msg = f"👋 تم إخراج البوت من الغرفة {room_id}."

    members_list = []
    for r in client.rooms:
        if str(r.id) == room_id:
            for m in r.members:
                if m != client.user:
                    members_list.append({"name": m.name, "id": getattr(m, "id", "N/A")})

    song_name = current_songs.get(room_id, "لا توجد أغنية تعمل حالياً")
    return render_template_string(
        HTML_TEMPLATE,
        room_id=room_id,
        is_allowed=is_allowed,
        msg=msg,
        members=members_list,
        current_song=song_name,
        replies=custom_replies,
        payment_info=PAYMENT_INFO
    )

@app.route("/control", methods=["POST"])
def control_music():
    room_id = request.form.get("room_id", "").strip()
    cmd = request.form.get("cmd")
    song_query = request.form.get("song_query", "").strip()
    if check_allowed(room_id):
        if cmd == "play" and song_query:
            asyncio.run_coroutine_threadsafe(play_song_task(room_id, song_query), client.loop)
        elif cmd == "stop":
            asyncio.run_coroutine_threadsafe(stop_song_task(room_id), client.loop)
    return redirect(url_for("index", room_id=room_id, msg="تم تنفيذ أمر الموسيقى ✅"))

@app.route("/kick", methods=["POST"])
def kick_user():
    room_id = request.form.get("room_id", "").strip()
    target_name = request.form.get("target_name", "").strip()
    if check_allowed(room_id) and target_name:
        asyncio.run_coroutine_threadsafe(kick_member_task(room_id, target_name), client.loop)
    return redirect(url_for("index", room_id=room_id, msg=f"تم إرسال أمر طرد {target_name} 🚫"))

@app.route("/add_reply", methods=["POST"])
def add_reply():
    room_id = request.form.get("room_id", "").strip()
    trigger = request.form.get("trigger", "").strip()
    reply = request.form.get("reply", "").strip()
    if check_allowed(room_id) and trigger and reply:
        custom_replies[trigger] = reply
    return redirect(url_for("index", room_id=room_id, msg="تم حفظ الرد المخصص بنجاح ✅"))

async def join_room_task(room_id):
    try:
        room = await client.join_room(room_id)
    except Exception as e:
        print(e)
