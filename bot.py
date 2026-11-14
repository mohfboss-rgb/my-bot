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
        val = val.split("room-")[-1].split("-")[0]
    return val

# إعدادات الغرف والمميزات
rooms_db = {}
room_members = {}
song_queues = {}
custom_replies = {"هلا": "هلا بك منور الروم يا {user} 🌹"}

if DEFAULT_ROOM:
    r0 = clean_room_id(DEFAULT_ROOM)
    if r0:
        rooms_db[r0] = {
            "active": True, "dj_only": False, "host": "", "mods": [],
            "welcome_on": True, "welcome_msg": "🌟 Welcome {user} to the room!",
            "shield_on": False, "current_song": "لا يوجد"
        }

bot_state = {"logged_in": False, "log": "جاري الاتصال بالسيرفر...", "cid": ""}

def search_yt(query, limit=1):
    try:
        with yt_dlp.YoutubeDL({"format": "bestaudio", "noplaylist": True, "quiet": True}) as ydl:
            entries = ydl.extract_info(f"ytsearch{limit}:{query}", download=False).get("entries", [])
            return [{"title": e.get("title", ""), "url": e.get("webpage_url", "")} for e in entries if e]
    except Exception:
        return []

def ask_gemini(prompt):
    if not ai_model:
        return "مفتاح الذكاء الاصطناعي غير مضاف."
    try:
        res = ai_model.generate_content("أنت بوت موسيقى ومشرف ذكي في IMVU. رد بالعربية باختصار ولباقة: " + prompt)
        return res.text.strip()
    except Exception:
        return "حاول مرة أخرى بعد قليل."

def is_allowed(rid, sender):
    cfg = rooms_db.get(rid)
    if not cfg or not cfg["active"]:
        return False
    if not cfg["dj_only"]:
        return True
    allowed = [cfg["host"].lower()] + [m.lower() for m in cfg["mods"]]
    return sender.lower() in allowed

class ProIMVUBot:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "IMVU/9.12.0 (Android 13; SM-S918B) okhttp/4.11.0",
            "Accept": "application/json", "Content-Type": "application/json"
        })
        self.cid = None
        self.sauce = None

    def login(self):
        if not BOT_USERNAME or not BOT_PASSWORD:
            bot_state["log"] = "بيانات الحساب ناقصة في Render"
            return False
        try:
            resp = self.session.post("https://imvu.com", json={"username": BOT_USERNAME, "password": BOT_PASSWORD}, timeout=15)
            if resp.status_code == 429:
                bot_state["log"] = "حظر مؤقت (429) - سينتظر البوت 10 دقائق تلقائياً"
                return "429"
            if not resp.text.strip().startswith("{"):
                bot_state["log"] = f"رد غير متوقع ({resp.status_code})"
                return False
            data = resp.json()
            if data.get("status") == "success":
                u = data["denormalized"][data["id"]]["data"]
                self.cid, self.sauce = str(u["user"]["id"]), u["sauce"]
                bot_state["logged_in"], bot_state["cid"] = True, self.cid
                bot_state["log"] = f"متصل وجاهز بالروم (CID: {self.cid})"
                return True
            bot_state["log"] = f"رسالة اللعبة: {data.get('message', 'تحقق من الحساب')}"
            return False
        except Exception as e:
            bot_state["log"] = f"خطأ اتصال: {e}"
            return False

    async def run_ws(self):
        st = self.login()
        if st == "429":
            await asyncio.sleep(600)
            return
        if not st:
            return
        try:
            async with websockets.connect("wss://://imvu.com") as ws:
                await ws.send(json.dumps({"type": "imq_connect", "user_id": self.cid, "sauce": self.sauce}))
                await asyncio.sleep(1)
                joined = set()
                while True:
                    for rid, cfg in list(rooms_db.items()):
                        if cfg["active"] and rid not in joined:
                            ch = f"imvu:room:{rid}"
                            await ws.send(json.dumps({"type": "imq_join", "channel": ch}))
                            joined.add(rid)
                            room_members.setdefault(rid, {})
                            song_queues.setdefault(rid, [])
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": "🎵 تم تفعيل البوت الذكي بنجاح!"}))
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    except asyncio.TimeoutError:
                        continue
                    msg = json.loads(raw)
                    mtype = msg.get("type", "")
                    ch = msg.get("channel", "")
                    rid = ch.replace("imvu:room:", "") if ch.startswith("imvu:room:") else ""
                    uid = str(msg.get("user_id", ""))
                    uname = str(msg.get("username", uid))
                    if not rid or not uid or uid == self.cid:
                        continue

                    room_members.setdefault(rid, {})
                    cfg = rooms_db.get(rid, {})

                    # رصد الدخول والخروج والترحيب التلقائي
                    if mtype in ["imq_user_join", "imq_join"] and uid not in room_members[rid]:
                        room_members[rid][uid] = uname
                        if cfg.get("shield_on") and uname.lower().startswith("guest_"):
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": f"🛡️ تم حظر الحساب الوهمي {uname}"}))
                            continue
                        if cfg.get("welcome_on"):
                            w_txt = cfg.get("welcome_msg", "Welcome {user}").replace("{user}", uname)
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": w_txt}))
                    elif mtype in ["imq_user_leave", "imq_leave"]:
                        room_members[rid].pop(uid, None)
                    else:
                        room_members[rid][uid] = uname

                    text = msg.get("message", "").strip()
                    if not text:
                        continue

                    # الردود التلقائية المخصصة
                    for trigger, rep in custom_replies.items():
                        if trigger in text:
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": rep.replace("{user}", uname)}))
                            break

                    if not is_allowed(rid, uname):
                        continue

                    # أوامر الموسيقى والذكاء الاصطناعي
                    if text.startswith("!play ") or text.startswith("!شغل "):
                        q = text.split(" ", 1)[1].strip()
                        res = search_yt(q, 1)
                        if res:
                            song = res[0]
                            cfg["current_song"] = song["title"]
                            song_queues[rid].append(song["title"])
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": f"🎶 تعمل الآن: {song['title']} | {song['url']}"}))
                        else:
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": "❌ لم أجد الأغنية."}))
                    elif text in ["!stop", "!وقف"]:
                        cfg["current_song"] = "متوقف"
                        await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": "⏹️ تم إيقاف الموسيقى."}))
                    elif text in ["!next", "!تخطي"]:
                        if len(song_queues[rid]) > 1:
                            song_queues[rid].pop(0)
                            cfg["current_song"] = song_queues[rid][0]
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": f"⏭️ التالي: {cfg['current_song']}"}))
                    elif text in ["!queue", "!انتظار"]:
                        q_list = " | ".join(song_queues[rid][:5]) or "القائمة فارغة"
                        await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": f"📜 الانتظار: {q_list}"}))
                    elif text.startswith("!بوت ") or text.startswith("بوت "):
                        ans = ask_gemini(text.split(" ", 1)[1].strip())
                        await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": ans}))
        except Exception:
            bot_state["logged_in"] = False
            bot_state["log"] = "إعادة محاولة الاتصال..."

def worker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot = ProIMVUBot()
    while True:
        loop.run_until_complete(bot.run_ws())
        time.sleep(60)

threading.Thread(target=worker, daemon=True).start()

HTML = """<!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>لوحة تحكم البوت</title>
<style>
body{font-family:Tahoma,sans-serif;background:#090d16;color:#f1f5f9;margin:0;padding:12px;text-align:center}
.card{background:linear-gradient(145deg,#131b2e,#0f1626);border:1px solid #1e293b;border-radius:16px;padding:16px;max-width:460px;margin:12px auto;box-shadow:0 8px 20px rgba(0,0,0,.4)}
.badge{display:inline-block;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:bold;background:#064e3b;color:#34d399}
.badge.off{background:#450a0a;color:#f87171}
              
