"""Process discovery: directly-follows graph, variants and a Mermaid process map."""
from __future__ import annotations

import re

import pandas as pd

from .eventlog import EventLog


def dfg(log: EventLog) -> pd.DataFrame:
    """Directly-follows graph with frequency and median/mean waiting time per edge."""
    e = log.events.dropna(subset=["next_activity"])
    out = (e.groupby(["activity", "next_activity"])
             .agg(count=("case_id", "size"), median_wait_h=("wait_h", "median"), mean_wait_h=("wait_h", "mean"),
                  total_wait_h=("wait_h", "sum"))
             .reset_index().sort_values("count", ascending=False))
    return out.reset_index(drop=True)


def start_end(log: EventLog) -> tuple[pd.Series, pd.Series]:
    g = log.events.groupby("case_id")["activity"]
    return g.first().value_counts(), g.last().value_counts()


def variants(log: EventLog, top: int | None = None) -> pd.DataFrame:
    tr = log.traces()
    v = tr.value_counts().rename_axis("trace").reset_index(name="cases")
    v["share"] = v["cases"] / v["cases"].sum()
    v["cum_share"] = v["share"].cumsum()
    v["length"] = v["trace"].map(len)
    v["variant"] = v["trace"].map(" → ".join)
    v = v.drop(columns="trace")
    return v.head(top) if top else v


def _node(a: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", a)


def mermaid(log: EventLog, min_share: float = 0.02) -> str:
    """Process map as a Mermaid flowchart. Edges used by fewer than `min_share` of cases are hidden
    (the usual 'path slider' in process mining tools)."""
    d = dfg(log)
    n = log.n_cases
    d = d[d["count"] >= min_share * n]
    starts, ends = start_end(log)
    acts = sorted(set(d["activity"]) | set(d["next_activity"]))
    lines = ["flowchart TD", "    START((start))", "    END((end))"]
    freq = log.events["activity"].value_counts()
    for a in acts:
        lines.append(f'    {_node(a)}["{a}<br/>{freq.get(a, 0):,}"]')
    for a, c in starts.items():
        if c >= min_share * n:
            lines.append(f"    START -->|{c:,}| {_node(a)}")
    for _, r in d.iterrows():
        lines.append(f"    {_node(r.activity)} -->|{int(r['count']):,} · {r.median_wait_h:.0f}h| {_node(r.next_activity)}")
    for a, c in ends.items():
        if c >= min_share * n:
            lines.append(f"    {_node(a)} -->|{c:,}| END")
    return "\n".join(lines)
