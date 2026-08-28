# Architecture

## Data flow

```
Source A (real, ground truth)          Source B (messy, the merchant's books)
  Razorpay test-mode Payments   --->   generate_ledger.py derives a synthetic
  (app/razorpay_client.py, or          internal ledger from Source A and
  data/mock_source.py until            deliberately injects known mismatch
  live keys are configured)            types, each labeled for scoring.
              |                                     |
              +------------------+------------------+
                                 v
                     app/reconciliation/engine.py
                (Layer 1 — three-stage proof-based matcher)
                                 |
              +------------------+------------------+
              v                                     v
   app/reconciliation/proof_chain.py      app/invariants/conservation_check.py
   (hash-chained proofs,                  (Layer 2 — whole-batch drift check,
    "re-verify everything")                decimal + optional z3)
                                 |
                                 v
                  app/selftest/adversarial_gen.py
              (Layer 3 — self-generated edge cases,
                     known_limitations.json)
                                 |
                                 v
                       app/metrics.py + app/dashboard/streamlit_app.py
```

## Layer 1 — per-record proof, not prose

`app/reconciliation/models.py` defines the money math once: Razorpay's fee
(2%) and GST-on-fee (18%) rates, and `PaymentRecord.true_ledger_amount` —
what a correct ledger entry for that payment should say.

`engine.reconcile()` runs three stages per payment:

1. **Structural check.** No ledger entry → exception ("no ledger entry
   found"). More than one entry referencing the same payment → exception
   ("ambiguous, needs human review"). Neither case is ever guessed through.
2. **Rule-based proof.** Three deterministic templates (`net_settlement`,
   `gst_fee_miss`, `refund_not_reflected`) are executed in
   `app/reconciliation/sandbox.py` — a restricted `exec` environment with no
   `import`, no I/O, and a wall-clock timeout. A rule is accepted only if
   its output reproduces the actual ledger amount within tolerance
   (`TOLERANCE = 0.02`, i.e. 2 paise).
3. **LLM-assisted proof.** Only for gaps stage 2 can't explain, Claude is
   asked to write a `compute()` script. It's accepted only if *executing*
   it reproduces the actual number — never on the model's say-so. If
   `ANTHROPIC_API_KEY` isn't set, this stage is skipped and the gap
   correctly falls through to the exception list instead.

`app/reconciliation/proof_chain.py` hashes each `ProofRecord` (payload +
previous hash) into an append-only chain. `reverify_all()` — the
dashboard's "Re-verify everything" button — re-executes every stored proof
from its stored raw inputs and re-derives every hash link, entirely without
AI, entirely from what's on disk.

## Layer 2 — whole-batch conservation proof

A per-record proof can be individually correct and still hide a systemic
pattern: several small, individually-*explained* discrepancies can be
biased in the same direction and not cancel out in aggregate, even though
each one alone looked fine. `app/invariants/conservation_check.py` sums,
across every verified record, `actual_value - true_ledger_amount` (the net
drift), and checks it against a tolerance that scales with the number of
verified records (`0.02 * n`). Rounding noise nets out and stays inside
that tolerance; a systematic pattern (e.g. GST consistently miscalculated)
does not — and the check correctly reports `balanced: false` even though
every individual record passed Layer 1. `try_z3_check()` encodes the same
check as constraints solved by `z3-solver` when installed, as an
independent second opinion.

## Layer 3 — the agent hunts its own blind spots

`app/selftest/adversarial_gen.py` generates edge cases designed to stress
the exact rule set Layer 1 relies on: rounding noise straddling the
tolerance boundary, a payment with two sequential partial refunds where
the ledger only reflects one, and GST applied at the wrong slab (12%
instead of 18%). These are run through the same `reconcile()` engine used
for real data. Anything it can't resolve is logged as a limitation the
system found on its own, before a human did.

## Safety note

Generated verification scripts run in a restricted sandbox
(`app/reconciliation/sandbox.py`): no filesystem or network access,
whitelisted names only (`Decimal`, `math`, and a handful of safe
builtins), execution timeout via a worker thread. This guards against
*accidentally* unsafe generated code — it is not a hardened boundary
against a deliberately adversarial script, since the only code that ever
reaches it is our own deterministic templates or short model-generated
arithmetic snippets, never untrusted third-party input.

## Known failure fixed during development

Two real bugs were caught and fixed while building this:

1. `ProofRecord.created_at` originally defaulted to `datetime.utcnow()`
   evaluated once at class-definition time (a classic Python/Pydantic
   mutable-default trap) — every record silently got the same timestamp.
   Fixed with `Field(default_factory=lambda: datetime.now(timezone.utc))`.
2. The first version of the Layer 2 conservation check reconstructed the
   gross captured amount by uniformly adding back fee + GST + refund to
   every verified record's ledger amount — which is only valid for the
   `net_settlement` rule shape. Applied to `gst_fee_miss`-explained
   records, it silently double-counted the very discrepancy Layer 1 had
   just explained, producing a meaningless imbalance number. Fixed by
   reframing the check around net drift from truth (`actual_value -
   true_ledger_amount`) instead of a per-rule-shape reconstruction —
   which is what turned out to be the actually meaningful signal: it
   reveals systematic bias across explained records, which is exactly
   what a whole-batch check should catch that a per-record check can't.
