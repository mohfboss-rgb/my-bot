import os
import asyncio
import threading
from flask import Flask, request, render_template_string
import imvu
import yt_dlp
import google.generativeai as genai

USERNAME = os.environ.get("BOT_USERNAME")
PASSWORD = os.environ.get("BOT_PASSWORD")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SECRET_PASS = os.environ.get("SECRET_PASS", "12345")
MY_ROOM_ID = os.environ.get("MY_ROOM_ID")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    system_instruction="أنت بوت ذكي وموسيقي في لعبة IMVU. رد باللهجة العربية الودودة والقصيرة (سطر أو سطرين كحد أقصى)."
)

client = imvu.Client()
app = Flask(__name__)

HTML_PAGE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>لوحة تحكم البوت الذكي</title>
    <style>
        body { background-color: #0f172a; color: white; font-family: Tahoma, sans-serif; text-align: center; padding: 30px; }
        .card { background: #1e293b; max-width: 400px; margin: auto; padding: 25px; border-radius: 15px; }
        input { width: 90%; padding: 12px; margin: 10px 0; border-radius: 8px; border: none; background: #334155; color: white; text-align: center; }
        button { width: 45%; padding: 12px; margin: 10px 2%; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; }
        .btn-join { background: #10b981; color: white; }
        .btn-leave { background: #ef4444; color: white; }
        .msg { margin-top: 15px; color: #38bdf8; font-weight: bold; }
    </style>
</head>
<body>
    <div class="card">
        <h2>🎵 لوحة تحكم البوت الذكي</h2>
        <form method="POST">
            <input type="text" name="room_id" placeholder="رقم الغرفة (مثال: 350431027-27)" required>
            <input type="password" name="code" placeholder="رمز الاشتراك السري" required>
            <br>
            <button type="submit" name="action" value="join" class="btn-join">إدخال البوت ✅</button>
            <button type="submit" name="action" value="leave" class="btn-leave">إخراج البوت ❌</button>
        </form>
        {% if message %}
            <div class="msg">{{ message }}</div>
        {% endif %}
    </div>
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def home():
    msg = ""
    if request.method == "POST":
        room_id = request.form.get("room_id", "").strip()
        code = request.form.get("code", "").strip()
        action = request.form.get("action")

        if code != SECRET_PASS:
            msg = "❌ رمز الاشتراك غير صحيح!"
        elif action == "join":
            asyncio.run_coroutine_threadsafe(join_customer_room(room_id), client.loop)
            msg = f"✅ تم إرسال البوت إلى الغرفة {room_id}!"
        elif action == "leave":
            asyncio.run_coroutine_threadsafe(leave_customer_room(room_id), client.loop)
            msg = f"👋 تم سحب البوت من الغرفة {room_id}."
    return render_template_string(HTML_PAGE, message=msg)

async def join_customer_room(room_id):
    try:
        room = await client.join_room(room_id)
        await room.send("تم تفعيل البوت الذكي! اكتب (يا بوت) للدردشة معي، أو (!شغل اسم الأغنية) للموسيقى 🎶🤖")
    except Exception as e:
        print(f"خطأ: {e}")

async def leave_customer_room(room_id):
    for room in client.rooms:
        if str(room.id) == room_id:
            await room.send("تم إيقاف البوت من لوحة التحكم. وداعاً! 👋")
            await room.leave()

@client.event
async def on_ready():
    print("البوت يعمل الآن بنجاح!")
    if MY_ROOM_ID:
        await join_customer_room(MY_ROOM_ID)

@client.event
async def on_member_join(member):
    if member != client.user:
        await member.room.send(f"نورت الغرفة يا {member.name}! 🌹✨")

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    text = message.content.strip()

    if text.startswith("!شغل "):
        song_name = text.replace("!شغل ", "")
        await message.room.send(f"جاري البحث عن: {song_name} ⏳...")
        try:
            ydl_opts = {'format': 'bestaudio/best', 'noplaylist': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch:{song_name}", download=False)['entries']
                await message.room.set_music(info['url'])
                await message.room.send(f"يتم الآن تشغيل: {info['title']} 🎶")
        except Exception:
            await message.room.send("عذراً، لم أتمكن من تشغيل هذه الأغنية.")

    elif "بوت" in text:
        try:
            response = model.generate_content(f"المستخدم ({message.author.name}) يقول: {text}")
            if response.text:
                await message.room.send(response.text.strip())
        except Exception:
            pass

def run_web():
    app.run(host="0.0.0.0", port=8000)

threading.Thread(target=run_web, daemon=True).start()
client.run(USERNAME, PASSWORD)
