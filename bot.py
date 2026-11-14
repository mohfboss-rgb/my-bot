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

def clean_id(raw):
    v = str(raw).strip()
    if "room-" in v:
        v = v.split("room-")[-1].split("-")
    return v

rooms_db = {}
room_members = {}
custom_replies = {"هلا": "هلا بك منور الروم يا {user} 🌹"}

if DEFAULT_ROOM:
    r0 = clean_id(DEFAULT_ROOM)
    if r0:
        rooms_db[r0] = {
            "active": True, "dj": False, "host": "", "mods": [],
            "welcome": True, "wmsg": "🌟 Welcome {user}!",
            "shield": False, "song": "لا يوجد"
        }

state = {"ok": False, "log": "جاري الاتصال..."}

def yt_search(q):
    try:
        opts = {"format": "bestaudio", "noplaylist": True, "quiet": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(f"ytsearch1:{q}", download=False).get("entries", [])
            if res:
                return res.get("title", q), res.get("webpage_url", "")
    except Exception:
        pass
    return None, None

def ask_ai(p):
    if not ai_model:
        return "مفتاح الذكاء الاصطناعي غير مضاف."
    try:
        r = ai_model.generate_content("أنت بوت ذكي في IMVU. رد بالعربية باختصار: " + p)
        return r.text.strip()
    except Exception:
        return "حاول مرة أخرى."

def allowed(rid, user):
    cfg = rooms_db.get(rid)
    if not cfg or not cfg["active"]:
        return False
    if not cfg["dj"]:
        return True
    ok_list = [cfg["host"].lower()] + [m.lower() for m in cfg["mods"]]
    return user.lower() in ok_list

class BotClient:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "IMVU/9.12.0 (Android 13) okhttp/4.11.0",
            "Accept": "application/json",
            "Content-Type": "application/json"
        })
        self.cid = None
        self.sauce = None

    def login(self):
        if not BOT_USERNAME or not BOT_PASSWORD:
            state["log"] = "بيانات الحساب ناقصة في Render"
            return False
        try:
            payload = {"username": BOT_USERNAME, "password": BOT_PASSWORD}
            r = self.s.post("https://imvu.com", json=payload, timeout=15)
            if r.status_code == 429:
                state["log"] = "حظر مؤقت (429) - سينتظر 10 دقائق"
                return "429"
            if not r.text.strip().startswith("{"):
                state["log"] = f"رد غير متوقع ({r.status_code})"
                return False
            d = r.json()
            if d.get("status") == "success":
                u = d["denormalized"][d["id"]]["data"]
                self.cid, self.sauce = str(u["user"]["id"]), u["sauce"]
                state["ok"] = True
                state["log"] = f"متصل بالروم (CID: {self.cid})"
                return True
            state["log"] = d.get("message", "تحقق من الحساب")
            return False
        except Exception as e:
            state["log"] = f"خطأ: {e}"
            return False

    async def run(self):
        st = self.login()
        if st == "429":
            await asyncio.sleep(600)
            return
        if not st:
            return
        try:
            async with websockets.connect("wss://://imvu.com") as ws:
                auth = {"type": "imq_connect", "user_id": self.cid, "sauce": self.sauce}
                await ws.send(json.dumps(auth))
                await asyncio.sleep(1)
                joined = set()
                while True:
                    for rid, cfg in list(rooms_db.items()):
                        if cfg["active"] and rid not in joined:
                            ch = f"imvu:room:{rid}"
                            await ws.send(json.dumps({"type": "imq_join", "channel": ch}))
                            joined.add(rid)
                            room_members.setdefault(rid, {})
                            msg_hi = {"type": "imq_send", "channel": ch, "message": "🎵 البوت متصل!"}
                            await ws.send(json.dumps(msg_hi))
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    except asyncio.TimeoutError:
                        continue
                    msg = json.loads(raw)
                    mt = msg.get("type", "")
                    ch = msg.get("channel", "")
                    rid = ch.replace("imvu:room:", "") if ch.startswith("imvu:room:") else ""
                    uid = str(msg.get("user_id", ""))
                    uname = str(msg.get("username", uid))
                    if not rid or not uid or uid == self.cid:
                        continue
                    room_members.setdefault(rid, {})
                    cfg = rooms_db.get(rid, {})
                    if mt in ["imq_user_join", "imq_join"] and uid not in room_members[rid]:
                        room_members[rid][uid] = uname
                        if cfg.get("shield") and uname.lower().startswith("guest_"):
                            m = {"type": "imq_send", "channel": ch, "message": f"🛡️ حظر {uname}"}
                            await ws.send(json.dumps(m))
                            continue
                        if cfg.get("welcome"):
                            wt = cfg.get("wmsg", "Welcome {user}").replace("{user}", uname)
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": wt}))
                    elif mt in ["imq_user_leave", "imq_leave"]:
                        room_members[rid].pop(uid, None)
                    else:
                        room_members[rid][uid] = uname

                    txt = msg.get("message", "").strip()
                    if not txt:
                        continue
                    for k, v in custom_replies.items():
                        if k in txt:
                            rep = v.replace("{user}", uname)
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": rep}))
                            break
                    if not allowed(rid, uname):
                        continue
                    if txt.startswith("!play ") or txt.startswith("!شغل "):
                        q = txt.split(" ", 1).strip()
                        t, u = yt_search(q)
                        if t:
                            cfg["song"] = t
                            out = f"🎶 {t} | {u}"
                        else:
                            out = "❌ لم أجد الأغنية."
                        await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": out}))
                    elif txt.startswith("!stop") or txt.startswith("!وقف"):
                        cfg["song"] = "متوقف"
                        await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": "⏹️ تم الإيقاف"}))
                    elif txt.startswith("!بوت ") or txt.startswith("بوت "):
                        ans = ask_ai(txt.split(" ", 1).strip())
                        await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": ans}))
        except Exception:
            state["ok"] = False
            state["log"] = "إعادة الاتصال..."

def loop_worker():
    lp = asyncio.new_event_loop()
    asyncio.set_event_loop(lp)
    b = BotClient()
    while True:
        lp.run_until_complete(b.run())
        time.sleep(60)

threading.Thread(target=loop_worker, daemon=True).start()

PAGE = """<!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:Tahoma;background:#090d16;color:#fff;text-align:center;padding:10px}
.box{background:#131b2e;border:1px solid #1e293b;border-radius:14px;padding:15px;max-width:450px;margin:10px auto}
input,button{width:90%;padding:10px;margin:5px 0;border-radius:8px;border:none;background:#1e293b;color:#fff}
button{background:#2563eb;font-weight:bold}
.row{display:flex;justify-content:space-between;background:#0b101d;padding:8px;border-radius:8px;margin:5px 0}
</style></head><body>
<div class="box"><h2>🎵 لوحة تحكم البوت</h2><p>{{state.log}}</p>{% if msg %}<p style="color:#38bdf8">{{msg}}</p>{% endif %}</div>
<div class="box"><h3>🎛️ إعدادات الروم</h3><form method="POST" action="/save">
<input type="password" name="sec" placeholder="كلمة سر المالك" required>
<input type="text" name="rid" placeholder="رقم الروم" required>
<input type="text" name="host" placeholder="اسم الهوست">
<input type="text" name="mods" placeholder="المشرفين بفاصلة">
<input type="text" name="wmsg" value="🌟 Welcome {user}!">
<div class="row"><span>🛡️ حماية الوهمي</span><input type="checkbox" name="sh" style="width:auto"></div>
<div class="row"><span>🎧 DJ للمشرفين فقط</span><input type="checkbox" name="dj" style="width:auto"></div>
<div class="row"><span>👋 ترحيب تلقائي</span><input type="checkbox" name="wl" checked style="width:auto"></div>
<button>حفظ ودخول الروم</button></form></div>
{% for rid, cfg in rooms.items() %}<div class="box"><h3>👥 المتواجدون ({{rid}})</h3>
<p>🎶 {{cfg.song}}</p>{% for uid, un in members.get(rid, {}).items() %}
<div class="row"><span>{{un}} ({{uid}})</span><form method="POST" action="/kick" style="margin:0">
<input type="hidden" name="rid" value="{{rid}}"><input type="hidden" name="uid" value="{{uid}}">
<button style="background:#dc2626;padding:5px 10px;width:auto">طرد</button></form></div>
{% endfor %}</div>{% endfor %}
                
