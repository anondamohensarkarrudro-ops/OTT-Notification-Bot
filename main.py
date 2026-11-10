"""
OTT বাংলা নোটিফায়ার বট — v8  (ZEE5 + SonyLIV + JioHotstar • প্রোমো/স্পয়লার • Replit-রেডি)

Render-এ চালানোর নিয়ম (নিচে Replit-এর মতোই Environment Variables-এ BOT_TOKEN দিন):
  1) এই ফাইলটা main.py নামে রাখুন
  2) বাঁদিকের 🔒 Secrets-এ BOT_TOKEN বসান (কোডে টোকেন লিখবেন না)
     দরকার হলে PROXY_URL ও OWNER_ID ও Secrets-এ দিতে পারেন
  3) Run চাপুন (requests লাইব্রেরি Replit নিজেই ইনস্টল করে নেয়)

কমান্ড: /start /latest /shows /settings /notify /status /help
অ্যাডমিনের জন্য: /add /remove /test /extras /restart
          (বটে সরাসরি ZEE5/SonyLIV সিরিয়ালের লিংক পাঠালেও সিরিয়াল যোগ হয়ে যাবে)
"""

import base64
import hashlib
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, urljoin, urlparse, urlunparse

import requests
from requests.adapters import HTTPAdapter

# ======================= শুধু এই অংশ বদলান =======================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()          # Replit Secrets থেকে আসবে
OWNER_ID = int(os.getenv("OWNER_ID", "8032210356"))      # আপনার Telegram ID

# সিরিয়ালের লিংক এখানে দিন (প্রতিটা আলাদা লাইনে, শেষে কমা)।
# নতুন সিরিয়াল চাইলে বটে লিংক পাঠিয়েও যোগ করা যায় — কোড খুলতে হবে না।
SHOW_LINKS = [
    "https://www.zee5.com/tv-shows/details/sashuri-boumar-rannaghar/0-6-4z5990769",
    "https://www.zee5.com/tv-shows/details/kamala-nibas/0-6-4z5906917",
    "https://www.sonyliv.com/shows/bade-achhe-lagte-hai-bengali-1790007692",
    "https://www.sonyliv.com/shows/kailasher-mahagatha-1790007852",
    # "https://www.zee5.com/tv-shows/details/নাম/0-6-xxxxxxxx",
    # "https://www.sonyliv.com/shows/নাম-1790000000",
]

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "5"))  # কত সেকেন্ড পরপর চেক (কম = ফাস্ট, ব্লকের ঝুঁকি বেশি)
WORKERS = 12                                              # একসাথে কয়টা শো চেক হবে
PROXY_URL = os.getenv("PROXY_URL", "")                    # ZEE5 ব্লক করলে ইন্ডিয়ান প্রক্সি, নইলে ফাঁকা
TZ_HOURS = float(os.getenv("TZ_HOURS", "6"))              # সময় দেখানোর জন্য: বাংলাদেশ = 6, ভারত = 5.5
HASHTAGS = "#NewEpisode #{platform} #AnandoBots"
BRAND = "OTTNotification Bot"
STATE_FILE = "state.json"
PAGE_SIZE = 8                                             # সিরিয়াল তালিকার প্রতি পেজে কয়টা
KEEPALIVE_PORT = int(os.getenv("PORT", "8080"))           # Replit-এর জন্য ছোট ওয়েব সার্ভার
ADMIN_IDS = {OWNER_ID} | {int(x) for x in re.findall(r"\d+", os.getenv("ADMIN_IDS", ""))}   # এক্সট্রা অ্যাডমিন চাইলে Secrets-এ ADMIN_IDS (কমা দিয়ে)
EXTRAS_INTERVAL = int(os.getenv("EXTRAS_INTERVAL", "120"))   # প্রোমো/স্পয়লার কত সেকেন্ড পরপর চেক হবে
SPOILER_WORDS = ("spoiler", "sneak peek", "sneak-peek")      # এই শব্দ থাকলে "এপিসোড স্পয়লার" ধরা হবে
PROMO_WORDS = ("promo", "teaser", "trailer", "preview")      # এই শব্দ থাকলে "প্রোমো" ধরা হবে
# ===============================================================

BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
LAUNCH_URL = "https://launchapi.zee5.com/launch"
API = "https://gwapi.zee5.com/content/tvshow"
MAX_PAGES = 15
LINE = "━━━━━━━━━━━━━━━━"
LOCAL_TZ = timezone(timedelta(hours=TZ_HOURS))
ZLINK_RE = re.compile(r"https?://(?:www\.)?zee5\.com/tv-shows/details/[^\s<>\"']+")
SLINK_RE = re.compile(r"https?://(?:www\.)?sonyliv\.com/shows/[^\s<>\"']+")
HLINK_RE = re.compile(r"https?://(?:www\.)?hotstar\.com/(?:[a-z]{2}/)?shows/[^\s<>\"']+")
HOT_ID_RE = re.compile(r"hotstar\.com/(?:[a-z]{2}/)?shows/([^/?#\s]+)/(\d{8,12})")
ANY_LINK_RE = re.compile(ZLINK_RE.pattern + "|" + SLINK_RE.pattern + "|" + HLINK_RE.pattern)
SONY_ID_RE = re.compile(r"sonyliv\.com/shows/[^/?#\s]*?-(\d{10})(?:[/?#]|$)")

Z_HEADERS = {
    "Origin": "https://www.zee5.com",
    "Referer": "https://www.zee5.com/",
    "Sec-CH-UA-Platform": '"Android"',
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 8.0.0; SM-G955U Build/R16NW) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/87.0.4280.141 Mobile Safari/537.36"
    ),
}
PROXIES = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None

# SonyLIV ভারতের বাইরে ব্লক করে। আলাদা প্রক্সি দিতে চাইলে SONY_PROXY_URL, নইলে PROXY_URL-ই ব্যবহার হবে
SONY_PROXY_URL = os.getenv("SONY_PROXY_URL", "") or PROXY_URL
SONY_PROXIES = {"http": SONY_PROXY_URL, "https": SONY_PROXY_URL} if SONY_PROXY_URL else None
SONY_API = "https://apiv2.sonyliv.com/AGL"
SONY_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.sonyliv.com",
    "Referer": "https://www.sonyliv.com",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
}

LANGUAGE_NAMES = {
    "bn": "Bengali (বাংলা)", "en": "English", "gu": "Gujarati (ગુજરાતી)",
    "hi": "Hindi (हिन्दी)", "kn": "Kannada (ಕನ್ನಡ)", "ml": "Malayalam (മലയാളം)",
    "mr": "Marathi (मराठी)", "or": "Odia (ଓଡ଼ିଆ)", "pa": "Punjabi (ਪੰਜਾਬੀ)",
    "ta": "Tamil (தமிழ்)", "te": "Telugu (తెలుగు)", "ur": "Urdu (اردو)",
}

lock = threading.RLock()
season_cache = {}
runtime = {"last_check": None, "cycle": 0.0, "started": time.time(), "sent": 0}
blocks = {p: {"until": 0.0, "wait": 300, "alerted": False} for p in ("zee5", "sony", "hotstar")}
PNAME = {"zee5": "ZEE5", "sony": "SonyLIV", "hotstar": "JioHotstar"}


def is_sony(sid):
    return isinstance(sid, str) and sid.startswith("sl-")


def is_hot(sid):
    return isinstance(sid, str) and sid.startswith("hs-")


def provider(sid):
    return "hotstar" if is_hot(sid) else ("sony" if is_sony(sid) else "zee5")


def ptag(sid):
    return "HS" if is_hot(sid) else ("SL" if is_sony(sid) else "Z5")


def track_breakdown():
    n_s = sum(1 for s in SHOW_SLUGS if is_sony(s))
    n_h = sum(1 for s in SHOW_SLUGS if is_hot(s))
    return f"ZEE5 {len(SHOW_SLUGS) - n_s - n_h}, SonyLIV {n_s}, JioHotstar {n_h}"

state = {"seen": {}, "subs": {}, "names": {}, "latest": {}, "links": [], "removed": [], "seen_x": {}, "imgs": {}}
SHOW_SLUGS = {}    # শো আইডি -> লিংকের slug (ক্রম অনুযায়ী)

# থ্রেড পুল (একবারই বানানো হয়, বারবার নয় — তাই ফাস্ট)
check_pool = ThreadPoolExecutor(WORKERS, thread_name_prefix="check")
notify_pool = ThreadPoolExecutor(4, thread_name_prefix="notify")
fan_pool = ThreadPoolExecutor(12, thread_name_prefix="fan")
handler_pool = ThreadPoolExecutor(8, thread_name_prefix="handler")


class AccessDenied(RuntimeError):
    pass


def make_session(headers=None, proxy=False):
    """কানেকশন-পুলসহ সেশন: বারবার নতুন কানেকশন না খুলে আগেরটা ব্যবহার করে (দ্রুত)।"""
    s = requests.Session()
    ad = HTTPAdapter(pool_connections=32, pool_maxsize=64, max_retries=0)
    s.mount("https://", ad)
    s.mount("http://", ad)
    if headers:
        s.headers.update(headers)
    if proxy and PROXIES:
        s.proxies = PROXIES
    return s


tg_http = make_session()
launch_http = make_session(proxy=True)
img_http = make_session(Z_HEADERS, proxy=True)


# ---------------------------------------------------------------- সেভ/লোড
_dirty = threading.Event()


def mark_dirty():
    _dirty.set()


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                state.update(json.load(f))
        except Exception as e:
            print("state লোড করা যায়নি:", e)
    for k in ("seen", "subs", "names", "latest", "seen_x", "imgs"):
        state.setdefault(k, {})
    for k in ("links", "removed"):
        state.setdefault(k, [])
    state["subs"].setdefault(str(OWNER_ID), {"on": True, "name": "Owner", "muted": []})


def save_state():
    with lock:
        data = json.dumps(state, ensure_ascii=False)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
    os.replace(tmp, STATE_FILE)


def saver():
    """ডিস্কে সেভ ব্যাকগ্রাউন্ডে হয়, তাই চেকিং কখনো আটকে থাকে না।"""
    while True:
        _dirty.wait()
        time.sleep(0.5)
        _dirty.clear()
        try:
            save_state()
        except Exception as e:
            print("[সেভ ত্রুটি]", e)


def ensure_sub(chat_id, name=""):
    with lock:
        s = state["subs"].setdefault(str(chat_id), {"on": True, "name": name, "muted": []})
        s.setdefault("muted", [])
        s.setdefault("on", True)
        s.setdefault("promo", True)
        s.setdefault("spoiler", True)
        return s


# ---------------------------------------------------------------- Telegram
def tg(method, _t=30, **params):
    clean = {}
    for k, v in params.items():
        if v is None:
            continue
        clean[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
    for attempt in range(3):
        try:
            j = tg_http.post(f"{BASE}/{method}", data=clean, timeout=_t).json()
        except Exception as e:
            if method != "getUpdates":
                print(f"[Telegram {method} ত্রুটি] {e}")
            return {}
        if j.get("ok"):
            return j
        if j.get("error_code") == 429 and attempt < 2:
            time.sleep(j.get("parameters", {}).get("retry_after", 1) + 0.5)
            continue
        desc = j.get("description", "")
        if "not modified" not in desc:
            print(f"[Telegram {method}] {desc}")
        return j
    return {}


def send_text(chat_id, text, markup=None):
    return tg("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
              disable_web_page_preview=True, reply_markup=markup)


def edit_text(chat_id, msg_id, text, markup=None):
    return tg("editMessageText", chat_id=chat_id, message_id=msg_id, text=text,
              parse_mode="HTML", disable_web_page_preview=True, reply_markup=markup)


def tg_upload_photo(chat_id, data, caption, markup):
    try:
        form = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
        if markup:
            form["reply_markup"] = json.dumps(markup)
        r = tg_http.post(f"{BASE}/sendPhoto", data=form,
                         files={"photo": ("thumb.jpg", data)}, timeout=60)
        return r.json()
    except Exception as e:
        print("[ছবি আপলোড ত্রুটি]", e)
        return {}


def photo_file_id(j):
    try:
        return j["result"]["photo"][-1]["file_id"]
    except Exception:
        return None


sony_img_http = make_session(SONY_HEADERS)
if SONY_PROXIES:
    sony_img_http.proxies = SONY_PROXIES


def download_image(url):
    try:
        if "slivcdn" in url or "sonyliv" in url:
            r = sony_img_http.get(url, timeout=(5, 20))
        else:
            r = img_http.get(url, timeout=(5, 20))
        ct = r.headers.get("Content-Type", "")
        if r.ok and ct.startswith("image") and 0 < len(r.content) <= 10 * 1024 * 1024:
            return r.content
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- হেল্পার
def show_name(sid):
    n = state["names"].get(sid)
    if n:
        return n
    slug = SHOW_SLUGS.get(sid, "")
    return slug.replace("-", " ").title() if slug else sid


def is_on(chat_id):
    return state["subs"].get(str(chat_id), {}).get("on", False)


def selected_count(chat_id):
    muted = set(ensure_sub(chat_id)["muted"])
    return sum(1 for s in SHOW_SLUGS if s not in muted)


def fmt_dt(ts):
    return datetime.fromtimestamp(ts, LOCAL_TZ).strftime("%d %b, %I:%M:%S %p")


def fmt_uptime(sec):
    sec = int(sec)
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    return (f"{d} দিন " if d else "") + f"{h} ঘণ্টা {m} মিনিট"


# ---------------------------------------------------------------- OTT গ্রুপ • অ্যাডমিন • বাটন
OTT_ORDER = ("zee5", "sony", "hotstar")
OTT_ICON = {"zee5": "🟣", "sony": "🔵", "hotstar": "🟦"}
OTT_SHORT = {"z": "zee5", "s": "sony", "h": "hotstar"}
OTT_CODE = {v: k for k, v in OTT_SHORT.items()}
KIND_META = {
    "episode": {"head": "🔔 <b>NEW EPISODE</b> ✨", "tag": "#NewEpisode", "word": "Episode"},
    "promo": {"head": "🎬 <b>NEW PROMO</b> ✨", "tag": "#NewPromo", "word": "Promo"},
    "spoiler": {"head": "👀 <b>EPISODE SPOILER</b> ✨", "tag": "#EpisodeSpoiler", "word": "Spoiler"},
}
poll_state = {"offset": None}


def is_admin(uid):
    return uid in ADMIN_IDS


def grouped_ids(ids=None):
    """সিরিয়ালগুলো OTT ধরে সাজানো (ZEE5 -> SonyLIV -> JioHotstar), প্রতিটার ভেতরে আগের ক্রম।"""
    ids = list(SHOW_SLUGS) if ids is None else list(ids)
    return sorted(ids, key=lambda s: OTT_ORDER.index(provider(s)))


def count_by_ott():
    return {p: sum(1 for s in SHOW_SLUGS if provider(s) == p) for p in OTT_ORDER}


def ott_header_row(p, n):
    return [{"text": f"{OTT_ICON[p]} ━━ {PNAME[p]} ({n}) ━━", "callback_data": "noop"}]


def make_key(sid, kind, eid):
    return hashlib.md5(f"{sid}|{kind}|{eid}".encode("utf-8")).hexdigest()[:10]


def store_img(info):
    """'Get Image' বাটনের জন্য ছবির লিংক/টাইটেল মনে রাখে (সর্বশেষ ৪০০টা)।"""
    with lock:
        imgs = state.setdefault("imgs", {})
        imgs.pop(info["key"], None)
        imgs[info["key"]] = {"images": info["images"], "cap": info["img_cap"],
                             "title": info["title"], "link": info["link"]}
        while len(imgs) > 400:
            imgs.pop(next(iter(imgs)))
    mark_dirty()


def notif_markup(i):
    link = i["link"]
    if 0 < len(link) <= 256:
        copy_btn = {"text": "📋 Copy", "copy_text": {"text": link}}      # ক্লিক করলেই লিংক কপি
    else:
        copy_btn = {"text": "📋 Copy", "callback_data": f"cp:{i['key']}"}
    return {"inline_keyboard": [
        [{"text": "🖼 Get Image", "callback_data": f"gi:{i['key']}"},
         copy_btn,
         {"text": "📤 Share",
          "url": f"https://t.me/share/url?url={quote(link)}&text={quote(i['title'])}"}],
    ]}


def send_photo_any(chat_id, images, caption, markup=None):
    """ছবির লিংক -> নিজে ডাউনলোড করে আপলোড -> শেষে শুধু টেক্সট।"""
    for url in images:
        j = tg("sendPhoto", chat_id=chat_id, photo=url, caption=caption,
               parse_mode="HTML", reply_markup=markup)
        if j.get("ok"):
            return j
    for url in images:
        data = download_image(url)
        if data:
            j = tg_upload_photo(chat_id, data, caption, markup)
            if j.get("ok"):
                return j
    return send_text(chat_id, caption, markup)


def _img_ext(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return "jpg"


def send_image_file(chat_id, key):
    """'Get Image' চাপলে: ছবি ডাউনলোড করে HD ফাইল হিসেবে বটে পাঠায়, নিচে নোটিফিকেশনের টাইটেল।"""
    info = state.get("imgs", {}).get(key)
    if not info or not info.get("images"):
        send_text(chat_id, "⚠️ এই নোটিফিকেশনের ছবি পাওয়া যায়নি (খুব পুরনো হলে মুছে যায়)।")
        return
    for url in info["images"]:
        data = download_image(url)
        if not data:
            continue
        fname = f"{(slugify(info.get('title') or '') or 'image')[:60]}.{_img_ext(data)}"
        try:
            r = tg_http.post(f"{BASE}/sendDocument",
                             data={"chat_id": chat_id, "caption": info.get("cap", ""), "parse_mode": "HTML"},
                             files={"document": (fname, data)}, timeout=60)
            if r.json().get("ok"):
                return
        except Exception as e:
            print("[ইমেজ ফাইল ত্রুটি]", e)
    send_text(chat_id, "⚠️ ছবি ডাউনলোড করা যায়নি, একটু পরে আবার চেষ্টা করুন।")


# ---------------------------------------------------------------- সেটিংস (প্রোমো / স্পয়লার আলাদা)
def _onoff(v):
    return "চালু ✅" if v else "বন্ধ ❌"


def settings_text(chat_id):
    s = ensure_sub(chat_id)
    return (
        "⚙️ <b>সেটিংস</b>\n" + LINE + "\n"
        "ZEE5, SonyLIV ও JioHotstar — তিনটারই জন্য আলাদা আলাদা চালু/বন্ধ করা যায়।\n\n"
        f"🔔 নতুন এপিসোড: <b>{_onoff(s.get('on', True))}</b>\n"
        f"🎬 প্রোমো: <b>{_onoff(s.get('promo', True))}</b>\n"
        f"👀 এপিসোড স্পয়লার: <b>{_onoff(s.get('spoiler', True))}</b>\n\n"
        "<i>👇 বাটনে ট্যাপ করলেই বদলে যাবে</i>"
    )


def settings_markup(chat_id):
    s = ensure_sub(chat_id)
    return {"inline_keyboard": [
        [{"text": f"🔔 এপিসোড: {_onoff(s.get('on', True))}", "callback_data": "st:ep"}],
        [{"text": f"🎬 প্রোমো: {_onoff(s.get('promo', True))}", "callback_data": "st:promo"}],
        [{"text": f"👀 স্পয়লার: {_onoff(s.get('spoiler', True))}", "callback_data": "st:spoiler"}],
        [{"text": "🏠 মূল মেনু", "callback_data": "home"}],
    ]}


def toggle_setting(chat_id, which):
    s = ensure_sub(chat_id)
    with lock:
        s[which] = not s.get(which, True)
    mark_dirty()
    return s[which]


# ---------------------------------------------------------------- সর্বশেষ এপিসোড (OTT ধরে + থাম্বনেইল)
def latest_items(prov):
    with lock:
        items = [(k, v) for k, v in state["latest"].items() if k in SHOW_SLUGS and provider(k) == prov]
    return sorted(items, key=lambda kv: kv[1].get("date", ""), reverse=True)


def latest_menu_text():
    return (f"📺 <b>সর্বশেষ এপিসোড</b>\n{LINE}\n\n"
            "কোন OTT-র সিরিয়াল দেখবেন? 👇\n"
            "<i>প্রতিটার থাম্বনেইল ও ওয়াচ লিংকসহ আসবে।</i>")


def latest_menu_markup():
    rows = []
    for p, n in count_by_ott().items():
        if n:
            rows.append([{"text": f"{OTT_ICON[p]} {PNAME[p]} ({n})", "callback_data": f"lt:{OTT_CODE[p]}"}])
    rows.append([{"text": "📚 সব OTT একসাথে", "callback_data": "lt:a"}])
    rows.append([{"text": "🏠 মূল মেনু", "callback_data": "home"}])
    return {"inline_keyboard": rows}


def latest_back_markup():
    return {"inline_keyboard": [[{"text": "🔙 OTT বাছাই", "callback_data": "latest"},
                                 {"text": "🏠 মূল মেনু", "callback_data": "home"}]]}


def latest_text(prov=None):
    provs = [prov] if prov else list(OTT_ORDER)
    head = f"📺 <b>সর্বশেষ এপিসোড</b>{(' — ' + PNAME[prov]) if prov else ''}\n{LINE}"
    out, size, found = [head], len(head), False
    for p in provs:
        items = latest_items(p)[:15]
        if not items:
            continue
        found = True
        sec = f"\n\n{OTT_ICON[p]} <b>{PNAME[p]}</b>"
        if size + len(sec) > 3800:
            break
        out.append(sec)
        size += len(sec)
        for i, (_, it) in enumerate(items, 1):
            blk = (
                f"\n<b>{i}. {escape(it['show'])}</b>\n"
                f"    🎞 <code>{escape(it['label'])}</code>   📅 {escape(it['date_s'])}\n"
                f"    ▶️ <a href=\"{escape(it['link'], quote=True)}\">এখনই দেখুন</a>"
            )
            if size + len(blk) > 3800:
                break
            out.append(blk)
            size += len(blk)
    if not found:
        return head + "\n\n⏳ এখনো তথ্য আসেনি, একটু পরে আবার চেষ্টা করুন।"
    return "".join(out)


def send_latest_albums(chat_id, prov=None):
    """প্রতিটা OTT-র সর্বশেষ এপিসোডের থাম্বনেইল (অ্যালবাম) — প্রতিটার ক্যাপশনে লিংক থাকে।"""
    for p in ([prov] if prov else list(OTT_ORDER)):
        entries = []
        for _, v in latest_items(p)[:10]:
            imgs = v.get("images") or []
            if not imgs:
                continue
            cap = (f"<b>{escape(v['show'])}</b> <i>[{escape(v['platform'])}]</i>\n"
                   f"🎞 <code>{escape(v['label'])}</code>   📅 {escape(v['date_s'])}\n"
                   f"▶️ <a href=\"{escape(v['link'], quote=True)}\">এখনই দেখুন</a>")
            entries.append((imgs, cap))
        if not entries:
            continue
        if len(entries) == 1:
            send_photo_any(chat_id, *entries[0])
            continue
        media = [{"type": "photo", "media": imgs[0], "caption": cap, "parse_mode": "HTML"}
                 for imgs, cap in entries]
        j = tg("sendMediaGroup", _t=60, chat_id=chat_id, media=media)
        if not j.get("ok"):                              # অ্যালবাম না গেলে একটা একটা করে
            for imgs, cap in entries:
                send_photo_any(chat_id, imgs, cap)


# ---------------------------------------------------------------- বট স্ট্যাটাস • রিস্টার্ট (শুধু অ্যাডমিন)
def status_markup(chat_id):
    rows = [[{"text": "🔄 রিফ্রেশ", "callback_data": "status"},
             {"text": "🏠 মূল মেনু", "callback_data": "home"}]]
    if is_admin(chat_id):
        rows.insert(0, [{"text": "♻️ বট রিস্টার্ট", "callback_data": "rs"}])
    return {"inline_keyboard": rows}


def restart_confirm_markup():
    return {"inline_keyboard": [[
        {"text": "✅ হ্যাঁ, রিস্টার্ট করুন", "callback_data": "rsy"},
        {"text": "↩️ না", "callback_data": "status"},
    ]]}


def do_restart(chat_id, msg_id):
    with lock:
        state["restart_notice"] = {"chat_id": chat_id, "msg_id": msg_id, "t": time.time()}
    try:
        save_state()
    except Exception as e:
        print("[রিস্টার্ট-সেভ ত্রুটি]", e)
    if poll_state["offset"] is not None:           # এই বাটনের আপডেটটা কনফার্ম করি, নইলে নতুন প্রসেসে আবার আসত
        tg("getUpdates", _t=10, offset=poll_state["offset"], timeout=0, limit=1)
    print("♻️ বট রিস্টার্ট হচ্ছে...")
    try:
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        print("[রিস্টার্ট ব্যর্থ]", e)
        send_text(chat_id, f"❌ রিস্টার্ট করা যায়নি: <code>{escape(str(e)[:80])}</code>")


# ---------------------------------------------------------------- মেনু ডিজাইন
def main_menu(chat_id):
    on = is_on(chat_id)
    rows = [
        [{"text": "📺 সর্বশেষ এপিসোড", "callback_data": "latest"},
         {"text": "🎯 সিরিয়াল বাছাই", "callback_data": "shows"}],
        [{"text": "🔔 নোটিফিকেশন: চালু ✅" if on else "🔕 নোটিফিকেশন: বন্ধ ❌",
          "callback_data": "toggle"}],
        [{"text": "⚙️ সেটিংস (প্রোমো • স্পয়লার)", "callback_data": "settings"}],
        [{"text": "📊 বট স্ট্যাটাস", "callback_data": "status"},
         {"text": "ℹ️ সাহায্য", "callback_data": "help"}],
    ]
    if is_admin(chat_id):
        rows.append([{"text": "➕ সিরিয়াল যোগ", "callback_data": "add_help"},
                     {"text": "🗑 সিরিয়াল সরান", "callback_data": "rm_menu"}])
    return {"inline_keyboard": rows}


def back_menu(refresh=None):
    row = []
    if refresh:
        row.append({"text": "🔄 রিফ্রেশ", "callback_data": refresh})
    row.append({"text": "🏠 মূল মেনু", "callback_data": "home"})
    return {"inline_keyboard": [row]}


def welcome_text(name, chat_id):
    total = len(SHOW_SLUGS)
    return (
        f"🎬 <b>OTT বাংলা নোটিফায়ার</b>\n"
        f"{LINE}\n\n"
        f"👋 স্বাগতম, <b>{escape(name)}</b>!\n\n"
        f"ZEE5, SonyLIV ও JioHotstar-এর <b>নতুন এপিসোড</b>, <b>প্রোমো</b> আর "
        f"<b>এপিসোড স্পয়লার</b> আসার সাথে সাথেই পেয়ে যান — "
        f"HD ছবি, তারিখ ও ওয়াচ লিংকসহ।\n\n"
        f"<blockquote>⚡ প্রতি {CHECK_INTERVAL} সেকেন্ডে অটো চেক\n"
        f"🎯 পছন্দের সিরিয়াল বেছে নেওয়া যায়\n"
        f"🎬 প্রোমো ও 👀 স্পয়লার আলাদাভাবে চালু/বন্ধ\n"
        f"🔔 যখন খুশি নোটিফিকেশন চালু/বন্ধ</blockquote>\n\n"
        f"📡 ট্র্যাক হচ্ছে: <b>{total}</b>টি সিরিয়াল  •  "
        f"🔔 আপনার: <b>{selected_count(chat_id)}</b>টি\n"
        f"{LINE}\n"
        f"<i>Powered by {escape(BRAND)}</i>"
    )


def help_text(is_owner=False):
    t = (
        "ℹ️ <b>সাহায্য</b>\n" + LINE + "\n"
        "/start — 🏠 মূল মেনু\n"
        "/latest — 📺 সর্বশেষ এপিসোড (OTT ধরে)\n"
        "/shows — 🎯 সিরিয়াল বেছে নিন\n"
        "/settings — ⚙️ প্রোমো / স্পয়লার চালু-বন্ধ\n"
        "/notify — 🔔 সব নোটিফিকেশন চালু/বন্ধ\n"
        "/status — 📊 বটের অবস্থা\n"
        "/help — ℹ️ এই সাহায্য"
    )
    if is_owner:
        t += (
            "\n\n👑 <b>অ্যাডমিনের কমান্ড</b>\n"
            "/add <code>লিংক</code> — সিরিয়াল যোগ (একসাথে অনেক লিংকও চলবে)\n"
            "/remove — সিরিয়াল সরান\n"
            "/test — নমুনা নোটিফিকেশন (<code>/test promo</code>, <code>/test spoiler</code>ও চলবে)\n"
            "/extras — প্রোমো/স্পয়লার চেকের রিপোর্ট\n"
            "/restart — ♻️ বট রিস্টার্ট\n"
            "💡 শুধু ZEE5/SonyLIV/JioHotstar লিংক পাঠালেই সিরিয়াল যোগ হয়ে যাবে।"
        )
    return t


def add_help_text():
    return (
        "➕ <b>নতুন সিরিয়াল যোগ</b>\n" + LINE + "\n"
        "ZEE5, SonyLIV বা JioHotstar সিরিয়ালের লিংক এখানে পাঠান — একসাথে অনেকগুলো পাঠালেও হবে।\n\n"
        "<blockquote>উদাহরণ:\n"
        "https://www.zee5.com/tv-shows/details/kamala-nibas/0-6-4z5906917\n"
        "https://www.sonyliv.com/shows/kailasher-mahagatha-1790007852\n"
        "https://www.hotstar.com/in/shows/kumkum/1271648427</blockquote>\n\n"
        "যোগ হলে বট পুরনো এপিসোড, প্রোমো ও স্পয়লার চুপচাপ রেকর্ড করে রাখবে, "
        "শুধু <b>নতুন</b>গুলোতেই নোটিফিকেশন যাবে।"
    )


def shows_text(chat_id, page=0):
    total = len(SHOW_SLUGS)
    pages = max(1, -(-total // PAGE_SIZE))
    return (
        f"🎯 <b>সিরিয়াল বাছাই</b>  <i>(পেজ {min(page, pages - 1) + 1}/{pages})</i>\n{LINE}\n"
        f"🔔 = নোটিফিকেশন আসবে\n🔕 = আসবে না\n\n"
        f"👇 নামে ট্যাপ করে চালু/বন্ধ করুন (OTT ধরে সাজানো)\n"
        f"✅ নির্বাচিত: <b>{selected_count(chat_id)}/{total}</b>"
    )


def shows_markup(chat_id, page=0):
    muted = set(ensure_sub(chat_id)["muted"])
    ids = grouped_ids()
    cnt = count_by_ott()
    pages = max(1, -(-len(ids) // PAGE_SIZE))
    page = max(0, min(page, pages - 1))
    rows, last = [], None
    for sid in ids[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
        p = provider(sid)
        if p != last:
            rows.append(ott_header_row(p, cnt[p]))
            last = p
        icon = "🔕" if sid in muted else "🔔"
        rows.append([{"text": f"{icon} {show_name(sid)}"[:60], "callback_data": f"t:{sid}:{page}"}])
    if pages > 1:
        rows.append([
            {"text": "◀️", "callback_data": f"p:{(page - 1) % pages}"},
            {"text": f"{page + 1}/{pages}", "callback_data": "noop"},
            {"text": "▶️", "callback_data": f"p:{(page + 1) % pages}"},
        ])
    rows.append([{"text": "✅ সব চালু", "callback_data": f"all_on:{page}"},
                 {"text": "🚫 সব বন্ধ", "callback_data": f"all_off:{page}"}])
    rows.append([{"text": "🏠 মূল মেনু", "callback_data": "home"}])
    return {"inline_keyboard": rows}


def remove_markup():
    cnt = count_by_ott()
    rows, last = [], None
    for sid in grouped_ids():
        p = provider(sid)
        if p != last:
            rows.append(ott_header_row(p, cnt[p]))
            last = p
        rows.append([{"text": f"🗑 {show_name(sid)}"[:60], "callback_data": f"rm:{sid}"}])
    rows.append([{"text": "🏠 মূল মেনু", "callback_data": "home"}])
    return {"inline_keyboard": rows}


def status_text(chat_id):
    lc = runtime["last_check"]
    now = time.time()
    paused = [PNAME[p] for p, b in blocks.items() if b["until"] > now]
    state_line = ("🟠 ব্লক — বিরতিতে: " + ", ".join(paused)) if paused else "🟢 চালু আছে"
    cnt = count_by_ott()
    s = ensure_sub(chat_id)
    txt = (
        "📊 <b>বট স্ট্যাটাস</b>\n" + LINE + "\n"
        f"{state_line}\n"
        f"⏳ আপটাইম: {fmt_uptime(time.time() - runtime['started'])}\n"
        f"🎬 ট্র্যাক: <b>{len(SHOW_SLUGS)}</b>টি সিরিয়াল\n"
        f"    " + "  •  ".join(f"{OTT_ICON[p]} {PNAME[p]} {cnt[p]}" for p in OTT_ORDER) + "\n"
        f"⏱ চেক: প্রতি {CHECK_INTERVAL} সেকেন্ডে (একটা রাউন্ড ~{runtime['cycle']:.1f}s)\n"
        f"🕒 শেষ চেক: {fmt_dt(lc) if lc else 'এখনো হয়নি'}\n"
        f"🔔 আপনার নোটিফিকেশন: {'চালু ✅' if is_on(chat_id) else 'বন্ধ ❌'}\n"
        f"🎬 প্রোমো: {_onoff(s.get('promo', True))}   👀 স্পয়লার: {_onoff(s.get('spoiler', True))}"
    )
    if is_admin(chat_id):
        subs = sum(1 for x in state["subs"].values() if x.get("on"))
        txt += f"\n👥 সাবস্ক্রাইবার: {subs}\n📨 পাঠানো নোটিফিকেশন: {runtime['sent']}"
    return txt


# ---------------------------------------------------------------- সিরিয়াল যোগ/সরানো
def register_link(link):
    sid = show_id_from(link)
    if sid and sid not in SHOW_SLUGS:
        SHOW_SLUGS[sid] = slug_from(link)
    return sid


def add_shows(text):
    """মেসেজ থেকে ZEE5 লিংক বের করে সিরিয়াল যোগ করে। রিটার্ন: উত্তরের লাইনগুলো।"""
    links = list(dict.fromkeys(l.rstrip(".,)") for l in ANY_LINK_RE.findall(text)))
    if not links:
        return ["❌ কোনো ZEE5/SonyLIV/JioHotstar সিরিয়ালের লিংক পাওয়া যায়নি।"]
    out, added = [], []
    for link in links:
        sid = show_id_from(link)
        if not sid:
            out.append(f"❌ আইডি পাওয়া যায়নি:\n<code>{escape(link)}</code>")
            continue
        if sid in SHOW_SLUGS:
            out.append(f"ℹ️ আগে থেকেই আছে: <b>{escape(show_name(sid))}</b>")
            continue
        try:
            show = fetch_show(sid)
        except AccessDenied:
            out.append("⚠️ ওই প্ল্যাটফর্ম এখন অ্যাক্সেস ব্লক করেছে (SonyLIV হলে ইন্ডিয়ান প্রক্সি লাগবে), একটু পরে আবার চেষ্টা করুন।")
            continue
        except Exception as e:
            out.append(f"⚠️ যাচাই করা যায়নি ({escape(str(e)[:60])})")
            continue
        if not show:
            out.append(f"❌ লিংকটা ঠিক মনে হচ্ছে না:\n<code>{escape(link)}</code>")
            continue
        title = show.get("title") or show.get("original_title") or sid
        with lock:
            SHOW_SLUGS[sid] = slug_from(link)
            state["names"][sid] = title
            if link not in state["links"]:
                state["links"].append(link)
            if sid in state["removed"]:
                state["removed"].remove(sid)
        added.append(sid)
        out.append(f"✅ যোগ হয়েছে: <b>{escape(title)}</b>")
    if added:
        mark_dirty()
        for sid in added:                       # সাথে সাথেই পুরনো এপিসোড রেকর্ড (নোটিফিকেশন ছাড়া)
            check_pool.submit(check_show, sid)
        out.append(f"\n📡 মোট ট্র্যাক হচ্ছে: <b>{len(SHOW_SLUGS)}</b>টি সিরিয়াল")
    return out


def remove_show(sid):
    with lock:
        if sid not in SHOW_SLUGS:
            return None
        name = show_name(sid)
        SHOW_SLUGS.pop(sid, None)
        state["links"] = [l for l in state["links"] if show_id_from(l) != sid]
        if sid not in state["removed"]:
            state["removed"].append(sid)
        state["seen"].pop(sid, None)
        state["seen_x"].pop(sid, None)
        state["latest"].pop(sid, None)
        season_cache.pop(sid, None)
    mark_dirty()
    return name


# ---------------------------------------------------------------- কমান্ড হ্যান্ডলার
def toggle(chat_id, name=""):
    s = ensure_sub(chat_id, name)
    with lock:
        s["on"] = not s.get("on", True)
    mark_dirty()
    return s["on"]


def toggle_show(chat_id, sid):
    s = ensure_sub(chat_id)
    with lock:
        m = set(s["muted"])
        m.symmetric_difference_update({sid})
        s["muted"] = sorted(m)
    mark_dirty()


def set_all(chat_id, on):
    s = ensure_sub(chat_id)
    with lock:
        s["muted"] = [] if on else list(SHOW_SLUGS)
    mark_dirty()


def handle_message(m):
    chat_id = m["chat"]["id"]
    uid = m.get("from", {}).get("id", chat_id)
    name = m.get("from", {}).get("first_name", "বন্ধু")
    text = (m.get("text") or "").strip()
    owner = is_admin(uid)

    if not text.startswith("/"):
        if owner and ANY_LINK_RE.search(text):          # অ্যাডমিন শুধু লিংক পাঠালেই যোগ হবে
            send_text(chat_id, "⏳ লিংক যাচাই করছি...")
            send_text(chat_id, "\n".join(add_shows(text)), main_menu(chat_id))
        return

    cmd = text.split()[0].lower().split("@")[0]
    if cmd in ("/start", "/star"):
        ensure_sub(chat_id, name)
        mark_dirty()
        send_text(chat_id, welcome_text(name, chat_id), main_menu(chat_id))
    elif cmd == "/latest":
        send_text(chat_id, latest_menu_text(), latest_menu_markup())
    elif cmd == "/shows":
        ensure_sub(chat_id, name)
        send_text(chat_id, shows_text(chat_id), shows_markup(chat_id))
    elif cmd == "/settings":
        ensure_sub(chat_id, name)
        send_text(chat_id, settings_text(chat_id), settings_markup(chat_id))
    elif cmd == "/notify":
        on = toggle(chat_id, name)
        send_text(chat_id, "🔔 নোটিফিকেশন <b>চালু</b> হয়েছে ✅" if on
                  else "🔕 নোটিফিকেশন <b>বন্ধ</b> হয়েছে ❌", main_menu(chat_id))
    elif cmd == "/status":
        send_text(chat_id, status_text(chat_id), status_markup(chat_id))
    elif cmd == "/help":
        send_text(chat_id, help_text(owner), back_menu())
    elif cmd == "/add" and owner:
        if ANY_LINK_RE.search(text):
            send_text(chat_id, "\n".join(add_shows(text)), main_menu(chat_id))
        else:
            send_text(chat_id, add_help_text(), back_menu())
    elif cmd == "/remove" and owner:
        send_text(chat_id, "🗑 <b>কোন সিরিয়াল সরাবেন?</b>\n" + LINE, remove_markup())
    elif cmd == "/restart":
        if owner:
            send_text(chat_id, "♻️ <b>বট রিস্টার্ট করবেন?</b>\n" + LINE + "\nপ্রসেস নতুন করে চালু হবে, তথ্য সেভ থাকবে।",
                      restart_confirm_markup())
        else:
            send_text(chat_id, "⛔ শুধু অ্যাডমিন বট রিস্টার্ট করতে পারেন।")
    elif cmd == "/extras" and owner:
        send_text(chat_id, extras_report(), back_menu())
    elif cmd == "/test" and owner:
        parts = text.split()
        kind = parts[1].lower() if len(parts) > 1 and parts[1].lower() in ("promo", "spoiler") else "episode"
        sample = {
            "id": f"test-{int(time.time())}", "title": f"Sample {KIND_META[kind]['word']}", "episode_number": 38,
            "release_date": datetime.now(LOCAL_TZ).strftime("%Y-%m-%d"),
            "audio_languages": ["bn"], "web_url": "https://www.zee5.com/",
        }
        info = ep_info({"title": "Sample Serial"}, 1, sample, "sample", "", kind)
        store_img(info)
        cap, markup = build_caption(info)
        send_text(chat_id, cap, markup)


def handle_callback(cb):
    msg = cb.get("message")
    if not msg:
        tg("answerCallbackQuery", callback_query_id=cb["id"])
        return
    chat_id = msg["chat"]["id"]
    msg_id = msg["message_id"]
    uid = cb.get("from", {}).get("id", chat_id)
    name = cb.get("from", {}).get("first_name", "বন্ধু")
    owner = is_admin(uid)
    parts = (cb.get("data") or "").split(":")
    cmd = parts[0]
    ensure_sub(chat_id, name)

    answer, after, alert = None, None, None

    if cmd == "toggle":
        on = toggle(chat_id, name)
        answer = "🔔 চালু হয়েছে" if on else "🔕 বন্ধ হয়েছে"
        after = lambda: edit_text(chat_id, msg_id, welcome_text(name, chat_id), main_menu(chat_id))
    elif cmd == "t" and len(parts) >= 2 and parts[1] in SHOW_SLUGS:
        sid = parts[1]
        page = to_int(parts[2]) if len(parts) > 2 else 0
        toggle_show(chat_id, sid)
        answer = "🔕 বন্ধ করা হলো" if sid in ensure_sub(chat_id)["muted"] else "🔔 চালু করা হলো"
        after = lambda: edit_text(chat_id, msg_id, shows_text(chat_id, page), shows_markup(chat_id, page))
    elif cmd in ("all_on", "all_off"):
        page = to_int(parts[1]) if len(parts) > 1 else 0
        set_all(chat_id, cmd == "all_on")
        answer = "✅ সব চালু" if cmd == "all_on" else "🚫 সব বন্ধ"
        after = lambda: edit_text(chat_id, msg_id, shows_text(chat_id, page), shows_markup(chat_id, page))
    elif cmd == "p":
        page = to_int(parts[1]) if len(parts) > 1 else 0
        after = lambda: edit_text(chat_id, msg_id, shows_text(chat_id, page), shows_markup(chat_id, page))
    elif cmd == "home":
        after = lambda: edit_text(chat_id, msg_id, welcome_text(name, chat_id), main_menu(chat_id))
    elif cmd == "shows":
        after = lambda: edit_text(chat_id, msg_id, shows_text(chat_id), shows_markup(chat_id))
    elif cmd == "settings":
        after = lambda: edit_text(chat_id, msg_id, settings_text(chat_id), settings_markup(chat_id))
    elif cmd == "st" and len(parts) > 1 and parts[1] in ("ep", "promo", "spoiler"):
        which = {"ep": "on", "promo": "promo", "spoiler": "spoiler"}[parts[1]]
        now_on = toggle_setting(chat_id, which)
        answer = "✅ চালু হয়েছে" if now_on else "🚫 বন্ধ হয়েছে"
        after = lambda: edit_text(chat_id, msg_id, settings_text(chat_id), settings_markup(chat_id))
    elif cmd == "latest":
        after = lambda: edit_text(chat_id, msg_id, latest_menu_text(), latest_menu_markup())
    elif cmd == "lt" and len(parts) > 1:
        prov = None if parts[1] == "a" else OTT_SHORT.get(parts[1])
        answer = "⏳ থাম্বনেইল আনছি..."

        def after():
            edit_text(chat_id, msg_id, latest_text(prov), latest_back_markup())
            send_latest_albums(chat_id, prov)
    elif cmd == "gi" and len(parts) > 1:
        answer = "⏳ ছবি আনছি..."
        after = lambda: send_image_file(chat_id, parts[1])
    elif cmd == "cp" and len(parts) > 1:
        info = state.get("imgs", {}).get(parts[1])
        answer = "📋 লিংক নিচে পাঠালাম"
        after = lambda: send_text(chat_id, f"<code>{escape(info['link'])}</code>") if info else None
    elif cmd == "status":
        after = lambda: edit_text(chat_id, msg_id, status_text(chat_id), status_markup(chat_id))
    elif cmd in ("rs", "rsy"):
        if not owner:                                    # শুধু অ্যাডমিন
            answer, alert = "⛔ শুধু অ্যাডমিন বট রিস্টার্ট করতে পারেন", True
        elif cmd == "rs":
            after = lambda: edit_text(
                chat_id, msg_id,
                "♻️ <b>বট রিস্টার্ট করবেন?</b>\n" + LINE + "\nপ্রসেস নতুন করে চালু হবে, তথ্য সেভ থাকবে।",
                restart_confirm_markup())
        else:
            answer = "♻️ রিস্টার্ট হচ্ছে..."

            def after():
                edit_text(chat_id, msg_id, "♻️ <b>বট রিস্টার্ট হচ্ছে...</b>\nকয়েক সেকেন্ড অপেক্ষা করুন।")
                do_restart(chat_id, msg_id)
    elif cmd == "help":
        after = lambda: edit_text(chat_id, msg_id, help_text(owner), back_menu())
    elif cmd == "add_help" and owner:
        after = lambda: edit_text(chat_id, msg_id, add_help_text(), back_menu())
    elif cmd == "rm_menu" and owner:
        after = lambda: edit_text(chat_id, msg_id, "🗑 <b>কোন সিরিয়াল সরাবেন?</b>\n" + LINE, remove_markup())
    elif cmd == "rm" and owner and len(parts) > 1 and parts[1] in SHOW_SLUGS:
        sid = parts[1]
        kb = {"inline_keyboard": [[
            {"text": "✅ হ্যাঁ, সরান", "callback_data": f"rmy:{sid}"},
            {"text": "↩️ না", "callback_data": "rm_menu"},
        ]]}
        after = lambda: edit_text(
            chat_id, msg_id, f"⚠️ <b>{escape(show_name(sid))}</b> সরিয়ে দেবেন?", kb)
    elif cmd == "rmy" and owner and len(parts) > 1:
        removed = remove_show(parts[1])
        answer = "🗑 সরানো হলো" if removed else None
        after = lambda: edit_text(
            chat_id, msg_id,
            (f"🗑 <b>{escape(removed)}</b> সরানো হয়েছে।\n" if removed else "") +
            "🗑 <b>আর কোনটা সরাবেন?</b>\n" + LINE, remove_markup())

    tg("answerCallbackQuery", callback_query_id=cb["id"], text=answer, show_alert=alert)   # আগে স্পিনার বন্ধ (দ্রুত)
    if after:
        after()


def _safe(fn, arg):
    try:
        fn(arg)
    except Exception as e:
        print("[হ্যান্ডলার ত্রুটি]", e)


def poller():
    offset = None
    while True:
        j = tg("getUpdates", _t=70, timeout=50, offset=offset,
               allowed_updates=["message", "callback_query"])
        for u in j.get("result", []):
            offset = u["update_id"] + 1
            poll_state["offset"] = offset
            if "message" in u:
                handler_pool.submit(_safe, handle_message, u["message"])
            elif "callback_query" in u:
                handler_pool.submit(_safe, handle_callback, u["callback_query"])
        if not j.get("ok"):
            time.sleep(3)


# ---------------------------------------------------------------- Zee5 ডাটা
_tok = {"v": None, "exp": 0.0}
_tok_lock = threading.Lock()
_local = threading.local()


def zsession():
    s = getattr(_local, "s", None)
    if s is None:
        s = _local.s = make_session(Z_HEADERS, proxy=True)
    return s


def platform_token(force=False):
    with _tok_lock:
        if not force and _tok["v"] and time.time() < _tok["exp"]:
            return _tok["v"]
        r = launch_http.get(
            LAUNCH_URL,
            params={"ccode": "IN", "lang": "en", "version": "4", "country": "IN",
                    "state": "WB", "translation": "en", "platform_name": "androidtv_app"},
            headers={"User-Agent": "okhttp/4.9.3"}, timeout=(5, 15),
        )
        if r.status_code == 403:
            raise AccessDenied("ZEE5 launch API: HTTP 403")
        r.raise_for_status()
        token = (r.json().get("platform_token") or {}).get("token")
        if not token:
            raise RuntimeError("platform token পাওয়া যায়নি")
        _tok["v"], _tok["exp"] = token, time.time() + 300
        return token


def zget(url, params=None):
    """টোকেনসহ GET। ৪০০ হলে None। ৪০১/৪০৩ হলে টোকেন বদলে একবার আবার চেষ্টা।"""
    for attempt in (0, 1):
        r = zsession().get(url, params=params, timeout=(5, 15),
                           headers={"X-Access-Token": platform_token(force=attempt == 1)})
        if r.status_code == 400:
            return None
        if r.status_code in (401, 403):
            if attempt == 0:
                continue
            if r.status_code == 403:
                raise AccessDenied(f"ZEE5 HTTP 403 ({url[:60]})")
        r.raise_for_status()
        return r.json()
    return None


def show_id_from(link):
    if "hotstar.com" in link:
        m = HOT_ID_RE.search(link)
        if not m:
            return None
        HS_SLUGS["hs-" + m.group(2)] = m.group(1)
        return f"hs-{m.group(2)}"
    if "sonyliv.com" in link:
        m = SONY_ID_RE.search(link)
        return f"sl-{m.group(1)}" if m else None
    m = re.search(r"0-6-[0-9a-zA-Z_-]+", link)
    return m.group(0) if m else None


def slug_from(link):
    if "hotstar.com" in link:
        m = HOT_ID_RE.search(link)
        return m.group(1) if m else ""
    if "sonyliv.com" in link:
        parts = [p for p in urlparse(link).path.split("/") if p]
        return parts[1] if len(parts) > 1 and parts[0] == "shows" else ""
    parts = [p for p in urlparse(link).path.split("/") if p]
    for i, p in enumerate(parts):
        if p == "details" and i + 1 < len(parts) and not parts[i + 1].startswith("0-"):
            return parts[i + 1]
    return ""


def to_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def first_nonempty(d, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


def release_date(ep):
    keys = ("release_date", "releaseDate", "air_date", "airDate", "published_date",
            "publish_date", "on_air_date", "onair_date", "date")
    v = first_nonempty(ep, *keys)
    if v is not None:
        return str(v)
    for p in ("episode_details", "metadata", "details"):
        parent = ep.get(p)
        if isinstance(parent, dict):
            v = first_nonempty(parent, *keys)
            if v is not None:
                return str(v)
    return ""


def extract_languages(data):
    for key in ("audio_languages", "languages", "language"):
        values = data.get(key)
        if not isinstance(values, list):
            values = [values]
        labels = []
        for v in values:
            if isinstance(v, dict):
                v = first_nonempty(v, "name", "language", "code", "id")
            if isinstance(v, str) and v.strip():
                n = v.strip()
                labels.append(LANGUAGE_NAMES.get(n.lower(), n))
        if labels:
            return ", ".join(dict.fromkeys(labels))
    return None


def hd_image_url(u):
    """ZEE5 এর ছোট লিস্ট-থাম্বনেইলকে অরিজিনাল (ফুল সাইজ) ছবির লিংকে বদলায়।"""
    p = urlparse(u)
    parts = p.path.split("/")
    if (p.scheme in ("http", "https") and p.hostname == "akamaividz.zee5.com"
            and len(parts) == 6 and parts[1] == "resources" and parts[2]
            and re.fullmatch(r"\d+x\d+", parts[4]) and parts[5]):
        path = f"/image/upload/resources/{parts[2]}/{parts[3]}/{parts[5]}"
        return urlunparse(("https", "akamaividz2.zee5.com", path, "", p.query, ""))
    return u


def find_image(obj):
    if isinstance(obj, dict):
        for key in ("image_url", "image", "list_image_url", "imageUrl", "thumbnail", "cover_image"):
            v = obj.get(key)
            if isinstance(v, str) and v.startswith("http"):
                return v
        for v in obj.values():
            r = find_image(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_image(v)
            if r:
                return r
    return None


def find_url(obj):
    keys = ("web_url", "weburl", "url", "web_link", "deeplink", "deep_link", "permalink", "share_url")
    if isinstance(obj, dict):
        for k in keys:
            v = obj.get(k)
            if isinstance(v, str) and "zee5.com" in v:
                return v
        for v in obj.values():
            r = find_url(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_url(v)
            if r:
                return r
    return None


def slugify(text):
    t = (text or "").strip().lower().replace("'", "")
    t = re.sub(r"[^a-z0-9]+", "-", t)
    return re.sub(r"-+", "-", t).strip("-")


def episode_link(ep, sid, show_name_, slug):
    if ep.get("link"):
        return ep["link"]
    if is_hot(sid):
        return "https://www.hotstar.com/"
    if is_sony(sid):
        return sony_episode_link(ep, slug)
    u = find_url(ep)
    if u:
        return u
    path = first_nonempty(ep, "web_url", "weburl", "slug")
    if isinstance(path, str) and path.lstrip("/").startswith("tv-shows/details/"):
        return urljoin("https://www.zee5.com/", path.lstrip("/"))
    eid = ep.get("id")
    es = slugify(first_nonempty(ep, "title", "original_title") or "")
    if eid and es:
        return f"https://www.zee5.com/tv-shows/details/{slug or slugify(show_name_)}/{sid}/{es}/{eid}"
    return "https://www.zee5.com/"


def ep_info(show, season_no, ep, sid, slug, kind="episode"):
    default_title = {"episode": "New Episode", "promo": "New Promo", "spoiler": "Episode Spoiler"}[kind]
    title = ep.get("title") or ep.get("original_title") or default_title
    name = show.get("title") or show.get("original_title") or ""
    ep_no = to_int(ep.get("episode_number") or ep.get("orderid"), 0)
    date_raw = release_date(ep)[:10]
    try:
        d = datetime.strptime(date_raw, "%Y-%m-%d")
        long_date, short_date = d.strftime("%B %d, %Y"), d.strftime("%d-%B-%Y")
    except ValueError:
        long_date = short_date = date_raw or "N/A"
    lang = extract_languages(ep) or extract_languages(show) or "N/A"
    raw = find_image(ep) or ""
    images = []
    if raw:
        for u in (hd_image_url(raw), raw):
            if u not in images:
                images.append(u)
    for u in list(ep.get("image_alts") or []) + [show.get("image_url") or ""]:
        if u and u.startswith("http") and u not in images:
            images.append(u)
    eid = str(ep.get("id") or "")
    label = f"S{int(season_no):02d}·E{ep_no:02d}" if kind == "episode" else KIND_META[kind]["word"].upper()
    return {
        "title": title, "show": name, "label": label,
        "long_date": long_date, "short_date": short_date, "lang": lang,
        "link": episode_link(ep, sid, name, slug), "date_raw": date_raw,
        "images": images,
        "platform": PNAME[provider(sid)],
        "kind": kind, "eid": eid, "key": make_key(sid, kind, eid or title),
        "img_cap": f"🖼 <b>{escape(name)}</b>\n📝 {escape(title)} - {escape(long_date)}",
    }


def build_caption(i):
    kind = i.get("kind", "episode")
    meta = KIND_META[kind]

    def make(with_link):
        t = (
            f"{meta['head']}\n"
            f"<blockquote>📺 <b>{escape(i['show'])}</b></blockquote>\n"
        )
        if kind == "episode":
            t += f"🎞 <b>Season • Episode:</b> <code>{i['label']}</code>\n"
        t += (
            f"📝 <b>{meta['word']}:</b> <code>{escape(i['title'])} - {escape(i['long_date'])}</code>\n"
            f"📅 <b>Release Date:</b> <code>{escape(i['short_date'])}</code>\n"
            f"🗣 <b>Language:</b> <code>{escape(i['lang'])}</code>\n"
            f"📡 <b>Platform:</b> <code>{escape(i['platform'])}</code>\n"
        )
        if with_link:
            t += f"\n⚡ <b>Watch Link:</b>\n<code>{escape(i['link'])}</code>\n"
        tags = HASHTAGS.format(platform=i["platform"]).replace("#NewEpisode", meta["tag"])
        return t + "\n" + escape(tags)

    cap = make(True)
    if len(cap) > 1000:                       # ছবির ক্যাপশনের সীমা ১০২৪ — লিংক বাটনে আছেই
        cap = make(False)
    return cap, notif_markup(i)


# ---------------------------------------------------------------- এপিসোড আনা
def newest_first(items):
    if len(items) < 2:
        return False
    a = to_int(items[0].get("episode_number") or items[0].get("orderid"))
    b = to_int(items[-1].get("episode_number") or items[-1].get("orderid"))
    return a > b > 0


def season_episodes(season_id):
    page = zget(API + "/", {
        "season_id": season_id, "translation": "en", "country": "IN",
        "type": "episode", "on_air": "true", "asset_subtype": "tvshow",
        "page": 1, "limit": 100,
    })
    if not page:
        return []
    items = list(page.get("episode") or [])
    if newest_first(items):                 # নতুন-থেকে-পুরনো হলে ১ রিকোয়েস্টই যথেষ্ট
        return items
    seen_urls = set()
    while page.get("next_episode_api") and len(seen_urls) < MAX_PAGES:
        u = page["next_episode_api"]
        if u in seen_urls:
            break
        seen_urls.add(u)
        page = zget(u)
        if not page:
            break
        more = list(page.get("episode") or [])
        if not more:
            break
        items.extend(more)
    return items


def latest_episodes(sid):
    if is_hot(sid):
        return hs_latest_episodes(sid)
    if is_sony(sid):
        return sony_latest_episodes(sid)
    c = season_cache.get(sid)
    if not c or time.time() - c["ts"] > 3600:        # সিজন তথ্য ১ ঘণ্টা ক্যাশ
        show = zget(f"{API}/{sid}", {"translation": "en", "country": "IN"})
        if not show:
            raise RuntimeError("শো ডিটেইলস পাওয়া যায়নি")
        seasons = sorted(show.get("seasons") or [],
                         key=lambda s: to_int(s.get("orderid") or s.get("index")))
        seasons = [s for s in seasons if s.get("id")]
        if not seasons:
            raise RuntimeError("কোনো সিজন পাওয়া যায়নি")
        c = {"show": show, "seasons": seasons, "use": len(seasons) - 1, "ts": time.time()}
        season_cache[sid] = c

    seasons = c["seasons"]
    order = [c["use"]] + [i for i in range(len(seasons) - 1, -1, -1) if i != c["use"]]
    for idx in order:
        eps = season_episodes(seasons[idx]["id"])
        if eps:
            c["use"] = idx
            s = seasons[idx]
            season_no = to_int(s.get("orderid") or s.get("index"), idx + 1)
            return c["show"], season_no, eps
    return c["show"], 1, []


# ---------------------------------------------------------------- SonyLIV ডাটা
_stok = {"v": None, "exp": 0.0}
_stok_lock = threading.Lock()
_slocal = threading.local()
sony_tok_http = make_session(SONY_HEADERS)
if SONY_PROXIES:
    sony_tok_http.proxies = SONY_PROXIES


def ssession():
    s = getattr(_slocal, "s", None)
    if s is None:
        s = _slocal.s = make_session(SONY_HEADERS)
        if SONY_PROXIES:
            s.proxies = SONY_PROXIES
    return s


def sony_token(force=False):
    with _stok_lock:
        if not force and _stok["v"] and time.time() < _stok["exp"]:
            return _stok["v"]
        r = sony_tok_http.get(f"{SONY_API}/1.4/A/ENG/WEB/ALL/GETTOKEN", timeout=(5, 15))
        if r.status_code in (401, 403):
            raise AccessDenied(f"SonyLIV token API: HTTP {r.status_code}")
        r.raise_for_status()
        token = r.json().get("resultObj")
        if not isinstance(token, str) or not token:
            raise RuntimeError("SonyLIV security token পাওয়া যায়নি")
        _stok["v"], _stok["exp"] = token, time.time() + 600
        return token


def sget(path, params=None):
    """SonyLIV API GET। ৪০০/৪০৪ হলে None। ৪০১/৪০৩ হলে টোকেন বদলে একবার আবার চেষ্টা।"""
    for attempt in (0, 1):
        r = ssession().get(f"{SONY_API}/{path}", params=params, timeout=(5, 15),
                           headers={"security_token": sony_token(force=attempt == 1)})
        if r.status_code in (400, 404):
            return None
        if r.status_code in (401, 403):
            if attempt == 0:
                continue
            raise AccessDenied(f"SonyLIV HTTP {r.status_code} ({path[:50]})")
        r.raise_for_status()
        j = r.json()
        if j.get("resultCode") == "KO":
            raise RuntimeError(str(j.get("message") or "SonyLIV error")[:80])
        return j.get("resultObj")
    return None


_IMG_EXT = re.compile(r"\.(?:jpe?g|png|webp)(?:\?|$)", re.I)
_IMG_KEYS = ("thumbnail", "thumb", "landscapethumb", "portraitthumb", "imageurl", "image",
             "poster", "landscape", "episodeimg", "episodethumbnail")


def _sony_images(obj, out, key=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            _sony_images(v, out, str(k).lower())
    elif isinstance(obj, list):
        for v in obj:
            _sony_images(v, out, key)
    elif isinstance(obj, str) and obj.startswith("http"):
        host_ok = "slivcdn.com" in obj or "sonyliv.com" in obj
        if host_ok and (_IMG_EXT.search(obj) or key in _IMG_KEYS):
            if obj not in out:
                out.append(obj)


def sony_images(obj):
    """সম্ভাব্য সব ছবির লিংক — সেরাটা আগে। (প্রথমটা ফেল করলে পরেরটা চেষ্টা হবে)"""
    found = []
    _sony_images(obj, found)
    good = [u for u in found if "logo" not in u.lower()]
    thumbs = [u for u in good if "thumb" in u.lower()]
    ordered = []
    for u in thumbs + good + found:
        if u not in ordered:
            ordered.append(u)
    return ordered


def sony_image(obj):
    imgs = sony_images(obj)
    if not imgs:
        return ""
    return re.sub(r"([?&]w=)\d+", r"\g<1>1280", imgs[0])


def sony_date(m):
    for src in (m, m.get("emfAttributes") if isinstance(m.get("emfAttributes"), dict) else {}):
        for k in ("broadcastDate", "telecastDate", "airDate", "releaseDate", "creationDate"):
            v = src.get(k)
            if v in (None, ""):
                continue
            n = to_int(v, 0)
            if n > 10 ** 11:                       # মিলিসেকেন্ড
                n //= 1000
            if n > 10 ** 8:
                return datetime.fromtimestamp(n, LOCAL_TZ).strftime("%Y-%m-%d")
            if isinstance(v, str) and re.match(r"\d{4}-\d{2}-\d{2}", v):
                return v[:10]
    return ""


def sony_episode_link(ep, slug):
    eid = ep.get("id")
    if not slug or not eid:
        return "https://www.sonyliv.com/"
    es = slugify(ep.get("title") or "") or f"episode-{to_int(ep.get('episode_number'))}"
    return f"https://www.sonyliv.com/shows/{slug}/{es}-{eid}?watch=true"


def sony_norm(c, show):
    """SonyLIV এর এপিসোড কন্টেইনারকে ZEE5-র মতো সহজ ডিক্টে বদলায়, যাতে বাকি কোড একই থাকে।"""
    m = c.get("metadata") or {}
    lang = m.get("language") or m.get("audioLanguage")
    return {
        "id": str(c.get("id")),
        "title": m.get("episodeTitle") or m.get("title") or "",
        "episode_number": to_int(m.get("episodeNumber")),
        "release_date": sony_date(m),
        "audio_languages": lang if isinstance(lang, list) else ([lang] if lang else []),
        "image_url": sony_image(c) or show.get("image_url") or "",
        "image_alts": sony_images(c)[:4],
    }


def sony_details(real_id):
    """রিটার্ন: (শো ডিক্ট বা None, সিজন লিস্ট — পুরনো -> নতুন)"""
    res = sget(f"1.9/R/ENG/WEB/IN/DL/DETAIL/{real_id}",
               {"kids_safe": "false", "from": 0, "to": 49})
    conts = (res or {}).get("containers") or []
    if not conts or not isinstance(conts[0], dict):
        return None, []
    cont = conts[0]
    meta = cont.get("metadata") or {}
    seasons = [c for c in (cont.get("containers") or [])
               if isinstance(c, dict) and to_int(c.get("id"))]
    seasons.sort(key=lambda c: to_int((c.get("metadata") or {}).get("season")))
    show = {"title": meta.get("title") or meta.get("originalTitle") or "",
            "language": meta.get("language"), "image_url": sony_image(cont)}
    return show, seasons


def sony_season_episodes(season_id):
    path = f"1.4/R/ENG/WEB/IN/CONTENT/DETAIL/BUNDLE/{season_id}"

    def page(cursor, order):
        res = sget(path, {"from": cursor, "to": cursor + 99,
                          "orderBy": "episodeNumber", "sortOrder": order})
        conts = (res or {}).get("containers") or []
        inner = (conts[0] or {}).get("containers") if conts and isinstance(conts[0], dict) else []
        return [c for c in (inner or []) if isinstance(c, dict) and to_int(c.get("id"))]

    items = page(0, "desc")                      # সবচেয়ে নতুন ১০০টা — ১ রিকোয়েস্টই যথেষ্ট
    if not items:
        return []
    a = to_int((items[0].get("metadata") or {}).get("episodeNumber"))
    b = to_int((items[-1].get("metadata") or {}).get("episodeNumber"))
    if len(items) < 2 or a > b > 0:
        return items
    items = []                                   # ক্রম অন্যরকম হলে পুরোটা পেজ করে আনি
    for n in range(MAX_PAGES):
        batch = page(n * 100, "asc")
        items.extend(batch)
        if len(batch) < 100:
            break
    return items


def sony_latest_episodes(sid):
    real = sid[3:]
    c = season_cache.get(sid)
    if not c or time.time() - c["ts"] > 3600:
        show, seasons = sony_details(real)
        if not show:
            raise RuntimeError("SonyLIV শো ডিটেইলস পাওয়া যায়নি")
        if not seasons:
            raise RuntimeError("SonyLIV: কোনো সিজন পাওয়া যায়নি")
        c = {"show": show, "seasons": seasons, "use": len(seasons) - 1, "ts": time.time()}
        season_cache[sid] = c
    seasons = c["seasons"]
    order = [c["use"]] + [i for i in range(len(seasons) - 1, -1, -1) if i != c["use"]]
    for idx in order:
        raw = sony_season_episodes(seasons[idx]["id"])
        if raw:
            c["use"] = idx
            sm = seasons[idx].get("metadata") or {}
            season_no = to_int(sm.get("season") or sm.get("seasonNumber"), idx + 1)
            return c["show"], season_no, [sony_norm(x, c["show"]) for x in raw]
    return c["show"], 1, []


# ---------------------------------------------------------------- JioHotstar ডাটা
HS_SLUGS = {}                      # hs-আইডি -> শো slug (যেমন kumkum)
HS_BASE = "https://www.hotstar.com"
HS_APP_VER = "26.10.16.0"
HS_ENV_TOKEN = os.getenv("HOTSTAR_TOKEN", "").strip()      # চাইলে ব্রাউজার থেকে নেওয়া টোকেন (২৪ ঘণ্টা চলে)
HS_PROXY_URL = os.getenv("HOTSTAR_PROXY_URL", "") or PROXY_URL
HS_PROXIES = {"http": HS_PROXY_URL, "https": HS_PROXY_URL} if HS_PROXY_URL else None
_htok = {"v": None, "exp": 0.0, "did": None}
_htok_lock = threading.Lock()


def _hs_rand(n):
    return "".join(random.choice("0123456789abcdef") for _ in range(n))


def _hs_device_id():
    return f"{_hs_rand(6)}-{_hs_rand(6)}-{_hs_rand(6)}-{_hs_rand(6)}"


def _jwt_payload(tok):
    try:
        b = tok.split(".")[1]
        b += "=" * (-len(b) % 4)
        return json.loads(base64.urlsafe_b64decode(b))
    except Exception:
        return {}


def _find_jwt(obj):
    if isinstance(obj, str):
        return obj if obj.startswith("eyJ") and obj.count(".") == 2 else None
    if isinstance(obj, dict):
        for v in obj.values():
            r = _find_jwt(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_jwt(v)
            if r:
                return r
    return None


def hs_headers(token, did):
    return {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/156.0.0.0 Safari/537.36"),
        "Origin": HS_BASE, "Referer": HS_BASE + "/",
        "x-hs-usertoken": token,
        "X-HS-Platform": "web", "X-Country-Code": "in",
        "accept-language": "eng", "X-HS-Accept-language": "eng",
        "x-hs-device-id": did,
        "x-hs-client": (f"platform:web;app_version:{HS_APP_VER};browser:Chrome;schema_version:0.0.1797;"
                        "os:Linux;os_version:x86_64;browser_version:156;network_data:4g"),
        "x-hs-app": "261016000",
        "x-hs-is-retry": "false", "x-hs-retry-count": "0",
    }


hs_http = make_session()
if HS_PROXIES:
    hs_http.proxies = HS_PROXIES


def hs_token(force=False):
    """অতিথি টোকেন। আগে HOTSTAR_TOKEN (Secrets) দেখে, না থাকলে Hotstar-এর start API থেকে আনার চেষ্টা করে।"""
    with _htok_lock:
        if not force and _htok["v"] and time.time() < _htok["exp"]:
            return _htok["v"], _htok["did"]
        tok, did = None, None
        if HS_ENV_TOKEN and not force:
            tok = HS_ENV_TOKEN
            did = (json.loads(_jwt_payload(tok).get("sub", "{}") or "{}")).get("deviceId")
        if not tok:
            did = _hs_device_id()
            r = hs_http.post(f"{HS_BASE}/api/internal/bff/v2/start", json={}, timeout=(5, 15),
                             headers=hs_headers("", did))
            if r.status_code in (401, 403) and not HS_ENV_TOKEN:
                raise AccessDenied(f"Hotstar start API: HTTP {r.status_code}")
            try:
                tok = _find_jwt(r.json())
            except Exception:
                tok = None
            if not tok:
                raise RuntimeError("Hotstar টোকেন পাওয়া যায়নি — Secrets-এ HOTSTAR_TOKEN দিন")
            did = (json.loads(_jwt_payload(tok).get("sub", "{}") or "{}")).get("deviceId") or did
        exp = _jwt_payload(tok).get("exp") or (time.time() + 3600)
        _htok["v"], _htok["did"] = tok, did or _hs_device_id()
        _htok["exp"] = min(float(exp) - 300, time.time() + 6 * 3600)
        return _htok["v"], _htok["did"]


def hs_get_page(real_id):
    """শো পেজের JSON টেক্সট। ৪০৪ হলে None। ৪০১/৪০৩ হলে টোকেন বদলে একবার আবার চেষ্টা।"""
    slug = HS_SLUGS.get("hs-" + real_id) or "show"
    url = f"{HS_BASE}/api/internal/bff/v2/slugs/in/shows/{slug}/{real_id}"
    for attempt in (0, 1):
        tok, did = hs_token(force=attempt == 1 and not HS_ENV_TOKEN)
        r = hs_http.get(url, headers=hs_headers(tok, did), timeout=(5, 20))
        if r.status_code in (400, 404):
            return None
        if r.status_code in (401, 403):
            if attempt == 0:
                continue
            raise AccessDenied(f"Hotstar HTTP {r.status_code}")
        r.raise_for_status()
        return r.text
    return None


def _hs_walk(obj, key):
    """JSON-এর ভেতরে প্রথম যে ডিক্টে `key` আছে তার মান।"""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = _hs_walk(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _hs_walk(v, key)
            if r is not None:
                return r
    return None


def _hs_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _hs_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _hs_strings(v)


def _hs_title_from_ctx(strings, eid):
    """CTA-র protobuf কনটেক্সট থেকে এপিসোডের আসল নাম বের করে (eid-র ঠিক পরে)।"""
    for s in strings:
        if len(s) < 40 or not re.fullmatch(r"[A-Za-z0-9+/=_-]+", s):
            continue
        try:
            raw = base64.b64decode(s + "=" * (-len(s) % 4), altchars=b"-_" if "-" in s or "_" in s else None)
        except Exception:
            continue
        i = raw.find(eid.encode())
        if i < 0:
            continue
        after = raw[i + len(eid):]
        if len(after) > 2 and after[0] == 0x12 and 0 < after[1] < 120 and len(after) >= 2 + after[1]:
            t = after[2:2 + after[1]].decode("utf-8", "ignore").strip()
            if t:
                return t
    return ""


def _hs_date(sub):
    """'29 Oct' -> YYYY-MM-DD (বছর ধরে নেয়া হয়)। না বুঝলে আজকের তারিখ।"""
    now = datetime.now(LOCAL_TZ)
    m = re.match(r"\s*(\d{1,2})\s+([A-Za-z]{3})", sub or "")
    if m:
        try:
            d = datetime.strptime(f"{m.group(1)} {m.group(2)} {now.year}", "%d %b %Y").replace(tzinfo=LOCAL_TZ)
            if d - now > timedelta(days=2):
                d = d.replace(year=now.year - 1)
            return d.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return now.strftime("%Y-%m-%d")


def hs_parse(text, real_id):
    """রিটার্ন: (শো ডিক্ট, [সর্বশেষ এপিসোড]) — না পেলে (শো, [])।"""
    try:
        j = json.loads(text)
    except Exception:
        raise RuntimeError("Hotstar রেসপন্স বোঝা যায়নি")
    strings = list(_hs_strings(j))
    info = _hs_walk(j, "content_info") or {}
    hero = _hs_walk(j, "hero_img") or {}
    img = ("https://img1.hotstarext.com/image/upload/f_auto/" + hero["src"]) if hero.get("src") else ""
    show = {"title": info.get("title") or "", "language": None, "image_url": img}
    m_slug = None
    for s in strings:
        m_slug = re.search(r"/shows/([^/]+)/%s/([^/]+)/(\d{6,})/watch[^\s\"]*" % re.escape(real_id), s)
        if m_slug:
            page_slug = m_slug.group(0)
            break
    if not m_slug:
        return show, []
    ep_slug, eid = m_slug.group(2), m_slug.group(3)
    title = _hs_title_from_ctx(strings, eid) or ep_slug.replace("-", " ").title()
    cta = _hs_walk(j, "primary_cta") or {}
    n_ep = 0
    m_n = re.search(r'numberOfEpisodes\\*"\s*:\s*\\*"(\d+)', text)
    if m_n:
        n_ep = int(m_n.group(1))
    lang_tags = [t.get("value") for t in (info.get("core_meta_tags") or []) if isinstance(t, dict) and t.get("type") == "text"]
    lang = next((x for x in lang_tags if x and not re.fullmatch(r"\d{4}", x)), None)
    show["language"] = lang
    ep = {
        "id": eid, "title": title, "episode_number": n_ep,
        "release_date": _hs_date(cta.get("sublabel")),
        "audio_languages": [lang] if lang else [],
        "image_url": img,
        "link": HS_BASE + "/in" + page_slug if page_slug.startswith("/shows") else HS_BASE + page_slug,
    }
    return show, [ep]


_hs_page = {}


def hs_page_cached(real_id, ttl=20):
    """একই শো-র পেজ ২০ সেকেন্ড ক্যাশ — এপিসোড ও প্রোমো চেক একই রিকোয়েস্ট ব্যবহার করে।"""
    c = _hs_page.get(real_id)
    if c and time.time() - c[0] < ttl:
        return c[1]
    text = hs_get_page(real_id)
    if text:
        _hs_page[real_id] = (time.time(), text)
    return text


def hs_details(real_id):
    text = hs_page_cached(real_id)
    if not text:
        return None, []
    return hs_parse(text, real_id)


def hs_latest_episodes(sid):
    real = sid[3:]
    show, eps = hs_details(real)
    if not show or not show.get("title"):
        raise RuntimeError("Hotstar শো ডিটেইলস পাওয়া যায়নি")
    return show, 1, eps


def fetch_show(sid):
    """সিরিয়াল যোগের সময় লিংক ঠিক কি না যাচাই করতে।"""
    if is_hot(sid):
        show, _ = hs_details(sid[3:])
        return show if show and show.get("title") else None
    if is_sony(sid):
        show, _ = sony_details(sid[3:])
        return show
    return zget(f"{API}/{sid}", {"translation": "en", "country": "IN"})


def sort_key(ep):
    return (release_date(ep), to_int(ep.get("episode_number") or ep.get("orderid")))


# ---------------------------------------------------------------- নোটিফিকেশন (ফাস্ট)
def wants(s, sid, kind):
    """এই সাবস্ক্রাইবার কি এই সিরিয়ালের এই ধরনের নোটিফিকেশন চায়?"""
    if not s.get("on", True) or sid in s.get("muted", []):
        return False
    if kind == "promo":
        return s.get("promo", True)
    if kind == "spoiler":
        return s.get("spoiler", True)
    return True


def notify_all(sid, show, season_no, ep, kind="episode"):
    info = ep_info(show, season_no, ep, sid, SHOW_SLUGS.get(sid, ""), kind)
    store_img(info)
    cap, markup = build_caption(info)
    with lock:
        targets = [int(c) for c, s in state["subs"].items() if wants(s, sid, kind)]
    if not targets:
        return

    # প্রথম জনকে পাঠিয়ে Telegram এর file_id নেওয়া হয়, বাকিদের সেটা দিয়ে একসাথে (প্যারালাল) পাঠানো হয়
    first, rest = targets[0], targets[1:]
    fid, sent = None, False
    for url in info["images"]:                       # ১) ছবির লিংক সরাসরি
        j = tg("sendPhoto", chat_id=first, photo=url, caption=cap,
               parse_mode="HTML", reply_markup=markup)
        if j.get("ok"):
            fid, sent = photo_file_id(j), True
            break
    if not sent:
        for url in info["images"]:                   # ২) নিজে ডাউনলোড করে আপলোড
            data = download_image(url)
            if data:
                j = tg_upload_photo(first, data, cap, markup)
                if j.get("ok"):
                    fid, sent = photo_file_id(j), True
                    break
    if not sent:                                     # ৩) শেষে শুধু টেক্সট
        send_text(first, cap, markup)
    runtime["sent"] += 1

    def send_one(chat_id):
        j = {}
        if fid:
            j = tg("sendPhoto", chat_id=chat_id, photo=fid, caption=cap,
                   parse_mode="HTML", reply_markup=markup)
        if not j.get("ok"):
            j = send_text(chat_id, cap, markup)
        if j.get("ok"):
            runtime["sent"] += 1
        elif j.get("error_code") == 403 and chat_id != OWNER_ID:   # বট ব্লক করেছে — বন্ধ করে দিই
            with lock:
                state["subs"].get(str(chat_id), {})["on"] = False
            mark_dirty()

    if rest:
        list(fan_pool.map(send_one, rest))


def dispatch(sid, show, season_no, new_eps, kind="episode"):
    """নতুন এপিসোডগুলো পুরনো -> নতুন ক্রমে পাঠায় (ব্যাকগ্রাউন্ডে)।"""
    for ep in new_eps:
        try:
            notify_all(sid, show, season_no, ep, kind)
            print(f"[নোটিফাই:{kind}] {show.get('title')} - {ep.get('title')}")
        except Exception as e:
            print("[নোটিফাই ত্রুটি]", e)


# ---------------------------------------------------------------- প্রোমো ও এপিসোড স্পয়লার
extras_pool = ThreadPoolExecutor(3, thread_name_prefix="extras")
_extras_last = {}
_extras_busy = set()
extras_stats = {}                      # sid -> {"ts", "promo", "spoiler", "err", "sample"}
ZEE_EXTRA_TYPES = ("promo", "clip", "spoiler", "preview")      # ZEE5 API-র সম্ভাব্য টাইপ (যেটা পায় সেটাই কাজ করে)
_WATCH_RE_T = r"/shows/[^/]+/%s/([^/]+)/(\d{6,})/watch[^\s\"]*"


def classify_extra(*parts):
    t = " ".join(str(p) for p in parts if p).lower()
    if any(w in t for w in SPOILER_WORDS):
        return "spoiler"
    if any(w in t for w in PROMO_WORDS):
        return "promo"
    return None


def _titled_dicts(obj, out, depth=0):
    if depth > 30:
        return
    if isinstance(obj, dict):
        if obj.get("id") and isinstance(obj.get("title") or obj.get("original_title"), str):
            out.append(obj)
        for v in obj.values():
            if isinstance(v, (dict, list)):
                _titled_dicts(v, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _titled_dicts(v, out, depth + 1)


def zee_extras(sid):
    c = season_cache.get(sid)
    if not c:
        return []
    cand = []
    _titled_dicts(c["show"], cand)
    try:
        season_id = c["seasons"][c["use"]]["id"]
    except Exception:
        season_id = None
    if season_id:
        for t in ZEE_EXTRA_TYPES:
            try:
                page = zget(API + "/", {"season_id": season_id, "translation": "en", "country": "IN",
                                        "type": t, "page": 1, "limit": 50})
            except AccessDenied:
                raise
            except Exception:
                continue
            if page:
                _titled_dicts(page, cand)
    out = []
    for it in cand:
        sub = " ".join(str(it.get(k) or "") for k in ("asset_subtype", "asset_type", "sub_type", "type"))
        kind = classify_extra(it.get("title"), it.get("original_title"), sub)
        if kind:
            d = dict(it)
            d["kind"] = kind
            out.append(d)
    return out


def sony_extras(sid):
    res = sget(f"1.9/R/ENG/WEB/IN/DL/DETAIL/{sid[3:]}", {"kids_safe": "false", "from": 0, "to": 49})
    out, slug = [], SHOW_SLUGS.get(sid, "")

    def walk(o, depth=0):
        if depth > 30:
            return
        if isinstance(o, dict):
            m = o.get("metadata")
            if isinstance(m, dict) and o.get("id"):
                sub = str(m.get("contentSubtype") or m.get("objectSubtype") or "")
                if sub.upper() not in ("EPISODE", "SEASON", "SHOW"):
                    kind = classify_extra(m.get("title"), m.get("episodeTitle"), sub)
                    if kind:
                        d = sony_norm(o, {})
                        d["kind"] = kind
                        d["link"] = sony_episode_link(d, slug)
                        out.append(d)
            for v in o.values():
                if isinstance(v, (dict, list)):
                    walk(v, depth + 1)
        elif isinstance(o, list):
            for v in o:
                walk(v, depth + 1)

    walk(res)
    return out


def hs_extras(sid):
    real = sid[3:]
    text = hs_page_cached(real)
    if not text:
        return []
    try:
        j = json.loads(text)
    except Exception:
        return []
    show, _ = hs_parse(text, real)
    pat = re.compile(_WATCH_RE_T % re.escape(real))
    out, seen = [], set()

    def walk(o, title, depth=0):
        if depth > 40:
            return
        if isinstance(o, dict):
            ci = o.get("content_info")
            t = (ci.get("title") if isinstance(ci, dict) else None) or (
                o.get("title") if isinstance(o.get("title"), str) else None) or title
            for v in o.values():
                walk(v, t, depth + 1)
        elif isinstance(o, list):
            for v in o:
                walk(v, title, depth + 1)
        elif isinstance(o, str):
            m = pat.search(o)
            if m and m.group(2) not in seen:
                ep_slug, cid = m.group(1), m.group(2)
                kind = classify_extra(title, ep_slug.replace("-", " "))
                if kind:
                    seen.add(cid)
                    path = m.group(0)
                    out.append({
                        "id": cid, "kind": kind,
                        "title": (title if title and title != show.get("title") else ep_slug.replace("-", " ").title()),
                        "release_date": "", "audio_languages": [show.get("language")] if show.get("language") else [],
                        "image_url": show.get("image_url") or "",
                        "link": HS_BASE + ("/in" + path if path.startswith("/shows") else path),
                    })

    walk(j, "")
    return out


def fetch_extras(sid):
    if is_hot(sid):
        return hs_extras(sid)
    if is_sony(sid):
        return sony_extras(sid)
    return zee_extras(sid)


def check_extras(sid, show):
    items = fetch_extras(sid)
    today = datetime.now(LOCAL_TZ)
    uniq = {}
    for it in items:
        if it.get("id"):
            uniq.setdefault(f"{it['kind']}:{it['id']}", it)
    extras_stats[sid] = {
        "ts": time.time(), "err": "",
        "promo": sum(1 for it in uniq.values() if it["kind"] == "promo"),
        "spoiler": sum(1 for it in uniq.values() if it["kind"] == "spoiler"),
        "sample": [str(it.get("title"))[:40] for it in list(uniq.values())[:2]],
    }
    if not uniq:
        return                                       # কিছু পাওয়া না গেলে বেসলাইন বসাই না (ভুয়া "নতুন" এড়াতে)
    keys = list(uniq)
    with lock:
        seen = state["seen_x"].get(sid)
        if seen is None:                             # প্রথমবার: সব রেকর্ড, নোটিফিকেশন নয়
            state["seen_x"][sid] = keys[:3000]
            new = []
        else:
            ss = set(seen)
            fresh = [k for k in keys if k not in ss]
            new = [uniq[k] for k in fresh]
            if fresh:
                state["seen_x"][sid] = (fresh + seen)[:3000]
    mark_dirty()
    sent = 0
    for it in reversed(new):                         # পুরনো -> নতুন
        rd = release_date(it)[:10]
        try:
            if rd and datetime.strptime(rd, "%Y-%m-%d").replace(tzinfo=LOCAL_TZ) < today - timedelta(days=3):
                continue                             # অনেক পুরনো আইটেম হঠাৎ দেখা গেলে নোটিফিকেশন নয়
        except ValueError:
            pass
        if sent >= 4:
            break
        if not rd:
            it = dict(it, release_date=today.strftime("%Y-%m-%d"))
        notify_pool.submit(dispatch, sid, show, 1, [it], it["kind"])
        sent += 1


def _run_extras(sid, show):
    try:
        check_extras(sid, show)
    except AccessDenied:
        pass
    except Exception as e:
        print(f"[এক্সট্রা ত্রুটি] {sid}: {e}")
        extras_stats[sid] = {"ts": time.time(), "err": str(e)[:80], "promo": 0, "spoiler": 0, "sample": []}
    finally:
        with lock:
            _extras_busy.discard(sid)


def maybe_extras(sid, show):
    """প্রোমো/স্পয়লার আলাদা থ্রেডে, EXTRAS_INTERVAL সেকেন্ড পরপর — এপিসোড চেক ধীর হয় না।"""
    now = time.time()
    with lock:
        if sid in _extras_busy or now - _extras_last.get(sid, 0) < EXTRAS_INTERVAL:
            return
        _extras_busy.add(sid)
        _extras_last[sid] = now
    extras_pool.submit(_run_extras, sid, show)


def extras_report():
    lines = ["🧪 <b>প্রোমো / স্পয়লার রিপোর্ট</b>", LINE]
    for p in OTT_ORDER:
        ids = [s for s in grouped_ids() if provider(s) == p]
        if not ids:
            continue
        lines.append(f"\n{OTT_ICON[p]} <b>{PNAME[p]}</b>")
        for sid in ids:
            st = extras_stats.get(sid)
            if not st:
                row = "⏳ এখনো চেক হয়নি"
            elif st.get("err"):
                row = f"⚠️ {escape(st['err'])}"
            else:
                row = f"🎬 {st['promo']}  👀 {st['spoiler']}"
                if st.get("sample"):
                    row += f"  <i>({escape('; '.join(st['sample']))})</i>"
            lines.append(f"• {escape(show_name(sid))}: {row}")
    lines.append("\n💡 সবখানে 🎬 0 👀 0 এলে ওই OTT-র পেজে প্রোমো/স্পয়লার আলাদা API থেকে আসে — আমাকে জানান।")
    return "\n".join(lines)[:4000]


def check_show(sid):
    """রিটার্ন: ok / denied / error"""
    try:
        show, season_no, eps = latest_episodes(sid)
    except AccessDenied as e:
        print(f"[ব্লক] {sid}: {e}")
        return "denied"
    except Exception as e:
        print(f"[ত্রুটি] {sid}: {e}")
        return "error"
    if sid in SHOW_SLUGS:
        maybe_extras(sid, show)
    if not eps or sid not in SHOW_SLUGS:
        return "ok"

    slug = SHOW_SLUGS.get(sid, "")
    eps = sorted(eps, key=sort_key, reverse=True)    # নতুন আগে
    newest = ep_info(show, season_no, eps[0], sid, slug)
    ids = [e["id"] for e in eps if e.get("id")]
    with lock:
        state["names"][sid] = show.get("title") or show.get("original_title") or sid
        state["latest"][sid] = {
            "show": newest["show"], "label": newest["label"], "link": newest["link"],
            "date": newest["date_raw"], "date_s": newest["short_date"],
            "platform": newest["platform"], "images": newest["images"], "ep_title": newest["title"],
        }
        seen = state["seen"].get(sid)
        if seen is None:                              # প্রথমবার: সব আইডি রেকর্ড, নোটিফিকেশন নয়
            state["seen"][sid] = ids[:3000]
            new_eps = []
        else:
            seen_set = set(seen)
            new_eps = [e for e in eps if e.get("id") and e["id"] not in seen_set]
            if new_eps:                               # আগে "দেখা" মার্ক, তারপর পাঠানো — ডুপ্লিকেট হবে না
                new_ids = [e["id"] for e in new_eps]
                state["seen"][sid] = (new_ids + seen)[:3000]
    mark_dirty()

    if new_eps:
        # নিরাপত্তা: হঠাৎ অনেক "নতুন" দেখা গেলে শুধু সবচেয়ে নতুন ৩টার নোটিফিকেশন যাবে
        batch = list(reversed(new_eps[:3]))           # পুরনো -> নতুন
        notify_pool.submit(dispatch, sid, show, season_no, batch)
    return "ok"


def checker():
    first_cycle = True
    while True:
        t0 = time.time()
        all_ids = list(SHOW_SLUGS)
        ids = [x for x in all_ids if t0 >= blocks[provider(x)]["until"]]
        if all_ids and not ids:                       # সব প্ল্যাটফর্মই বিরতিতে
            nearest = min(blocks[provider(x)]["until"] for x in all_ids)
            time.sleep(min(30, max(2, nearest - t0)))
            continue

        results = list(check_pool.map(lambda x: (provider(x), check_show(x)), ids)) if ids else []

        for p, b in blocks.items():                   # ব্লক ধরা হয় প্ল্যাটফর্ম ধরে — একটা ব্লক হলে অন্যটা থামে না
            rs = [r for pp, r in results if pp == p]
            if "denied" in rs:
                b["until"] = time.time() + b["wait"]
                if not b["alerted"]:
                    b["alerted"] = True
                    env = {"sony": "SONY_PROXY_URL", "hotstar": "HOTSTAR_PROXY_URL"}.get(p, "PROXY_URL")
                    send_text(OWNER_ID, f"⚠️ {PNAME[p]} অ্যাক্সেস ব্লক (HTTP 403)।\n"
                                        f"{b['wait'] // 60} মিনিট বিরতি দিয়ে আবার চেষ্টা হবে।\n"
                                        f"💡 ইন্ডিয়ান IP/প্রক্সি ({env}) থেকে চালালে ভালো হয়।")
                b["wait"] = min(b["wait"] * 2, 1800)
                print(f"[ব্লক] {PNAME[p]}: {int(b['until'] - time.time())} সেকেন্ড বিরতি")
            elif "ok" in rs:
                b["wait"], b["alerted"] = 300, False

        runtime["last_check"] = time.time()
        runtime["cycle"] = time.time() - t0

        if first_cycle:
            first_cycle = False
            lines = []
            for p in ("zee5", "sony", "hotstar"):
                tot = sum(1 for pp, _ in results if pp == p)
                ok = sum(1 for pp, r in results if pp == p and r == "ok")
                if tot:
                    lines.append(f"• {PNAME[p]}: {ok}/{tot} চেক হয়েছে" + ("" if ok == tot else " ⚠️"))
            send_text(OWNER_ID,
                      f"✅ <b>বট চালু হয়েছে!</b>\n{LINE}\n"
                      f"🎬 মোট {len(all_ids)}টি সিরিয়াল\n" + "\n".join(lines) + "\n"
                      f"⏱ প্রতি {CHECK_INTERVAL} সেকেন্ডে চেক হবে",
                      main_menu(OWNER_ID))
        time.sleep(max(1, CHECK_INTERVAL - (time.time() - t0)) + random.uniform(0, 0.5))


# ---------------------------------------------------------------- স্টার্টআপ
def setup_commands():
    base = [
        {"command": "start", "description": "🏠 মূল মেনু"},
        {"command": "latest", "description": "📺 সর্বশেষ এপিসোড"},
        {"command": "shows", "description": "🎯 সিরিয়াল বাছাই"},
        {"command": "settings", "description": "⚙️ প্রোমো / স্পয়লার সেটিংস"},
        {"command": "notify", "description": "🔔 নোটিফিকেশন চালু/বন্ধ"},
        {"command": "status", "description": "📊 বট স্ট্যাটাস"},
        {"command": "help", "description": "ℹ️ সাহায্য"},
    ]
    tg("setMyCommands", commands=base)
    admin_cmds = base + [
        {"command": "add", "description": "➕ সিরিয়াল যোগ (লিংক দিন)"},
        {"command": "remove", "description": "🗑 সিরিয়াল সরান"},
        {"command": "test", "description": "🧪 নমুনা নোটিফিকেশন"},
        {"command": "extras", "description": "🎬 প্রোমো/স্পয়লার রিপোর্ট"},
        {"command": "restart", "description": "♻️ বট রিস্টার্ট"},
    ]
    for aid in ADMIN_IDS:
        tg("setMyCommands", commands=admin_cmds, scope={"type": "chat", "chat_id": aid})
    tg("setChatMenuButton", menu_button={"type": "commands"})


class _Ping(BaseHTTPRequestHandler):
    def _ok(self, body=True):
        data = "OTT Bot (ZEE5 + SonyLIV + JioHotstar) is running ✅".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if body:
            self.wfile.write(data)

    def do_GET(self):
        self._ok()

    def do_HEAD(self):
        self._ok(False)

    def log_message(self, *a):
        pass


def start_keepalive():
    """Replit-এ Run দিলে ওয়েব পোর্ট খোলা থাকে; UptimeRobot দিয়ে এই লিংকে পিং করলে বট ঘুমায় না।"""
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", KEEPALIVE_PORT), _Ping)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        print(f"🌐 কিপ-অ্যালাইভ সার্ভার চালু (পোর্ট {KEEPALIVE_PORT})")
    except OSError as e:
        print("কিপ-অ্যালাইভ সার্ভার চালু হয়নি:", e)


def main():
    if ":" not in BOT_TOKEN:
        print("❌ BOT_TOKEN পাওয়া যায়নি।\n"
              "   Replit-এর 🔒 Secrets-এ BOT_TOKEN নামে BotFather-এর টোকেন বসান।")
        raise SystemExit(1)

    load_state()
    removed = set(state["removed"])
    for link in SHOW_LINKS + state["links"]:
        sid = show_id_from(link)
        if sid and sid not in removed:
            register_link(link)
    if not SHOW_SLUGS:
        print("⚠️ এখনো কোনো সিরিয়াল নেই — বটে ZEE5/SonyLIV/JioHotstar লিংক পাঠান বা SHOW_LINKS এ বসান।")

    start_keepalive()
    setup_commands()
    note = state.pop("restart_notice", None)          # রিস্টার্টের পর অ্যাডমিনকে জানাই
    if note and time.time() - note.get("t", 0) < 300:
        edit_text(note["chat_id"], note["msg_id"],
                  "✅ <b>বট রিস্টার্ট সম্পন্ন!</b>\nআবার চালু হয়ে গেছে।", status_markup(note["chat_id"]))
        mark_dirty()
    threading.Thread(target=saver, daemon=True).start()
    threading.Thread(target=poller, daemon=True).start()
    print(f"বট চালু হয়েছে ({len(SHOW_SLUGS)}টি সিরিয়াল)... বন্ধ করতে Ctrl+C")
    try:
        checker()
    except KeyboardInterrupt:
        print("বন্ধ করা হচ্ছে...")
    finally:
        save_state()


if __name__ == "__main__":
    main()
