# Getting real Razorpay test-mode data into this project

This is the actual, verified recipe — walked through end-to-end for a real
6-payment batch (₹14,343 total), not a theoretical one. Earlier drafts of
this doc guessed at a Postman-based approach and recommended a test card
that turned out to be wrong; both are corrected below based on what
actually worked.

## 1. Get test-mode keys

1. Sign up at [dashboard.razorpay.com](https://dashboard.razorpay.com) (no
   business verification needed to use test mode).
2. In the dashboard, make sure **Test Mode** is toggled on (top right).
3. Settings → API Keys → Generate Test Key. Copy the Key ID and Key
   Secret.
4. Put them in `.env`:
   ```
   RAZORPAY_KEY_ID=rzp_test_...
   RAZORPAY_KEY_SECRET=...
   ```

## 2. Create Payment Links (automated, no dashboard login needed)

Razorpay doesn't offer an API to programmatically "pay" — capture must go
through Checkout, since that's the same code path that would move real
money in production. **Payment Links** are the practical way in: create
them via the API with your existing keys, no dashboard session required,
each one gives a hosted Checkout URL you (or anyone) can pay from a
browser:

```python
from app.razorpay_client import get_client

client = get_client()
link = client.payment_link.create({
    "amount": 50000,  # paise
    "currency": "INR",
    "description": "Test payment",
    "customer": {"name": "Test Customer", "contact": "+919876543210", "email": "test@example.com"},
    "notify": {"sms": False, "email": False},
    "reminder_enable": False,
})
print(link["short_url"])
```

## 3. Complete Checkout with a *domestic* test card

Open the `short_url` and pay. Two real gotchas hit while doing this:

- **The generic `4111 1111 1111 1111` Visa test number fails** with
  "International cards are not supported" — Razorpay India's test mode
  specifically wants a domestic card. Use the documented domestic
  Mastercard instead: **`5267 3181 8797 5449`**, any future expiry, any
  3-digit CVV.
- **Contact verification is mandatory even with `customer` pre-filled** —
  Checkout still prompts for a mobile number. Any correctly-formatted
  10-digit Indian mobile number works; `9123456780` is confirmed working.
- After the card, an **Axis Bank OTP simulation screen** appears — enter
  `1221` (Razorpay's standard test OTP) and continue.
- A "Save your card" bottom sheet may appear once or twice — dismiss it
  ("Maybe later" / the X) and click Continue again; it doesn't block the
  payment.
- The UI doesn't always render the final "PAID" confirmation screen
  reliably. **Don't trust the UI alone** — verify via the API:
  ```python
  link = client.payment_link.fetch("plink_...")
  print(link["status"], link["amount_paid"])  # "paid", amount in paise
  ```

This is manual-per-payment (no bulk automation built here yet) — realistic
for a handful of payments to prove the pipeline against real data, not
for hundreds.

## 4. Pull the data

```bash
python -c "from app.razorpay_client import fetch_payments; print(fetch_payments(count=60))"
```

Or just run `python scripts/seed_demo_data.py` / the dashboard — both
automatically use live data instead of the mock source once
`RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET` are set (see
`razorpay_client.has_live_keys()`).

## Known scope limits once real data is flowing

See the docstring on `fetch_payments()` — only single-capture, INR,
`captured`-status payments are mapped. Non-INR, multi-capture, and
authorized-not-captured payments are counted and skipped, not silently
mismapped.
