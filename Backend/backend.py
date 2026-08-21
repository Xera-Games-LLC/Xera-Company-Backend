"""
Xera Company Private Server, by Juelz Irons
For AC 1.60 - 1.75 (Quest AND Steam supported!)

This is months of Animal Company RE work, released free for everyone.
If you use this, please star the repo! it costs nothing and helps a ton:
https://github.com/Xera-Games-LLC/Xera-Company-Backend

I highly reccomend using PythonAnywhere for this.
I will not support people in setting up the server or redirecting animal company to their backend, thats on you.
"""

from flask import Flask, request, jsonify, g, send_file
import json
import secrets
import base64
import time
import sqlite3
import hashlib
import os
import threading
import requests as http_requests
from datetime import datetime, timezone, timedelta
import pytz

app = Flask(__name__)


# +-------------------------------------------------------------------------+
# ✦  SERVER CONFIG - edit this section to configure your own server         ✦
# ✦  BACKEND MADE BY XERA!                                                  ✦
# ✦  If this backend is powering your server, please star the repo:         ✦
# ✦  https://github.com/Xera-Games-LLC/Xera-Company-Backend                 ✦
# +-------------------------------------------------------------------------+


# ---- Access control ---------------------------------------------------
# Usernames that get developer/admin menu in-game.
DEV_USERNAMES           = {"juelzirons"}

# Usernames that are blocked from the server entirely.
BANNED_USERNAMES        = {"NONE", "NONE", "NONE", "NONE", "NONE"}

# IP addresses that are blocked from the server entirely. Add IPs as strings,
BANNED_IPS              = {""}

# The one IP that's allowed to use the in-game dev menu and that triggers
# the debug webhook below. Set this to your own IP.
DEV_IP                  = "127.0.0.1"

# ---- Secrets (set these via environment variables, see note above) ----
# Random string you invent yourself; required in the `X-Dev-Secret` header
# to call the /AddUserToDevMenu and /RemoveUserFromDevMenu endpoints.
DISCORD_DEV_SECRET      = os.environ.get("XERA_DISCORD_DEV_SECRET", "")

# Access token used to verify Meta/Oculus platform-integrity attestation.
META_ACCESS_TOKEN       = os.environ.get("XERA_META_ACCESS_TOKEN", "")

# Discord webhook URL that receives a live feed of requests/responses from
# DEV_IP when DEBUG_WEBHOOK_ENABLED is True. Leave the env var unset (empty)
# to effectively disable it even if DEBUG_WEBHOOK_ENABLED is True.
DEBUG_WEBHOOK_URL       = os.environ.get("XERA_DEBUG_WEBHOOK_URL", "")

DISCORD_DEV_DB_PATH     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "discord_devs.db")

def _discord_dev_db():
    conn = sqlite3.connect(DISCORD_DEV_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS discord_devs (oculus_username TEXT PRIMARY KEY COLLATE NOCASE, discord_id TEXT NOT NULL)")
    conn.commit()
    return conn

def is_discord_dev(username):
    """Look up whether `username` has been linked to a Discord dev via the
    /AddUserToDevMenu endpoint."""
    if not username:
        return False
    try:
        conn = _discord_dev_db()
        row = conn.execute("SELECT 1 FROM discord_devs WHERE oculus_username = ? COLLATE NOCASE", (username,)).fetchone()
        conn.close()
        return row is not None
    except Exception:
        return False

# Turn the debug webhook on/off entirely. When on, every request/response
# from DEV_IP gets posted to DEBUG_WEBHOOK_URL as a Discord embed.
DEBUG_WEBHOOK_ENABLED   = True

# ---- Currency / economy settings ---------------------------------------
EST_TIMEZONE            = pytz.timezone("America/New_York")

# Balances players are set to while "weekend mode" is active (see
# is_weekend_est() below). Currently absurdly high on purpose.
WEEKEND_SOFT            = 9999999
WEEKEND_HARD            = 9999999
WEEKEND_RESEARCH        = 9999999

# Starting/weekly-reset balances used the rest of the week.
WEEKDAY_STARTING_HARD     = 5000
WEEKDAY_STARTING_RESEARCH = 10
WEEKDAY_STARTING_SOFT     = 100


# +-------------------------------------------------------------------------+
# ✦  WEEKEND CHECK                                                         ✦
# +-------------------------------------------------------------------------+
# Controls whether WEEKEND_* balances (see SERVER CONFIG above) are active.
# Currently hardcoded to always return True. Swap in the commented-out
# version below if you want it to actually only be true on Sat/Sun in EST.

def is_weekend_est():
    return True

# def is_weekend_est():
#     now_est = datetime.now(EST_TIMEZONE)
#     return now_est.weekday() >= 5


# +-------------------------------------------------------------------------+
# ✦  DEBUG WEBHOOK                                                         ✦
# +-------------------------------------------------------------------------+

@app.after_request
def debug_webhook(response):
    if not DEBUG_WEBHOOK_ENABLED:
        return response
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    if ip != DEV_IP:
        return response
    try:
        body = request.get_data(as_text=True)
        try:
            body_fmt = json.dumps(json.loads(body), indent=2)
        except Exception:
            body_fmt = body or "(empty)"
        try:
            resp_body = response.get_data(as_text=True)
            try:
                resp_fmt = json.dumps(json.loads(resp_body), indent=2)
            except Exception:
                resp_fmt = resp_body or "(empty)"
        except Exception:
            resp_fmt = "(unreadable)"
        embed = {
            "title": f"{request.method} {request.path} -> {response.status_code}",
            "fields": [
                {"name": "Full URL",       "value": request.url[:1024],                                          "inline": False},
                {"name": "Request Body",   "value": f"```json\n{body_fmt[:900]}\n```" if body_fmt else "*(empty)*", "inline": False},
                {"name": "Response",       "value": f"```json\n{resp_fmt[:900]}\n```" if resp_fmt else "*(empty)*", "inline": False},
            ],
            "color": 0x57F287 if response.status_code < 400 else 0xED4245,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        threading.Thread(
            target=lambda: http_requests.post(DEBUG_WEBHOOK_URL, json={"embeds": [embed]}, timeout=5),
            daemon=True
        ).start()
    except Exception:
        pass
    return response


# +-------------------------------------------------------------------------+
# ✦  IP BAN MIDDLEWARE                                                     ✦
# +-------------------------------------------------------------------------+

@app.before_request
def enforce_ip_ban():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    if ip in BANNED_IPS:
        return jsonify({"error": "banned", "message": "You have been IP banned from Xera Company. Boo hoo"}), 403


# +-------------------------------------------------------------------------+
# ✦  PATHS & EXTERNAL SERVICE IDS                                          ✦
# +-------------------------------------------------------------------------+

# Local file paths - these are computed automatically, no need to touch them.
SCRIPT_DIR      = os.path.dirname(os.path.abspath(__file__))
DB_PATH         = os.path.join(SCRIPT_DIR, "Data.db")
ITEMS_PATH      = os.path.join(SCRIPT_DIR, "items.json")
GAME_DATA_PATH  = os.path.join(SCRIPT_DIR, "game-data-prod.zip")

# Public URL where the client downloads game-data-prod.zip from. Update this
# to wherever you're actually hosting the server.
GAME_DATA_URL   = os.environ.get("XERA_GAME_DATA_URL", "https://juelz.pythonanywhere.com/game-data-prod.zip")

# Photon (Exit Games) multiplayer app IDs. Get your own from
# https://dashboard.photonengine.com if you're standing up your own server -
# reusing someone else's will fight over the same connection quota.
PHOTON_APP_ID       = os.environ.get("XERA_PHOTON_APP_ID", "")
PHOTON_VOICE_APP_ID = os.environ.get("XERA_PHOTON_VOICE_APP_ID", "")


# +-------------------------------------------------------------------------+
# ✦  DATABASE                                                              ✦
# +-------------------------------------------------------------------------+

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     TEXT PRIMARY KEY,
            username    TEXT NOT NULL,
            custom_id   TEXT NOT NULL UNIQUE,
            ip          TEXT NOT NULL DEFAULT '',
            lang_tag    TEXT NOT NULL DEFAULT 'en',
            metadata    TEXT NOT NULL DEFAULT '{}',
            create_time TEXT NOT NULL,
            update_time TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS wallets (
            user_id          TEXT PRIMARY KEY REFERENCES users(user_id),
            soft_currency    INTEGER NOT NULL DEFAULT 100,
            hard_currency    INTEGER NOT NULL DEFAULT 5000,
            research_points  INTEGER NOT NULL DEFAULT 10,
            fish_currency    INTEGER NOT NULL DEFAULT 0,
            stash_rows       INTEGER NOT NULL DEFAULT 2,
            stash_cols       INTEGER NOT NULL DEFAULT 4
        );
        CREATE TABLE IF NOT EXISTS storage (
            user_id          TEXT NOT NULL REFERENCES users(user_id),
            collection       TEXT NOT NULL,
            key              TEXT NOT NULL,
            value            TEXT NOT NULL DEFAULT '{}',
            version          TEXT NOT NULL,
            permission_read  INTEGER NOT NULL DEFAULT 1,
            permission_write INTEGER NOT NULL DEFAULT 1,
            create_time      TEXT NOT NULL,
            update_time      TEXT NOT NULL,
            PRIMARY KEY (user_id, collection, key)
        );
        CREATE TABLE IF NOT EXISTS purchases (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        TEXT NOT NULL REFERENCES users(user_id),
            product_id     TEXT NOT NULL,
            transaction_id TEXT NOT NULL,
            store          INTEGER NOT NULL DEFAULT 3,
            purchase_time  INTEGER NOT NULL,
            create_time    INTEGER NOT NULL,
            environment    INTEGER NOT NULL DEFAULT 2
        );
        CREATE TABLE IF NOT EXISTS promo_codes (
            code                  TEXT PRIMARY KEY,
            reward_soft           INTEGER NOT NULL DEFAULT 0,
            reward_hard           INTEGER NOT NULL DEFAULT 0,
            reward_research       INTEGER NOT NULL DEFAULT 0,
            reward_avatar_items   TEXT NOT NULL DEFAULT '[]',
            reward_research_items TEXT NOT NULL DEFAULT '[]',
            max_redemptions       INTEGER NOT NULL DEFAULT -1,
            times_redeemed        INTEGER NOT NULL DEFAULT 0,
            active                INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS promo_redemptions (
            user_id     TEXT NOT NULL,
            code        TEXT NOT NULL,
            redeemed_at INTEGER NOT NULL,
            PRIMARY KEY (user_id, code)
        );
        CREATE TABLE IF NOT EXISTS daily_mission_progress (
            user_id    TEXT NOT NULL,
            mission_id TEXT NOT NULL,
            date_key   TEXT NOT NULL,
            progress   TEXT NOT NULL DEFAULT '',
            completed  INTEGER NOT NULL DEFAULT 0,
            collected  INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, mission_id, date_key)
        );
        CREATE TABLE IF NOT EXISTS scavenger_hunt_progress (
            user_id   TEXT NOT NULL,
            hunt_id   TEXT NOT NULL,
            item_ids  TEXT NOT NULL DEFAULT '[]',
            completed INTEGER NOT NULL DEFAULT 0,
            collected INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, hunt_id)
        );
        CREATE TABLE IF NOT EXISTS private_rooms (
            code                  TEXT PRIMARY KEY,
            owner                 TEXT NOT NULL,
            expires_at            INTEGER NOT NULL,
            members               TEXT NOT NULL DEFAULT '[]',
            members_only          INTEGER NOT NULL DEFAULT 0,
            members_can_moderate  INTEGER NOT NULL DEFAULT 0,
            members_can_manage    INTEGER NOT NULL DEFAULT 0,
            friendly_fire         INTEGER NOT NULL DEFAULT 0,
            banned_users          TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS user_reports (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id    TEXT NOT NULL,
            target_user_id TEXT NOT NULL,
            reason         TEXT NOT NULL,
            created_at     INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS quest_progress (
            user_id   TEXT PRIMARY KEY,
            version   INTEGER NOT NULL DEFAULT 1,
            completed TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS currency_reset_log (
            user_id    TEXT PRIMARY KEY,
            last_reset TEXT NOT NULL
        );
    """)
    try:
        cur.execute("SELECT fish_currency FROM wallets LIMIT 1")
    except sqlite3.OperationalError:
        cur.execute("ALTER TABLE wallets ADD COLUMN fish_currency INTEGER NOT NULL DEFAULT 0")
    conn.commit()
    conn.close()

init_db()


# +-------------------------------------------------------------------------+
# ✦  CURRENCY RESET LOGIC                                                  ✦
# +-------------------------------------------------------------------------+

def get_current_monday_key():
    now_est = datetime.now(EST_TIMEZONE)
    days_since_monday = now_est.weekday()
    monday = now_est - timedelta(days=days_since_monday)
    return monday.strftime("%Y-%m-%d")

def maybe_reset_weekly_currency(user_id):
    if is_weekend_est():
        return
    db = get_db()
    current_monday = get_current_monday_key()
    row = db.execute("SELECT last_reset FROM currency_reset_log WHERE user_id = ?", (user_id,)).fetchone()
    if row and row["last_reset"] == current_monday:
        return
    db.execute("UPDATE wallets SET soft_currency = ? WHERE user_id = ?", (WEEKDAY_STARTING_SOFT, user_id))
    db.execute("""
        INSERT INTO currency_reset_log (user_id, last_reset) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET last_reset = excluded.last_reset
    """, (user_id, current_monday))
    db.commit()


# +-------------------------------------------------------------------------+
# ✦  INTERNAL HELPERS                                                      ✦
# +-------------------------------------------------------------------------+

def iso_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def make_version():
    return hashlib.md5(secrets.token_bytes(16)).hexdigest()

def safe_json_body(req):
    body = req.get_json(force=True, silent=True)
    if body is None:
        return {}
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except Exception:
            return {}
    if isinstance(body, dict):
        return body
    return {}

def parse_rpc_payload(req):
    body = safe_json_body(req)
    if "payload" not in body:
        return body
    payload = body["payload"]
    if isinstance(payload, dict):
        return payload
    try:
        return json.loads(payload)
    except Exception:
        return {}

def b64url(obj):
    return base64.urlsafe_b64encode(json.dumps(obj, separators=(",", ":")).encode()).decode().rstrip("=")

def make_jwt(user_id, username):
    now = int(time.time())
    header  = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "tid": secrets.token_hex(16),
        "uid": user_id,
        "usn": username,
        "vrs": {"clientUserAgent": "MetaQuest 1.61.2.0000_5edcbd98", "loginType": "meta_quest"},
        "exp": now + 7200,
        "iat": now,
    }
    return f"{b64url(header)}.{b64url(payload)}.{secrets.token_urlsafe(32)}"

def extract_uid_from_token():
    auth  = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "").strip()
    if not token:
        return None
    try:
        payload_b64  = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload      = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload.get("uid")
    except Exception:
        return None

def get_client_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr)

def get_or_create_user(custom_id, username):
    db  = get_db()
    ip  = get_client_ip()
    now = iso_now()

    row = db.execute(
        "SELECT user_id, custom_id FROM users WHERE username = ? ORDER BY update_time DESC LIMIT 1",
        (username,)
    ).fetchone()
    if row:
        user_id = row["user_id"]
        if row["custom_id"] != custom_id:
            try:
                db.execute("UPDATE users SET custom_id = ?, ip = ?, update_time = ? WHERE user_id = ?",
                           (custom_id, ip, now, user_id))
                db.commit()
            except sqlite3.IntegrityError:
                db.execute("UPDATE users SET ip = ?, update_time = ? WHERE user_id = ?", (ip, now, user_id))
                db.commit()
        else:
            db.execute("UPDATE users SET ip = ?, update_time = ? WHERE user_id = ?", (ip, now, user_id))
            db.commit()
        if not db.execute("SELECT user_id FROM wallets WHERE user_id = ?", (user_id,)).fetchone():
            db.execute("INSERT INTO wallets (user_id, soft_currency, hard_currency, research_points) VALUES (?, ?, ?, ?)",
                       (user_id, WEEKDAY_STARTING_SOFT, WEEKDAY_STARTING_HARD, WEEKDAY_STARTING_RESEARCH))
            db.commit()
        return user_id

    row = db.execute("SELECT user_id FROM users WHERE custom_id = ?", (custom_id,)).fetchone()
    if row:
        user_id = row["user_id"]
        db.execute("UPDATE users SET username = ?, ip = ?, update_time = ? WHERE user_id = ?",
                   (username, ip, now, user_id))
        db.commit()
        if not db.execute("SELECT user_id FROM wallets WHERE user_id = ?", (user_id,)).fetchone():
            db.execute("INSERT INTO wallets (user_id, soft_currency, hard_currency, research_points) VALUES (?, ?, ?, ?)",
                       (user_id, WEEKDAY_STARTING_SOFT, WEEKDAY_STARTING_HARD, WEEKDAY_STARTING_RESEARCH))
            db.commit()
        return user_id

    raw_id  = secrets.token_hex(16)
    user_id = f"{raw_id[:8]}-{raw_id[8:12]}-{raw_id[12:16]}-{raw_id[16:20]}-{raw_id[20:]}"

    db.execute(
        "INSERT INTO users (user_id, username, custom_id, ip, create_time, update_time) VALUES (?,?,?,?,?,?)",
        (user_id, username, custom_id, ip, now, now)
    )
    db.execute(
        "INSERT INTO wallets (user_id, soft_currency, hard_currency, research_points) VALUES (?, ?, ?, ?)",
        (user_id, WEEKDAY_STARTING_SOFT, WEEKDAY_STARTING_HARD, WEEKDAY_STARTING_RESEARCH)
    )

    storage_defaults = [
        ("user_avatar", "0", json.dumps({
            "head": "bp_head_gorilla", "torso": "bp_torso_gorilla",
            "armLeft": "bp_arm_l_gorilla", "armRight": "bp_arm_r_gorilla",
            "eyeLeft": "bp_eye_gorilla", "eyeRight": "bp_eye_gorilla",
            "butt": "bp_butt_gorilla", "tail": "", "accessories": [],
            "primaryColor": "604170",
        }), 2, 0),
        ("user_inventory", "avatar", json.dumps({
            "items": ["animal_gorilla", "bp_head_gorilla", "bp_eye_gorilla",
                      "bp_torso_gorilla", "bp_arm_l_gorilla", "bp_arm_r_gorilla", "bp_butt_gorilla"]
        }), 1, 1),
        ("user_inventory", "research", json.dumps({"nodes": []}), 1, 1),
        ("user_inventory", "stash", json.dumps(
            {"items": [], "materials": [], "stashPos": 0, "version": 1}
        ), 1, 1),
        ("user_inventory", "gameplay_loadout",  json.dumps({"version": 1}), 1, 1),
        ("user_preferences", "gameplay_items",  json.dumps({"recents": [], "favorites": []}), 1, 1),
    ]

    storage_defaults += [
        ("user_inventory",  "upgrades",          json.dumps({"upgrades": []}), 1, 1),
        ("user_inventory",  "fishing",            json.dumps({"baitSystemUnlocked": False, "rods": [], "fish": {}, "baits": {}}), 1, 1),
        ("user_inventory",  "loadout_templates",  json.dumps([]), 1, 1),
        ("user_inventory",  "blueprints",         json.dumps([]), 1, 1),
        ("user_preferences","skills",             json.dumps({"disabledSkills": []}), 1, 1),
        ("user_preferences","settings",           json.dumps({
            "appearOffline": False, "arachnophobiaMode": False,
            "isMicMuted": False, "megaphonesMuted": False,
            "snapTurnEnabled": False, "snapTurnIncrement": 45,
            "selectedLoadoutSlot": "", "masterVolume": 1.0,
            "smoothTurnEnabled": False, "smoothTurnSpeed": 1.0,
            "rightHandedWatch": True, "thumbstickDeadzone": 0.15,
        }), 1, 1),
    ]

    for coll, key, val, pread, pwrite in storage_defaults:
        ver = make_version()
        db.execute(
            "INSERT INTO storage (user_id,collection,key,value,version,permission_read,permission_write,create_time,update_time)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (user_id, coll, key, val, ver, pread, pwrite, now, now)
        )

    db.execute("INSERT OR IGNORE INTO quest_progress (user_id, version, completed) VALUES (?, 1, '[]')", (user_id,))

    db.commit()
    return user_id

def fetch_wallet(user_id):
    db  = get_db()
    row = db.execute("SELECT * FROM wallets WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        db.execute(
            "INSERT INTO wallets (user_id, soft_currency, hard_currency, research_points) VALUES (?, ?, ?, ?)",
            (user_id, WEEKDAY_STARTING_SOFT, WEEKDAY_STARTING_HARD, WEEKDAY_STARTING_RESEARCH)
        )
        db.commit()
        row = db.execute("SELECT * FROM wallets WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row)

def serialize_wallet(wallet, user_id=None):
    if is_weekend_est():
        return {
            "softCurrency":    WEEKEND_SOFT,
            "hardCurrency":    WEEKEND_HARD,
            "researchPoints":  WEEKEND_RESEARCH,
        }
    return {
        "softCurrency":   wallet["soft_currency"],
        "hardCurrency":   wallet["hard_currency"],
        "researchPoints": wallet["research_points"],
    }

def fetch_user(user_id):
    return get_db().execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

def fetch_all_storage(user_id):
    rows = get_db().execute("SELECT * FROM storage WHERE user_id = ?", (user_id,)).fetchall()
    return [dict(r) for r in rows]

def serialize_storage_object(obj):
    return {
        "collection":       obj["collection"],
        "key":              obj["key"],
        "user_id":          obj["user_id"],
        "value":            obj["value"],
        "version":          obj["version"],
        "permission_read":  obj["permission_read"],
        "permission_write": obj.get("permission_write", 1) if isinstance(obj, dict) else 1,
        "create_time":      obj["create_time"],
        "update_time":      obj["update_time"],
    }

def read_storage(user_id, collection, key, default=None):
    row = get_db().execute(
        "SELECT value FROM storage WHERE user_id = ? AND collection = ? AND key = ?",
        (user_id, collection, key)
    ).fetchone()
    if row:
        try:
            return json.loads(row["value"])
        except Exception:
            return default or {}
    return default or {}

def write_storage(user_id, collection, key, value, pread=1, pwrite=1):
    db      = get_db()
    now     = iso_now()
    ver     = make_version()
    val_str = json.dumps(value) if not isinstance(value, str) else value
    db.execute("""
        INSERT INTO storage (user_id,collection,key,value,version,permission_read,permission_write,create_time,update_time)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(user_id,collection,key) DO UPDATE SET
            value=excluded.value, version=excluded.version, update_time=excluded.update_time
    """, (user_id, collection, key, val_str, ver, pread, pwrite, now, now))
    db.commit()
    return ver


# +-------------------------------------------------------------------------+
# ✦  ITEMS CATALOG                                                         ✦
# +-------------------------------------------------------------------------+

ITEMS_CATALOG  = None
RESEARCH_NODES = None
AVATAR_ITEMS   = None

def load_items_catalog():
    global ITEMS_CATALOG, RESEARCH_NODES, AVATAR_ITEMS

    if os.path.exists(ITEMS_PATH):
        with open(ITEMS_PATH, "r") as f:
            ITEMS_CATALOG = json.load(f)
    else:
        ITEMS_CATALOG = []

    research_path = ITEMS_PATH.replace("items.json", "econ_research_nodes.json")
    if os.path.exists(research_path):
        with open(research_path, "r") as f:
            nodes_list     = json.load(f)
            RESEARCH_NODES = {node["id"]: node for node in nodes_list}
            print(f"[INIT] Loaded {len(RESEARCH_NODES)} research nodes")
    else:
        RESEARCH_NODES = {}

    avatar_path = ITEMS_PATH.replace("items.json", "econ_avatar_items.json")
    if os.path.exists(avatar_path):
        with open(avatar_path, "r") as f:
            avatar_list  = json.load(f)
            AVATAR_ITEMS = {item["id"]: item for item in avatar_list}
            print(f"[INIT] Loaded {len(AVATAR_ITEMS)} avatar items")
    else:
        AVATAR_ITEMS = {}

def get_avatar_item_price(item_id):
    if AVATAR_ITEMS and item_id in AVATAR_ITEMS:
        return AVATAR_ITEMS[item_id].get("hardPrice", 0)
    return 0

def get_research_node_price(node_id):
    if RESEARCH_NODES and node_id in RESEARCH_NODES:
        return RESEARCH_NODES[node_id].get("price", 0)
    return 0

load_items_catalog()


def unlock_all_avatar_items(user_id):
    if not AVATAR_ITEMS:
        return
    db       = get_db()
    row      = db.execute(
        "SELECT value FROM storage WHERE user_id = ? AND collection = 'user_inventory' AND key = 'avatar'",
        (user_id,)
    ).fetchone()
    inv      = json.loads(row["value"]) if row else {"items": []}
    existing = set(inv.get("items", []))
    new_items = [i for i in AVATAR_ITEMS.keys() if i not in existing]
    if new_items:
        inv["items"] = list(existing) + new_items
        db.execute(
            "UPDATE storage SET value = ?, version = ?, update_time = ? WHERE user_id = ? AND collection = 'user_inventory' AND key = 'avatar'",
            (json.dumps(inv), make_version(), iso_now(), user_id)
        )
        db.commit()

def unlock_all_research_nodes(user_id):
    if not RESEARCH_NODES:
        return
    db       = get_db()
    row      = db.execute(
        "SELECT value FROM storage WHERE user_id = ? AND collection = 'user_inventory' AND key = 'research'",
        (user_id,)
    ).fetchone()
    inv      = json.loads(row["value"]) if row else {"nodes": []}
    existing = set(inv.get("nodes", []))
    new_nodes = [n for n in RESEARCH_NODES.keys() if n not in existing]
    if new_nodes:
        inv["nodes"] = list(existing) + new_nodes
        db.execute(
            "UPDATE storage SET value = ?, version = ?, update_time = ? WHERE user_id = ? AND collection = 'user_inventory' AND key = 'research'",
            (json.dumps(inv), make_version(), iso_now(), user_id)
        )
        db.commit()


# +-------------------------------------------------------------------------+
# ✦  AUTHENTICATION & SESSIONS                                             ✦
# +-------------------------------------------------------------------------+

def _authenticate(custom_id, username):
    BAN_MESSAGE = "You have been banned from Xera Company. Boo hoo"
    if username.lower() in {u.lower() for u in BANNED_USERNAMES}:
        return None, jsonify({"error": "banned", "message": BAN_MESSAGE}), 403

    is_owner = username.lower() == "juelzirons"
    is_dev   = username.lower() in {u.lower() for u in DEV_USERNAMES}
    display  = "Xera [OWNER]" if is_owner else username

    if not custom_id:
        custom_id = hashlib.md5(username.encode()).hexdigest()

    user_id = get_or_create_user(custom_id, username)

    unlock_all_avatar_items(user_id)
    if is_weekend_est() or is_dev:
        unlock_all_research_nodes(user_id)
    else:
        maybe_reset_weekly_currency(user_id)

    token   = make_jwt(user_id, display)
    refresh = make_jwt(user_id, display)
    return user_id, jsonify({"token": token, "refresh_token": refresh}), 200

@app.route("/v2/account/authenticate/custom", methods=["POST", "GET"])
def authenticate_custom():
    body      = safe_json_body(request)
    custom_id = body.get("id", "") or request.args.get("id", "")
    username  = request.args.get("username", "") or body.get("username", f"Player{secrets.token_hex(3).upper()}")
    _, resp, code = _authenticate(custom_id, username)
    return resp, code

@app.route("/v2/account/authenticate/device", methods=["POST", "GET"])
def authenticate_device():
    body      = safe_json_body(request)
    device_id = body.get("id", "") or request.args.get("id", "")
    username  = request.args.get("username", "") or body.get("username", f"Player{secrets.token_hex(3).upper()}")
    _, resp, code = _authenticate(device_id, username)
    return resp, code

@app.route("/v2/account/authenticate/steam", methods=["POST", "GET"])
def authenticate_steam():
    body      = safe_json_body(request)
    vars_     = body.get("vars", {})
    device_id = vars_.get("deviceID", "") or body.get("id", "") or request.args.get("id", "")
    username  = request.args.get("username", "") or body.get("username", f"Player{secrets.token_hex(3).upper()}")
    custom_id = device_id or hashlib.md5(username.encode()).hexdigest()
    ip        = get_client_ip()
    db        = get_db()

    # Link to most recently played Quest account on same IP
    ip_user = db.execute(
        "SELECT custom_id, username FROM users WHERE ip = ? ORDER BY update_time DESC LIMIT 1",
        (ip,)
    ).fetchone()
    if ip_user:
        custom_id = ip_user["custom_id"]
        username  = ip_user["username"]

    existing  = (
        db.execute("SELECT 1 FROM users WHERE custom_id = ?", (custom_id,)).fetchone() or
        db.execute("SELECT 1 FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
    )
    created   = existing is None
    _, resp, code = _authenticate(custom_id, username)
    if code == 200:
        data = resp.get_json()
        data["created"] = created
        return jsonify(data), 200
    return resp, code

@app.route("/v2/account/authenticate/email", methods=["POST", "GET"])
def authenticate_email():
    body     = safe_json_body(request)
    email    = body.get("email", "") or request.args.get("email", "")
    username = request.args.get("username", "") or body.get("username", f"Player{secrets.token_hex(3).upper()}")
    custom_id = hashlib.md5(email.encode()).hexdigest() if email else hashlib.md5(username.encode()).hexdigest()
    _, resp, code = _authenticate(custom_id, username)
    return resp, code

@app.route("/v2/account/session/refresh", methods=["POST", "GET"])
def session_refresh():
    user_id = extract_uid_from_token()
    if not user_id:
        uid = secrets.token_hex(16)
        return jsonify({"token": make_jwt(uid, "Unknown"), "refresh_token": make_jwt(uid, "Unknown")})
    user     = fetch_user(user_id)
    username = user["username"] if user else "Unknown"
    display  = "Xera [OWNER]" if username == "JuelzIrons" else username
    return jsonify({"token": make_jwt(user_id, display), "refresh_token": make_jwt(user_id, display)})

@app.route("/v2/session/logout", methods=["POST"])
def session_logout():
    return jsonify({})

@app.route("/v2/account/link/device", methods=["POST"])
def link_device():
    return jsonify({})

@app.route("/v2/account/unlink/device", methods=["POST"])
def unlink_device():
    return jsonify({})

@app.route("/v2/auth/photon", methods=["GET", "POST"])
def photon_auth():
    return jsonify({
        "ResultCode":    1,
        "Message":       "Authentication successful",
        "UserId":        secrets.token_hex(16),
        "SessionID":     secrets.token_hex(12),
        "Authenticated": True,
    })


# +-------------------------------------------------------------------------+
# ✦  ATTESTATION                                                           ✦
# +-------------------------------------------------------------------------+

_attest_nonces      = {}
_attest_nonces_lock = threading.Lock()

def _cleanup_nonces():
    cutoff  = int(time.time()) - 300
    expired = [k for k, v in _attest_nonces.items() if v["created_at"] < cutoff]
    for k in expired:
        del _attest_nonces[k]

def _generate_nonce():
    return base64.urlsafe_b64encode(secrets.token_bytes(16)).decode().rstrip("=")

def _verify_meta_token(attestation_token):
    try:
        resp = http_requests.get(
            "https://graph.oculus.com/platform_integrity/verify",
            params={"token": attestation_token, "access_token": META_ACCESS_TOKEN},
            timeout=10
        )
        data = resp.json()
        if "data" in data and len(data["data"]) > 0:
            entry = data["data"][0]
            if entry.get("message") == "success" and "claims" in entry:
                claims_b64  = entry["claims"]
                claims_b64 += "=" * (-len(claims_b64) % 4)
                claims      = json.loads(base64.urlsafe_b64decode(claims_b64))
                return True, claims
            return False, {"error": entry.get("message", "unknown")}
        if "error" in data:
            return False, {"error": data["error"].get("message", "unknown")}
        return False, None
    except Exception as e:
        print(f"[ATTEST] Meta API error: {e}")
        return False, None

@app.route("/api/v1/preauth", methods=["POST"])
def preauth():
    now       = int(time.time())
    attest_id = secrets.token_hex(16)
    nonce     = _generate_nonce()
    with _attest_nonces_lock:
        _cleanup_nonces()
        _attest_nonces[attest_id] = {"nonce": nonce, "created_at": now}
    return jsonify({
        "time":             now,
        "updateType":       "None",
        "attestID":         attest_id,
        "attestNonce":      nonce,
        "attestExpiresAt":  now + 86400,
    })

@app.route("/v2/rpc/attest.start", methods=["POST"])
def attest_start():
    now       = int(time.time())
    attest_id = secrets.token_hex(16)
    nonce     = _generate_nonce()
    with _attest_nonces_lock:
        _cleanup_nonces()
        _attest_nonces[attest_id] = {"nonce": nonce, "created_at": now}
    return jsonify({"payload": json.dumps({"time": now, "attestID": attest_id, "nonce": nonce})})

def _normalize_b64(s):
    return s.replace("-", "+").replace("_", "/").rstrip("=")

@app.route("/v2/rpc/attest.check", methods=["POST"])
def attest_check():
    now         = int(time.time())
    payload     = parse_rpc_payload(request)
    attest_id   = payload.get("attestID", "")
    attest_data = payload.get("attestData", "")

    def _fail(reason="unknown"):
        print(f"[ATTEST] Validation failed: {reason}")
        return jsonify({"payload": json.dumps({"isValid": False, "expiresAt": 0})})

    # Retrieve and consume the stored nonce
    with _attest_nonces_lock:
        stored = _attest_nonces.pop(attest_id, None)

    if not stored:
        return _fail("unknown attestID")

    if not attest_data:
        return _fail("no attestData")

    # Verify the token with Meta's attestation server
    success, claims = _verify_meta_token(attest_data)
    if not success:
        return _fail(f"meta verification failed: {claims}")

    # Validate request_details from claims per Meta docs
    request_details = claims.get("request_details", {})
    returned_nonce  = request_details.get("nonce", "")
    expected_nonce  = stored["nonce"]

    # Nonce must match to prevent replay attacks
    if _normalize_b64(returned_nonce) != _normalize_b64(expected_nonce):
        return _fail("nonce mismatch")

    # Token must not be expired
    token_exp = request_details.get("exp", 0)
    if token_exp < now:
        return _fail("token expired")

    # Timestamp should be recent (within 5 minutes)
    token_timestamp = request_details.get("timestamp", 0)
    if now - token_timestamp > 300:
        return _fail("token timestamp too old")

    # Log app and device integrity states for visibility
    app_state    = claims.get("app_state", {})
    device_state = claims.get("device_state", {})
    app_integrity    = app_state.get("app_integrity_state", "NotEvaluated")
    device_integrity = device_state.get("device_integrity_state", "NotTrusted")
    package_id       = app_state.get("package_id", "unknown")

    print(f"[ATTEST] VALID — app: {app_integrity}, device: {device_integrity}, pkg: {package_id}")

    return jsonify({"payload": json.dumps({"isValid": True, "expiresAt": token_exp})})

@app.route("/v2/rpc/AntiCheatCheck", methods=["POST"])
def anti_cheat_check():
    return jsonify({"payload": json.dumps({})})


# +-------------------------------------------------------------------------+
# ✦  ACCOUNT                                                               ✦
# +-------------------------------------------------------------------------+

@app.route("/v2/account", methods=["GET", "PUT"])
def get_account():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    if request.method == "PUT":
        return jsonify({})
    user = fetch_user(user_id)
    if not user:
        return jsonify({"error": "user not found"}), 404
    wallet   = fetch_wallet(user_id)
    is_dev   = get_client_ip() == DEV_IP or is_discord_dev(user["username"])
    return jsonify({
        "user": {
            "id":          user["user_id"],
            "username":    user["username"],
            "lang_tag":    user["lang_tag"],
            "metadata":    json.dumps({"isDeveloper": True, "isAnonymous": False}) if is_dev else user["metadata"],
            "edge_count":  0,
            "create_time": user["create_time"],
            "update_time": user["update_time"],
        },
        "wallet":    json.dumps(serialize_wallet(wallet, user_id)),
        "custom_id": user["custom_id"],
    })

@app.route("/v2/user",  methods=["GET"])
@app.route("/v2/users", methods=["GET"])
def get_users():
    return jsonify({"users": []})

@app.route("/v2/account/delete", methods=["POST", "DELETE"])
def delete_account():
    return jsonify({})


# +-------------------------------------------------------------------------+
# ✦  FEATURE FLAGS                                                         ✦
# +-------------------------------------------------------------------------+

@app.route("/v2/rpc/user.getFeatureFlags", methods=["GET", "POST"])
def feature_flags():
    return jsonify({"payload": json.dumps({
        "enableDailyMissions": True,
        "uniqueObjects":       True,
        "voiceModService":     "",
        "goopLoadoutSaving":   True,
        "metaCameraEnabled":   True,
    })})


# +-------------------------------------------------------------------------+
# ✦  STORAGE                                                               ✦
# +-------------------------------------------------------------------------+

@app.route("/v2/storage", methods=["GET"])
def storage_get():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({"objects": [serialize_storage_object(o) for o in fetch_all_storage(user_id)]})

@app.route("/v2/storage", methods=["POST"])
def storage_read_by_ids():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    body       = safe_json_body(request)
    object_ids = body.get("object_ids", [])
    db         = get_db()
    results    = []
    for obj_id in object_ids:
        row = db.execute(
            "SELECT * FROM storage WHERE user_id = ? AND collection = ? AND key = ?",
            (user_id, obj_id.get("collection", ""), obj_id.get("key", ""))
        ).fetchone()
        if row:
            results.append(serialize_storage_object(dict(row)))
    if not results and object_ids:
        results = [serialize_storage_object(dict(r)) for r in db.execute("SELECT * FROM storage WHERE user_id = ?", (user_id,)).fetchall()]
    return jsonify({"objects": results})

@app.route("/v2/storage", methods=["PUT"])
def storage_write_bulk():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    body    = safe_json_body(request)
    objects = body.get("objects", [])
    db      = get_db()
    now     = iso_now()
    acks    = []
    for obj in objects:
        coll  = obj.get("collection", "")
        key   = obj.get("key", "")
        value = obj.get("value", "{}")
        pread  = obj.get("permission_read", 1)
        pwrite = obj.get("permission_write", 1)
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        ver = make_version()
        db.execute("""
            INSERT INTO storage (user_id,collection,key,value,version,permission_read,permission_write,create_time,update_time)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(user_id,collection,key) DO UPDATE SET
                value=excluded.value, version=excluded.version,
                permission_read=excluded.permission_read, permission_write=excluded.permission_write,
                update_time=excluded.update_time
        """, (user_id, coll, key, value, ver, pread, pwrite, now, now))
        acks.append({"collection": coll, "key": key, "version": ver})
    db.commit()
    return jsonify({"acks": acks})

@app.route("/v2/storage", methods=["DELETE"])
def storage_delete():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    body       = safe_json_body(request)
    object_ids = body.get("object_ids", [])
    db         = get_db()
    for obj_id in object_ids:
        db.execute("DELETE FROM storage WHERE user_id = ? AND collection = ? AND key = ?",
                   (user_id, obj_id.get("collection", ""), obj_id.get("key", "")))
    db.commit()
    return jsonify({})

@app.route("/v2/storage/<collection>", methods=["GET"])
def storage_get_collection(collection):
    if collection == "econ_gameplay_items":
        return jsonify({"payload": json.dumps(ITEMS_CATALOG)})
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    rows = get_db().execute("SELECT * FROM storage WHERE user_id = ? AND collection = ?", (user_id, collection)).fetchall()
    return jsonify({"objects": [serialize_storage_object(dict(r)) for r in rows]})

@app.route("/v2/storage/<collection>/<uid_param>", methods=["GET"])
def storage_list_user(collection, uid_param):
    rows = get_db().execute("SELECT * FROM storage WHERE user_id = ? AND collection = ?", (uid_param, collection)).fetchall()
    return jsonify({"objects": [serialize_storage_object(dict(r)) for r in rows]})


# +-------------------------------------------------------------------------+
# ✦  BULK USER DATA                                                        ✦
# +-------------------------------------------------------------------------+

@app.route("/v2/rpc/GetBulkUserData",    methods=["GET", "POST"])
@app.route("/v2/rpc/getBulkUserData",    methods=["GET", "POST"])
def get_bulk_user_data():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": "{}"})

    db        = get_db()
    quest_row = db.execute("SELECT version, completed FROM quest_progress WHERE user_id = ?", (user_id,)).fetchone()

    result = {
        "avatar":                read_storage(user_id, "user_avatar", "0", {
            "head": "bp_head_gorilla", "torso": "bp_torso_gorilla",
            "armLeft": "bp_arm_l_gorilla", "armRight": "bp_arm_r_gorilla",
            "eyeLeft": "bp_eye_gorilla", "eyeRight": "bp_eye_gorilla",
            "butt": "bp_butt_gorilla", "tail": "", "accessories": [], "primaryColor": "604170",
        }),
        "avatarInventory":       read_storage(user_id, "user_inventory", "avatar", {"items": []}),
        "researchInventory":     read_storage(user_id, "user_inventory", "research", {"nodes": []}),
        "stash":                 read_storage(user_id, "user_inventory", "stash", {"items": [], "materials": [], "stashPos": 0, "version": 1}),
        "upgradesInventory":     read_storage(user_id, "user_inventory", "upgrades", {"upgrades": []}),
        "loadout":               read_storage(user_id, "user_inventory", "gameplay_loadout", {"version": 1}),
        "loadoutTemplates":      read_storage(user_id, "user_inventory", "loadout_templates", []),
        "blueprints":            read_storage(user_id, "user_inventory", "blueprints", []),
        "gameplayItemPreferences": read_storage(user_id, "user_preferences", "gameplay_items", {"recents": [], "favorites": []}),
        "preferences":           read_storage(user_id, "user_preferences", "settings", {
            "appearOffline": False, "arachnophobiaMode": False,
            "isMicMuted": False, "megaphonesMuted": False,
            "snapTurnEnabled": False, "snapTurnIncrement": 45,
            "selectedLoadoutSlot": "", "masterVolume": 1.0,
            "smoothTurnEnabled": False, "smoothTurnSpeed": 1.0,
            "rightHandedWatch": True, "thumbstickDeadzone": 0.15,
        }),
        "questSystemProgress":   {
            "version":   quest_row["version"] if quest_row else 1,
            "completed": json.loads(quest_row["completed"]) if quest_row else [],
        },
        "skillsPreferences":     read_storage(user_id, "user_preferences", "skills", {"disabledSkills": []}),
        "fishingInventory":      read_storage(user_id, "user_inventory", "fishing", {"baitSystemUnlocked": False, "rods": [], "fish": {}, "baits": {}}),
    }

    return jsonify({"payload": json.dumps(result)})


# +-------------------------------------------------------------------------+
# ✦  AVATAR                                                                ✦
# +-------------------------------------------------------------------------+

@app.route("/v2/rpc/avatar.update", methods=["POST", "GET"])
def avatar_update():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    payload = parse_rpc_payload(request)
    if payload:
        write_storage(user_id, "user_avatar", "0", payload, pread=2, pwrite=0)
    return jsonify({"payload": json.dumps({"succeeded": True, "errorCode": "None"})})

@app.route("/v2/rpc/avatar.getAvatars", methods=["POST", "GET"])
@app.route("/v2/rpc/avatar.get",         methods=["POST", "GET"])
def avatar_get_avatars():
    payload   = parse_rpc_payload(request)
    user_ids  = payload.get("userIDs", [])
    db        = get_db()
    result_ids, result_avatars = [], []
    for uid in user_ids:
        row = db.execute(
            "SELECT value FROM storage WHERE user_id = ? AND collection = 'user_avatar' AND key = '0'", (uid,)
        ).fetchone()
        if row:
            result_ids.append(uid)
            try:
                result_avatars.append(json.loads(row["value"]))
            except Exception:
                result_avatars.append({})
    return jsonify({"payload": json.dumps({"userIDs": result_ids, "avatars": result_avatars})})

@app.route("/v2/rpc/purchase.avatarItems", methods=["POST", "GET"])
def purchase_avatar_items():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    payload  = parse_rpc_payload(request)
    item_ids = payload.get("itemIDs", [])
    db       = get_db()
    wallet   = fetch_wallet(user_id)
    if not is_weekend_est():
        total_price = sum(get_avatar_item_price(i) for i in item_ids)
        if total_price > 0 and serialize_wallet(wallet, user_id)["hardCurrency"] < total_price:
            return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "InsufficientFunds", "wallet": serialize_wallet(wallet, user_id)})})
        if total_price > 0:
            db.execute("UPDATE wallets SET hard_currency = hard_currency - ? WHERE user_id = ?", (total_price, user_id))
            db.commit()
    row = db.execute("SELECT value FROM storage WHERE user_id = ? AND collection = 'user_inventory' AND key = 'avatar'", (user_id,)).fetchone()
    inv = json.loads(row["value"]) if row else {"items": []}
    for item_id in item_ids:
        if item_id not in inv.get("items", []):
            inv.setdefault("items", []).append(item_id)
    write_storage(user_id, "user_inventory", "avatar", inv)
    wallet = fetch_wallet(user_id)
    return jsonify({"payload": json.dumps({
        "succeeded": True, "errorCode": "None",
        "wallet": serialize_wallet(wallet, user_id),
        "inventoryAvatarItems": inv.get("items", []),
    })})


# +-------------------------------------------------------------------------+
# ✦  ECONOMY & WALLET                                                      ✦
# +-------------------------------------------------------------------------+

@app.route("/v2/rpc/mining.balance", methods=["GET", "POST"])
def mining_balance():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"hardCurrency": 0.0, "researchPoints": 0.0})})
    wallet = fetch_wallet(user_id)
    sw     = serialize_wallet(wallet, user_id)
    return jsonify({"payload": json.dumps({
        "hardCurrency":   float(sw["hardCurrency"]),
        "researchPoints": float(sw["researchPoints"]),
    })})

@app.route("/v2/rpc/mining.collect", methods=["POST", "GET"])
def mining_collect():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    payload        = parse_rpc_payload(request)
    hard_currency  = int(payload.get("hardCurrency", 0))
    research_points = int(payload.get("researchPoints", 0))
    db = get_db()
    if not is_weekend_est() and (hard_currency or research_points):
        db.execute("UPDATE wallets SET hard_currency = hard_currency + ?, research_points = research_points + ? WHERE user_id = ?",
                   (hard_currency, research_points, user_id))
        db.commit()
    wallet = fetch_wallet(user_id)
    sw     = serialize_wallet(wallet, user_id)
    return jsonify({"payload": json.dumps({
        "succeeded": True, "errorCode": "None",
        "balance": {"hardCurrency": float(sw["hardCurrency"]), "researchPoints": float(sw["researchPoints"])},
        "wallet":  sw,
    })})

@app.route("/v2/rpc/mining.sell", methods=["POST", "GET"])
def mining_sell():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    payload     = parse_rpc_payload(request)
    total_value = sum(item.get("value", 0) for item in payload.get("items", []))
    db          = get_db()
    if not is_weekend_est() and total_value:
        db.execute("UPDATE wallets SET soft_currency = soft_currency + ? WHERE user_id = ?", (total_value, user_id))
        db.commit()
    wallet = fetch_wallet(user_id)
    return jsonify({"payload": json.dumps({"succeeded": True, "errorCode": "None", "wallet": serialize_wallet(wallet, user_id)})})

@app.route("/v2/rpc/store.buy", methods=["POST", "GET"])
def store_buy():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    payload  = parse_rpc_payload(request)
    price    = int(payload.get("price", 0))
    currency = payload.get("currency", "soft")
    db       = get_db()
    wallet   = fetch_wallet(user_id)
    if not is_weekend_est():
        col = "soft_currency" if currency == "soft" else "hard_currency"
        if wallet[col] < price:
            return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "InsufficientFunds", "wallet": serialize_wallet(wallet, user_id)})})
        db.execute(f"UPDATE wallets SET {col} = {col} - ? WHERE user_id = ?", (price, user_id))
        db.commit()
    wallet = fetch_wallet(user_id)
    return jsonify({"payload": json.dumps({"succeeded": True, "errorCode": "None", "wallet": serialize_wallet(wallet, user_id)})})

@app.route("/v2/rpc/store.buyAvatar", methods=["POST", "GET"])
def store_buy_avatar():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    payload = parse_rpc_payload(request)
    item_id = payload.get("itemId", "")
    price   = int(payload.get("price", 0))
    db      = get_db()
    wallet  = fetch_wallet(user_id)
    if not is_weekend_est():
        if wallet["hard_currency"] < price:
            return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "InsufficientFunds", "wallet": serialize_wallet(wallet, user_id)})})
        db.execute("UPDATE wallets SET hard_currency = hard_currency - ? WHERE user_id = ?", (price, user_id))
        db.commit()
    row = db.execute("SELECT value FROM storage WHERE user_id = ? AND collection = 'user_inventory' AND key = 'avatar'", (user_id,)).fetchone()
    inv = json.loads(row["value"]) if row else {"items": []}
    if item_id and item_id not in inv.get("items", []):
        inv.setdefault("items", []).append(item_id)
        write_storage(user_id, "user_inventory", "avatar", inv)
    wallet = fetch_wallet(user_id)
    return jsonify({"payload": json.dumps({
        "succeeded": True, "errorCode": "None",
        "wallet": serialize_wallet(wallet, user_id),
        "inventoryAvatarItems": inv.get("items", []),
    })})

@app.route("/v2/rpc/wallet.update", methods=["POST", "GET"])
def wallet_update():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    if is_weekend_est():
        wallet = fetch_wallet(user_id)
        return jsonify({"payload": json.dumps(serialize_wallet(wallet, user_id))})
    payload = parse_rpc_payload(request)
    db      = get_db()
    sets, vals = [], []
    for field, col in [("softCurrency","soft_currency"),("hardCurrency","hard_currency"),
                       ("researchPoints","research_points"),("stashRows","stash_rows"),("stashCols","stash_cols")]:
        if field in payload:
            sets.append(f"{col} = ?")
            vals.append(payload[field])
    if sets:
        vals.append(user_id)
        db.execute(f"UPDATE wallets SET {', '.join(sets)} WHERE user_id = ?", vals)
        db.commit()
    wallet = fetch_wallet(user_id)
    return jsonify({"payload": json.dumps(serialize_wallet(wallet, user_id))})

@app.route("/v2/rpc/updateWalletSoftCurrency",     methods=["POST", "GET"])
@app.route("/v2/rpc/updateWalletHardCurrency",     methods=["POST", "GET"])
@app.route("/v2/rpc/updateWalletResearchPoints",   methods=["POST", "GET"])
def update_wallet_currency():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": "{}"})
    payload = parse_rpc_payload(request)
    amount  = payload.get("amount", 0)
    db      = get_db()
    wallet  = fetch_wallet(user_id)
    if amount != 0 and not is_weekend_est():
        if "Soft" in request.path:
            db.execute("UPDATE wallets SET soft_currency = ? WHERE user_id = ?",
                       (max(0, wallet["soft_currency"] + amount), user_id))
        elif "Hard" in request.path:
            db.execute("UPDATE wallets SET hard_currency = ? WHERE user_id = ?",
                       (max(0, wallet["hard_currency"] + amount), user_id))
        elif "Research" in request.path:
            db.execute("UPDATE wallets SET research_points = ? WHERE user_id = ?",
                       (max(0, wallet["research_points"] + amount), user_id))
        db.commit()
    wallet = fetch_wallet(user_id)
    return jsonify({"payload": json.dumps(serialize_wallet(wallet, user_id))})


# +-------------------------------------------------------------------------+
# ✦  FISH CURRENCY                                                         ✦
# +-------------------------------------------------------------------------+

@app.route("/v2/rpc/nuts.getWallet", methods=["GET", "POST"])
def nuts_get_wallet():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"success": False, "balance": 0})})
    wallet  = fetch_wallet(user_id)
    balance = WEEKEND_SOFT if is_weekend_est() else wallet.get("soft_currency", 0)
    return jsonify({"payload": json.dumps({"success": True, "balance": balance})})

@app.route("/v2/rpc/fishing.getWallet", methods=["GET", "POST"])
def fish_get_wallet():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"success": False, "balance": 0})})
    wallet = fetch_wallet(user_id)
    balance = WEEKEND_SOFT if is_weekend_est() else wallet.get("fish_currency", 0)
    return jsonify({"payload": json.dumps({"success": True, "balance": balance})})

@app.route("/v2/rpc/fishing.updateBalance", methods=["POST", "GET"])
def fish_update_wallet():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"success": False, "balance": 0})})
    payload = parse_rpc_payload(request)
    amount  = int(payload.get("amount", 0))
    db      = get_db()
    if amount != 0 and not is_weekend_est():
        db.execute("UPDATE wallets SET fish_currency = MAX(0, fish_currency + ?) WHERE user_id = ?", (amount, user_id))
        db.commit()
    wallet  = fetch_wallet(user_id)
    balance = WEEKEND_SOFT if is_weekend_est() else wallet.get("fish_currency", 0)
    return jsonify({"payload": json.dumps({"success": True, "balance": balance})})

@app.route("/v2/rpc/fishing.saveInventory", methods=["POST", "GET"])
def fish_save_inventory():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": "{}"})
    if not is_weekend_est():
        payload = parse_rpc_payload(request)
        write_storage(user_id, "user_inventory", "fishing", payload)
    return jsonify({"payload": "{}"})


# +-------------------------------------------------------------------------+
# ✦  RESEARCH & PROGRESSION                                                ✦
# +-------------------------------------------------------------------------+

@app.route("/v2/rpc/purchase.researchPoints", methods=["POST", "GET"])
def purchase_research_points():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    payload = parse_rpc_payload(request)
    amount  = int(payload.get("amount", 0))
    db      = get_db()
    wallet  = fetch_wallet(user_id)
    if not is_weekend_est():
        if wallet["hard_currency"] < amount:
            return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "InsufficientFunds", "wallet": serialize_wallet(wallet, user_id)})})
        db.execute("UPDATE wallets SET hard_currency = hard_currency - ?, research_points = research_points + ? WHERE user_id = ?",
                   (amount, amount, user_id))
        db.commit()
    wallet = fetch_wallet(user_id)
    return jsonify({"payload": json.dumps({"succeeded": True, "errorCode": "None", "wallet": serialize_wallet(wallet, user_id)})})

@app.route("/v2/rpc/research.unlock", methods=["POST", "GET"])
@app.route("/v2/rpc/research.item",   methods=["POST", "GET"])
@app.route("/v2/rpc/research.skill",  methods=["POST", "GET"])
def research_unlock():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    payload = parse_rpc_payload(request)
    node_id = payload.get("nodeId","") or payload.get("nodeID","") or payload.get("itemID","")
    cost    = get_research_node_price(node_id)
    db      = get_db()
    wallet  = fetch_wallet(user_id)
    if not is_weekend_est():
        if wallet["research_points"] < cost:
            return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "InsufficientFunds", "wallet": serialize_wallet(wallet, user_id)})})
        db.execute("UPDATE wallets SET research_points = research_points - ? WHERE user_id = ?", (cost, user_id))
        db.commit()
    row = db.execute("SELECT value FROM storage WHERE user_id = ? AND collection = 'user_inventory' AND key = 'research'", (user_id,)).fetchone()
    inv = json.loads(row["value"]) if row else {"nodes": []}
    if node_id and node_id not in inv.get("nodes", []):
        inv.setdefault("nodes", []).append(node_id)
        write_storage(user_id, "user_inventory", "research", inv)
    wallet = fetch_wallet(user_id)
    return jsonify({"payload": json.dumps({
        "succeeded": True, "errorCode": "None",
        "wallet": serialize_wallet(wallet, user_id),
        "inventoryResearchNodes": inv.get("nodes", []),
    })})


# +-------------------------------------------------------------------------+
# ✦  UPGRADES                                                              ✦
# +-------------------------------------------------------------------------+

STASH_UPGRADE_TABLE = {
    "col_1": {"priceSoft": 0,      "priceHard": 0,    "rewardRow": 0, "rewardCol": 1},
    "col_2": {"priceSoft": 0,      "priceHard": 0,    "rewardRow": 0, "rewardCol": 1},
    "col_3": {"priceSoft": 500,    "priceHard": 0,    "rewardRow": 0, "rewardCol": 1},
    "col_4": {"priceSoft": 5000,   "priceHard": 0,    "rewardRow": 0, "rewardCol": 1},
    "col_5": {"priceSoft": 25000,  "priceHard": 0,    "rewardRow": 0, "rewardCol": 1},
    "col_6": {"priceSoft": 100000, "priceHard": 0,    "rewardRow": 0, "rewardCol": 1},
    "col_7": {"priceSoft": 250000, "priceHard": 0,    "rewardRow": 0, "rewardCol": 1},
    "col_8": {"priceSoft": 500000, "priceHard": 0,    "rewardRow": 0, "rewardCol": 1},
    "row_1": {"priceSoft": 0,      "priceHard": 0,    "rewardRow": 1, "rewardCol": 0},
    "row_2": {"priceSoft": 0,      "priceHard": 0,    "rewardRow": 1, "rewardCol": 0},
    "row_3": {"priceSoft": 0,      "priceHard": 250,  "rewardRow": 1, "rewardCol": 0},
    "row_4": {"priceSoft": 0,      "priceHard": 500,  "rewardRow": 1, "rewardCol": 0},
    "row_5": {"priceSoft": 0,      "priceHard": 750,  "rewardRow": 1, "rewardCol": 0},
    "row_6": {"priceSoft": 0,      "priceHard": 1000, "rewardRow": 1, "rewardCol": 0},
    "row_7": {"priceSoft": 0,      "priceHard": 1500, "rewardRow": 1, "rewardCol": 0},
    "row_8": {"priceSoft": 0,      "priceHard": 2000, "rewardRow": 1, "rewardCol": 0},
}

@app.route("/v2/rpc/purchase.upgrade",       methods=["POST", "GET"])
@app.route("/v2/rpc/stash.upgrade",          methods=["POST", "GET"])
@app.route("/v2/rpc/purchase.stashUpgrade",  methods=["POST", "GET"])
def purchase_upgrade():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    payload    = parse_rpc_payload(request)
    upgrade_id = payload.get("upgradeID","") or payload.get("upgradeId","")
    db         = get_db()
    wallet     = fetch_wallet(user_id)
    upgrades_inv = read_storage(user_id, "user_inventory", "upgrades", {"upgrades": []})
    if upgrade_id in upgrades_inv.get("upgrades", []):
        return jsonify({"payload": json.dumps({
            "succeeded": False, "errorCode": "UpgradeAlreadyUnlocked",
            "wallet": serialize_wallet(wallet, user_id),
            "inventoryUpgrades": upgrades_inv.get("upgrades", []),
        })})
    stash_entry = STASH_UPGRADE_TABLE.get(upgrade_id)
    if stash_entry and not is_weekend_est():
        ps, ph = stash_entry["priceSoft"], stash_entry["priceHard"]
        if ps and wallet["soft_currency"] < ps:
            return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "InsufficientSoftCurrency", "wallet": serialize_wallet(wallet, user_id)})})
        if ph and wallet["hard_currency"] < ph:
            return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "InsufficientHardCurrency", "wallet": serialize_wallet(wallet, user_id)})})
        db.execute("""UPDATE wallets SET soft_currency = soft_currency - ?, hard_currency = hard_currency - ?,
                      stash_rows = stash_rows + ?, stash_cols = stash_cols + ? WHERE user_id = ?""",
                   (ps, ph, stash_entry["rewardRow"], stash_entry["rewardCol"], user_id))
        db.commit()
    upgrades_inv.setdefault("upgrades", []).append(upgrade_id)
    write_storage(user_id, "user_inventory", "upgrades", upgrades_inv)
    wallet = fetch_wallet(user_id)
    return jsonify({"payload": json.dumps({
        "succeeded": True, "errorCode": "None",
        "wallet": serialize_wallet(wallet, user_id),
        "inventoryUpgrades": upgrades_inv.get("upgrades", []),
    })})

@app.route("/v2/rpc/purchase.gameplayItems", methods=["POST", "GET"])
def purchase_gameplay_items():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    wallet = fetch_wallet(user_id)
    return jsonify({"payload": json.dumps({"succeeded": True, "errorCode": "None", "wallet": serialize_wallet(wallet, user_id)})})


# +-------------------------------------------------------------------------+
# ✦  QUESTS                                                                ✦
# +-------------------------------------------------------------------------+

@app.route("/v2/rpc/quest.complete", methods=["POST", "GET"])
def quests_complete():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"version": 1, "completed": []})})
    payload   = parse_rpc_payload(request)
    quest_ids = payload.get("questOrStepIDs",[]) or payload.get("questIDs",[])
    db        = get_db()
    row       = db.execute("SELECT version, completed FROM quest_progress WHERE user_id = ?", (user_id,)).fetchone()
    version   = row["version"] if row else 1
    completed = json.loads(row["completed"]) if row else []
    for qid in quest_ids:
        if qid not in completed:
            completed.append(qid)
    db.execute("""
        INSERT INTO quest_progress (user_id, version, completed) VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET completed = excluded.completed
    """, (user_id, version, json.dumps(completed)))
    db.commit()
    return jsonify({"payload": json.dumps({"version": version, "completed": completed})})


# +-------------------------------------------------------------------------+
# ✦  DAILY MISSIONS                                                        ✦
# +-------------------------------------------------------------------------+

@app.route("/v2/rpc/dailyMission.schedule", methods=["GET", "POST"])
def daily_missions_get_schedule():
    now      = int(time.time())
    today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return jsonify({"payload": json.dumps({
        "dailyMissionDateKey":   today,
        "dailyMissions":         ["daily_reward", "daily_sell_items", "daily_kill_monsters"],
        "dailyMissionResetTime": int(tomorrow.timestamp()),
        "currentTime":           now,
    })})

@app.route("/v2/rpc/dailyMission.getData", methods=["POST", "GET"])
def daily_missions_get_data():
    payload     = parse_rpc_payload(request)
    mission_ids = payload.get("missionIDs", [])
    missions    = [{
        "id":                mid,
        "name":              mid.replace("_", " ").title(),
        "description":       f"Complete the {mid} mission",
        "rewardHard":        50,
        "rewardResearchPoints": 5,
        "taskType":          "DailyReward",
        "args":              [],
    } for mid in mission_ids]
    return jsonify({"payload": json.dumps({"missions": missions})})

@app.route("/v2/rpc/dailyMission.progress", methods=["POST", "GET"])
def daily_missions_get_progress():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"progress": []})})
    payload  = parse_rpc_payload(request)
    date_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if "missionID" in payload and "progress" in payload:
        if not is_weekend_est():
            db = get_db()
            db.execute("""
                INSERT INTO daily_mission_progress (user_id, mission_id, date_key, progress, completed)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, mission_id, date_key) DO UPDATE SET
                    progress = excluded.progress, completed = excluded.completed
            """, (user_id, payload["missionID"], date_key, payload.get("progress",""), 1 if payload.get("completed") else 0))
            db.commit()
        return jsonify({"payload": json.dumps({"succeeded": True, "errorCode": "None"})})
    date_key = payload.get("date", date_key)
    db   = get_db()
    rows = db.execute("SELECT * FROM daily_mission_progress WHERE user_id = ? AND date_key = ?", (user_id, date_key)).fetchall()
    return jsonify({"payload": json.dumps({"progress": [
        {"id": r["mission_id"], "progress": r["progress"], "completed": bool(r["completed"]), "collected": bool(r["collected"])}
        for r in rows
    ]})})

@app.route("/v2/rpc/dailyMission.reportProgress", methods=["POST", "GET"])
def daily_missions_report_progress():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    payload    = parse_rpc_payload(request)
    mission_id = payload.get("missionID", "")
    progress   = payload.get("progress", "")
    completed  = payload.get("completed", False)
    date_key   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not is_weekend_est():
        db = get_db()
        db.execute("""
            INSERT INTO daily_mission_progress (user_id, mission_id, date_key, progress, completed)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, mission_id, date_key) DO UPDATE SET
                progress = excluded.progress, completed = excluded.completed
        """, (user_id, mission_id, date_key, progress, 1 if completed else 0))
        db.commit()
    return jsonify({"payload": json.dumps({"succeeded": True, "errorCode": "None"})})

@app.route("/v2/rpc/dailyMission.collect", methods=["POST", "GET"])
def daily_missions_collect_reward():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    payload    = parse_rpc_payload(request)
    mission_id = payload.get("missionID", "")
    date_key   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    db         = get_db()
    row        = db.execute("SELECT * FROM daily_mission_progress WHERE user_id = ? AND mission_id = ? AND date_key = ?",
                            (user_id, mission_id, date_key)).fetchone()
    if not row:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "MissionNotFound"})})
    if not row["completed"]:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "MissionNotCompleted"})})
    if row["collected"]:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "MissionAlreadyCollected"})})
    reward_hard = 50
    reward_rp   = 5
    db.execute("UPDATE daily_mission_progress SET collected = 1 WHERE user_id = ? AND mission_id = ? AND date_key = ?",
               (user_id, mission_id, date_key))
    if not is_weekend_est():
        db.execute("UPDATE wallets SET hard_currency = hard_currency + ?, research_points = research_points + ? WHERE user_id = ?",
                   (reward_hard, reward_rp, user_id))
    db.commit()
    wallet = fetch_wallet(user_id)
    return jsonify({"payload": json.dumps({
        "succeeded": True, "errorCode": "None",
        "wallet": serialize_wallet(wallet, user_id),
        "rewardHardCurrency":    reward_hard,
        "rewardResearchPoints":  reward_rp,
    })})


# +-------------------------------------------------------------------------+
# ✦  SCAVENGER HUNTS                                                       ✦
# +-------------------------------------------------------------------------+

@app.route("/v2/rpc/scavengerHunt.progress", methods=["POST", "GET"])
def scavenger_hunt_get_progress():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"itemIDs": [], "completed": False, "collected": False})})
    payload = parse_rpc_payload(request)
    hunt_id = payload.get("scavengerHuntID", "")
    db      = get_db()
    row     = db.execute("SELECT * FROM scavenger_hunt_progress WHERE user_id = ? AND hunt_id = ?", (user_id, hunt_id)).fetchone()
    if row:
        return jsonify({"payload": json.dumps({
            "itemIDs":   json.loads(row["item_ids"]),
            "completed": bool(row["completed"]),
            "collected": bool(row["collected"]),
        })})
    return jsonify({"payload": json.dumps({"itemIDs": [], "completed": False, "collected": False})})

@app.route("/v2/rpc/scavengerHunt.reportProgress", methods=["POST", "GET"])
@app.route("/v2/rpc/scavengerHunt.report",          methods=["POST", "GET"])
def scavenger_hunt_report_progress():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    payload = parse_rpc_payload(request)
    hunt_id = payload.get("scavengerHuntID", "")
    item_id = payload.get("scavengerHuntItemID", "")
    db      = get_db()
    row     = db.execute("SELECT * FROM scavenger_hunt_progress WHERE user_id = ? AND hunt_id = ?", (user_id, hunt_id)).fetchone()
    if row:
        items = json.loads(row["item_ids"])
        if item_id in items:
            wallet = fetch_wallet(user_id)
            return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "ScavengerHuntItemAlreadyCollected", "wallet": serialize_wallet(wallet, user_id), "rewardHardCurrency": 0})})
        items.append(item_id)
        db.execute("UPDATE scavenger_hunt_progress SET item_ids = ? WHERE user_id = ? AND hunt_id = ?", (json.dumps(items), user_id, hunt_id))
    else:
        db.execute("INSERT INTO scavenger_hunt_progress (user_id, hunt_id, item_ids) VALUES (?, ?, ?)", (user_id, hunt_id, json.dumps([item_id])))
    db.commit()
    wallet = fetch_wallet(user_id)
    return jsonify({"payload": json.dumps({"succeeded": True, "completed": False, "errorCode": "None", "wallet": serialize_wallet(wallet, user_id), "rewardHardCurrency": 0})})

@app.route("/v2/rpc/scavengerHunt.collect", methods=["POST", "GET"])
def scavenger_hunt_collect_reward():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    payload = parse_rpc_payload(request)
    hunt_id = payload.get("scavengerHuntID", "")
    db      = get_db()
    row     = db.execute("SELECT * FROM scavenger_hunt_progress WHERE user_id = ? AND hunt_id = ?", (user_id, hunt_id)).fetchone()
    if not row:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "ScavengerHuntNotFound"})})
    if not row["completed"]:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "ScavengerHuntNotCompleted"})})
    if row["collected"]:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "ScavengerHuntAlreadyCollected"})})
    reward_hard = 100
    reward_rp   = 10
    db.execute("UPDATE scavenger_hunt_progress SET collected = 1 WHERE user_id = ? AND hunt_id = ?", (user_id, hunt_id))
    if not is_weekend_est():
        db.execute("UPDATE wallets SET hard_currency = hard_currency + ?, research_points = research_points + ? WHERE user_id = ?",
                   (reward_hard, reward_rp, user_id))
    db.commit()
    wallet = fetch_wallet(user_id)
    return jsonify({"payload": json.dumps({
        "succeeded": True, "errorCode": "None",
        "wallet": serialize_wallet(wallet, user_id),
        "rewardHardCurrency":   reward_hard,
        "rewardResearchPoints": reward_rp,
    })})


# +-------------------------------------------------------------------------+
# ✦  PROMO CODES                                                           ✦
# +-------------------------------------------------------------------------+

@app.route("/v2/rpc/promo.redeem", methods=["POST", "GET"])
def promo_code_redeem():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    payload = parse_rpc_payload(request)
    code    = payload.get("code", "").strip().upper()
    db      = get_db()
    if db.execute("SELECT * FROM promo_redemptions WHERE user_id = ? AND code = ?", (user_id, code)).fetchone():
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "AlreadyRedeemed"})})
    promo = db.execute("SELECT * FROM promo_codes WHERE code = ? AND active = 1", (code,)).fetchone()
    if not promo:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "PromoCodeNotFound"})})
    if promo["max_redemptions"] > 0 and promo["times_redeemed"] >= promo["max_redemptions"]:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "RedeemLimitReached"})})
    reward_soft            = promo["reward_soft"]
    reward_hard            = promo["reward_hard"]
    reward_rp              = promo["reward_research"]
    reward_avatar_items    = json.loads(promo["reward_avatar_items"])
    reward_research_items  = json.loads(promo["reward_research_items"])
    if reward_soft or reward_hard or reward_rp:
        db.execute("UPDATE wallets SET soft_currency = soft_currency + ?, hard_currency = hard_currency + ?, research_points = research_points + ? WHERE user_id = ?",
                   (reward_soft, reward_hard, reward_rp, user_id))
    if reward_avatar_items:
        inv = read_storage(user_id, "user_inventory", "avatar", {"items": []})
        for item in reward_avatar_items:
            if item not in inv.get("items", []):
                inv.setdefault("items", []).append(item)
        write_storage(user_id, "user_inventory", "avatar", inv)
    if reward_research_items:
        inv = read_storage(user_id, "user_inventory", "research", {"nodes": []})
        for node in reward_research_items:
            if node not in inv.get("nodes", []):
                inv.setdefault("nodes", []).append(node)
        write_storage(user_id, "user_inventory", "research", inv)
    db.execute("INSERT INTO promo_redemptions (user_id, code, redeemed_at) VALUES (?, ?, ?)", (user_id, code, int(time.time())))
    db.execute("UPDATE promo_codes SET times_redeemed = times_redeemed + 1 WHERE code = ?", (code,))
    db.commit()
    wallet       = fetch_wallet(user_id)
    avatar_inv   = read_storage(user_id, "user_inventory", "avatar", {"items": []})
    research_inv = read_storage(user_id, "user_inventory", "research", {"nodes": []})
    return jsonify({"payload": json.dumps({
        "succeeded": True, "errorCode": "None",
        "rewardSoftCurrency":   reward_soft,
        "rewardHardCurrency":   reward_hard,
        "rewardResearchPoints": reward_rp,
        "wallet":               serialize_wallet(wallet, user_id),
        "inventoryAvatarItems":   avatar_inv.get("items", []),
        "inventoryResearchItems": research_inv.get("nodes", []),
    })})


# +-------------------------------------------------------------------------+
# ✦  VR PRESENCE                                                           ✦
# +-------------------------------------------------------------------------+

@app.route("/v2/rpc/user.getVRPresence", methods=["GET", "POST"])
def presence_get_current():
    return jsonify({"payload": json.dumps({
        "presence": {"roomCode": "", "gameMode": 0, "appearOffline": False, "clientVersion": "", "photonVersion": ""},
        "errorCode": 0,
    })})


# +-------------------------------------------------------------------------+
# ✦  SANCTIONS                                                             ✦
# +-------------------------------------------------------------------------+

@app.route("/v2/rpc/user.getActiveSanctions", methods=["GET", "POST"])
def sanctions_get_active():
    return jsonify({"payload": json.dumps([])})


# +-------------------------------------------------------------------------+
# ✦  USER PREFERENCES                                                      ✦
# +-------------------------------------------------------------------------+

@app.route("/v2/rpc/preferences.get", methods=["GET", "POST"])
def preferences_get():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": "{}"})
    return jsonify({"payload": json.dumps(read_storage(user_id, "user_preferences", "settings", {}))})

@app.route("/v2/rpc/preferences.set", methods=["POST", "GET"])
def preferences_set():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": "{}"})
    write_storage(user_id, "user_preferences", "settings", parse_rpc_payload(request))
    return jsonify({"payload": "{}"})

@app.route("/v2/rpc/preferences.getGameplayItems", methods=["GET", "POST"])
def preferences_get_gameplay_items():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": "{}"})
    return jsonify({"payload": json.dumps(read_storage(user_id, "user_preferences", "gameplay_items", {"recents": [], "favorites": []}))})

@app.route("/v2/rpc/preferences.setGameplayItems", methods=["POST", "GET"])
def preferences_set_gameplay_items():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": "{}"})
    write_storage(user_id, "user_preferences", "gameplay_items", parse_rpc_payload(request))
    return jsonify({"payload": "{}"})

@app.route("/v2/rpc/preferences.getSkills", methods=["GET", "POST"])
def preferences_get_skills():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": "{}"})
    return jsonify({"payload": json.dumps(read_storage(user_id, "user_preferences", "skills", {"disabledSkills": []}))})

@app.route("/v2/rpc/preferences.setSkills", methods=["POST", "GET"])
def preferences_set_skills():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": "{}"})
    write_storage(user_id, "user_preferences", "skills", parse_rpc_payload(request))
    return jsonify({"payload": "{}"})


# +-------------------------------------------------------------------------+
# ✦  PRIVATE ROOMS                                                         ✦
# +-------------------------------------------------------------------------+

def _build_room_response(db, code, succeeded=True, error="None"):
    row = db.execute("SELECT * FROM private_rooms WHERE code = ?", (code,)).fetchone()
    if not row:
        return {"succeeded": False, "errorCode": "Unknown",
                "privateRoom": {"code": "", "expiresAt": 0, "owner": "", "members": [], "settings": {}}, "bannedUsers": []}
    return {
        "succeeded":  succeeded,
        "errorCode":  error,
        "privateRoom": {
            "code":      row["code"],
            "expiresAt": row["expires_at"],
            "owner":     row["owner"],
            "members":   json.loads(row["members"]),
            "settings": {
                "membersOnly":          bool(row["members_only"]),
                "membersCanModerate":   bool(row["members_can_moderate"]),
                "membersCanManage":     bool(row["members_can_manage"]),
                "friendlyFireEnabled":  bool(row["friendly_fire"]),
            },
        },
        "bannedUsers": json.loads(row["banned_users"]),
    }

@app.route("/v2/rpc/privateRooms.get", methods=["POST", "GET"])
def private_room_get():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    payload = parse_rpc_payload(request)
    db      = get_db()
    return jsonify({"payload": json.dumps(_build_room_response(db, payload.get("roomCode", "")))})

@app.route("/v2/rpc/privateRooms.purchase", methods=["POST", "GET"])
def private_room_purchase():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    payload   = parse_rpc_payload(request)
    room_code = payload.get("roomCode","") or secrets.token_hex(4).upper()
    db        = get_db()
    if db.execute("SELECT * FROM private_rooms WHERE code = ?", (room_code,)).fetchone():
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "AlreadyOwned"})})
    db.execute("INSERT INTO private_rooms (code, owner, expires_at, members) VALUES (?, ?, ?, ?)",
               (room_code, user_id, int(time.time()) + (30*24*3600), json.dumps([])))
    db.commit()
    return jsonify({"payload": json.dumps(_build_room_response(db, room_code))})

@app.route("/v2/rpc/privateRooms.update", methods=["POST", "GET"])
def private_room_update_settings():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    payload   = parse_rpc_payload(request)
    room_code = payload.get("roomCode", "")
    settings  = payload.get("settings", {})
    db        = get_db()
    room      = db.execute("SELECT * FROM private_rooms WHERE code = ?", (room_code,)).fetchone()
    if not room:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    if room["owner"] != user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "NotOwner"})})
    db.execute("UPDATE private_rooms SET members_only=?, members_can_moderate=?, members_can_manage=?, friendly_fire=? WHERE code=?",
               (settings.get("membersOnly",False), settings.get("membersCanModerate",False),
                settings.get("membersCanManage",False), settings.get("friendlyFireEnabled",False), room_code))
    db.commit()
    return jsonify({"payload": json.dumps(_build_room_response(db, room_code))})

@app.route("/v2/rpc/privateRooms.addMember", methods=["POST", "GET"])
def private_room_add_member():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    payload   = parse_rpc_payload(request)
    room_code = payload.get("roomCode", "")
    target_id = payload.get("targetUserID", "")
    db        = get_db()
    room      = db.execute("SELECT * FROM private_rooms WHERE code = ?", (room_code,)).fetchone()
    if not room:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    members = json.loads(room["members"])
    if target_id not in members:
        members.append(target_id)
        db.execute("UPDATE private_rooms SET members = ? WHERE code = ?", (json.dumps(members), room_code))
        db.commit()
    return jsonify({"payload": json.dumps(_build_room_response(db, room_code))})

@app.route("/v2/rpc/privateRooms.removeMember", methods=["POST", "GET"])
def private_room_remove_member():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    payload   = parse_rpc_payload(request)
    room_code = payload.get("roomCode", "")
    target_id = payload.get("targetUserID", "")
    db        = get_db()
    room      = db.execute("SELECT * FROM private_rooms WHERE code = ?", (room_code,)).fetchone()
    if not room:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    members = json.loads(room["members"])
    if target_id in members:
        members.remove(target_id)
        db.execute("UPDATE private_rooms SET members = ? WHERE code = ?", (json.dumps(members), room_code))
        db.commit()
    return jsonify({"payload": json.dumps(_build_room_response(db, room_code))})

@app.route("/v2/rpc/privateRooms.kickUser", methods=["POST", "GET"])
def private_room_kick():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    payload   = parse_rpc_payload(request)
    room_code = payload.get("roomCode", "")
    target_id = payload.get("targetUserID", "")
    clear     = payload.get("clear", False)
    db        = get_db()
    room      = db.execute("SELECT * FROM private_rooms WHERE code = ?", (room_code,)).fetchone()
    if not room:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    if clear:
        members = json.loads(room["members"])
        if target_id in members:
            members.remove(target_id)
            db.execute("UPDATE private_rooms SET members = ? WHERE code = ?", (json.dumps(members), room_code))
            db.commit()
    return jsonify({"payload": json.dumps(_build_room_response(db, room_code))})

@app.route("/v2/rpc/privateRooms.banUser", methods=["POST", "GET"])
def private_room_ban():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    payload   = parse_rpc_payload(request)
    room_code = payload.get("roomCode", "")
    target_id = payload.get("targetUserID", "")
    clear     = payload.get("clear", False)
    db        = get_db()
    room      = db.execute("SELECT * FROM private_rooms WHERE code = ?", (room_code,)).fetchone()
    if not room:
        return jsonify({"payload": json.dumps({"succeeded": False, "errorCode": "Unknown"})})
    banned  = json.loads(room["banned_users"])
    members = json.loads(room["members"])
    if clear:
        if target_id in banned:
            banned.remove(target_id)
    else:
        if target_id not in banned:
            banned.append(target_id)
        if target_id in members:
            members.remove(target_id)
    db.execute("UPDATE private_rooms SET banned_users = ?, members = ? WHERE code = ?",
               (json.dumps(banned), json.dumps(members), room_code))
    db.commit()
    return jsonify({"payload": json.dumps(_build_room_response(db, room_code))})


# +-------------------------------------------------------------------------+
# ✦  REPORTING & MODERATION                                                ✦
# +-------------------------------------------------------------------------+

@app.route("/v2/rpc/report.user", methods=["POST", "GET"])
def report_user():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": "{}"})
    payload   = parse_rpc_payload(request)
    target_id = payload.get("targetUserID", "")
    reason    = payload.get("reason", "")
    db        = get_db()
    db.execute("INSERT INTO user_reports (reporter_id, target_user_id, reason, created_at) VALUES (?, ?, ?, ?)",
               (user_id, target_id, reason, int(time.time())))
    db.commit()
    return jsonify({"payload": "{}"})

@app.route("/v2/rpc/room.ban", methods=["POST", "GET"])
def room_ban_user():
    return jsonify({"payload": "{}"})


# +-------------------------------------------------------------------------+
# ✦  MOBILE LINKING                                                        ✦
# +-------------------------------------------------------------------------+

@app.route("/v2/rpc/mobile.getPairingCode", methods=["GET", "POST"])
def mobile_get_pairing_code():
    now = int(time.time())
    return jsonify({"payload": json.dumps({"pairingCode": secrets.token_hex(4).upper(), "expiresAt": now + 300, "errorCode": 0})})

@app.route("/v2/rpc/mobile.startLinkDevice", methods=["POST", "GET"])
def mobile_start_link():
    now = int(time.time())
    return jsonify({"payload": json.dumps({"verificationCode": secrets.token_hex(3).upper(), "expiresAt": now + 300})})

@app.route("/v2/rpc/mobile.confirmLinkDevice", methods=["POST", "GET"])
def mobile_confirm_link():
    return jsonify({"payload": json.dumps({})})

@app.route("/v2/rpc/mobile.finishLinkDevice", methods=["POST", "GET"])
def mobile_finish_link():
    user_id = extract_uid_from_token()
    now     = int(time.time())
    return jsonify({"payload": json.dumps({
        "deviceID":  secrets.token_hex(8),
        "secret":    secrets.token_hex(16),
        "password":  secrets.token_hex(16),
        "expiresAt": now + 86400 * 365,
        "userID":    user_id or "",
        "username":  "",
    })})

@app.route("/v2/rpc/mobile.abortLinkDevice", methods=["POST", "GET"])
def mobile_abort_link():
    return jsonify({"payload": json.dumps({"errorCode": 0})})


# +-------------------------------------------------------------------------+
# ✦  FRIENDS & NOTIFICATIONS                                               ✦
# +-------------------------------------------------------------------------+

@app.route("/v2/friend",  methods=["GET"])
@app.route("/v2/friends", methods=["GET"])
def list_friends():
    return jsonify({"friends": [], "cursor": ""})

@app.route("/v2/friend", methods=["POST"])
def add_friends():
    return jsonify({})

@app.route("/v2/friend",       methods=["DELETE"])
@app.route("/v2/friend/block", methods=["POST"])
def manage_friends():
    return jsonify({})

@app.route("/v2/notification", methods=["GET"])
def list_notifications():
    return jsonify({"notifications": [], "cacheable_cursor": ""})

@app.route("/v2/notification", methods=["DELETE"])
def delete_notifications():
    return jsonify({})


# +-------------------------------------------------------------------------+
# ✦  PURCHASES & IAP                                                       ✦
# +-------------------------------------------------------------------------+

@app.route("/v2/rpc/purchase.list", methods=["GET"])
def purchase_list():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"purchases": []})})
    db   = get_db()
    rows = db.execute("SELECT * FROM purchases WHERE user_id = ? ORDER BY purchase_time DESC", (user_id,)).fetchall()
    return jsonify({"payload": json.dumps({"purchases": [
        {"product_id": r["product_id"], "transaction_id": r["transaction_id"], "store": r["store"]} for r in rows
    ]})})

IAP_REWARD_TABLE = {
    "CELESTIAL_CELEBRATION_PACK":   {"hard": 5000, "research": 10, "avatarItems": []},
    "CURRENCY_SMALL":               {"hard": 1000, "avatarItems": []},
    "CURRENCY_MEDIUM":              {"hard": 2200, "avatarItems": []},
    "CURRENCY_LARGE":               {"hard": 5000, "avatarItems": []},
    "EXTRA_LARGE_CURRENCY_PACK":    {"hard": 11000, "avatarItems": []},
    "FROG_BUNDLE":                  {"hard": 10000, "avatarItems": ["character_sigma_frog","acc_fit_business_suit","acc_head_black_1984_headphones","animal_frog","bp_arm_l_frog","bp_arm_r_frog","bp_butt_frog","bp_eye_frog","bp_head_frog","bp_torso_frog"]},
    "G.O.A.T_BUNDLE":               {"hard": 10000, "avatarItems": ["character_goat","character_goat_ram","character_goat_smallhorns","acc_face_glasses_coolglasses","acc_fit_coolsuit","acc_fit_coolsuit_bluewhite","acc_fit_coolsuit_purplewhite","animal_goat","bp_arm_l_goat","bp_arm_r_goat","bp_butt_goat","bp_eye_goat","bp_head_goat","bp_head_goat_ramhorns","bp_head_goat_shorthorns","bp_tail_goat","bp_torso_goat","outfit_employee_suit_blue","outfit_employee_suit_gold","outfit_employee_suit_purple"]},
    "GRIM_GORILLA_BUNDLE":          {"hard": 10000, "avatarItems": ["character_grim_gorilla","acc_fit_grimreaper","animal_skeletongorilla","bp_arm_l_skeletongorilla","bp_arm_r_skeletongorilla","bp_butt_skeletongorilla","bp_eye_skeletongorilla","bp_head_skeletongorilla","bp_torso_skeletongorilla"]},
    "HOLIDAY_COINS_BAG":            {"hard": 2500, "avatarItems": []},
    "LUCKY_PACK":                   {"hard": 2500, "avatarItems": []},
    "MOLE_A_TOV_BUNDLE":            {"hard": 10000, "avatarItems": ["character_mole_a_tov","outfit_demolitionjumpsuit","outfit_demolitionjumpsuit_green","outfit_demolitionjumpsuit_red","acc_face_goggles","acc_face_goggles_green","acc_face_goggles_red","acc_fit_demolitionjumpsuit","acc_fit_demolitionjumpsuit_green","acc_fit_demolitionjumpsuit_red","acc_head_minerhat","acc_head_minerhat_green","acc_head_minerhat_red","animal_mole","bp_arm_l_mole","bp_arm_r_mole","bp_butt_mole","bp_eye_mole","bp_head_mole","bp_tail_mole","bp_torso_mole"]},
    "POLAR_PAWS_BUNDLE":            {"hard": 2000, "avatarItems": ["character_polar_paws","acc_fit_winterscarf","acc_head_winterglasses","animal_polarbear","bp_arm_l_polarbear","bp_arm_r_polarbear","bp_butt_polarbear","bp_eye_polarbear","bp_head_polarbear","bp_tail_polarbear","bp_torso_polarbear"]},
    "POT_OF_GOLD":                  {"hard": 10000, "avatarItems": []},
    "RED_ENVELOPE_PACK":            {"hard": 2200, "research": 4, "avatarItems": []},
    "RESEARCH_PACK":                {"soft": 25000, "research": 12, "avatarItems": []},
    "SHELLLONG_BUNDLE":             {"hard": 10000, "avatarItems": ["bp_torso_turtle_shell2","bp_torso_turtle_shell3","bp_torso_turtle_shell4","character_shelllong","outfit_kungfu_black","outfit_kungfu_blue","acc_fit_kungfucoat","acc_fit_kungfucoat_black","acc_fit_kungfucoat_blue","acc_head_kungfuhat","acc_head_ricepattyhat","acc_head_ricepattyhat_blue","animal_turtle","bp_arm_l_turtle","bp_arm_r_turtle","bp_butt_turtle","bp_eye_turtle","bp_head_turtle","bp_torso_turtle"]},
    "SPRING_BLING_SUPER":           {"hard": 3500, "research": 10, "avatarItems": []},
    "SPRING_BUNDLE_STARTER":        {"hard": 1500, "research": 4, "avatarItems": []},
    "SWAG_STAG_BUNDLE":             {"hard": 10000, "avatarItems": ["character_swag_stag","acc_face_glasses_holiday","acc_fit_holidaysuit","animal_reindeer","bp_arm_l_reindeer","bp_arm_r_reindeer","bp_butt_reindeer","bp_eye_reindeer","bp_head_reindeer","bp_tail_reindeer","bp_torso_reindeer"]},
    "TURKEY_HUNTER_BUNDLE":         {"hard": 10000, "avatarItems": ["character_turkey_hunter","acc_fit_turkeyhunter","acc_head_turkeyhunter","animal_turkey","bp_arm_l_turkey","bp_arm_r_turkey","bp_butt_turkey","bp_eye_turkey","bp_head_turkey","bp_tail_turkey","bp_torso_turkey"]},
    "VALENTINES_BUNDLE_A":          {"hard": 1000, "avatarItems": ["outfit_valentines_youme","acc_face_glasses_heart","acc_fit_tight_fit_blue_tshirt_heartshirt"]},
    "VALENTINES_BUNDLE_B":          {"hard": 2200, "avatarItems": ["outfit_valentines_suit","acc_fit_business_suit_heartsuit","acc_mouthcorner_rose"]},
}

@app.route("/v2/rpc/purchase.validate",            methods=["POST", "GET"])
@app.route("/v2/rpc/purchase.metaQuest",           methods=["POST", "GET"])
@app.route("/v2/rpc/purchase.validateMetaQuest",   methods=["POST", "GET"])
def purchase_validate():
    user_id = extract_uid_from_token()
    if not user_id:
        return jsonify({"payload": json.dumps({"valid": False, "newPurchase": False, "id": ""})})
    payload        = parse_rpc_payload(request)
    product_id     = payload.get("product_id","") or payload.get("productId","") or payload.get("sku","") or payload.get("Sku","")
    transaction_id = payload.get("id","") or payload.get("transactionId","") or payload.get("transaction_id","") or payload.get("ID","") or secrets.token_hex(8)
    db             = get_db()
    now            = int(time.time())
    is_new         = not db.execute("SELECT id FROM purchases WHERE user_id = ? AND transaction_id = ?", (user_id, transaction_id)).fetchone()
    if is_new:
        db.execute("INSERT INTO purchases (user_id, product_id, transaction_id, purchase_time, create_time) VALUES (?,?,?,?,?)",
                   (user_id, product_id, transaction_id, now, now))
        rewards        = IAP_REWARD_TABLE.get(product_id, {})
        reward_soft    = rewards.get("soft", 0)
        reward_hard    = rewards.get("hard", 0)
        reward_research = rewards.get("research", 0)
        reward_avatar  = rewards.get("avatarItems", [])
        if reward_soft or reward_hard or reward_research:
            db.execute("UPDATE wallets SET soft_currency = soft_currency + ?, hard_currency = hard_currency + ?, research_points = research_points + ? WHERE user_id = ?",
                       (reward_soft, reward_hard, reward_research, user_id))
        if reward_avatar:
            inv = read_storage(user_id, "user_inventory", "avatar", {"items": []})
            for item in reward_avatar:
                if item not in inv.get("items", []):
                    inv.setdefault("items", []).append(item)
            write_storage(user_id, "user_inventory", "avatar", inv)
        db.commit()
    return jsonify({"payload": json.dumps({"valid": True, "newPurchase": is_new, "id": transaction_id})})


# +-------------------------------------------------------------------------+
# ✦  GAME DATA & BOOTSTRAP                                                 ✦
# +-------------------------------------------------------------------------+

@app.route("/AddUserToDevMenu", methods=["POST"])
def add_user_to_dev_menu():
    if request.headers.get("X-Dev-Secret", "") != DISCORD_DEV_SECRET:
        return jsonify({"error": "unauthorized"}), 401
    body = safe_json_body(request)
    oculus_username = (body.get("oculus_username") or "").strip()
    discord_id      = str(body.get("discord_id") or "").strip()
    if not oculus_username or not discord_id:
        return jsonify({"error": "missing oculus_username or discord_id"}), 400
    conn = _discord_dev_db()
    conn.execute(
        "INSERT INTO discord_devs (oculus_username, discord_id) VALUES (?, ?) "
        "ON CONFLICT(oculus_username) DO UPDATE SET discord_id = excluded.discord_id",
        (oculus_username, discord_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/RemoveUserFromDevMenu", methods=["POST"])
def remove_user_from_dev_menu():
    if request.headers.get("X-Dev-Secret", "") != DISCORD_DEV_SECRET:
        return jsonify({"error": "unauthorized"}), 401
    body = safe_json_body(request)
    oculus_username = (body.get("oculus_username") or "").strip()
    discord_id      = str(body.get("discord_id") or "").strip()
    if not oculus_username and not discord_id:
        return jsonify({"error": "missing oculus_username or discord_id"}), 400
    conn = _discord_dev_db()
    if oculus_username:
        cur = conn.execute("DELETE FROM discord_devs WHERE oculus_username = ? COLLATE NOCASE", (oculus_username,))
    else:
        cur = conn.execute("DELETE FROM discord_devs WHERE discord_id = ?", (discord_id,))
    conn.commit()
    removed = cur.rowcount
    conn.close()
    return jsonify({"ok": True, "removed": removed})

@app.route("/canIuseDevMenu", methods=["GET"])
def can_use_dev_menu():
    allowed = get_client_ip() == DEV_IP
    return jsonify({"allowed": allowed})

@app.route("/v2/rpc/clientBootstrap", methods=["GET", "POST"])
def client_bootstrap():
    now = int(time.time())
    today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    payload  = {
        "attestResult":          "Valid",
        "attestTokenExpiresAt":  now + 36000,
        "photonAppID":           PHOTON_APP_ID,
        "photonVoiceAppID":      PHOTON_VOICE_APP_ID,
        "termsAcceptanceNeeded": [],
        "dailyMissionDateKey":   today,
        "dailyMissions":         ["daily_reward", "daily_sell_items", "daily_kill_monsters"],
        "dailyMissionResetTime": int(tomorrow.timestamp()),
        "vrPresence": {"roomCode": "", "gameMode": 0, "appearOffline": False, "clientVersion": "", "photonVersion": ""},
        "gameDataURL":           GAME_DATA_URL,
    }
    return jsonify({"payload": json.dumps(payload)})

@app.route("/game-data-prod.zip", methods=["GET"])
def game_data_prod():
    return send_file(GAME_DATA_PATH, mimetype="application/zip")


# +-------------------------------------------------------------------------+
# ✦  DEBUG & FALLBACK                                                      ✦
# +-------------------------------------------------------------------------+

@app.route("/v2/rpc/<path:rpc_id>", methods=["GET", "POST"])
def rpc_catchall(rpc_id):
    print(f"[RPC] Unhandled: {rpc_id} body={request.get_data(as_text=True)[:300]}")
    return jsonify({"payload": "{}"})

@app.route("/debug", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def debug_endpoint():
    return jsonify({
        "method":  request.method,
        "url":     request.url,
        "headers": dict(request.headers),
        "body":    request.get_data(as_text=True),
    })


# -----------------------------------------------------------------------------
# BACKEND MADE BY XERA, CREDIT IF USED!
# If you're running this, please star the repo - it's months of Animal
# Company RE work given away for free, and a star costs you nothing:
# https://github.com/Xera-Games-LLC/Xera-Company-Backend
# -----------------------------------------------------------------------------

application = app

if __name__ == "__main__":
    # Remember to set your env vars (or .env file) before running - see the
    # SERVER CONFIG section near the top of this file for what's needed.
    print("=" * 70)
    print("  Xera Company Private Server — starting up")
    print("  BACKEND MADE BY XERA, CREDIT IF USED!")
    print("  If you use this, please star the repo — costs nothing, helps a ton:")
    print("  https://github.com/Xera-Games-LLC/Xera-Company-Backend")
    print("=" * 70)
    app.run(debug=True, host="0.0.0.0", port=5000)
