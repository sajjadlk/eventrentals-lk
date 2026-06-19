# WhatsApp Order Flow Solutions — EventRentals.lk

> **Status:** Draft — for review and future implementation
> **Date:** 19 June 2026
> **Context:** Customer taps "Send Inquiry" on WhatsApp product card → Zara handles the rest

---

## Solution WA-OF-01: Zara-Guided Conversational Order Flow

### Phase 1: Customer Initiation

**Step 1** — Customer taps **"Send Inquiry"** on a WhatsApp product card
- Meta sends the system "welcome" message
- Zara picks up the conversation

**Step 2** — Zara greets the customer and begins collecting requirements

```
Decision 2A: Does customer say "I want to book/order [product]"?
├── YES → Proceed to Step 3
└── NO / BROWSING → Zara answers questions, recommends products
    └── Loop until customer signals intent to order → Step 3
```

### Phase 2: Detail Collection

**Step 3** — Zara asks for **Event Date**

```
Decision 3A: Date provided?
├── YES → Validate (not past date, within booking window)
│   ├── Valid → Step 4
│   └── Invalid → Zara says "Sorry, that date has passed / is unavailable. Please choose another"
│       └── Retry up to 3 times → If still invalid, offer to transfer to human
└── NO / "Not sure yet" → Zara asks for tentative date range
    └── Proceed with tentative → Customer can finalize later
```

**Step 4** — Zara asks **Delivery or Pickup?**

```
Decision 4A: Response?
├── DELIVERY → Step 4B
└── PICKUP → Skip delivery address → Step 5
```

**Step 4B** — If Delivery, Zara asks for **Delivery Address**

```
Decision 4C: Address provided?
├── YES → Step 5
└── NO → "Please share your delivery address so we can arrange delivery"
    └── If still refused → Note "TBC" and proceed
```

**Step 5** — Zara asks for **Items & Quantities**

```
Decision 5A: Multiple items or single?
├── SINGLE ITEM → "How many of [product] do you need?"
│   └── Quantity confirmed → Step 6
└── MULTIPLE ITEMS → "Here's what you've mentioned so far: [list]. Anything else to add?"
    └── Customer adds/removes → Zara maintains a running list
    └── When customer says "that's all" → Step 6
```

**Step 6** — Zara asks for **Billing Name & Contact**

```
Decision 6A: Is caller the same person as the WhatsApp number?
├── YES → "Great, I'll use the name from your WhatsApp profile. Can you confirm [name]?"
│   ├── Confirm → Step 7
│   └── Different → "What name should I put on the booking?"
└── NO / Different person → "Please share the billing name and contact number"
    └── Step 7
```

### Phase 3: Order Summary & Confirmation

**Step 7** — Zara presents full order summary:

```
📋 Order Summary
━━━━━━━━━━━━━━━━━━
Items: Product A (x2)
       Product B (x1)
Event Date: 25 July 2026
Delivery: [Address / Pickup]
Total: Rs. X,XXX
Security Deposit (30%): Rs. XXX
━━━━━━━━━━━━━━━━━━
Please confirm this is correct ✅
```

```
Decision 7A: Customer response?
├── "✅ Confirm" / "Yes correct" → Step 8
├── "❌ Change [something]" → Zara updates that field → Loop back to Step 7
└── Customer goes silent → Zara sends one follow-up after 15 mins
    └── Still no response → Order drafted as pending with note "Awaiting customer confirmation"
```

### Phase 4: Order Creation in WooCommerce

**Step 8** — Bot creates order in WooCommerce via REST API:
- **Status:** `on-hold`
- **Items:** Products & quantities from conversation
- **Billing:** Customer name + phone number
- **Shipping:** Delivery address (or "Pickup" if applicable)
- **Custom Meta Fields:**
  - `event_date`: date from conversation
  - `delivery_type`: "delivery" or "pickup"
  - `deposit_status`: "pending"
  - `wa_conversation_id`: for audit trail

```
Decision 8A: Order created successfully?
├── YES → Bot stores order ID, sends confirmation → Step 9
└── NO (API error) → Zara says "Sorry, I'm having trouble processing your order. Let me transfer you to our team."
    └── Forward to business number (handoff)
```

### Phase 5: Payment Instructions

**Step 9** — Zara sends payment instructions:

```
✅ Order #ER-XXXX is confirmed!

🔐 Security deposit of Rs. X,XXX (30%) required to lock your booking.

Bank: [Bank Name]
Account: [Account Number]
Name: EventRentals.lk

Please send payment confirmation screenshot when done.

Your order will be confirmed once deposit is received.
```

```
Decision 9A: Payment confirmation received?
├── YES (customer sends screenshot / "done") → Step 10
├── NO / "I'll pay later" → Zara: "No problem! Your order will be held for 24 hours."
│   └── Bot sets reminder: auto-follow-up after 24h if no payment
│       ├── Payment received → Step 10
│       └── 48h no payment → Bot auto-cancels order with note
└── "I want to pay full amount" → "Sure! Full payment of Rs. X,XXX. Same bank details."
    └── Step 10
```

### Phase 6: Payment Verification

**Step 10** — Manual verification of payment

```
Decision 10A: Payment confirmed by team?
├── YES → WooCommerce order status → processing
│   └── Zara sends: "✅ Payment received! Your order is confirmed.
│       We'll deliver on [date]. Our team will coordinate logistics."
└── NO (payment not clearing / incorrect amount) → "We're checking your payment.
    Our team will get back to you shortly."
    └── Human follows up
```

### Phase 7: Post-Confirmation

**Step 11** — Logistics coordination

```
Decision 11A: Delivery or Pickup?
├── DELIVERY → Team arranges delivery logistics
│   └── On delivery day → Bot sends reminder "Your delivery is today! 🚚"
└── PICKUP → Team prepares items for pickup
    └── Bot sends location & timing details
```

**Step 12** — Post-event follow-up
- After event date → Bot sends: "Hope everything went well! We'd love your feedback"
- Optionally: automated review request

### Edge Cases

| Scenario | Action |
|----------|--------|
| Customer goes silent mid-flow | Bot follows up once after 15 mins, then saves draft |
| Customer changes mind | "No problem!" Order drafted as `cancelled` |
| Partial payment | Team manually adjusts — order stays `on-hold` until full deposit |
| Wrong item quantity | Zara updates running list at any point before Step 7 |
| Urgent/last-minute booking | Zara detects date < 48h away → flags as urgent, alerts team |
| Customer asks human | Transfers to business number, attaches conversation summary |
| Duplicate order attempt | Bot checks if customer has active `on-hold` order already |

---

## Solution WA-OF-02: Structured Form → WooCommerce → Invoice Flow

### Overview

Customer sends inquiry → Zara sends structured form fields → Customer fills in one shot → WooCommerce order created → Team reviews & adds costs → Invoice sent to WhatsApp → Customer confirms → Payment flow

### Step-by-Step

**Step 1** — Customer taps **"Send Inquiry"** on product card
- Meta system message sent
- Zara picks up conversation

**Step 2** — Zara sends structured input fields in one message:

```
Please reply with your details:

📍 Event Date: ________
👤 Full Name: ________
📧 Email: ________
🚚 Pickup or Delivery: ________
⏰ Preferred Time: ________

Security deposit & transport costs will be calculated once all details are confirmed.
```

**Step 3** — Customer replies with all info in one message
- e.g. *"25 July 2026, Sajjad Jamaldeen, sajjad@email.com, Delivery, 8am"*

**Step 4** — Zara parses the structured reply → Creates **WooCommerce order**
- Items pulled from the catalog inquiry
- Customer info saved as order meta
- Billing = customer name + phone + email
- Shipping = delivery address or "Pickup"
- Custom meta: `event_date`, `delivery_type`, `preferred_time`
- **Status:** `pending`

**Step 5** — **Team reviews & updates the order**
- Adds security deposit amount
- Calculates transport costs
- Adjusts quantities if needed
- Saves order → triggers webhook

**Step 6** — WooCommerce update triggers **invoice PDF** sent to customer's **WhatsApp**
- Invoice generated by WooCommerce
- Sent via our bot as a PDF/attachment with summary message

**Step 7** — Customer reviews invoice → **Confirms via WhatsApp**

```
Decision 7A: Customer response?
├── ✅ Confirm → Step 8
└── ❌ Change needed → Team updates order → re-send invoice → back to Step 7
```

**Step 8** — Zara sends payment instructions:

```
✅ Thank you! Please make payment to:

Bank: [Bank Name]
Account: [Account Number]
Name: EventRentals.lk

Amount: Rs. X,XXX
(Includes: items + delivery + security deposit)

Send confirmation screenshot when done.
```

**Step 9** — Payment confirmed → order moves to `processing`
- Zara sends delivery/pickup confirmation

```
Decision 9A: Payment received?
├── YES → Order to processing. "Your order is confirmed! 🎉"
└── NO after 48h → Order auto-cancelled, customer notified
```

### Key Difference: OF-01 vs OF-02

| Aspect | WA-OF-01 (Conversational) | WA-OF-02 (Structured) |
|--------|--------------------------|------------------------|
| Data collection | Step-by-step Q&A | One-shot structured fields |
| Human touch | Full conversation | Form-like input |
| Speed | Slower but natural | Faster, less chatty |
| Team involvement | Minimal (only exceptions) | Reviews & finalizes order |
| Invoice trigger | Not built-in | Yes — WooCommerce → WhatsApp |
| Customer effort | Multiple back-and-forth | Single reply with all details |

---

## Implementation Priority

1. **Phase 1:** Zara's instructions & product data (in progress)
2. **Phase 2:** WhatsApp catalog + product sets (in progress)
3. **Phase 3:** Meta webhook setup (DNS + Caddy — blocked)
4. **Phase 4:** Order flow implementation (choose OF-01 or OF-02)
5. **Phase 5:** Payment verification integration
6. **Phase 6:** Post-event feedback automation

---

## Open Questions

- Which order flow to implement first?
- Will deposit be a flat % or per-product?
- Transport costs: flat fee per zone or calculated per km?
- Should invoice be auto-generated by WooCommerce or custom-built?
- What happens for recurring customers with saved preferences?
