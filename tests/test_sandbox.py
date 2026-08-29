from decimal import Decimal

import pytest

from app.reconciliation.sandbox import SandboxError, find_foreign_constants, run_proof_code


def test_normal_proof_code_runs():
    code = """
def compute(inputs):
    amount = Decimal(str(inputs["amount"]))
    return amount * Decimal("2")
"""
    result = run_proof_code(code, {"amount": "10.00"})
    assert result == Decimal("20.00")


def test_trusted_path_still_produces_correct_results():
    code = """
def compute(inputs):
    amount = Decimal(str(inputs["amount"]))
    return amount * Decimal("2")
"""
    result = run_proof_code(code, {"amount": "10.00"}, trusted=True)
    assert result == Decimal("20.00")


def test_trusted_path_still_enforces_ast_validation():
    # trusted=True skips the thread+timeout wrapper, not AST validation —
    # the dunder-escape and import guards must still apply either way.
    code = """
def compute(inputs):
    leak = ().__class__.__bases__[0].__subclasses__()
    return Decimal("1")
"""
    with pytest.raises(SandboxError):
        run_proof_code(code, {}, trusted=True)

    code_import = """
import os
def compute(inputs):
    return Decimal("1")
"""
    with pytest.raises(SandboxError):
        run_proof_code(code_import, {}, trusted=True)


def test_sandbox_rejects_import():
    code = """
import os
def compute(inputs):
    return Decimal("1")
"""
    with pytest.raises(SandboxError):
        run_proof_code(code, {})


def test_sandbox_rejects_dunder_class_escape():
    # the classic exec-sandbox escape: walk from an empty tuple to `object`
    # via __class__/__bases__/__subclasses__ to reach live class objects
    code = """
def compute(inputs):
    leak = ().__class__.__bases__[0].__subclasses__()
    return Decimal("1")
"""
    with pytest.raises(SandboxError):
        run_proof_code(code, {})


def test_sandbox_rejects_bare_dunder_name():
    code = """
def compute(inputs):
    return Decimal(str(__builtins__))
"""
    with pytest.raises(SandboxError):
        run_proof_code(code, {})


def test_sandbox_rejects_missing_compute_function():
    code = "x = 1"
    with pytest.raises(SandboxError):
        run_proof_code(code, {})


def test_sandbox_enforces_timeout():
    code = """
def compute(inputs):
    while True:
        pass
"""
    with pytest.raises(SandboxError):
        run_proof_code(code, {}, timeout=0.2)


def test_find_foreign_constants_handles_unparseable_code_gracefully():
    # real failure mode: Gemini generates inconsistently-indented code
    # often enough to hit in production. Must not crash the caller.
    bad_code = "def compute(inputs):\n  x = 1\n     y = 2\n  return x + y"
    foreign = find_foreign_constants(bad_code, {"1", "2"})
    assert foreign  # non-empty -> every call site's `if foreign: reject` still works


def test_find_foreign_constants_flags_hardcoded_answer():
    # a script that just returns the "target" value it was shown, instead
    # of deriving anything from the inputs it was actually given
    code = """
def compute(inputs):
    return Decimal("999.42")
"""
    allowed = {"10.00", "0.02", "0.18", "0"}
    foreign = find_foreign_constants(code, allowed)
    assert "999.42" in foreign


def test_find_foreign_constants_allows_input_derived_values():
    code = """
def compute(inputs):
    amount = Decimal(str(inputs["amount"]))
    fee_rate = Decimal(str(inputs["fee_rate"]))
    return amount * fee_rate
"""
    allowed = {"10.00", "0.02"}
    foreign = find_foreign_constants(code, allowed)
    assert foreign == []
