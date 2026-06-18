# WhatsApp Catalog Integration — Setup Reference

> **Business:** EventRentals.lk
> **Date:** June 2026
> **Meta Catalog ID:** `1808153763480253`
> **WABA ID:** `1470790067895018`
> **WhatsApp Number:** `+94 72 479 9555` (Phone Number ID: `1050615101468013`)
> **Test Number:** `94727474743`
> **Feed URL:** `https://raw.githubusercontent.com/sajjadlk/eventrentals-lk/main/facebook_feed.csv`

---

## 1. Overview

The goal is to send **native WhatsApp catalog product cards** (image + price + "View Product" button) instead of plain text + links. The stack:

```
WooCommerce ──cron──> CSV Feed ──> Meta Commerce Catalog ──> WABA ──> WhatsApp
                                     │
                                     └──> WhatChimp (optional monitoring)
```

The WhatsApp bot talks directly to Meta's Cloud API to send product cards using the catalog.

---

## 2. Product Feed (CSV)

### 2.1 Where it lives

- **Script:** `/opt/data/er-telegram-bot/generate_feed.py`
- **Output:** `/opt/data/er-telegram-bot/facebook_feed.csv`
- **Public URL:** `https://raw.githubusercontent.com/sajjadlk/eventrentals-lk/main/facebook_feed.csv`

### 2.2 Feed schema (required by Meta)

```
id,title,description,availability,condition,price,link,image_link,brand,product_type
```

| Field | Source | Example |
|-------|--------|---------|
| `id` | WooCommerce SKU (Content ID) | `TKSCHMDP0005` |
| `title` | Product name | `Traditional Bride and Groom Chairs` |
| `description` | Product short description | `Rent Traditional Bride...` |
| `availability` | Always `in stock` | `in stock` |
| `condition` | Always `new` | `new` |
| `price` | `LKR <amount>` with no decimals | `LKR 15000` |
| `link` | Product page URL | `https://eventrentals.lk/product/...` |
| `image_link` | Full-size image URL | `https://eventrentals.lk/wp-content/...` |
| `brand` | Store name | `The Kairos Store` |
| `product_type` | Category path | `Furniture` |

**Critical rules:**
- Price format: `LKR <number>` (no commas, no decimal points)
- ID must match `sku` in WooCommerce and must be unique
- Images must be publicly accessible (no hotlink protection)
- Only `published` products should be included

### 2.3 Generate feed script

```python
#!/usr/bin/env python3
"""Fetch published WooCommerce products and generate Meta catalog feed CSV."""
import csv, os, json, urllib.request, base64

BASE = "https://eventrentals.lk"
AUTH = base64.b64encode(b"zara@eventrentals.lk:JU7x taUx 3vvG 1nXk mpDw b9i5").decode()

def fetch_products():
    """Fetch all published products via WooCommerce REST API."""
    products = []
    page = 1
    while True:
        url = f"{BASE}/wp-json/wc/v3/products?per_page=100&page={page}&status=publish&_fields=id,name,slug,sku,price,sale_price,description,short_description,images,categories,dimensions"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Basic {AUTH}")
        with urllib.request.urlopen(req, timeout=30) as r:
            batch = json.loads(r.read())
        if not batch:
            break
        products.extend(batch)
        page += 1
    return products

def generate_feed(products, output_path="facebook_feed.csv"):
    fieldnames = ["id","title","description","availability","condition","price","link","image_link","brand","product_type"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in products:
            desc = (p.get("short_description") or p.get("description") or "").strip()
            desc = desc.replace("&#8211;", "—").replace("&amp;", "&").replace("&#215;", "×")
            img = p.get("images", [])
            img_url = img[0].get("src", "") if img else ""
            cat = p.get("categories", [])
            cat_name = cat[0].get("name", "All Products") if cat else "All Products"
            writer.writerow({
                "id": p.get("sku", "") or str(p["id"]),
                "title": p["name"],
                "description": desc[:9999],
                "availability": "in stock",
                "condition": "new",
                "price": f"LKR {p.get('price', '0').split('.')[0].replace(',', '')}",
                "link": f"{BASE}/product/{p['slug']}/",
                "image_link": img_url,
                "brand": "The Kairos Store",
                "product_type": cat_name,
            })
    print(f"✅ Wrote {len(products)} products to {output_path}")

if __name__ == "__main__":
    prods = fetch_products()
    generate_feed(prod s)
```

### 2.4 Daily cron (4am UTC)

```bash
# In crontab or Hermes cronjob:
0 4 * * * cd /opt/data/er-telegram-bot && python3 generate_feed.py && cd /opt/data/er-telegram-bot && git add facebook_feed.csv && git commit -m "Daily feed update $(date +%Y-%m-%d)" && git push
```

Or via Hermes cronjob tool:
- Schedule: `0 4 * * *`
- Script: `/opt/data/er-telegram-bot/generate_feed.py`
- Then push to GitHub

---

## 3. Meta Commerce Manager Setup

### 3.1 Create Catalog

1. Go to **Meta Business Suite → Commerce Manager**
2. Click **Create a catalog**
3. Choose **E-commerce** → **Upload product info**
4. Name it (e.g., "EventRentals.lk Catalog")
5. Note the **Catalog ID** from the URL or settings

### 3.2 Connect Feed to Catalog

1. In Commerce Manager → **Catalog → Data Sources**
2. **Add Items → Add via Data Feed**
3. Set **File URL** to your feed URL (e.g., GitHub raw URL)
4. Schedule: **Daily** (match your cron)
5. Map feed columns to Meta fields (auto-detected for CSV)

### 3.3 Link Catalog to WABA

**Critical step** — without this, WhatsApp can't use the catalog:

1. In Commerce Manager → **Settings → Business Assets**
2. Click **Add Assets** → Search for your **WhatsApp Business Account**
3. Assign **Manage** permission

Alternatively via WhatsApp Manager:
1. Go to **WhatsApp Manager** → your WABA
2. **Account Tools → Catalog**
3. **Connect Catalog** → enter Catalog ID

---

## 4. Meta System User & Token Setup

### 4.1 Create System User

1. **Meta Business Suite → Business Settings → Users → System Users**
2. **Add** → name it (e.g., "Zara API")
3. Set role to **Admin** (or custom with needed permissions)

### 4.2 Generate Token

1. Click on the system user → **Generate New Token**
2. Select the app (create one if needed: `developers.facebook.com` → **My Apps → Create App** → **Business**)
3. Scopes needed:
   - `whatsapp_business_management`
   - `whatsapp_business_messaging`
   - `catalog_management` (requires app approval — see §4.4)
   - `public_profile`
4. Save the token securely in `.env`

### 4.3 Assign Assets to System User

The system user needs access to **both** the WABA and the Catalog:

1. In **Business Settings → Users → System Users**
2. Click on your system user (e.g., "Zara API")
3. **Add Assets**
4. Add **WhatsApp Business Account** → Manage, Send Messages
5. **Add Assets** again
6. Add **Catalog** → Manage

**Without both, catalog product cards will fail.**

### 4.4 App Approval for Catalog API

If the token returns `"This application has not been approved to use this api"` for catalog endpoints:

1. Go to **developers.facebook.com**
2. Select your app → **App Review → Permissions and Features**
3. Search for `catalog_management`
4. Click **Request** or **Add**
5. Since it's in the same Business Manager, it may auto-approve
6. If not, submit for review with screenshots of your Commerce Manager setup

---

## 5. WhatChimp Integration

### 5.1 Connect Meta

1. In WhatChimp → **Settings → Integrations → Meta**
2. Authorize with your Facebook Business Manager account
3. Permissions needed: `catalog_management`, `whatsapp_business_management`

### 5.2 Verify Catalog

1. In WhatChimp → **e-Commerce → Catalog**
2. The connected Meta catalog should appear automatically
3. Products sync status visible here

**If catalog doesn't appear:** The catalog isn't connected to the WABA yet (see §3.3).

---

## 6. WhatsApp Bot — Catalog Product Cards

### 6.1 Required Config (in `zara_whatsapp_bot.py`)

```python
CATALOG_ID = "1808153763480253"         # From Commerce Manager
META_ACCESS_TOKEN = "..."               # System user token (from .env)
WC_PHONE_NUMBER_ID = "1050615101468013" # From WABA phone numbers
slug_to_content_id = {}                 # Built from WooCommerce SKUs at startup
```

### 6.2 Send Catalog Product Card

```python
def send_catalog_product(phone, content_id, body_text=None):
    """Send native WhatsApp catalog product card."""
    msg = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "product",
            "body": {"text": body_text[:1024]} if body_text else {},
            "action": {
                "catalog_id": CATALOG_ID,
                "product_retailer_id": content_id
            }
        }
    }
    # POST to https://graph.facebook.com/v22.0/{PNID}/messages
    # Authorization: Bearer {META_ACCESS_TOKEN}
```

**Important:** If the product hasn't passed Meta's review, this returns error 131009 — "product not found for product_retailer_id". Handle this by falling back to text+image cards.

### 6.3 Slug → Content ID Mapping

Built automatically during product cache initialization:

```python
# In _build_product_cache():
for p in products:
    slug = p.get("slug", "")
    sku = p.get("sku", "")
    if slug and sku:
        slug_to_content_id[slug] = sku
```

The Content ID must match the `id` field in the CSV feed, which is the WooCommerce SKU.

---

## 7. Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `"Unsupported get request"` on catalog | Token/app lacks catalog API permission | Enable `catalog_management` in app settings (§4.4) |
| `"product not found for product_retailer_id"` | Product still under Meta review | Wait 24-48h for review to complete |
| `"Invalid catalog_id"` | Catalog not linked to WABA | Connect in Commerce Manager settings (§3.3) |
| `"Object does not exist"` on WABA | System user not assigned to WABA | Add WABA to system user assets (§4.3) |
| WhatChimp can't see catalog | Catalog under different Business Manager | Share catalog to correct BM, or reconnect WhatChimp |
| Cloudflare 1010 on VPS | VPS IP blocked by WhatChimp's Cloudflare | Use different endpoint or route through Meta API directly |
| Products not showing in Commerce Manager | Feed format error | Check CSV for missing fields, invalid price format |
| Price shows as integer only | Feed has `LKR 15000` without decimals | This is correct for LKR — no decimal needed |
| Only 70/170 products synced | Meta processing in batches | Wait for next feed sync cycle |

### 7.1 Key IDs Reference

| Resource | ID |
|----------|----|
| Business Manager | — (The Kairos Store) |
| WABA | `1470790067895018` |
| Phone Number ID | `1050615101468013` |
| WhatsApp Number | `+94 72 479 9555` |
| Catalog ID | `1808153763480253` |
| ZaraWA App ID | `2201456480689062` |
| System User ID | `122103748911359787` |
| WhatChimp App ID | `1412251652772514` |

---

## 8. Reuse for a New Business

To replicate this for a different business:

### 8.1 New Setup Checklist

- [ ] WooCommerce site with published products
- [ ] WooCommerce REST API credentials (Consumer Key + Secret)
- [ ] Meta Business Manager account
- [ ] WhatsApp Business Account (WABA) — approved
- [ ] WhatsApp Business phone number — approved, "High quality"
- [ ] System user created with WABA + catalog permissions
- [ ] System user token generated (with `catalog_management` if needed)
- [ ] Catalog created in Commerce Manager
- [ ] Feed CSV generated and hosted publicly (GitHub raw URL works)
- [ ] Feed connected to catalog in Commerce Manager
- [ ] Catalog linked to WABA (in Commerce Manager settings)
- [ ] Products pass Meta review (24-48h)

### 8.2 What to Change in the Bot

```python
# In config section:
BASE_URL = "https://newbusiness.com"
APP_USER = "api@newbusiness.com"
APP_PASS = "consumer_secret_here"
CATALOG_ID = "new_catalog_id"
WC_PHONE_NUMBER_ID = "new_phone_number_id"
META_ACCESS_TOKEN = "new_token"
BUSINESS_HOTLINE = "94711111111"  # Team lead forward number

# Feed script:
BRAND = "New Business Name"
AUTH_CREDS = "email:app_password"  # base64 encoded
```

### 8.3 Critical Path

```
1. WooCommerce products published ✓
2. Feed CSV generated ✓
3. Feed hosted (GitHub) ✓
4. Catalog created in Commerce Manager ✓
5. Feed connected to catalog ✓
6. Catalog linked to WABA ← Most common failure point
7. Products pass review (24h)
8. Bot configured with new IDs
9. → Catalog cards work
```

---

## 9. Files & Locations

| File | Purpose |
|------|---------|
| `/opt/data/er-telegram-bot/generate_feed.py` | Generate product feed CSV from WooCommerce |
| `/opt/data/er-telegram-bot/facebook_feed.csv` | Current feed (regenerated daily) |
| `/opt/data/er-telegram-bot/zara_whatsapp_bot.py` | WhatsApp bot with catalog card support |
| `/opt/data/er-telegram-bot/.env` | Secrets: `META_ACCESS_TOKEN`, `ER_APP_PASS` |
| `/opt/data/er-telegram-bot/config.py` | Bot configuration (Telegram token, etc.) |
| `/opt/data/er-telegram-bot/setup_meta_feed.py` | One-time Meta API setup script |
| `/opt/data/er-telegram-bot/whatsapp_webhook.py` | Alternative WhatChimp webhook server |

---

## 10. Key Lessons Learned

1. **WABA and catalog are separate assets** — a system user needs access to BOTH, and the catalog must be linked to the WABA in Commerce Manager settings, not just shared to the same Business Manager.

2. **App-level permissions matter** — even with the right system user permissions, the Meta app itself needs `catalog_management` added under App Review → Permissions and Features.

3. **Product review delay** — after connecting a feed, Meta reviews each product before it becomes available for WhatsApp messaging. This takes 24-48 hours. Products show in Commerce Manager but return "product not found" if you try to send them as catalog cards.

4. **Price format** — Meta expects `LKR 15000` (no commas, no decimals). Different currencies use different formats.

5. **Content ID = SKU** — the `id` field in the feed must match the WooCommerce SKU. This is how the bot looks up products when sending catalog cards.

6. **WhatChimp is optional** — the bot sends catalog cards directly via Meta's Cloud API. WhatChimp is only needed if you want their dashboard/analytics or if you can't get the direct Meta API working.

7. **Text messages work fine via direct Meta API** — even when the app lacks catalog permissions, regular text messages can be sent. The catalog issue is additive.
