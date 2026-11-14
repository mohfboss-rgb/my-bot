import os, json, time, asyncio, threading, requests, websockets
from flask import Flask, request, render_template_string
import google.generativeai as genai
import yt_dlp

app = Flask(__name__)

BOT_USERNAME = os.environ.get("BOT_USERNAME", "")
BOT_PASSWORD = os.environ.get("BOT_PASSWORD", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "12345")
DEFAULT_ROOM = os.environ.get("MY_ROOM_ID", "")

ai_model = None
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    ai_model = genai.GenerativeModel("gemini-1.5-flash")

def clean_room_id(raw_id):
    val = str(raw_id).strip()
    if "room-" in val:
        val = val.split("room-")[-1].split("-")
    return val

vip_rooms = {}
active_rooms = set()
if DEFAULT_ROOM:
    r_clean = clean_room_id(DEFAULT_ROOM)
    if r_clean:
        active_rooms.add(r_clean)

bot_state = {"logged_in": False, "log": "جاري الاتصال كـ تطبيق موبايل...", "current_song": "لا يوجد", "connected_rooms": []}

def search_youtube_song(query):
    try:
        with yt_dlp.YoutubeDL({"format": "bestaudio", "noplaylist": True, "quiet": True}) as ydl:
            entries = ydl.extract_info(f"ytsearch1:{query}", download=False).get("entries", [])
            if entries:
                return entries.get("title", query), entries.get("webpage_url", "")
    except Exception:
        pass
    return None, None

def ask_gemini(prompt):
    if not ai_model:
        return "مفتاح الذكاء الاصطناعي غير مضاف."
    try:
        res = ai_model.generate_content("أنت بوت ذكي وممتع في غرفة IMVU. رد بالعربية باختصار ولباقة: " + prompt)
        return res.text.strip()
    except Exception:
        return "حاول مرة أخرى بعد قليل."

def can_use_bot(room_id, sender_name):
    sub = vip_rooms.get(str(room_id))
    if not sub or not sub.get("active"):
        return True
    allowed = [sub["host"].lower()] + [m.lower() for m in sub["mods"]]
    return sender_name.lower() in allowed

class MobileIMVUBot:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "IMVU/9.12.0 (Android 13; SM-S918B) okhttp/4.11.0",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-IMVU-Application": "imvu_mobile_android"
        })
        self.cid = None
        self.sauce = None

    def login(self):
        if not BOT_USERNAME or not BOT_PASSWORD:
            bot_state["log"] = "بيانات الحساب ناقصة في Render"
            return False
        try:
            payload = {
                "username": BOT_USERNAME,
                "password": BOT_PASSWORD,
                "gdpr_cookie_consent": True
            }
            resp = self.session.post("https://imvu.com", json=payload, timeout=15)
            if not resp.text.strip().startswith("{"):
                bot_state["log"] = f"رد غير متوقع من السيرفر (كود {resp.status_code})"
                return False
            data = resp.json()
            if data.get("status") == "success":
                u = data["denormalized"][data["id"]]["data"]
                self.cid = u["user"]["id"]
                self.sauce = u["sauce"]
                bot_state["logged_in"] = True
                bot_state["log"] = f"متصل بنجاح! (ID: {self.cid})"
                return True
            bot_state["log"] = f"رسالة اللعبة: {data.get('message', 'تحقق من الاسم وكلمة المرور')}"
            return False
        except Exception as e:
            bot_state["log"] = f"خطأ اتصال: {e}"
            return False

    async def run_ws(self):
        if not self.login():
            return
        try:
            async with websockets.connect("wss://://imvu.com") as ws:
                await ws.send(json.dumps({"type": "imq_connect", "user_id": str(self.cid), "sauce": self.sauce}))
                await asyncio.sleep(1)
                joined = set()
                while True:
                    for r_id in list(active_rooms):
                        if r_id not in joined:
                            ch = f"imvu:room:{r_id}"
                            await ws.send(json.dumps({"type": "imq_join", "channel": ch}))
                            joined.add(r_id)
                            bot_state["connected_rooms"] = list(joined)
                            mode_msg = "👑 وضع VIP (للهوست والمشرفين)" if vip_rooms.get(r_id, {}).get("active") else "🎉 وضع عام (مفتوح للكل)"
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": f"🤖 تم تفعيل البوت الذكي! {mode_msg}"}))
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
                    if not can_use_bot(room_id, sender_name):
                        continue
                    if text.startswith("!شغل ") or text.startswith("!play "):
                        q = text.split(" ", 1).strip()
                        title, link = search_youtube_song(q)
                        reply = f"🎶 {title} | {link}" if title else "❌ لم أجد الأغنية."
                        if title:
                            bot_state["current_song"] = title
                        await ws.send(json.dumps({"type": "imq_send", "channel": channel, "message": reply}))
                    elif text.startswith("!بوت ") or text.startswith("بوت "):
                        ai_ans = ask_gemini(text.split(" ", 1).strip())
                        await ws.send(json.dumps({"type": "imq_send", "channel": channel, "message": ai_ans}))
        except Exception:
            bot_state["logged_in"] = False
            bot_state["connected_rooms"] = []
            bot_state["log"] = "إعادة محاولة الاتصال..."

def worker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot = MobileIMVUBot()
    while True:
        loop.run_until_complete(bot.run_ws())
        time.sleep(15)

threading.Thread(target=worker, daemon=True).start()

HTML = """<!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>بوت IMVU</title><style>body{font-family:Tahoma;background:#0f172a;color:#fff;text-align:center;padding:15px}.box{background:#1e293b;padding:15px;border-radius:10px;max-width:450px;margin:10px auto}input,button{width:90%;padding:10px;margin:5px 0;border-radius:6px;border:none}input{background:#334155;color:#fff}button{background:#2563eb;color:#fff;font-weight:bold}</style></head><body><div class="box"><h2>🤖 لوحة البوت الذكي</h2><p>الحالة: <b>{{state.log}}</b></p><p>الغرف: <b>{{state.connected_rooms|join(', ') or 'لا يوجد'}}</b></p>{% if msg %}<p style="color:#38bdf8">{{msg}}</p>{% endif %}</div><div class="box"><h3>إدارة الغرف والاشتراكات</h3><form method="POST" action="/sub"><input type="password" name="sec" placeholder="كلمة سر المالك" required><input type="text" name="rid" placeholder="رقم الروم" required><input type="text" name="host" placeholder="اسم الهوست (اتركه فارغاً ليبقى للكل)"><input type="text" name="mods" placeholder="المشرفين بفاصلة (للاشتراك الخاص)"><button name="act" value="vip">تفعيل اشتراك VIP (للهوست والمشرفين)</button><button name="act" value="free" style="background:#16a34a">إدخال البوت مجاناً (مفتوح للكل)</button><button name="act" value="del" style="background:#dc2626">إلغاء الاشتراك (يعود للكل)</button></form></div></body></html>"""

@app.route("/")
def index():
    return render_template_string(HTML, state=bot_state, msg=None)

@app.route("/sub", methods=["POST"])
def sub():
    if request.form.get("sec") != ADMIN_SECRET:
        return render_template_string(HTML, state=bot_state, msg="⛔ كلمة سر خاطئة!")
    rid = clean_room_id(request.form.get("rid", ""))
    act = request.form.get("act")
    if act == "vip" and rid:
        active_rooms.add(rid)
        mods = [m.strip() for m in request.form.get("mods", "").split(",") if m.strip()]
        vip_rooms[rid] = {"host": request.form.get("host", "").strip(), "mods": mods, "active": True}
        m = f"👑 تم تفعيل اشتراك VIP للروم {rid} (للهوست والمشرفين فقط)"
    elif act == "free" and rid:
        active_rooms.add(rid)
        vip_rooms.pop(rid, None)
        m = f"🎉 تم إدخال البوت للروم {rid} بوضع مفتوح للكل"
    else:
        vip_rooms.pop(rid, None)
        m = f"🔓 تم إلغاء اشتراك VIP للروم {rid} وعاد مفتوحاً للكل"
    return render_template_string(HTML, state=bot_state, msg=m)

@app.route("/ping")
def ping():
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
