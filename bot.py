import os, json, time, asyncio, threading, requests, websockets
from flask import Flask, request, render_template
import yt_dlp

app = Flask(__name__)
USER = os.environ.get("BOT_USERNAME", "")
PASS = os.environ.get("BOT_PASSWORD", "")
KEY = os.environ.get("GEMINI_API_KEY", "")
SEC = os.environ.get("ADMIN_SECRET", "12345")

LOGIN_URL = "https://imvu.com"
WS_URL = "wss://://imvu.com"
API_BASE = "https://imvu.com"
DEF_R = os.environ.get("MY_ROOM_ID", "").split("room-")[-1].strip()

rooms = {DEF_R: {"dj": False, "shield": False, "host": "", "oid": "", "mods": [], "song": "لا يوجد", "q": []}} if DEF_R else {}
members = {}
state = {"log": "جاري الاتصال بالسيرفر...", "welcome": "✨ Welcome {user} to the room"}

def yt(q):
    try:
        with yt_dlp.YoutubeDL({"format": "bestaudio", "noplaylist": True, "quiet": True}) as y:
            e = y.extract_info(f"ytsearch1:{q}", download=False).get("entries", [])
            return (e[0]["title"], e[0]["webpage_url"]) if e else (None, None)
    except Exception:
        return None, None

def ask_smart_ai(uname, text):
    if not KEY:
        return "أهلاً بك يا غالي! 🌹"
    try:
        url = f"https://googleapis.com{KEY}"
        payload = {"contents": [{"parts": [{"text": f"أنت بوت موسيقى مرح في غرفة IMVU. اللاعب {uname} يقول: '{text}'. رد بالعربية باختصار ولباقة (سطرين كحد أقصى)."}]}]}
        r = requests.post(url, json=payload, timeout=10)
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return "تسلم يا غالي! 🌹"

class Bot:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "IMVU/9.12.0 (Android 13; SM-S918B) okhttp/4.11.0",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-IMVU-Application": "imvu_mobile_android"
        })

    def login(self):
        if not USER or not PASS:
            state["log"] = "بيانات الحساب ناقصة في Render"
            return None, None
        try:
            r = self.s.post(LOGIN_URL, json={"username": USER, "password": PASS}, timeout=15)
            if r.status_code == 429:
                state["log"] = "حظر مؤقت 429 - سينتظر البوت 10 دقائق تلقائياً"
                return "429", None
            if not r.text.strip().startswith("{"):
                state["log"] = f"حماية السيرفر (كود {r.status_code}) - سيحاول البوت تلقائياً"
                return None, None
            d = r.json()
            if d.get("status") == "success":
                u = d["denormalized"][d["id"]]["data"]
                cid = str(u["user"]["id"])
                state["log"] = f"متصل وجاهز بالروم (CID: {cid})"
                return cid, u["sauce"]
            state["log"] = d.get("message", "تحقق من اسم المستخدم وكلمة المرور")
        except Exception as e:
            state["log"] = f"خطأ اتصال: {e}"
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
                async with websockets.connect(WS_URL) as ws:
                    await ws.send(json.dumps({"type": "imq_connect", "user_id": cid, "sauce": sauce}))
                    await asyncio.sleep(1)
                    joined = set()
                    while True:
                        for old_r in list(joined):
                            if old_r not in rooms:
                                await ws.send(json.dumps({"type": "imq_leave", "channel": f"imvu:room:{old_r}"}))
                                joined.remove(old_r)
                                members.pop(old_r, None)

                        for rid, cfg in list(rooms.items()):
                            if rid not in joined:
                                await ws.send(json.dumps({"type": "imq_join", "channel": f"imvu:room:{rid}"}))
                                joined.add(rid)
                                members.setdefault(rid, {})
                                if cfg.get("oid"):
                                    try:
                                        self.s.post(f"{API_BASE}/user/user-{cid}/friends", json={"id": f"{API_BASE}/user/user-{cfg['oid']}"}, timeout=10)
                                    except Exception:
                                        pass
                                await ws.send(json.dumps({"type": "imq_send", "channel": f"imvu:room:{rid}", "message": "🎵 تم تفعيل بوت الموسيقى بنجاح!"}))

                        try:
                            m = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
                        except asyncio.TimeoutError:
                            continue

                        ch = m.get("channel", "")
                        uid = str(m.get("user_id", ""))
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

                        is_admin = uname.lower() in [cfg.get("host", "").lower()] + [x.lower() for x in cfg.get("mods", [])]

                        if txt in ["بوت اخرج", "!leave", "اخرج"] and is_admin:
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": "👋 جاري المغادرة بطلب من الهوست..."}))
                            await ws.send(json.dumps({"type": "imq_leave", "channel": ch}))
                            rooms.pop(rid, None)
                            joined.discard(rid)
                            continue

                        if txt.startswith(("!play ", "شغل ")):
                            if cfg.get("dj") and not is_admin:
                                continue
                            q_name = txt.split(" ", 1)[1]
                            t, u = yt(q_name)
                            if t:
                                cfg["song"] = t
                                cfg.setdefault("q", []).append(t)
                                await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": f"🎵 {t} | {u}"}))
                        elif txt in ["!next", "تخطي"] and len(cfg.get("q", [])) > 1:
                            cfg["q"].pop(0)
                            cfg["song"] = cfg["q"][0]
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": f"⏭️ التالي: {cfg['song']}"}))
                        elif txt in ["!queue", "الانتظار"]:
                            ql = " | ".join(cfg.get("q", [])[:5]) or "فارغة"
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": f"📜 الانتظار: {ql}"}))
                        elif txt in ["!stop", "وقف"]:
                            cfg["song"] = "متوقف"
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": "⏹️ تم الإيقاف"}))
                        elif txt.startswith(("!hug", "!kiss")):
                            tg = txt.split(" ", 1)[1] if " " in txt else "الجميع"
                            ac = "حضن دافئ لـ" if txt.startswith("!hug") else "قبلة لـ"
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": f"❤️ {uname} أرسل {ac} {tg}"}))
                        elif any(w in txt.lower() for w in ["بوت", "bot", "؟", "?"]):
                            ans = ask_smart_ai(uname, txt)
                            await ws.send(json.dumps({"type": "imq_send", "channel": ch, "message": ans}))
            except Exception as e:
                state["log"] = f"إعادة الاتصال... ({e})"
                await asyncio.sleep(30)

def start_bg():
    asyncio.run(Bot().run())

t = threading.Thread(target=start_bg, daemon=True)
t.start()

@app.route("/")
def index():
    return render_template("index.html", state=state, rooms=rooms, members=members, msg=None)

@app.route("/add", methods=["POST"])
def add():
    if request.form.get("s") != SEC:
        return render_template("index.html", state=state, rooms=rooms, members=members, msg="❌ كلمة السر خطأ")
    r = request.form.get("r", "").split("room-")[-1].strip()
    if r:
        rooms.clear()
        rooms[r] = {
            "dj": "dj" in request.form,
            "shield": "shield" in request.form,
            "oid": request.form.get("oid", "").strip(),
            "host": request.form.get("host", "").strip(),
            "mods": [m.strip() for m in request.form.get("mods", "").split(",") if m.strip()],
            "song": "لا يوجد",
            "q": []
        }
    return render_template("index.html", state=state, rooms=rooms, members=members, msg=f"✅ تم تفعيل الروم {r}")

@app.route("/welcome", methods=["POST"])
def welcome():
    if request.form.get("s") != SEC:
        return render_template("index.html", state=state, rooms=rooms, members=members, msg="❌ كلمة سر خاطئة")
    state["welcome"] = request.form.get("w", state["welcome"])
    return render_template("index.html", state=state, rooms=rooms, members=members, msg="✅ تم التحديث")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)

