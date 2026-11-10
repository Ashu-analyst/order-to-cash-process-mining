"""Purchase-to-pay analysis of the real BPI Challenge 2019 event log.

Data: van Dongen, B.F. (2019) BPI Challenge 2019. 4TU.ResearchData. https://doi.org/10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1
(purchase order handling at a multinational coatings and paints company, SAP, 2018; CC BY 4.0).

Usage:
    python scripts/analyse_bpi2019.py path/to/BPI_Challenge_2019.xes

The raw file (728 MB) is not committed. The first run caches a compact Parquet copy in data/bpi2019/.
Outputs go to docs/bpi2019/.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from o2cmining import discovery, p2p, performance  # noqa: E402
from o2cmining.eventlog import EventLog  # noqa: E402
from o2cmining.xes import read_xes  # noqa: E402

CASE_KEYS = ["Item Category", "Vendor", "Spend area text", "Sub spend area text", "Company", "Item Type",
             "Document Type", "GR-Based Inv. Verif.", "Goods Receipt"]
EVENT_KEYS = ["Cumulative net worth (EUR)", "User"]


def load(xes_path: str) -> EventLog:
    cache = ROOT / "data" / "bpi2019"
    cache.mkdir(parents=True, exist_ok=True)
    ev_p, cs_p = cache / "events.parquet", cache / "cases.parquet"
    if ev_p.exists() and cs_p.exists():
        ev, cs = pd.read_parquet(ev_p), pd.read_parquet(cs_p)
    else:
        t = time.time()
        ev, cs = read_xes(xes_path, EVENT_KEYS, CASE_KEYS)
        ev.to_parquet(ev_p, index=False)
        cs.to_parquet(cs_p, index=False)
        print(f"parsed XES in {time.time() - t:.0f}s")
    # data quality: drop events with impossible timestamps (the log has a few from 1948-2017)
    before = len(ev)
    ev = ev[(ev["timestamp"] >= "2017-01-01") & (ev["timestamp"] < "2020-01-01")]
    print(f"events {before:,} -> {len(ev):,} after removing out-of-range timestamps")
    return EventLog.from_frames(ev, cs)


def main(xes_path: str) -> dict:
    log = load(xes_path)
    out = ROOT / "docs" / "bpi2019"
    out.mkdir(parents=True, exist_ok=True)

    f = p2p.case_facts(log)
    ctrl = p2p.controls(f)
    k = p2p.kpis(f)
    auto = p2p.automation(log)
    hot = p2p.vendor_hotspots(f)
    var = discovery.variants(log)
    bn = performance.bottlenecks(log, top=10)
    rw = performance.rework(log)

    res = {
        "source": "BPI Challenge 2019, 4TU.ResearchData, doi:10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1",
        "log": {"items": log.n_cases, "events": int(len(log.events)), "activities": int(log.events["activity"].nunique()),
                "variants": int(len(var)), "users": int(log.events["resource"].nunique())},
        "variants": {"top10_share": round(float(var.head(10)["share"].sum()), 3),
                     "variants_for_80pct": int((var["cum_share"] >= 0.8).idxmax()) + 1},
        "kpis": k,
        "controls": ctrl.to_dict("records"),
        "bottlenecks": [{"edge": r.edge, "items": int(r["count"]), "median_wait_days": round(float(r.median_wait_h) / 24, 1),
                         "total_wait_years": round(float(r.total_wait_h) / 24 / 365, 1)} for _, r in bn.iterrows()],
        "rework_top": rw.head(8).to_dict("records"),
        "manual_work_top": [{"activity": a, "events": int(r.events), "batch_share": round(float(r.batch_share), 3),
                             "manual_events": int(r.manual_events)} for a, r in auto.head(8).iterrows()],
        "vendor_hotspots": [{"vendor": v, "items": int(r["items"]), "price_change_share": round(float(r.price_change), 3),
                             "payment_block_share": round(float(r.blocked), 3)} for v, r in hot.iterrows()],
    }
    (out / "results.json").write_text(json.dumps(res, indent=2, default=str))
    ctrl.to_csv(out / "controls.csv", index=False)
    (out / "process_map.md").write_text(
        "# BPI 2019: discovered process map (edges used by ≥ 5 % of items)\n\n```mermaid\n"
        + discovery.mermaid(log, 0.05) + "\n```\n", encoding="utf-8")
    charts(res, f, out)
    print(json.dumps({k2: res[k2] for k2 in ("log", "variants", "kpis")}, indent=1, default=str))
    print(ctrl.to_string())
    print(json.dumps(res["bottlenecks"][:5], indent=1))
    print(json.dumps(res["manual_work_top"][:5], indent=1))
    return res


def charts(res: dict, f: pd.DataFrame, out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    blue, red = "#1f6feb", "#d1242f"
    c = res["controls"]
    fig, ax = plt.subplots(figsize=(8.5, 3.4))
    names = [r["rule"] for r in c][::-1]
    vals = [100 * r["compliant"] for r in c][::-1]
    ax.barh(names, vals, color=[blue if v >= 99 else red for v in vals])
    for i, r in enumerate(c[::-1]):
        ax.text(min(100 * r["compliant"], 99), i, f"  {r['violations']:,} of {r['checked']:,}", va="center", fontsize=8)
    ax.set_xlim(min(vals) - 5, 108)
    ax.set_xlabel("Items compliant (%)")
    ax.set_title("BPI 2019 purchase-to-pay controls (real SAP log)")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out / "controls.png", dpi=150)
    plt.close(fig)

    m = res["manual_work_top"][:7][::-1]
    fig, ax = plt.subplots(figsize=(8.5, 3.4))
    ax.barh([x["activity"] for x in m], [x["manual_events"] / 1000 for x in m], color=blue)
    for i, x in enumerate(m):
        ax.text(x["manual_events"] / 1000, i, f"  {x['batch_share']:.0%} automated", va="center", fontsize=8)
    ax.set_xlabel("Manual executions (thousands)")
    ax.set_title("Where people still do the work")
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_xlim(0, max(x["manual_events"] for x in m) / 1000 * 1.35)
    fig.tight_layout()
    fig.savefig(out / "manual_work.png", dpi=150)
    plt.close(fig)

    paid = f.dropna(subset=["created", "clear_first"])
    days = (paid["clear_first"] - paid["created"]).dt.total_seconds() / 86400
    fig, ax = plt.subplots(figsize=(8, 3.2))
    for flow, color in [("3-way after GR", blue), ("3-way before GR", "#8250df"), ("2-way", "#bf8700")]:
        d = days[paid["flow"] == flow]
        if len(d):
            ax.hist(d.clip(0, 200), bins=80, histtype="step", lw=1.5, color=color, label=f"{flow} (median {d.median():.0f} d)")
    ax.set_xlabel("Days from PO item to payment (clipped at 200)")
    ax.set_ylabel("Items")
    ax.set_title("Purchase-to-pay cycle time by flow")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out / "cycle_time.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    if len(sys.argv) < 2 and not (ROOT / "data" / "bpi2019" / "events.parquet").exists():
        sys.exit(__doc__)
    main(sys.argv[1] if len(sys.argv) > 1 else "")
