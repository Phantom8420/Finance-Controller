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
   (hash-chained proofs,                  (Layer 2 — independent whole-batch
    "re-verify everything")                drift check, decimal + optional z3)
                                 |
                                 v
                  app/selftest/adversarial_gen.py
              (Layer 3 — dev-authored fuzz suite +
               optional AI-generated adversarial suite)
                                 |
              +------------------+------------------+
              v                                     v
     app/qa_agent.py                       app/forecast.py
     (stretch: grounded Q&A                (stretch: settlement-timing
      over Layer 1's proofs)                projection, not a forecast)
                                 |
                                 v
        app/metrics.py + app/dashboard/streamlit_app.py + frontend/
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
   `app/reconciliation/sandbox.py`. A rule is accepted only if its output
   reproduces the actual ledger amount within tolerance (`TOLERANCE =
   0.02`, i.e. 2 paise).
3. **LLM-assisted proof.** Only for gaps stage 2 can't explain, Gemini is
   asked to write a `compute()` script — deliberately never shown the
   target ledger amount, only the raw inputs, so it can't just hardcode
   the answer. The generated code is additionally statically checked
   (`find_foreign_constants`) to reject any numeric literal not traceable
   to those inputs, and only accepted if *executing* it reproduces the
   actual number. If `GEMINI_API_KEY` isn't set, this stage is skipped
   and the gap correctly falls through to the exception list instead.

`app/reconciliation/proof_chain.py` hashes each `ProofRecord` (payload +
previous hash) into an append-only chain, persisted to
`data/fixtures/proof_chain.json` on every run. `reverify_all()` — the
dashboard's "Re-verify everything" button, or the standalone
`scripts/verify_chain.py` run against the saved file with no dependency
on the process that produced it — re-executes every stored proof from its
raw inputs and re-derives every hash link, entirely without AI.

## Layer 2 — whole-batch conservation proof

A per-record proof can be individually correct and still hide a systemic
pattern: several small, individually-*explained* discrepancies can be
biased in the same direction and not cancel out in aggregate, even though
each one alone looked fine. `app/invariants/conservation_check.py`
deliberately does **not** read Layer 1's `ProofRecord` outputs — it
recomputes directly from the two raw sources (payments, ledger) via a
separate code path, so a Layer 1 bug (or Layer 1 not having run at all)
can't silently pass this check too. It sums, across every ledger entry
that actually exists, the drift from what it should say
(`entry.amount - true_ledger_amount`), and checks that against a
tolerance scaled to the number of entries compared (`0.02 * n`).
Rounding noise nets out and stays inside that tolerance; a systematic
pattern (e.g. GST consistently miscalculated) does not — the check
correctly reports `balanced: false` even when every individual record
passed Layer 1. Payments with no ledger entry at all are reported
separately (`amount_with_no_ledger_entry`), since there's no recorded
figure to compare against. `try_z3_check()` encodes the same check as
constraints solved by `z3-solver` when installed, as a genuine
constraint-solver second opinion, not just a restatement.

There is no third, independent data source here (no real bank-statement
feed) — that's a real, acknowledged limit, not a hidden one: what makes
this "independent" is that it's a structurally separate computation over
the same raw sources, not a second oracle.

## Layer 3 — the agent hunts its own blind spots

Two honestly-labeled sources, both run through the same `reconcile()`
engine used on real data:

- **`run_fixed_suite()`** — a developer-authored regression/fuzz suite
  (boundary rounding straddling the tolerance edge, chained partial
  refunds only half-reflected, GST at the wrong slab). Deterministic,
  always on, no API key needed. This is *not* the system inventing its
  own tests — it's a fixed suite the system runs against itself.
- **`run_llm_suite()`** — genuinely AI-generated cases: when
  `GEMINI_API_KEY` is set, Gemini invents its own plausible bookkeeping
  mistake and writes the code that produces it (same anti-gaming
  constant check as Stage 3), executed in the same sandbox. Additive to
  the fixed suite, never a silent replacement.

Anything either suite can't resolve is logged as a known limitation —
found before a human hit it. `app/metrics.py`'s `generalization_report()`
reports the resolution rate from these suites *alongside*
`score_reconciliation()`'s in-distribution number, not instead of it —
the in-distribution number is close to a self-fulfilling benchmark (the
injected mismatch formulas in `data/generate_ledger.py` are the algebraic
inverse of engine.py's own rules), so the generalization number is the
one that actually speaks to how the rules perform on cases they weren't
tuned against.

## Stretch: Q&A and cash forecast

`app/qa_agent.py` answers questions about specific reconciliation
outcomes grounded only in the `ProofRecord`s Layer 1 already computed —
it never re-derives a number itself, and cites which record(s) it used.
Requires `GEMINI_API_KEY`; returns a clear "not configured" result
otherwise, the same skipped-not-faked pattern as Layer 3b.

`app/forecast.py` projects near-term cash position from Layer 1's
verified records, spread across Razorpay's documented T+2 settlement
cycle, with every assumption returned in the output rather than baked in
silently; amounts tied to exceptions are excluded from the projection
entirely rather than counted as incoming cash. Pure arithmetic — no API
key needed, always available.

## Sandbox: trust-tiered execution

`app/reconciliation/sandbox.py` statically rejects dunder attribute/name
access and imports via `ast` (closing the classic
`().__class__.__bases__[0].__subclasses__()` sandbox-escape pattern, which
stripping builtins alone does not block), on top of a restricted
arithmetic-only builtin set.

Execution itself is trust-tiered via `run_proof_code(..., trusted=bool)`:

- **Untrusted (default)** — Stage 3's model-generated proofs, Layer 3's
  AI-generated adversarial cases, and *every* re-verification
  (`ProofChain.reverify_all`, `scripts/verify_chain.py`) run in a daemon
  thread with a wall-clock timeout, regardless of how the proof was
  originally resolved.
- **Trusted** — only `engine.py`'s three fixed rule templates (developer-
  authored, reviewed, never model- or externally-influenced) skip the
  thread wrapper — AST validation still runs unconditionally either way.
  This is a genuine ~2x throughput improvement (measured: ~1860 → ~4050
  records/sec on a 200-record batch) from removing OS thread-spawn
  overhead for code we can already vouch for, without weakening the
  audit: re-verification never sets this flag, so every stored proof —
  including ones resolved via the fast path — is re-checked through the
  full paranoid path when it matters.

## Known bugs caught and fixed during development

Real bugs, not hypothetical ones — each was actually hit while building
this, not invented after the fact for the buildathon's "what broke"
question:

1. `ProofRecord.created_at` originally defaulted to `datetime.utcnow()`
   evaluated once at class-definition time (a classic Python/Pydantic
   mutable-default trap) — every record silently got the same timestamp.
   Fixed with `Field(default_factory=lambda: datetime.now(timezone.utc))`.
2. The first version of the Layer 2 conservation check reconstructed the
   gross captured amount by uniformly adding back fee + GST + refund to
   every verified record's ledger amount — valid only for the
   `net_settlement` rule shape. Applied to `gst_fee_miss`-explained
   records, it silently double-counted the very discrepancy Layer 1 had
   just explained, producing a meaningless imbalance number. Fixed by
   reframing the check around net drift from truth instead of a
   per-rule-shape reconstruction — which turned out to be the actually
   meaningful signal.
3. A test asserting the sandbox's timeout enforcement (`while True: pass`)
   hung the *entire test process*, not just that one call.
   `ThreadPoolExecutor.__exit__` calls `shutdown(wait=True)`, and
   `concurrent.futures` registers an atexit hook that joins every
   non-daemon worker thread before the interpreter exits — so one
   runaway proof script would have hung the whole app at shutdown, not
   just timed out its own call. Fixed by switching to a plain
   `threading.Thread(daemon=True)`, which the OS abandons cleanly at
   process exit instead.
4. `ProofChain.load()` didn't restore `created_at` when reconstructing
   records from saved JSON, so every reloaded record got a fresh
   timestamp — since `created_at` is part of the hashed payload, every
   single record then failed hash verification on reload, even though
   nothing had been tampered with. Caught by actually running
   `scripts/verify_chain.py` against a freshly-saved chain instead of
   assuming it worked. Fixed by parsing `created_at` back from the saved
   JSON explicitly.
