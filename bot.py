import os, json, time, asyncio, threading, requests, websockets
from flask import Flask, request, render_template
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

rooms = {DEF_R: {"dj": False, "shield": False, "host": "", "oid": "", "mods": [], "song": "لا يوجد", "q": []}} if DEF_R else {}
members = {}
state = {"log": "جاري الاتصال...", "welcome": "🌟 !Welcome {user} to the room"}

def yt(q):
    try:
        with yt_dlp.YoutubeDL({"format": "bestaudio", "noplaylist": True, "quiet": True}) as y:
            e = y.extract_info(f"ytsearch1:{q}", download=False).get("entries", [])
            return (e[0]["title"], e[0]["webpage_url"]) if e else (None, None)
    except Exception:
        return None, None

def ask_smart_ai(uname, text):
    if not ai:
        return "مفتاح الذكاء الاصطناعي غير مفعل حالياً."
    try:
        prompt = (
            f"أنت بوت ذكي، خفيف الظل، وودود جداً داخل غرفة دردشة في لعبة IMVU. "
            f"اللاعب ({uname}) يقول لك: '{text}'. "
            f"رد عليه باللهجة العربية المحببة وبذكاء ولباقة (في سطر أو سطرين كحد أقصى ليناسب شات اللعبة):"
        )
        return ai.generate_content(prompt).text.strip()
    except Exception:
        return "تسلم يا غالي! 🌹"

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
                state["log"] = f"متصل وجاهز بالروم (CID: {u['user']['id']})"
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
                                if cfg.get("oid"):
                                    try:
                                        self.s.post(f"https://imvu.com{cid}/friends", json={"id": f"https://imvu.com{cfg['oid']}"})
                                    except Exception:
                                        pass
                                await ws.send(json.dumps({"type": "imq_send", "channel": f"imvu:room:{rid}", "message": "🎵 البوت الذكي متصل وجاهز!"}))
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
                        cfg = rooms.get(rid, {})
                        if m.get("type") in ["imq_user_join", "imq_join"]:
                            if cfg.get("shield") and uname.lower().startswith("guest_"):
                                await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": f"🛡️ حظر الوهمي {uname}"}))
                                continue
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": state["welcome"].replace("{user}", uname)}))
                        txt = m.get("message", "").strip()
                        if not txt:
                            continue

                        if txt.startswith(("!play ", "!شغل ")):
                            if cfg.get("dj") and uname.lower() not in [cfg.get("host", "").lower()] + cfg.get("mods", []):
                                continue
                            t, u = yt(txt.split(" ", 1)[1])
                            if t:
                                cfg["song"] = t
                                cfg.setdefault("q", []).append(t)
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": f"🎶 {t} | {u}" if t else "❌ لم أجدها"}))
                        elif txt in ["!next", "!تخطي"] and len(cfg.get("q", [])) > 1:
                            cfg["q"].pop(0)
                            cfg["song"] = cfg["q"][0]
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": f"⏭️ التالي: {cfg['song']}"}))
                        elif txt in ["!queue", "!انتظار"]:
                            ql = " | ".join(cfg.get("q", [])[:5]) or "فارغة"
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": f"📜 الانتظار: {ql}"}))
                        elif txt in ["!stop", "!وقف"]:
                            cfg["song"] = "متوقف"
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": "⏹️ تم الإيقاف"}))
                        elif txt.startswith(("!hug", "!kiss")):
                            tg = txt.split(" ", 1)[1] if " " in txt else "الجميع"
                            ac = "حضن دافئ لـ" if txt.startswith("!hug") else "قبلة لـ"
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": f"💖 {uname} أرسل {ac} {tg}!"}))
                        elif any(w in txt.lower() for w in ["بوت", "bot", "؟", "?"]):
                            ans = ask_smart_ai(uname, txt)
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": ans}))
            except Exception:
                state["log"] = "إعادة الاتصال..."
                await asyncio.sleep(30)

threading.Thread(target=lambda: asyncio.run(Bot().run()), daemon=True).start()

@app.route("/")
def index():
    return render_template("index.html", state=state, rooms=rooms, members=members, msg=None)

@app.route("/add", methods=["POST"])
def add():
    if request.form.get("s") != SEC:
        return render_template("index.html", state=state, rooms=rooms, members=members, msg="⛔ كلمة سر خاطئة")
    r = request.form.get("r", "").split("room-")[-1].split("-")[0].strip()
    if r:
        rooms[r] = {"dj": "dj" in request.form, "shield": "shield" in request.form, "oid": request.form.get("oid", "").strip(), "host": request.form.get("h", "").strip(), "mods": [x.strip().lower() for x in request.form.get("m", "").split(",") if x.strip()], "song": "لا يوجد", "q": []}
    return render_template("index.html", state=state, rooms=rooms, members=members, msg=f"✅ تم تفعيل الروم {r}")

@app.route("/welcome", methods=["POST"])
def welcome():
    if request.form.get("s") != SEC:
        return render_template("index.html", state=state, rooms=rooms, members=members, msg="⛔ كلمة سر خاطئة")
    state["welcome"] = request.form.get("w", state["welcome"])
    return render_template("index.html", state=state, rooms=rooms, members=members, msg="✅ تم حفظ الترحيب")

@app.route("/kick", methods=["POST"])
def kick():
    r, u = request.form.get("r", ""), request.form.get("u", "")
    if r in members:
        members[r].pop(u, None)
    return render_template("index.html", state=state, rooms=rooms, members=members, msg="تم إرسال الطرد")

@app.route("/ping")
def ping():
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
            
