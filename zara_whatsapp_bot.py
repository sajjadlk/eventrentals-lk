#!/opt/hermes/.venv/bin/python
"""
Zara WhatsApp Bot - Pure Natural Text
- Pre-caches all WooCommerce products at startup for instant lookups
- Reduced poll interval (2s)
- Pure natural conversation - no interactive menus, no buttons
- Zara handles everything via AI Engine (MWAI)
- Product cards sent when Zara includes URLs in her responses
- Lead capture and forwarding to business hotline
- Handles WhatChimp API edge cases
"""
import time, json, urllib.request, urllib.parse, logging, re, base64, random, os
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ——— Config ———
WC_API_KEY = "21199|21yrpyt9liOL3HDEbTqdlgWwex3bW2JbYRIzFxu18420061e"
WC_PHONE_NUMBER_ID = "1050615101468013"
WC_BASE = "https://app.whatchimp.com/api/v1"
BASE_URL = "https://eventrentals.lk"
APP_USER = "zara@eventrentals.lk"
APP_PASS = "JU7x taUx 3vvG 1nXk mpDw b9i5"
AUTH_ENC = base64.b64encode(f"{APP_USER}:{APP_PASS}".encode()).decode()
AUTH = {"Authorization": f"Basic {AUTH_ENC}"}
MWAI_URL = f"{BASE_URL}/wp-json/mwai/v1"
WC_URL = f"{BASE_URL}/wp-json/wc/v3"
BOT_ID = "zara-eventrentals"
ENV_ID = "5w30oam6"
POLL_INTERVAL = 2  # seconds between polls

# Meta WhatsApp Cloud API token (for sending images and interactive buttons).
# Generated via Business Settings → System Users → Zara API → Generate Token
# Stored in .env as META_ACCESS_TOKEN
META_ACCESS_TOKEN = ""
try:
    with open("/opt/data/er-telegram-bot/.env") as f:
        for line in f:
            line = line.strip()
            if line.startswith("META_ACCESS_TOKEN="):
                val = line.split("=", 1)[1].strip("\"'")
                if val:
                    META_ACCESS_TOKEN = val
except Exception:
    pass
if META_ACCESS_TOKEN:
    logger.info("✅ META_ACCESS_TOKEN loaded from .env")
else:
    logger.warning("⚠️ META_ACCESS_TOKEN not set — images and interactive buttons disabled")

# Business team hotline (forward leads here)
BUSINESS_HOTLINE = "94724999555"
TEST_NUMBER = "94727474743"  # Sajjad's test number — never forward leads from here

# Meta catalog (Commerce Manager) for native product cards
CATALOG_ID = "1808153763480253"
slug_to_content_id = {}     # slug -> Content ID from catalog feed

# ——— State ———
conversations = {}          # phone -> message list
last_seen = {}              # seen_key -> True
LAST_SEEN_FILE = os.path.join(os.path.dirname(__file__), "last_seen.json")

def _load_last_seen():
    global last_seen
    try:
        if os.path.exists(LAST_SEEN_FILE):
            with open(LAST_SEEN_FILE) as f:
                data = json.load(f)
                if isinstance(data, dict):
                    last_seen = data
                    logger.info(f"📦 Loaded {len(last_seen)} last_seen entries from disk")
                    return False  # not first run
    except Exception as e:
        logger.warning(f"⚠️ Could not load last_seen: {e}")
    return True  # first run — no saved state

def _save_last_seen():
    try:
        with open(LAST_SEEN_FILE, "w") as f:
            json.dump(last_seen, f)
    except Exception as e:
        logger.warning(f"⚠️ Could not save last_seen: {e}")
products_sent = {}          # phone -> set of product URLs sent this conversation
_nonce = ""
ZARA_INSTRUCTIONS = ""
product_cache = {}          # slug -> {name, price, sale_price, img_url, dimensions}
forwarded_leads = set()     # phone numbers already forwarded (avoid duplicates)

# ——— Product Cache (instant lookups, no API calls during response) ———
def _build_product_cache():
    """Fetch all WooCommerce products into a slug-keyed dict."""
    t0 = time.time()
    count = 0
    page = 1
    per_page = 100
    while True:
        url = f"{WC_URL}/products?per_page={per_page}&page={page}&status=publish&_fields=slug,name,price,sale_price,images,sku,dimensions,categories,permalink"
        req = urllib.request.Request(url, headers=AUTH)
        req.add_header("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                products = json.loads(r.read().decode())
        except Exception as e:
            logger.error(f"Cache build error page {page}: {e}")
            break
        if not products:
            break
        for p in products:
            slug = p.get("slug", "")
            if not slug:
                continue
            images = p.get("images", [])
            img_url = images[0].get("src", "") if images else ""
            product_cache[slug] = {
                "name": p.get("name", ""),
                "price": p.get("price", ""),
                "sale_price": p.get("sale_price", ""),
                "img_url": img_url,
                "sku": p.get("sku", ""),
                "dimensions": p.get("dimensions", {}),
                "categories": p.get("categories", []),
                "permalink": p.get("permalink", ""),
            }
            sku = p.get("sku", "")
            if sku:
                slug_to_content_id[slug] = sku
            count += 1
        page += 1
    elapsed = time.time() - t0
    logger.info(f"Cached {count} products in {elapsed:.1f}s")

def lookup_product(slug):
    """Instant lookup from cache — no API call."""
    return product_cache.get(slug)

# ——— MWAI Auth ———
def _refresh():
    global _nonce
    body = json.dumps({"botId": BOT_ID}).encode()
    req = urllib.request.Request(f"{MWAI_URL}/start_session", data=body, method="POST")
    for k, v in AUTH.items():
        req.add_header(k, v)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36")
    with urllib.request.urlopen(req, timeout=15) as r:
        _nonce = json.loads(r.read()).get("restNonce", "")
    logger.info(f"Nonce refreshed: {_nonce[:12]}...")

def _fetch_instructions():
    global ZARA_INSTRUCTIONS
    req = urllib.request.Request(f"{MWAI_URL}/settings/chatbots", headers=AUTH)
    req.add_header("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            bots = json.loads(r.read()).get("chatbots", [])
        for bot in bots:
            if bot.get("botId") == BOT_ID:
                ZARA_INSTRUCTIONS = bot.get("instructions", "")
                logger.info(f"Loaded Zara instructions: {len(ZARA_INSTRUCTIONS)} chars")
                return
    except Exception as e:
        logger.error(f"Failed to fetch instructions: {e}")

# ——— Zara API (timed) ———
def call_zara(messages):
    t0 = time.time()
    if not _nonce:
        _refresh()
    body = json.dumps({"botId": BOT_ID, "messages": messages, "envId": ENV_ID, "stream": False}).encode()
    req = urllib.request.Request(f"{MWAI_URL}/ai/completions", data=body, method="POST")
    for k, v in AUTH.items():
        req.add_header(k, v)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-WP-Nonce", _nonce)
    req.add_header("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read().decode())
            elapsed = time.time() - t0
            logger.info(f"Zara API: {elapsed:.1f}s")
            return resp.get("reply") or resp.get("data", "")
    except urllib.error.HTTPError as e:
        err = e.read().decode()[:300]
        logger.warning(f"Zara HTTP {e.code}: {err}")
        if e.code == 401:
            _refresh()
            req2 = urllib.request.Request(f"{MWAI_URL}/ai/completions", data=body, method="POST")
            for k, v in AUTH.items():
                req2.add_header(k, v)
            req2.add_header("Content-Type", "application/json")
            req2.add_header("X-WP-Nonce", _nonce)
            req2.add_header("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36")
            with urllib.request.urlopen(req2, timeout=60) as r2:
                resp2 = json.loads(r2.read().decode())
                elapsed = time.time() - t0
                logger.info(f"Zara API (retry): {elapsed:.1f}s")
                return resp2.get("reply") or resp2.get("data", "")
        return None

# ——— Text Processing ———
def clean_reply(text):
    if not text:
        return ""
    text = re.sub(r"<mwai-product-carousel[^>]*>.*?</mwai-product-carousel>", "", text, flags=re.DOTALL)
    text = re.sub(r"<mwai-product-carousel[^>]*/>", "", text)
    text = re.sub(r"<mwai[^>]*>.*?</mwai[^>]*>", "", text, flags=re.DOTALL)
    text = re.sub(r"<a\s+href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", r"\2: \1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def parse_product_lines(text):
    """Extract product entries with URLs from Zara's reply.
    Handles both numbered (1. Product...) and bullet (• Product...) formats.
    Also handles URLs on the line AFTER the product name."""
    lines = text.strip().split("\n")
    products = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line:
            continue
        # Check if this line starts a product entry
        is_product_line = bool(re.match(r"^\d+[\.\)]\s", line)) or bool(re.match(r"^[\•\-\*]\s", line))
        if not is_product_line:
            continue
        # Look for URL on this line
        urls = re.findall(r"https://eventrentals\.lk/product/[^/\s]+/", line)
        # If no URL on this line, check the next line
        if not urls and i < len(lines):
            next_line = lines[i].strip()
            urls = re.findall(r"https://eventrentals\.lk/product/[^/\s]+/", next_line)
            if urls:
                i += 1  # Consume the URL line
        if urls:
            products.append((line, urls[0]))
    return products

def _to_feet(inches_str):
    """Convert inches string to feet display, e.g. '144' -> '12ft', '42' -> '3.5ft'"""
    try:
        val = float(inches_str)
        feet = val / 12
        if feet == int(feet):
            return f"{int(feet)}ft"
        return f"{feet:.1f}ft"
    except (ValueError, TypeError):
        return None

def build_card_text(name, price, sale_price, product_url, dimensions=None):
    """Build a WhatsApp-friendly product card as text."""
    lines = [f"📦 *{name}*"]
    if price:
        if sale_price and sale_price != price:
            lines.append(f"💰 ~~Rs.{price}~~ Rs.{sale_price}")
        else:
            lines.append(f"💰 Rs.{price}")
    if dimensions:
        parts_inches = []
        parts_feet = []
        if dimensions.get("length"):
            parts_inches.append(f'{dimensions["length"]}"')
            ft = _to_feet(dimensions["length"])
            if ft:
                parts_feet.append(ft)
        if dimensions.get("width"):
            parts_inches.append(f'{dimensions["width"]}"')
            ft = _to_feet(dimensions["width"])
            if ft:
                parts_feet.append(ft)
        if dimensions.get("height"):
            parts_inches.append(f'{dimensions["height"]}"')
            ft = _to_feet(dimensions["height"])
            if ft:
                parts_feet.append(ft)
        if parts_inches:
            line = f"📐 {' × '.join(parts_inches)}"
            if parts_feet and parts_feet != parts_inches:
                line += f" ({' × '.join(parts_feet)})"
            lines.append(line)
    lines.append(f"🔗 {product_url}")
    lines.append("")
    lines.append("Tap the link above to view details and book!")
    return "\n".join(lines)

# ——— WhatChimp API ———
def wc_request(endpoint, data):
    encoded = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(f"{WC_BASE}/{endpoint}", data=encoded, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        logger.error(f"WC API error ({endpoint}): {e}")
        return None

def get_subscribers():
    resp = wc_request("whatsapp/subscriber/list", {
        "apiToken": WC_API_KEY,
        "phone_number_id": WC_PHONE_NUMBER_ID,
        "limit": 100, "offset": 0, "orderBy": 1
    })
    if resp and resp.get("status") == "1":
        return resp.get("message", [])
    return []

def get_conversation(phone):
    resp = wc_request("whatsapp/get/conversation", {
        "apiToken": WC_API_KEY,
        "phone_number_id": WC_PHONE_NUMBER_ID,
        "phone_number": phone, "limit": 10, "offset": 1
    })
    if resp and resp.get("status") == "1":
        msg_data = resp.get("message", {})
        # WhatChimp sometimes returns a list instead of dict — handle gracefully
        if isinstance(msg_data, dict):
            return msg_data
        if isinstance(msg_data, str):
            try:
                parsed = json.loads(msg_data)
                if isinstance(parsed, dict):
                    return parsed
            except: pass
        # Also handle list: try to wrap it or skip
        if isinstance(msg_data, list):
            logger.warning(f"get_conversation returned list (length {len(msg_data)}), treating as empty")
            return {}
    return {}

def extract_text(msg):
    raw = msg.get("message_content", "")
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(data, dict):
        if "text" in data and isinstance(data["text"], dict):
            return data["text"].get("body", "")
        if "entry" in data and isinstance(data["entry"], list):
            for entry in data["entry"]:
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    for m in value.get("messages", []):
                        if "text" in m:
                            return m["text"].get("body", "")
                        if "body" in m:
                            return m.get("body", "")
    return ""

# "Thinking" messages sent before Zara responds
THINKING_RESPONSES = [
    "⏳ Let me check on that for you...",
    "⏳ One moment, let me look that up...",
    "⏳ Give me a second to check...",
    "⏳ Just a moment, fetching details...",
    "⏳ Give me a moment to look into that...",
]

GREETINGS = re.compile(
    r"^(hi|hello|hey|howdy|what'?s up|sup|yo)"
    r"[\s,!.]*(there|zara|everyone)?[\s!?.]*$"
    r"|^(good\s*)?(morning|afternoon|evening|day)"
    r"[\s,!.]*(zara)?[\s!?.]*$"
    r"|^(morning|afternoon|evening)"
    r"[\s,!.]*(zara)?[\s!?.]*$",
    re.IGNORECASE
)

GREETING_RESPONSES = [
    "Hey, Zara here! 👋 Welcome to EventRentals.lk — I'm the AI assistant here to help you find the perfect rentals for your event! Whether it's tables, chairs, marquees, or decor, just ask. If you'd like to speak to someone on our team, call us on 94 724 999 555 📞",
    "Hey there! 😊 Zara here — your AI event planner! Ready to help you browse our catalog and find what you need. Want to speak to a team member instead? Call 94 724 999 555 📞",
    "Hey! 👋 Zara from EventRentals.lk — I'm an AI assistant, so feel free to ask me about our furniture, decor, tents, or anything event-related! Need to speak to a real person? Our team is at 94 724 999 555 📞",
]

# Casual acknowledgments that should NOT trigger a Zara query
# After receiving product info, users often reply with short affirmations
ACKNOWLEDGMENTS = re.compile(
    r"^(nice|great|awesome|amazing|perfect|good|okay?|ok|k|thanks|thank you|ty|"
    r"cool|sounds good|love it|like it|got it|noted|alright|sure|"
    r"yes|yeah|yep|yup|fine|deal|beautiful|interesting|wow|omg)"
    r"[\s!?.,;:)*\U0001F300-\U0001F9FF]*$",
    re.IGNORECASE | re.UNICODE
)

ACKNOWLEDGMENT_RESPONSES = [
    "Glad you like it! 😊 Feel free to browse more at eventrentals.lk or let me know if you need anything else!",
    "Happy to help! 🎉 You can book directly through the link or ask me about other items too!",
    "My pleasure! 😊 If you'd like to go ahead, just click the link to book online. Let me know if you need more info!",
]

def is_greeting(text):
    """Detect if a message is just a greeting (not a product query)."""
    return bool(GREETINGS.match(text.strip()))

def pick_greeting():
    """Pick a random greeting response."""
    return GREETING_RESPONSES[int(time.time()) % len(GREETING_RESPONSES)]

def is_acknowledgment(text):
    """Detect if a message is just a casual acknowledgment (not a new query)."""
    return bool(ACKNOWLEDGMENTS.match(text.strip()))

def pick_acknowledgment():
    """Pick a random acknowledgment response."""
    return ACKNOWLEDGMENT_RESPONSES[int(time.time()) % len(ACKNOWLEDGMENT_RESPONSES)]

def send_text(phone, message):
    return wc_request("whatsapp/send", {
        "apiToken": WC_API_KEY,
        "phone_number_id": WC_PHONE_NUMBER_ID,
        "message": message,
        "phone_number": phone
    })

def send_image(phone, image_url, caption):
    """Send an image with caption via WhatsApp. Tries Meta Cloud API first, falls back to text."""
    # Try Meta's WhatsApp Cloud API directly
    token = META_ACCESS_TOKEN
    if token:
        try:
            body = json.dumps({
                "messaging_product": "whatsapp",
                "to": phone,
                "type": "image",
                "image": {"link": image_url, "caption": caption}
            }).encode()
            req = urllib.request.Request(
                f"https://graph.facebook.com/v22.0/{WC_PHONE_NUMBER_ID}/messages",
                data=body, method="POST"
            )
            req.add_header("Authorization", f"Bearer {token}")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=15) as r:
                return True
        except Exception as e:
            logger.warning(f"Meta image send failed: {e}")
    # Fall back to text-only card
    send_text(phone, caption)
    return False

def send_catalog_product(phone, content_id, body_text=None):
    """Send a native WhatsApp catalog product card via Meta Cloud API.
    Shows product with image, price, name, and 'View Product' button.
    Falls back silently if catalog isn't set up or API fails."""
    if not META_ACCESS_TOKEN:
        return False
    try:
        msg = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "product",
            "product": {
                "product_retailer_id": content_id
            }
        }
        if body_text:
            msg["body"] = {"text": body_text[:1024]}
        body = json.dumps(msg).encode()
        req = urllib.request.Request(
            f"https://graph.facebook.com/v22.0/{WC_PHONE_NUMBER_ID}/messages",
            data=body, method="POST"
        )
        req.add_header("Authorization", f"Bearer {META_ACCESS_TOKEN}")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=15):
            return True
    except Exception as e:
        logger.warning(f"Catalog product send failed (Content ID: {content_id}): {e}")
        return False

# ——— Product Cards Sender ———
def send_product_cards(phone, clean_text, raw_reply):
    """Parse Zara's reply and send only product cards (no duplicate text)."""
    t0 = time.time()
    product_lines = parse_product_lines(raw_reply)

    if not product_lines:
        # No products — send Zara's text response directly
        send_text(phone, clean_text)
        elapsed = time.time() - t0
        logger.info(f"Send text: {elapsed:.1f}s")
        return

    # Look up each product from cache, fall back to live WooCommerce API
    results = {}
    for line_text, url in product_lines:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        data = lookup_product(slug)
        if data:
            results[url] = (data["name"], data["price"], data["sale_price"], data["img_url"], url, data.get("dimensions", {}))
        else:
            # Live fallback: try WooCommerce API for cache misses
            try:
                api_url = f"{WC_URL}/products?slug={slug}&_fields=slug,name,price,sale_price,images,sku,dimensions&per_page=1"
                req = urllib.request.Request(api_url, headers=AUTH)
                req.add_header("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36")
                with urllib.request.urlopen(req, timeout=8) as r:
                    live = json.loads(r.read().decode())
                if live:
                    p = live[0]
                    imgs = p.get("images", [])
                    img_url = imgs[0].get("src", "") if imgs else ""
                    results[url] = (p["name"], p.get("price", ""), p.get("sale_price", ""), img_url, url, p.get("dimensions", {}))
                    product_cache[slug] = {"name": p["name"], "price": p.get("price", ""),
                                           "sale_price": p.get("sale_price", ""), "img_url": img_url,
                                           "sku": p.get("sku", ""), "dimensions": p.get("dimensions", {})}
            except Exception:
                pass  # Product doesn't exist — fall back to raw text

    # Build and send cards — deduplicated by URL and by conversation
    phone_sent = products_sent.get(phone, set())
    cards = []
    seen_urls = set()
    for line_text, url in product_lines:
        if url in seen_urls or url in phone_sent:
            continue
        seen_urls.add(url)
        if url in results:
            name, price, sale_price, img_url, prod_url, dimensions = results[url]
            slug = url.rstrip("/").rsplit("/", 1)[-1]
            content_id = slug_to_content_id.get(slug)
            # Skip catalog cards (catalog not connected) — always use text/image
            card_text = build_card_text(name, price, sale_price, prod_url, dimensions)
            if img_url and META_ACCESS_TOKEN:
                cards.append(("image", img_url, card_text))
            else:
                cards.append(("text", card_text, None))
        else:
            cards.append(("text", line_text, None))

    # Send cards in Zara's order — parallel API calls but sequential delivery
    with ThreadPoolExecutor(max_workers=5) as pool:
        def send_item(item):
            kind = item[0]
            if kind == "catalog":
                send_catalog_product(phone, item[1], item[2])
            elif kind == "image":
                send_image(phone, item[1], item[2])
            else:
                send_text(phone, item[1])
        # Submit all tasks (parallel API calls)
        futures = [pool.submit(send_item, c) for c in cards]
        # Wait in order so promoted items arrive first
        for future in futures:
            future.result()

    elapsed = time.time() - t0
    logger.info(f"Sent {len(cards)} product cards in {elapsed:.1f}s")

    # Track sent products so they aren't re-sent later in this conversation
    if cards:
        if phone not in products_sent:
            products_sent[phone] = set()
        products_sent[phone].update(seen_urls)

# ——— Lead Detection & Forwarding ———
# Zara's instructions tell her to "Summarize for the team. Stop after handoff."
# These patterns detect when she's done that.
HANDOFF_PATTERNS = re.compile(
    r"(team (will|shall) (reach|contact|follow|get back)"
    r"|hand(?:ed?\s)?off|passed (along|to|over)"
    r"|connect you with|reach out to you"
    r"|i'?ve (forwarded|sent|passed|shared|noted)"
    r"|summary for (the|our|my) team"
    r"|lead (captured|registered|collected)"
    r"|noted your (details|info|request|requirements)"
    r"|let (the|our) team (know|handle|take it from here)"
    r"|forwarded this to|sent this to)",
    re.IGNORECASE
)

def is_handoff(reply_text, phone):
    """Detect if Zara has completed a lead capture / handoff."""
    if not reply_text:
        return False
    if phone in forwarded_leads:
        return False
    if phone == TEST_NUMBER:
        return False
    conv = conversations.get(phone, [])
    if len(conv) < 4:  # Need at least user→Zara→user→Zara exchanges
        return False
    return bool(HANDOFF_PATTERNS.search(reply_text))

def build_and_forward_lead(phone, zara_reply):
    """Send lead summary + contact info to business hotline."""
    logger.info(f"📞 Lead captured from {phone}, forwarding to business line")

    # Extract name and last few messages from conversation history
    conv = conversations.get(phone, [])
    user_messages = [m["content"] for m in conv if m["role"] == "user"]

    # Try to extract customer name from user messages
    customer_name = ""
    for msg in user_messages[-5:]:  # Only check last 5 messages
        # Common patterns: "my name is X", "I'm X", name at start
        m = re.search(r"(?:my name(?: is)?|i['’]?m|this is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", msg, re.IGNORECASE | re.MULTILINE)
        if m:
            customer_name = m.group(1)
            break
        # Also: [name] here, [name] reaching out
        m2 = re.match(r"^([A-Z][a-z]+)[,!\s]", msg)
        if m2 and len(m2.group(1)) > 2:
            customer_name = m2.group(1)
            break

    # Build a clean readable summary from Zara's reply
    clean_summary = clean_reply(zara_reply)[:400]

    summary = (
        f"📋 *New Lead from Zara*\n"
        f"📱 *Client:* +{phone}\n"
        f"👤 *Name:* {customer_name or '(not given)'}\n"
        f"━━━━━━━━━━━━━\n"
        f"{clean_summary}\n"
        f"━━━━━━━━━━━━━\n"
        f"🔗 *Quick reply:* wa.me/{phone}"
    )

    send_text(BUSINESS_HOTLINE, summary)
    forwarded_leads.add(phone)
    logger.info(f"✅ Lead forwarded for {phone}")

# ——— Poll Loop ———
def poll():
    global ZARA_INSTRUCTIONS

    logger.info("Building product cache...")
    _build_product_cache()

    _fetch_instructions()
    _load_last_seen()
    _refresh()

    # ——— SILENT CATCH-UP: runs on every restart ———
    # Mark ALL existing subscriber messages as seen so no one gets an unwanted reply.
    # Only messages arriving AFTER this point will be processed.
    logger.info("🔄 Catching up silently — marking all existing messages as seen")
    subscribers = get_subscribers()
    caught_up_count = 0
    for sub in subscribers:
        phone = sub.get("chat_id", "")
        if not phone:
            continue
        sub_id = sub.get("subscriber_id", phone)
        conv = get_conversation(phone)
        if not isinstance(conv, dict):
            continue
        marked = 0
        for msg_id_str in sorted(conv.keys(), reverse=True):
            msg = conv[msg_id_str]
            sender = msg.get("sender", "")
            if sender in ("user", "subscriber"):
                mid = int(msg.get("id", 0))
                seen_key = f"{sub_id}:{mid}"
                if not last_seen.get(seen_key):
                    last_seen[seen_key] = True
                    marked += 1
        if marked:
            logger.info(f"  ✓ {phone}: {marked} messages marked as seen")
            caught_up_count += 1
    _save_last_seen()
    logger.info(f"✅ Catch-up done: {caught_up_count} subscribers caught up, {len(last_seen)} total entries. Now handling only NEW messages.")

    logger.info(f"🚀 Zara WhatsApp Bot (optimized) polling started (interval: {POLL_INTERVAL}s)")

    while True:
        loop_t0 = time.time()
        try:
            subscribers = get_subscribers()
            for sub in subscribers[:5]:
                phone = sub.get("chat_id", "")
                if not phone:
                    continue
                sub_id = sub.get("subscriber_id", phone)

                conv = get_conversation(phone)
                if not conv:
                    continue

                # Find latest subscriber message
                latest_sub_msg = None
                latest_msg_id = 0
                # Handle dict vs other types gracefully
                if not isinstance(conv, dict):
                    continue
                for msg_id_str in sorted(conv.keys(), reverse=True):
                    msg = conv[msg_id_str]
                    sender = msg.get("sender", "")
                    if sender in ("user", "subscriber"):
                        mid = int(msg.get("id", 0))
                        if mid > latest_msg_id:
                            latest_sub_msg = msg
                            latest_msg_id = mid

                if not latest_sub_msg:
                    continue

                seen_key = f"{sub_id}:{latest_msg_id}"
                if last_seen.get(seen_key):
                    continue

                msg_text = extract_text(latest_sub_msg)

                # Text messages only from here on
                if not msg_text:
                    continue

                logger.info(f"❓ {phone}: \"{msg_text[:60]}\"")

                # ——— Normal Message Handling ———
                # Greeting detection — warm natural welcome
                if is_greeting(msg_text):
                    conversations[phone] = []  # Reset history — new conversation
                    products_sent[phone] = set()  # Reset product card tracking
                    send_text(phone, pick_greeting())
                    last_seen[seen_key] = True
                    _save_last_seen()
                    logger.info(f"💬 Greeting sent to {phone}")
                    continue

                # Acknowledgment detection — "Nice", "Thanks", etc.
                # After receiving product info, customers often reply with short affirmations.
                # No need to call Zara — just a warm reply.
                if is_acknowledgment(msg_text):
                    ack = pick_acknowledgment()
                    send_text(phone, ack)
                    last_seen[seen_key] = True
                    _save_last_seen()
                    logger.info(f"💬 Acknowledgment sent to {phone}: \"{msg_text[:40]}\"")
                    continue

                # Send acknowledgment for product queries
                send_text(phone, random.choice(THINKING_RESPONSES))

                # Build conversation with system instructions
                if phone not in conversations or not conversations.get(phone):
                    whatsapp_rules = (
                        "\n\n**WHATSAPP CHANNEL RULES (OVERRIDE ALL CONTRADICTIONS):**\n"
                        "- You are Zara, a **top-tier event rental AI assistant** for EventRentals.lk\n"
                        "- Be **warm, professional, and proactive** — recommend relevant products even if not directly asked\n"
                        "- Know your catalog: tables, chairs, marquees, tents, decor, glassware, cutlery, linens, bar equipment, staging\n"
                        "- FORMAT PRODUCT LISTINGS as a bullet list with prices and full URLs\n"
                        "  Example: • Barn Table — Rs.4000 (On Offer: Rs.3000) — https://eventrentals.lk/product/barn-table/\n"
                        "- **CRITICAL: Put the product URL on the SAME line as the product name, not on a separate line below it.**\n"
                        "- **CRITICAL: Only recommend products with a working eventrentals.lk URL**\n"
                        "- **PROMOTED PRODUCT (IMPORTANT):** When a customer asks about **chairs** or **seating**, ALWAYS list **Cross Back Chairs Dark Tan** FIRST as the featured option (Rs.350 on offer). Then list the other seating products.\n"
                        "- **CATEGORY MAPPINGS:** chairs/seating/seats/sitting → ALL products from the **Seating** section (chairs, bean bags, cushions, low tables, divans, bride and groom chairs).\n"
                        "- Ask about event type, date, and guest count to tailor recommendations\n"
                        "- Keep responses concise but helpful — suggest alternatives and upgrades\n"
                        '- **PRODUCT ENQUIRY FLOW:** When a customer sends a product link/name, do NOT ask for their name, phone number, or event date in your FIRST response. First acknowledge the product with price + one useful detail. If the product shows "(1 available)" in the listing, do NOT ask "how many" — just ask for their event date. If no "(1 available)" note, ask how many they need and their event date.\n'
                        "- **NO PHONE ASKING:** You already have their WhatsApp number. Do NOT ask for their phone number. Ask for name + event date instead. The team will confirm availability - you do not check availability yourself.\n"
                        "- **NO CIRCULAR LINKS:** Do NOT output wa.me links — the customer is already on WhatsApp.\\n"
                        "- **BUSINESS CONTACT:** If a customer asks for a phone number to call or to speak to someone, give them: **94 724 999 555** (business hotline). Clarify that you are an AI assistant and they can call that number to speak to the team.\\n"
                        "- **LEAD CAPTURE:** Collect name + event date naturally. Summarize for the team. Stop after handoff — no follow-up questions.\\n"
                        "- **NO REPEATING PRODUCTS:** If you already showed a product's URL to this customer earlier in the same conversation, do NOT include the URL again. Just reference it by name (e.g. \"the Barn Table we discussed\"). Only include the full product URL the first time you recommend it.\\n"\

                        "- **WHEN YOU DON'T KNOW:** If you don't have the exact information a customer is asking for (dimensions, specs, custom pricing, availability), do NOT guess or make things up. Say: \"I don't have that information on hand, but I can pass it to the team and they'll help you with that. Would you like me to do that?\" If they say yes, collect their name + event date and create a handoff summary.\\n"\

                    )
                    conversations[phone] = [
                        {"role": "system", "content": ZARA_INSTRUCTIONS + whatsapp_rules}
                    ]

                conversations[phone].append({"role": "user", "content": msg_text})
                conversations[phone] = conversations[phone][-21:]

                reply = call_zara(conversations[phone])
                if not reply:
                    continue

                clean = clean_reply(reply)
                if not clean:
                    clean = "I found some products for you! Browse them at eventrentals.lk/shop"

                conversations[phone].append({"role": "assistant", "content": reply})

                # Send product cards or plain text
                send_product_cards(phone, clean, reply)

                # Check if Zara has completed a lead capture / handoff
                if is_handoff(reply, phone):
                    build_and_forward_lead(phone, reply)

                last_seen[seen_key] = True
                _save_last_seen()

                # Prune old state
                if len(last_seen) > 1000:
                    keys = list(last_seen.keys())
                    for k in keys[:500]:
                        del last_seen[k]
                    _save_last_seen()
                if len(conversations) > 100:
                    old_keys = list(conversations.keys())[:50]
                    for k in old_keys:
                        del conversations[k]
                        products_sent.pop(k, None)

        except Exception as e:
            logger.error(f"⚠️ Poll error: {type(e).__name__}: {e}")

        elapsed = time.time() - loop_t0
        sleep_time = max(0, POLL_INTERVAL - elapsed)
        time.sleep(sleep_time)

if __name__ == "__main__":
    poll()
