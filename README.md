# AI Finance Controller — prove it, balance it, break it

Razorpay AI Buildathon, Track 04 (AI Finance Controller). A reconciliation
agent that doesn't just claim accuracy — it proves individual answers,
proves the whole batch balances, and then tries to break its own logic to
find blind spots before a human does.

## The three layers

1. **Per-record proof, not prose.** Every mismatch between a payment and
   the merchant's ledger is closed by a small script that recomputes the
   exact discrepancy from a specific rule, executed in a sandbox. If it
   reproduces the number, the script becomes that record's proof, hashed
   into an append-only chain. A "Re-verify everything" action re-executes
   every stored proof from raw data with **zero AI calls**.
2. **Whole-batch conservation proof.** Individually-explained discrepancies
   can still be biased in the same direction and not cancel out in
   aggregate. This checks the net drift across all verified records against
   a batch-scaled tolerance, using exact decimal arithmetic (and a `z3`
   constraint-solver check when installed).
3. **The agent hunts its own blind spots.** After the real batch, it
   generates its own adversarial edge cases designed to fool its own
   matching logic (boundary rounding, chained partial refunds, wrong GST
   slabs) and logs anything it can't resolve as a known limitation it
   found on its own.

See [docs/architecture.md](docs/architecture.md) for the full design and
[the buildathon plan](../.claude/plans/) for how this was scoped.

## Quickstart

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # fill in keys once you have them
python scripts/seed_demo_data.py
streamlit run app/dashboard/streamlit_app.py
```

Works out of the box with mock payment data (`data/mock_source.py`) if
`RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` aren't set yet — swap in real
Razorpay test-mode data via `app/razorpay_client.py` once you have keys.
Set `ANTHROPIC_API_KEY` to enable the Layer 1 stage-3 LLM-assisted proof
step; without it, gaps the rule-based stages can't explain still correctly
land in the exception list.

## Tests

```bash
pytest
```

One test per injected discrepancy type, asserting the engine reaches the
correct verdict and never force-matches an unexplained gap.

## Current status

- Layers 1-3 implemented and verified end-to-end against mock data
  (60-record batch: precision 1.0, recall 1.0, exception rate 0.15,
  ~1600 records/sec; conservation check correctly flags a systematic
  ₹88.50 drift from GST-miscalculation-type ledger entries; self-test
  generates 24 adversarial cases and honestly reports its blind spots).
- Real Razorpay test-mode wiring (`app/razorpay_client.py`) is scaffolded
  but not yet exercised against live keys — pending signup.
