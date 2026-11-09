"""Automation potential: touchless rate and sized automation candidates.

Each candidate is a concrete change with a rule, the cases it would affect and the waiting hours
it would remove, so it can go straight into a business case.
"""
from __future__ import annotations

import pandas as pd

from .eventlog import EventLog

BOTS = ("-Bot", "Bank", "Carrier")
# Order administration steps (physical warehouse work is out of scope for "touchless")
ADMIN = {"Create Sales Order", "Check Credit", "Credit Hold", "Release Credit Hold", "Request Price Approval",
         "Approve Price", "Change Price", "Change Quantity", "Create Invoice", "Cancel Order"}


def touchless_rate(log: EventLog) -> float:
    """Share of orders whose administration ran without a single manual step."""
    e = log.events
    admin = e[e["activity"].isin(ADMIN)]
    manual_cases = admin.loc[~admin["resource"].fillna("").str.endswith(BOTS), "case_id"].nunique()
    return 1 - manual_cases / log.n_cases


def candidates(log: EventLog) -> pd.DataFrame:
    e = log.events.merge(log.cases, on="case_id", how="left")
    out = []

    # 1) auto-approve small discounts: approvals for orders under 5k with discount <= 20 %
    ap = e[(e["activity"] == "Request Price Approval") & (e["next_activity"] == "Approve Price")]
    small = ap[(ap["order_value"] < 5000) & (ap["discount"] <= 0.20)]
    out.append({"candidate": "Auto-approve discounts ≤ 20 % on orders < €5k",
                "rule": "order_value < 5000 and discount <= 0.20",
                "cases": int(small["case_id"].nunique()), "wait_hours_removed": float(small["wait_h"].sum())})

    # 2) auto-release credit holds for repeat customers below a limit (here: order < 2k)
    ch = e[(e["activity"] == "Credit Hold") & (e["next_activity"] == "Release Credit Hold")]
    low = ch[ch["order_value"] < 2000]
    out.append({"candidate": "Auto-release credit holds for orders < €2k",
                "rule": "order_value < 2000 and no overdue invoices",
                "cases": int(low["case_id"].nunique()), "wait_hours_removed": float(low["wait_h"].sum())})

    # 3) automatic invoicing at goods issue (cases invoiced manually by the billing team)
    inv = e[(e["activity"] == "Ship Goods") & (e["next_activity"] == "Create Invoice")]
    manual_inv = inv.merge(e[e["activity"] == "Create Invoice"][["case_id", "resource"]], on="case_id",
                           suffixes=("", "_inv"))
    manual_inv = manual_inv[manual_inv["resource_inv"] == "Billing Team"]
    # a bot invoices within ~2 h; the saving is the wait above that
    saved = (manual_inv["wait_h"] - 2).clip(lower=0).sum()
    out.append({"candidate": "Invoice automatically at goods issue",
                "rule": "trigger Create Invoice on Ship Goods",
                "cases": int(manual_inv["case_id"].nunique()), "wait_hours_removed": float(saved)})

    # 4) automated credit check for SMB orders still checked manually
    cc = e[(e["activity"] == "Check Credit") & (e["resource"] == "Credit Team")]
    prev = e[e["next_activity"] == "Check Credit"][["case_id", "wait_h"]]
    cc = cc.merge(prev, on="case_id", suffixes=("", "_in"))
    out.append({"candidate": "Automated credit check for all SMB orders",
                "rule": "score via credit API, manual only if score < threshold",
                "cases": int(cc["case_id"].nunique()),
                "wait_hours_removed": float((cc["wait_h_in"] - 0.5).clip(lower=0).sum())})

    df = pd.DataFrame(out)
    df["share_of_cases"] = df["cases"] / log.n_cases
    df["wait_days_removed"] = df["wait_hours_removed"] / 24
    return df.sort_values("wait_hours_removed", ascending=False).reset_index(drop=True)
