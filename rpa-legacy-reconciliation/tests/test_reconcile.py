from decimal import Decimal

import pytest
from rpa_legacy.reconcile import reconcile


def test_reconciliation_categories_and_tolerance():
    d = Decimal
    system = [("A", "2026-10", d("10")), ("B", "2026-10", d("20")), ("C", "2026-10", d("30"))]
    payroll = [("A", "2026-10", d("10.01")), ("B", "2026-10", d("22")), ("D", "2026-10", d("40"))]
    assert [row[2] for row in reconcile(system, payroll, d("0.01"))] == ["Conciliado", "Divergência de valor", "Ausente na folha", "Ausente no sistema"]


def test_duplicate_keys_rejected():
    row = ("A", "2026-10", Decimal("1"))
    with pytest.raises(ValueError, match="Duplicate"):
        reconcile([row, row], [], Decimal("0"))
