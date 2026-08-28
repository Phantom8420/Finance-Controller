"""Restricted execution for generated proof scripts.

Every proof script must define `compute(inputs: dict) -> Decimal`. Before
execution, the code is statically checked (via `ast`) to reject dunder
attribute/name access and imports — this specifically closes the classic
`().__class__.__bases__[0].__subclasses__()`-style sandbox-escape pattern,
not just the `__import__`/`open` removal from builtins, which alone does
not block it. The restricted builtins are still stripped to an
arithmetic-only subset as defense in depth.

Residual, documented limitation: the timeout is enforced by giving up on
waiting for a worker thread, not by killing it — Python cannot forcibly
terminate a thread. A script that hangs (rather than raising or returning)
leaves that thread running in the background after `run_proof_code`
returns its timeout error. It's run as a plain daemon `threading.Thread`
rather than via `ThreadPoolExecutor` specifically so that leak can't block
process shutdown: `concurrent.futures.ThreadPoolExecutor` registers an
atexit hook that joins every non-daemon worker thread before the
interpreter exits, so a single runaway proof script would hang the entire
process at shutdown, not just the one call — a real bug that was actually
hit and fixed while building this (see docs/architecture.md). A daemon
thread is abandoned cleanly by the OS at process exit instead. This is an
acceptable trade-off here because the only code that ever reaches this
sandbox is our own deterministic templates or model-generated arithmetic
snippets — never third-party input — so the realistic failure mode is a
buggy generated script, not a hostile one. A fully adversarial threat
model would need process-level isolation instead.
"""
from __future__ import annotations

import ast
import math
import queue
import threading
from decimal import Decimal

_SAFE_BUILTINS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "len": len,
    "int": int,
    "float": float,
    "str": str,
}


class SandboxError(Exception):
    pass


def _validate_ast(code: str) -> ast.Module:
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        raise SandboxError(f"proof code failed to parse: {e}") from e

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise SandboxError("proof code may not import anything")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise SandboxError(f"proof code may not reference dunder name '{node.id}'")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise SandboxError(f"proof code may not access dunder attribute '.{node.attr}'")
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            raise SandboxError("proof code may not declare global/nonlocal names")

    return tree


def _is_decimal_like(value: str) -> bool:
    try:
        Decimal(value)
        return True
    except Exception:
        return False


def find_foreign_constants(code: str, allowed_values: set) -> list:
    """Anti-gaming check for model-generated proofs: statically finds any
    numeric literal in the code that isn't traceable to a known-allowed
    input value (or a small set of ordinary arithmetic constants). Without
    this, a generated `compute()` could simply hardcode the target answer
    (e.g. `return Decimal("123.45")`) and trivially "reproduce" any number
    it was shown, defeating the point of proving rather than asserting.
    `allowed_values` should include every raw input value plus 0/1/2/10/100
    for ordinary percentage arithmetic; callers pass those in explicitly.
    Only numeric constants are considered — ordinary string constants
    (dict keys like "amount", "fee_rate") are never flagged."""
    tree = ast.parse(code, mode="exec")
    allowed_decimals = {Decimal(v) for v in allowed_values if _is_decimal_like(v)}

    foreign = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        value = node.value
        if isinstance(value, bool):
            continue  # bool is a subclass of int; never a money constant
        if isinstance(value, (int, float)):
            raw = str(value)
        elif isinstance(value, str) and _is_decimal_like(value):
            raw = value
        else:
            continue  # non-numeric strings (dict keys, etc.) are never flagged

        if raw in allowed_values:
            continue
        if _is_decimal_like(raw) and Decimal(raw) in allowed_decimals:
            continue
        foreign.append(raw)
    return foreign


def run_proof_code(code: str, inputs: dict, timeout: float = 2.0, trusted: bool = False) -> Decimal:
    """`trusted=True` skips the thread+timeout wrapper below — AST
    validation still runs unconditionally either way. Only pass it for our
    own fixed, developer-authored templates, whose termination and safety
    we can vouch for directly, never for LLM-generated or otherwise
    externally-influenced code. Re-verification (ProofChain.reverify_all,
    scripts/verify_chain.py) never sets this: every stored proof, no
    matter how it was originally resolved, is re-checked through the full
    paranoid path on re-verification — this flag only speeds up the
    initial resolution of known-safe rules, it never weakens the audit."""
    _validate_ast(code)

    restricted_globals = {
        "__builtins__": _SAFE_BUILTINS,
        "Decimal": Decimal,
        "math": math,
    }
    local_ns: dict = {}

    def _run_and_get():
        exec(code, restricted_globals, local_ns)  # noqa: S102 - AST-validated + restricted globals above
        if "compute" not in local_ns:
            raise SandboxError("proof code must define a compute(inputs) function")
        return local_ns["compute"](inputs)

    if trusted:
        try:
            result = _run_and_get()
        except SandboxError:
            raise
        except Exception as e:  # noqa: BLE001 - reported to the caller below
            raise SandboxError(f"proof code raised {e!r}") from e
    else:
        result_queue: "queue.Queue[tuple[str, object]]" = queue.Queue(maxsize=1)

        def _run():
            try:
                result_queue.put(("ok", _run_and_get()))
            except Exception as e:  # noqa: BLE001 - reported to the caller below, never swallowed
                result_queue.put(("error", e))

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout)

        if thread.is_alive():
            raise SandboxError(f"proof code exceeded {timeout}s timeout")

        try:
            status, payload = result_queue.get_nowait()
        except queue.Empty as e:
            raise SandboxError("proof code thread exited without producing a result") from e

        if status == "error":
            raise SandboxError(f"proof code raised {payload!r}") from payload
        result = payload

    if isinstance(result, Decimal):
        return result
    try:
        return Decimal(str(result))
    except Exception as e:
        raise SandboxError("compute() must return a Decimal-convertible value") from e
