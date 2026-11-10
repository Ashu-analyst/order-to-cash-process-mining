"""Purchase-to-pay analysis for SAP-style purchase order logs (BPI Challenge 2019 schema).

Each case is one purchase order *item*. The item category decides which control applies:

* 3-way match, invoice after GR   - goods receipt and invoice must match the PO; invoice only after GR
* 3-way match, invoice before GR  - invoice may arrive first, but payment only after GR
* 2-way match                      - no goods receipt needed; invoice is matched to the PO
* Consignment                      - goods receipt only; invoicing happens elsewhere

The checks below are the ones an audit or a P2P process owner asks first.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .eventlog import EventLog

CREATE = ("Create Purchase Order Item", "Create Purchase Requisition Item")
GR = "Record Goods Receipt"
IR = "Record Invoice Receipt"
CLEAR = "Clear Invoice"
CHANGE_PRICE = "Change Price"
CHANGE_QTY = "Change Quantity"
BLOCK = "Set Payment Block"
REMOVE_BLOCK = "Remove Payment Block"
DELETE = "Delete Purchase Order Item"
VENDOR_INVOICE = "Vendor creates invoice"

FLOW_OF = {
    "3-way match, invoice after GR": "3-way after GR",
    "3-way match, invoice before GR": "3-way before GR",
    "2-way match": "2-way",
    "Consignment": "Consignment",
}


def flows(log: EventLog, col: str = "Item Category") -> pd.Series:
    return log.cases.set_index("case_id")[col].map(FLOW_OF).fillna("other")


def _first(log: EventLog, act: str) -> pd.Series:
    e = log.events
    return e[e["activity"] == act].groupby("case_id")["timestamp"].min()


def _count(log: EventLog, act: str) -> pd.Series:
    e = log.events
    return e[e["activity"] == act].groupby("case_id").size()


def case_facts(log: EventLog) -> pd.DataFrame:
    """One row per PO item with the timestamps and counts the controls need."""
    idx = log.events["case_id"].unique()
    f = pd.DataFrame(index=pd.Index(idx, name="case_id"))
    e = log.events
    f["created"] = e[e["activity"].isin(CREATE)].groupby("case_id")["timestamp"].min()
    f["first_event"] = e.groupby("case_id")["timestamp"].min()
    for name, act in [("gr", GR), ("ir", IR), ("clear", CLEAR), ("deleted", DELETE)]:
        f[f"{name}_first"] = _first(log, act)
    for name, act in [("n_gr", GR), ("n_ir", IR), ("n_clear", CLEAR), ("n_price", CHANGE_PRICE),
                      ("n_qty", CHANGE_QTY), ("n_block", BLOCK)]:
        f[name] = _count(log, act).reindex(f.index).fillna(0).astype(int)
    f["flow"] = flows(log).reindex(f.index)
    cs = log.cases.set_index("case_id")
    for c in ("Vendor", "Spend area text", "Company", "Item Type", "Document Type"):
        if c in cs.columns:
            f[c] = cs[c].reindex(f.index)
    # value of the item: last cumulative net worth seen
    if "Cumulative net worth (EUR)" in e.columns:
        f["value_eur"] = e.groupby("case_id")["Cumulative net worth (EUR)"].last()
    return f


def controls(f: pd.DataFrame) -> pd.DataFrame:
    """Control checks per flow. Each row: rule, flow, items checked, violations, compliant share."""
    rows = []

    def add(rule: str, desc: str, mask_applies: pd.Series, mask_violates: pd.Series) -> None:
        n = int(mask_applies.sum())
        v = int((mask_applies & mask_violates).sum())
        rows.append({"rule": rule, "description": desc, "checked": n, "violations": v,
                     "compliant": round(1 - v / n, 4) if n else 1.0})

    a_gr = f["flow"] == "3-way after GR"
    add("invoice_after_goods_receipt", "3-way (invoice after GR): invoice recorded only after goods receipt",
        a_gr & f["ir_first"].notna(), f["ir_first"] < f["gr_first"].fillna(pd.Timestamp.max))
    three = f["flow"].isin(["3-way after GR", "3-way before GR"])
    add("paid_only_after_goods_receipt", "3-way: invoice cleared only after goods were received",
        three & f["clear_first"].notna(), f["gr_first"].isna() | (f["clear_first"] < f["gr_first"]))
    add("no_payment_without_invoice", "Every cleared item has a recorded invoice",
        f["flow"].ne("Consignment") & f["clear_first"].notna(), f["n_ir"] == 0)
    add("not_paid_more_often_than_invoiced", "Cleared at most as often as invoiced (duplicate payment risk)",
        f["flow"].ne("Consignment") & (f["n_clear"] > 0), f["n_clear"] > f["n_ir"].clip(lower=1))
    add("po_before_invoice", "PO item created before the invoice (no 'after-the-fact' purchasing)",
        f["flow"].ne("Consignment") & f["ir_first"].notna() & f["created"].notna(), f["ir_first"] < f["created"])
    add("consignment_not_invoiced", "Consignment items are not invoiced through this process",
        f["flow"] == "Consignment", f["n_ir"] > 0)
    return pd.DataFrame(rows)


def kpis(f: pd.DataFrame) -> dict:
    paid = f["clear_first"].notna() & f["created"].notna()
    cycle = (f.loc[paid, "clear_first"] - f.loc[paid, "created"]).dt.total_seconds() / 86400
    ir_to_clear = ((f["clear_first"] - f["ir_first"]).dt.total_seconds() / 86400).dropna()
    return {
        "items": int(len(f)),
        "flows": f["flow"].value_counts().to_dict(),
        "items_paid": int(paid.sum()),
        "create_to_payment_days_median": round(float(cycle.median()), 1),
        "create_to_payment_days_p90": round(float(cycle.quantile(0.9)), 1),
        "invoice_to_payment_days_median": round(float(ir_to_clear[ir_to_clear >= 0].median()), 1),
        "price_change_rate": round(float((f["n_price"] > 0).mean()), 4),
        "quantity_change_rate": round(float((f["n_qty"] > 0).mean()), 4),
        "payment_block_rate": round(float((f["n_block"] > 0).mean()), 4),
        "deleted_rate": round(float(f["deleted_first"].notna().mean()), 4),
    }


def automation(log: EventLog) -> pd.DataFrame:
    """Share of each activity executed by batch (system) users vs. people: where manual work sits."""
    e = log.events
    res = e["resource"].astype(object).where(e["resource"].notna(), "NONE").astype(str)
    is_batch = res.str.lower().str.startswith("batch")
    g = pd.DataFrame({"activity": e["activity"], "batch": is_batch, "manual": ~is_batch & ~res.isin(["NONE", "UNKNOWN"])})
    out = g.groupby("activity").agg(events=("batch", "size"), batch_share=("batch", "mean"), manual_events=("manual", "sum"))
    return out.sort_values("manual_events", ascending=False)


def vendor_hotspots(f: pd.DataFrame, min_items: int = 200, top: int = 10) -> pd.DataFrame:
    """Vendors whose items most often need price changes or payment blocks (root-cause view)."""
    if "Vendor" not in f.columns:
        return pd.DataFrame()
    g = f.groupby("Vendor").agg(items=("flow", "size"), price_change=("n_price", lambda s: (s > 0).mean()),
                                blocked=("n_block", lambda s: (s > 0).mean()))
    g = g[g["items"] >= min_items]
    g["rework_items"] = (g["items"] * g["price_change"]).round().astype(int)
    return g.sort_values("rework_items", ascending=False).head(top)
