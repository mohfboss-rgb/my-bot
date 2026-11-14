import os, json, time, asyncio, threading, requests, websockets
from flask import Flask, request, render_template_string
import google.generativeai as genai
import yt_dlp

app = Flask(__name__)
USER = os.environ.get("BOT_USERNAME", "")
PASS = os.environ.get("BOT_PASSWORD", "")
KEY = os.environ.get("GEMINI_API_KEY", "")
SEC = os.environ.get("ADMIN_SECRET", "12345")
DEF_R = os.environ.get("MY_ROOM_ID", "").split("room-")[-1].split("-")[0].strip()

if KEY:
    genai.configure(api_key=KEY)
    ai = genai.GenerativeModel("gemini-1.5-flash")
else:
    ai = None

rooms = {DEF_R: {"dj": False, "host": "", "mods": [], "song": "لا يوجد"}} if DEF_R else {}
members = {}
state = {"log": "جاري الاتصال..."}

def yt(q):
    try:
        with yt_dlp.YoutubeDL({"format": "bestaudio", "noplaylist": True, "quiet": True}) as y:
            e = y.extract_info(f"ytsearch1:{q}", download=False).get("entries", [])
            return (e[0]["title"], e[0]["webpage_url"]) if e else (None, None)
    except Exception:
        return None, None

class Bot:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "IMVU/9.12.0 (Android 13)", "Content-Type": "application/json"})

    def login(self):
        if not USER or not PASS:
            state["log"] = "بيانات الحساب ناقصة في Render"
            return None, None
        try:
            r = self.s.post("https://imvu.com", json={"username": USER, "password": PASS}, timeout=15)
            if r.status_code == 429:
                state["log"] = "حظر مؤقت 429 - سينتظر البوت 10 دقائق"
                return "429", None
            d = r.json()
            if d.get("status") == "success":
                u = d["denormalized"][d["id"]]["data"]
                state["log"] = f"متصل بنجاح! (ID: {u['user']['id']})"
                return str(u["user"]["id"]), u["sauce"]
            state["log"] = d.get("message", "خطأ في بيانات الحساب")
        except Exception as e:
            state["log"] = f"خطأ: {e}"
        return None, None

    async def run(self):
        while True:
            cid, sauce = self.login()
            if cid == "429":
                await asyncio.sleep(600)
                continue
            if not cid:
                await asyncio.sleep(60)
                continue
            try:
                async with websockets.connect("wss://://imvu.com") as ws:
                    await ws.send(json.dumps({"type": "imq_connect", "user_id": cid, "sauce": sauce}))
                    await asyncio.sleep(1)
                    joined = set()
                    while True:
                        for rid, cfg in list(rooms.items()):
                            if rid not in joined:
                                await ws.send(json.dumps({"type": "imq_join", "channel": f"imvu:room:{rid}"}))
                                joined.add(rid)
                                members.setdefault(rid, {})
                                await ws.send(json.dumps({"type": "imq_send", "channel": f"imvu:room:{rid}", "message": "🎵 البوت متصل!"}))
                        try:
                            m = json.loads(await asyncio.wait_for(ws.recv(), timeout=3.0))
                        except asyncio.TimeoutError:
                            continue
                        ch, uid = m.get("channel", ""), str(m.get("user_id", ""))
                        rid = ch.replace("imvu:room:", "") if ch.startswith("imvu:room:") else ""
                        uname = str(m.get("username", uid))
                        if not rid or not uid or uid == cid:
                            continue
                        members.setdefault(rid, {})[uid] = uname
                        if m.get("type") in ["imq_user_join", "imq_join"]:
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": f"🌟 Welcome {uname}!"}))
                        txt = m.get("message", "").strip()
                        cfg = rooms.get(rid, {})
                        if not txt or (cfg.get("dj") and uname.lower() not in [cfg.get("host", "").lower()] + cfg.get("mods", [])):
                            continue
                        if txt.startswith(("!play ", "!شغل ")):
                            t, u = yt(txt.split(" ", 1)[1])
                            cfg["song"] = t or cfg["song"]
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": f"🎶 {t} | {u}" if t else "❌ لم أجدها"}))
                        elif txt.startswith(("!بوت ", "بوت ")) and ai:
                            ans = ai.generate_content("رد بالعربية باختصار: " + txt.split(" ", 1)[1]).text.strip()
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": ans}))
            except Exception:
                state["log"] = "إعادة الاتصال..."
                await asyncio.sleep(30)

threading.Thread(target=lambda: asyncio.run(Bot().run()), daemon=True).start()

UI = """<!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font-family:Tahoma;background:#090d16;color:#fff;text-align:center;padding:10px}
.b{background:#131b2e;padding:15px;border-radius:12px;max-width:420px;margin:10px auto}
input,button{width:90%;padding:10px;margin:5px 0;border-radius:8px;border:none;background:#1e293b;color:#fff}
button{background:#2563eb;font-weight:bold}</style></head><body>
<div class="b"><h2>🎵 لوحة البوت</h2><p>{{state.log}}</p>{% if msg %}<p style="color:#38bdf8">{{msg}}</p>{% endif %}</div>
<div class="b"><form method="POST" action="/add">
<input type="password" name="s" placeholder="كلمة سر المالك" required>
<input type="text" name="r" placeholder="رقم الروم" required>
<input type="text" name="h" placeholder="اسم الهوست">
<input type="text" name="m" placeholder="المشرفين بفاصلة">
<label><input type="checkbox" name="dj" style="width:auto"> وضع VIP (للمشرفين فقط)</label>
<button>تفعيل ودخول الروم</button></form></div>
{% for r, c in rooms.items() %}<div class="b"><h3>👥 المتواجدون ({{r}})</h3><p>🎶 {{c.song}}</p>
{% for u, n in members.get(r, {}).items() %}<p>{{n}} ({{u}})</p>{% endfor %}</div>{% endfor %}</body></html>"""

@app.route("/")
def index():
    return render_template_string(UI, state=state, rooms=rooms, members=members, msg=None)

@app.route("/add", methods=["POST"])
def add():
    if request.form.get("s") != SEC:
        return render_template_string(UI, state=state, rooms=rooms, members=members, msg="⛔ كلمة سر خاطئة")
    r = request.form.get("r", "").split("room-")[-1].split("-")[0].strip()
    if r:
        rooms[r] = {"dj": "dj" in request.form, "host": request.form.get("h", "").strip(), "mods": [x.strip().lower() for x in request.form.get("m", "").split(",") if x.strip()], "song": "لا يوجد"}
    return render_template_string(UI, state=state, rooms=rooms, members=members, msg=f"✅ تم تفعيل {r}")

@app.route("/ping")
def ping():
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
