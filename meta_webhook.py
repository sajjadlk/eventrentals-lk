#!/opt/hermes/.venv/bin/python
"""
Meta WhatsApp Webhook Bot - Direct integration (no WhatChimp)
Receives messages via Meta Cloud API webhook, replies via Meta API.
Uses Zara's MWAI AI Engine for responses.
"""
import json, os, re, logging, urllib.request, base64
from http.server import HTTPServer, BaseHTTPRequestHandler

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Config ---
PORT = 8085
VERIFY_TOKEN = "zara-webhook-2026"

# Meta WhatsApp Cloud API
META_PHONE_NUMBER_ID = "1050615101468013"
META_API = "https://graph.facebook.com/v22.0/{}/messages".format(META_PHONE_NUMBER_ID)

# Load Meta token from .env
META_ACCESS_TOKEN = ""
env_path = "/opt/data/er-telegram-bot/.env"
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("META_ACCESS_TOKEN="):
                val = line.split("=", 1)[1].strip(' "\'')
                if val:
                    META_ACCESS_TOKEN = val

# MWAI (Zara) config
BASE = "https://eventrentals.lk"
APP_USER = "zara@eventrentals.lk"
APP_PASS = "JU7x taUx 3vvG 1nXk mpDw b9i5"
AUTH_FIELD = "{}:{}".format(APP_USER, APP_PASS)
AUTH_ENC = base64.b64encode(AUTH_FIELD.encode()).decode()
AUTH_HEADERS = {"Authorization": "Basic {}".format(AUTH_ENC), "User-Agent": "Mozilla/5.0"}

# BOT SELECTOR - switch between production and test
USE_TEST_BOT = True  # Set True to use test bot
PROD_BOT_ID = "zara-eventrentals"
PROD_ENV_ID = "5w30oam6"
TEST_BOT_ID = "chatbot-rc3469"  # Zara Test
TEST_ENV_ID = "5w30oam6"

def get_active_config():
    if USE_TEST_BOT:
        return TEST_BOT_ID, TEST_ENV_ID
    return PROD_BOT_ID, PROD_ENV_ID

# State
conversations = {}
nonce = ""

def refresh_nonce():
    global nonce
    bot_id, _ = get_active_config()
    body = json.dumps({"botId": bot_id}).encode()
    req = urllib.request.Request(BASE + "/wp-json/mwai/v1/start_session", data=body, method="POST")
    for k, v in AUTH_HEADERS.items():
        req.add_header(k, v)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            nonce = json.loads(r.read()).get("restNonce", "")
        logger.info("Nonce refreshed: {}...".format(nonce[:12]))
    except Exception as e:
        logger.error("Nonce refresh failed: {}".format(e))

def call_zara(messages):
    global nonce
    if not nonce:
        refresh_nonce()
    bot_id, env_id = get_active_config()
    body = json.dumps({"botId": bot_id, "messages": messages, "envId": env_id, "stream": False}).encode()
    url = BASE + "/wp-json/mwai/v1/ai/completions"
    req = urllib.request.Request(url, data=body, method="POST")
    for k, v in AUTH_HEADERS.items():
        req.add_header(k, v)
    req.add_header("X-WP-Nonce", nonce)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read().decode())
            return resp.get("reply") or resp.get("data", "")
    except urllib.error.HTTPError as e:
        err = e.read().decode()[:300]
        logger.warning("Zara HTTP {}: {}".format(e.code, err))
        if e.code == 401:
            refresh_nonce()
            req2 = urllib.request.Request(url, data=body, method="POST")
            for k, v in AUTH_HEADERS.items():
                req2.add_header(k, v)
            req2.add_header("X-WP-Nonce", nonce)
            req2.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req2, timeout=60) as r2:
                resp2 = json.loads(r2.read().decode())
                return resp2.get("reply") or resp2.get("data", "")
        return None

def send_whatsapp(phone, text):
    if not META_ACCESS_TOKEN:
        logger.error("No META_ACCESS_TOKEN")
        return False
    body = json.dumps({
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": text[:4096]}
    }).encode()
    req = urllib.request.Request(META_API, data=body, method="POST")
    req.add_header("Authorization", "Bearer {}".format(META_ACCESS_TOKEN))
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15):
            return True
    except Exception as e:
        logger.error("Send failed: {}".format(e))
        return False

def handle_message(phone, msg_text):
    # Detect chairs/tables queries
    is_chair = bool(re.search(r'\b(chairs?|seating|seats|sitting)\b', msg_text, re.IGNORECASE))
    is_table = bool(re.search(r'\b(tables?|dining)\b', msg_text, re.IGNORECASE))
    
    # Inject promoted product prompt
    if is_chair:
        user_prompt = (
            "IMPORTANT: You MUST list **Cross Back Chairs Dark Tan** FIRST as the featured option. "
            "It is Rs.350 (on offer) - https://eventrentals.lk/product/cross-back-chairs-dark-tan/\n\n"
            "Then list the other seating products.\n\n"
            "DO NOT include Cooler Fans, Mirrors, or other non-seating items.\n\n"
            "Customer: " + msg_text
        )
    elif is_table:
        user_prompt = (
            "IMPORTANT: You MUST list **Barn Table** FIRST as the featured table option. "
            "It is Rs.3000 (on offer) - https://eventrentals.lk/product/barn-table/\n\n"
            "Then list the other table options.\n\n"
            "DO NOT include Cooler Fans, Mirrors, or other non-table items.\n\n"
            "Customer: " + msg_text
        )
    else:
        user_prompt = msg_text
    
    if phone not in conversations:
        conversations[phone] = [
            {"role": "system", "content": "You are Zara, EventRentals.lk AI assistant. Help customers with product info, pricing, and bookings. Be warm and concise."}
        ]
    conversations[phone].append({"role": "user", "content": user_prompt})
    conversations[phone] = conversations[phone][-21:]
    reply = call_zara(conversations[phone])
    if reply:
        conversations[phone].append({"role": "assistant", "content": reply})
        # Send promoted product card first
        if is_chair:
            send_whatsapp(phone, "\ud83d\udce6 *Cross Back Chairs Dark Tan* - Rs.350 (on offer)\nhttps://eventrentals.lk/product/cross-back-chairs-dark-tan/")
        elif is_table:
            send_whatsapp(phone, "\ud83d\udce6 *Barn Table* - Rs.3000 (on offer)\nhttps://eventrentals.lk/product/barn-table/")
        send_whatsapp(phone, reply)
        logger.info("Replied to {}: {}...".format(phone, reply[:80]))
    else:
        logger.warning("No reply for {}".format(phone))

class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = {}
        if "?" in self.path:
            for part in self.path.split("?")[1].split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    params[k] = v
        mode = params.get("hub.mode", "")
        token = params.get("hub.verify_token", "")
        challenge = params.get("hub.challenge", "")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(challenge.encode())
            logger.info("Webhook verified!")
        else:
            self.send_response(403)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self.send_response(200)
            self.end_headers()
            return
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    phone = msg.get("from", "")
                    msg_type = msg.get("type", "")
                    if msg_type == "text":
                        text = msg.get("text", {}).get("body", "")
                        if text and phone:
                            logger.info("Incoming {}: {}".format(phone, text[:60]))
                            handle_message(phone, text)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok"}).encode())

    def log_message(self, format, *args):
        logger.info("{} {} {}".format(args[0], args[1], args[2]))

def main():
    refresh_nonce()
    bot_id, env_id = get_active_config()
    mode = "TEST" if USE_TEST_BOT else "PRODUCTION"
    logger.info("Meta Webhook Bot starting on port {} (MODE: {}, bot: {}, env: {})".format(PORT, mode, bot_id, env_id))
    logger.info("Verify token: {}".format(VERIFY_TOKEN))
    logger.info("Meta API configured: {}".format(bool(META_ACCESS_TOKEN)))
    server = HTTPServer(("0.0.0.0", PORT), WebhookHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()

if __name__ == "__main__":
    main()
