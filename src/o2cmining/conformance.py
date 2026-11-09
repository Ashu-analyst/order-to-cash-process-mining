"""Rule-based conformance checking against the target O2C process.

Each rule is a declarative constraint (in the style of DECLARE): it is checked on every case and
reports how many cases violate it and which ones, so auditors and process owners can drill down.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from .eventlog import EventLog

Trace = tuple


def _idx(trace: Trace, act: str) -> list[int]:
    return [i for i, a in enumerate(trace) if a == act]


@dataclass
class Rule:
    name: str
    description: str
    applies: Callable[[Trace, dict], bool]
    holds: Callable[[Trace, dict], bool]
    severity: str = "high"


def precedence(a: str, b: str) -> Callable[[Trace, dict], bool]:
    """Every b must be preceded by some a."""
    def f(t: Trace, _c: dict) -> bool:
        ia = _idx(t, a)
        return all(ia and ia[0] < j for j in _idx(t, b))
    return f


def response(a: str, b: str) -> Callable[[Trace, dict], bool]:
    """Every a must eventually be followed by b."""
    def f(t: Trace, _c: dict) -> bool:
        ib = _idx(t, b)
        return all(any(j > i for j in ib) for i in _idx(t, a))
    return f


def reapproval_after_price_change(t: Trace, _c: dict) -> bool:
    """After every price change there must be a new approval before shipping."""
    for i in _idx(t, "Change Price"):
        ship = [j for j in _idx(t, "Ship Goods") if j > i]
        appr = [j for j in _idx(t, "Approve Price") if j > i]
        if ship and not (appr and appr[0] < ship[0]):
            return False
    return True


RULES: list[Rule] = [
    Rule("approval_before_shipping", "Orders with discount > 15 % need a price approval before shipping",
         lambda t, c: "Ship Goods" in t and c.get("discount", 0) > 0.15, precedence("Approve Price", "Ship Goods")),
    Rule("credit_check_before_picking", "Credit must be checked before goods are picked",
         lambda t, c: "Pick Goods" in t, precedence("Check Credit", "Pick Goods")),
    Rule("hold_released_before_picking", "A credit hold must be released before picking",
         lambda t, c: "Credit Hold" in t and "Pick Goods" in t, precedence("Release Credit Hold", "Pick Goods")),
    Rule("invoice_after_shipping", "Invoices are created only after the goods are shipped",
         lambda t, c: "Create Invoice" in t, precedence("Ship Goods", "Create Invoice"), severity="medium"),
    Rule("reapproval_after_price_change", "A price change after approval needs a new approval",
         lambda t, c: "Change Price" in t, reapproval_after_price_change),
    Rule("shipped_orders_get_invoiced", "Every shipped order is invoiced",
         lambda t, c: "Ship Goods" in t, lambda t, c: "Create Invoice" in t, severity="medium"),
]


def check(log: EventLog, rules: list[Rule] = RULES) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (summary per rule, long table of violating case ids)."""
    traces = log.traces()
    attrs = log.cases.set_index("case_id").to_dict("index")
    rows, viol = [], []
    for r in rules:
        applicable = violated = 0
        for cid, t in traces.items():
            c = attrs.get(cid, {})
            if not r.applies(t, c):
                continue
            applicable += 1
            if not r.holds(t, c):
                violated += 1
                viol.append({"rule": r.name, "case_id": cid})
        rows.append({"rule": r.name, "description": r.description, "severity": r.severity,
                     "cases_checked": applicable, "violations": violated,
                     "fitness": 1 - violated / applicable if applicable else 1.0})
    return pd.DataFrame(rows), pd.DataFrame(viol, columns=["rule", "case_id"])
