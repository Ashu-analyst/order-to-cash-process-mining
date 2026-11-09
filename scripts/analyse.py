"""Run the full analysis and write docs/results.json, docs/process_map.md and charts."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from o2cmining import automation, conformance, discovery, performance  # noqa: E402
from o2cmining.eventlog import EventLog  # noqa: E402


def main() -> dict:
    log = EventLog.from_csv(ROOT / "data" / "events.csv", ROOT / "data" / "cases.csv")
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)

    var = discovery.variants(log)
    lt = performance.throughput(log)
    bn = performance.bottlenecks(log)
    rw = performance.rework(log)
    conf, viol = conformance.check(log)
    cand = automation.candidates(log)
    hold_by_region = performance.edge_breakdown(log, "Credit Hold", "Release Credit Hold", "region")
    lt_by_segment = performance.breakdown(lt, "lead_time_h", "segment")

    res = {
        "log": {"cases": log.n_cases, "events": int(len(log.events)), "activities": int(log.events["activity"].nunique()),
                "variants": int(len(var))},
        "variants": {"top5_share": round(float(var.head(5)["share"].sum()), 3),
                     "cases_covered_by_top10": round(float(var.head(10)["share"].sum()), 3),
                     "happy_path": var.iloc[0]["variant"], "happy_path_share": round(float(var.iloc[0]["share"]), 3)},
        "lead_time_order_to_ship_h": {"median": round(float(lt["lead_time_h"].median()), 1),
                                      "p90": round(float(lt["lead_time_h"].quantile(0.9)), 1)},
        "lead_time_by_segment_median_h": {k: round(float(v), 1) for k, v in lt_by_segment["median"].items()},
        "bottlenecks": [{"edge": r.edge, "cases": int(r["count"]), "median_wait_h": round(float(r.median_wait_h), 1),
                         "total_wait_h": round(float(r.total_wait_h)), "share_of_wait": round(float(r.share_of_wait), 3)}
                        for _, r in bn.iterrows()],
        "credit_hold_release_by_region_median_h": {k: round(float(v), 1) for k, v in hold_by_region["median"].items()},
        "rework": [{"activity": r.activity, "cases": int(r.cases), "share": round(float(r.share_of_cases), 3)} for _, r in rw.iterrows()],
        "conformance": [{"rule": r.rule, "checked": int(r.cases_checked), "violations": int(r.violations),
                         "fitness": round(float(r.fitness), 3), "severity": r.severity} for _, r in conf.iterrows()],
        "touchless_rate": round(automation.touchless_rate(log), 3),
        "automation_candidates": [{"candidate": r.candidate, "cases": int(r.cases), "share": round(float(r.share_of_cases), 3),
                                   "wait_days_removed": round(float(r.wait_days_removed), 1)} for _, r in cand.iterrows()],
    }
    (docs / "results.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
    viol.to_csv(docs / "conformance_violations.csv", index=False)
    var.head(15).to_csv(docs / "top_variants.csv", index=False)
    (docs / "process_map.md").write_text(
        "# Discovered process map (edges used by ≥ 2 % of cases; label = cases · median wait)\n\n```mermaid\n"
        + discovery.mermaid(log, 0.02) + "\n```\n", encoding="utf-8")
    charts(res, lt, var, docs)
    print(json.dumps({k: res[k] for k in ("log", "variants", "lead_time_order_to_ship_h", "touchless_rate")}, indent=2))
    print(json.dumps(res["bottlenecks"][:4], indent=1))
    print(json.dumps(res["conformance"], indent=1))
    print(json.dumps(res["automation_candidates"], indent=1))
    print(res["credit_hold_release_by_region_median_h"])
    return res


def charts(res: dict, lt, var, docs: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    blue, grey = "#1f6feb", "#9aa5b1"

    bn = res["bottlenecks"][:6][::-1]
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.barh([b["edge"] for b in bn], [b["total_wait_h"] / 24 for b in bn], color=blue)
    for i, b in enumerate(bn):
        ax.text(b["total_wait_h"] / 24, i, f"  {b['cases']:,} cases · median {b['median_wait_h']:.0f} h", va="center", fontsize=8)
    ax.set_xlabel("Total waiting time (days, all cases)")
    ax.set_title("Where order-to-ship time is lost")
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_xlim(0, max(b["total_wait_h"] for b in bn) / 24 * 1.6)
    fig.tight_layout()
    fig.savefig(docs / "bottlenecks.png", dpi=150)
    plt.close(fig)

    conf = res["conformance"]
    fig, ax = plt.subplots(figsize=(8, 3.2))
    ax.barh([c["rule"] for c in conf][::-1], [100 * c["fitness"] for c in conf][::-1],
            color=[blue if c["fitness"] >= 0.98 else "#d1242f" for c in conf][::-1])
    for i, c in enumerate(conf[::-1]):
        ax.text(100 * c["fitness"], i, f"  {c['violations']} violations", va="center", fontsize=8)
    ax.set_xlim(70, 104)
    ax.set_xlabel("Cases compliant (%)")
    ax.set_title("Conformance against the target process")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(docs / "conformance.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 3.4))
    ax.plot(range(1, len(var) + 1), var["cum_share"] * 100, color=blue)
    ax.axhline(80, color=grey, ls="--", lw=1)
    k80 = int((var["cum_share"] >= 0.8).idxmax()) + 1
    ax.annotate(f"{k80} variants cover 80 % of cases", (k80, 80), xytext=(k80 + 8, 60), arrowprops={"arrowstyle": "->"})
    ax.set_xlabel("Variants (most frequent first)")
    ax.set_ylabel("Cases covered (%)")
    ax.set_title(f"{len(var)} process variants in {int(var['cases'].sum()):,} orders")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(docs / "variants.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
