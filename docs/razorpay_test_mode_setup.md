# Getting real Razorpay test-mode data into this project

`app/razorpay_client.py` automates as much of this as Razorpay's APIs
allow — but turning a created order into a *captured payment* is not
fully API-automatable, and earlier project material implied otherwise.
Here's exactly what's automated and what isn't.

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

## 2. Seed orders (automated)

```bash
python -c "from app.razorpay_client import seed_test_orders; print(seed_test_orders(60))"
```

This creates 60 test-mode Orders via the API. This part is fully
automated — no manual step.

## 3. Turn orders into captured payments (semi-manual)

Razorpay does not offer an API to programmatically "pay" an order in test
mode — payment capture requires going through Checkout (or a webhook
simulation), because that's the same code path that would move real money
in production. Two practical options:

- **Checkout, using Razorpay's documented test cards** — open Razorpay's
  [Checkout test flow](https://razorpay.com/docs/payments/payments/test-card-upi-details/)
  for each order, pay with a test card (e.g. `4111 1111 1111 1111`, any
  future expiry, any CVV). Tedious for 60 orders by hand — realistically
  you'd script a headless browser against Checkout, which is out of scope
  for this repo right now.
- **Razorpay's Postman/test-mode payment simulation** — Razorpay publishes
  a Postman collection that can create+capture a payment against a test
  order in one call, bypassing Checkout's UI. This is the more practical
  path for generating a real batch quickly; see Razorpay's API reference
  for the current endpoint, since test-mode simulation endpoints have
  moved before.

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
