"""Performance analysis: throughput, bottlenecks, rework and root-cause breakdowns."""
from __future__ import annotations

import pandas as pd

from .discovery import dfg
from .eventlog import EventLog

# Waits between operational steps; customer payment terms are not a process bottleneck.
EXCLUDE_FROM_BOTTLENECKS = {("Create Invoice", "Receive Payment"), ("Send Dunning Letter", "Receive Payment"),
                            ("Create Invoice", "Send Dunning Letter"), ("Ship Goods", "Receive Payment")}


def throughput(log: EventLog, until: str = "Ship Goods") -> pd.DataFrame:
    """Order-to-shipment lead time per case (cases that reached `until`)."""
    e = log.events
    first = e.groupby("case_id")["timestamp"].min()
    reached = e[e["activity"] == until].groupby("case_id")["timestamp"].min()
    lt = ((reached - first.loc[reached.index]).dt.total_seconds() / 3600).rename("lead_time_h")
    return lt.reset_index().merge(log.cases, on="case_id", how="left")


def bottlenecks(log: EventLog, top: int = 8) -> pd.DataFrame:
    """Edges ranked by total waiting hours (= frequency x wait): where the time is actually lost."""
    d = dfg(log)
    d = d[[(a, b) not in EXCLUDE_FROM_BOTTLENECKS for a, b in zip(d.activity, d.next_activity)]]
    d = d.sort_values("total_wait_h", ascending=False).head(top).copy()
    d["share_of_wait"] = d["total_wait_h"] / d["total_wait_h"].sum()
    d["edge"] = d["activity"] + " → " + d["next_activity"]
    return d.reset_index(drop=True)


def rework(log: EventLog) -> pd.DataFrame:
    """Activities that occur more than once in the same case."""
    c = log.events.groupby(["case_id", "activity"]).size()
    rep = c[c > 1].reset_index(name="times")
    out = rep.groupby("activity").agg(cases=("case_id", "nunique")).reset_index()
    out["share_of_cases"] = out["cases"] / log.n_cases
    return out.sort_values("cases", ascending=False).reset_index(drop=True)


def breakdown(df: pd.DataFrame, value: str, by: str) -> pd.DataFrame:
    g = df.groupby(by)[value]
    return pd.DataFrame({"cases": g.size(), "median": g.median(), "p90": g.quantile(0.9)}).sort_values("median", ascending=False)


def edge_breakdown(log: EventLog, src: str, dst: str, by: str) -> pd.DataFrame:
    """Waiting time on one edge split by a case attribute (root-cause view)."""
    e = log.events[(log.events["activity"] == src) & (log.events["next_activity"] == dst)]
    e = e.merge(log.cases[["case_id", by]], on="case_id", how="left")
    return breakdown(e, "wait_h", by)
