import json
from pathlib import Path

import pandas as pd
import pytest

from o2cmining import automation, conformance, discovery, performance
from o2cmining.eventlog import EventLog

ROOT = Path(__file__).resolve().parents[1]


def mklog(traces, cases=None, step_h=1.0):
    rows = []
    for cid, acts in traces.items():
        t = pd.Timestamp("2026-01-01 08:00")
        for i, a in enumerate(acts):
            res = "Credit-Bot" if a in ("Check Credit",) else "Billing-Bot" if a == "Create Invoice" else "EDI-Bot" if a == "Create Sales Order" else "Person"
            rows.append({"case_id": cid, "activity": a, "timestamp": t + pd.Timedelta(hours=step_h * i), "resource": res})
    cs = pd.DataFrame(cases) if cases else None
    return EventLog.from_frames(pd.DataFrame(rows), cs)


HAPPY = ["Create Sales Order", "Check Credit", "Pick Goods", "Pack Goods", "Ship Goods", "Create Invoice", "Receive Payment"]


def test_requires_columns():
    with pytest.raises(ValueError):
        EventLog.from_frames(pd.DataFrame({"case_id": [1], "activity": ["a"]}))


def test_sorting_and_waits():
    log = mklog({"A": ["x", "y", "z"]}, step_h=2)
    assert list(log.events["activity"]) == ["x", "y", "z"]
    assert log.events["wait_h"].dropna().tolist() == [2.0, 2.0]


def test_dfg_counts():
    log = mklog({"A": ["a", "b", "c"], "B": ["a", "b", "b", "c"]})
    d = discovery.dfg(log).set_index(["activity", "next_activity"])["count"]
    assert d[("a", "b")] == 2 and d[("b", "b")] == 1 and d[("b", "c")] == 2


def test_variants_shares_sum_to_one():
    log = mklog({"A": ["a", "b"], "B": ["a", "b"], "C": ["a", "c"]})
    v = discovery.variants(log)
    assert v.iloc[0]["cases"] == 2 and abs(v["share"].sum() - 1) < 1e-9


def test_mermaid_hides_rare_paths():
    log = mklog({**{f"N{i}": ["a", "b"] for i in range(99)}, "R": ["a", "c"]})
    m = discovery.mermaid(log, min_share=0.02)
    assert "a -->" in m and "c[" not in m


def test_rework_detection():
    log = mklog({"A": ["Pick Goods", "Change Quantity", "Pick Goods"], "B": ["Pick Goods"]})
    rw = performance.rework(log)
    assert rw.iloc[0]["activity"] == "Pick Goods" and rw.iloc[0]["share_of_cases"] == 0.5


def test_conformance_rules():
    traces = {
        "ok": ["Create Sales Order", "Check Credit", "Request Price Approval", "Approve Price", "Pick Goods",
               "Pack Goods", "Ship Goods", "Create Invoice"],
        "no_approval": ["Create Sales Order", "Check Credit", "Pick Goods", "Ship Goods", "Create Invoice"],
        "early_invoice": ["Create Sales Order", "Check Credit", "Pick Goods", "Create Invoice", "Ship Goods"],
        "price_change": ["Create Sales Order", "Check Credit", "Approve Price", "Change Price", "Pick Goods",
                         "Ship Goods", "Create Invoice"],
    }
    cases = [{"case_id": k, "discount": 0.2} for k in traces]
    summary, viol = conformance.check(mklog(traces, cases))
    s = summary.set_index("rule")
    assert s.loc["approval_before_shipping", "violations"] == 2  # no_approval, early_invoice
    assert s.loc["invoice_after_shipping", "violations"] == 1
    assert s.loc["reapproval_after_price_change", "violations"] == 1
    assert set(viol[viol.rule == "invoice_after_shipping"].case_id) == {"early_invoice"}


def test_discount_rule_only_applies_above_threshold():
    traces = {"small": ["Create Sales Order", "Check Credit", "Pick Goods", "Ship Goods", "Create Invoice"]}
    summary, _ = conformance.check(mklog(traces, [{"case_id": "small", "discount": 0.05}]))
    assert summary.set_index("rule").loc["approval_before_shipping", "cases_checked"] == 0


def test_touchless_rate():
    log = mklog({"bot": ["Create Sales Order", "Check Credit", "Pick Goods", "Create Invoice"],
                 "manual": ["Create Sales Order", "Check Credit", "Approve Price", "Pick Goods"]})
    assert automation.touchless_rate(log) == 0.5


def test_bottlenecks_exclude_payment_terms():
    log = mklog({"A": HAPPY})
    edges = set(performance.bottlenecks(log)["edge"])
    assert "Create Invoice → Receive Payment" not in edges


def test_full_analysis_findings():
    r = json.loads((ROOT / "docs" / "results.json").read_text())
    assert r["log"]["cases"] == 5000
    hold = r["credit_hold_release_by_region_median_h"]
    assert max(hold, key=hold.get) == "Southern Europe" and hold["Southern Europe"] > 2 * hold["DACH"]
    conf = {c["rule"]: c for c in r["conformance"]}
    assert conf["credit_check_before_picking"]["violations"] == 0
    assert conf["reapproval_after_price_change"]["violations"] > 0
    assert sum(c["wait_days_removed"] for c in r["automation_candidates"]) > 500
