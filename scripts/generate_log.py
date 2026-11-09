"""Generate a reproducible order-to-cash event log (case_id, activity, timestamp, resource + case attributes).

The simulation contains the problems a real O2C process mining project usually finds:
* credit holds that wait for a manual release, much longer in one region
* manual price approval for discounts above 15 %, with a slow approver queue
* price changes after approval that trigger re-approval (rework)
* order changes (quantity) that loop back to picking
* compliance deviations: shipping without approval, invoicing before shipment
* a share of cancelled orders
"""
from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
rng = random.Random(7)

REGIONS = ["DACH", "DACH", "DACH", "Benelux", "Nordics", "Southern Europe"]
SEGMENTS = ["Key Account", "Mid-Market", "Mid-Market", "SMB", "SMB", "SMB"]
CHANNELS = ["EDI", "Email", "Email", "Web Shop", "Sales Rep"]


def hours(lo: float, hi: float) -> timedelta:
    return timedelta(hours=rng.uniform(lo, hi))


def bizhours(h: float) -> timedelta:
    return timedelta(hours=rng.expovariate(1 / h))


def simulate_case(cid: str, start: datetime) -> tuple[list[dict], dict]:
    region, segment, channel = rng.choice(REGIONS), rng.choice(SEGMENTS), rng.choice(CHANNELS)
    value = round(rng.lognormvariate(8.2, 0.9), 2)  # ~3.6k median
    discount = max(0.0, rng.gauss(0.08, 0.07))
    attrs = {"case_id": cid, "region": region, "segment": segment, "channel": channel,
             "order_value": value, "discount": round(discount, 3)}
    t = start
    ev: list[dict] = []

    def add(act: str, res: str, dt: timedelta = timedelta(0)) -> None:
        nonlocal t
        t = t + dt
        ev.append({"case_id": cid, "activity": act, "timestamp": t.isoformat(timespec="minutes"), "resource": res})

    add("Create Sales Order", "EDI-Bot" if channel == "EDI" else rng.choice(["Order Desk A", "Order Desk B"]))
    if channel != "EDI":
        pass
    add("Check Credit", "Credit-Bot" if segment != "SMB" or rng.random() < 0.4 else "Credit Team", bizhours(0.5 if segment != "SMB" else 3))
    credit_risk = 0.22 if segment == "SMB" else 0.08
    if rng.random() < credit_risk:
        add("Credit Hold", "Credit-Bot", timedelta(minutes=5))
        wait = 52 if region == "Southern Europe" else 18
        add("Release Credit Hold", "Credit Team", bizhours(wait))
    skip_approval = rng.random() < 0.035  # maverick: ships without the required approval
    needs_approval = discount > 0.15
    if needs_approval and not skip_approval:
        add("Request Price Approval", "Sales Rep", hours(0.1, 1))
        add("Approve Price", rng.choice(["Sales Director", "Sales Director", "Head of Sales"]), bizhours(30 if value > 10000 else 16))
    if rng.random() < 0.06:
        add("Cancel Order", "Order Desk A", bizhours(20))
        return ev, attrs | {"outcome": "cancelled"}
    if needs_approval and not skip_approval and rng.random() < 0.18:
        add("Change Price", "Sales Rep", bizhours(10))
        if rng.random() > 0.15:  # 15 % of price changes slip through without re-approval
            add("Request Price Approval", "Sales Rep", hours(0.1, 1))
            add("Approve Price", "Sales Director", bizhours(20))
    add("Pick Goods", rng.choice(["Warehouse 1", "Warehouse 2"]), bizhours(14))
    if rng.random() < 0.09:
        add("Change Quantity", "Order Desk B", bizhours(4))
        add("Pick Goods", rng.choice(["Warehouse 1", "Warehouse 2"]), bizhours(8))
    add("Pack Goods", "Warehouse 1", bizhours(3))
    early_invoice = rng.random() < 0.04
    if early_invoice:
        add("Create Invoice", "Billing-Bot", bizhours(1))
        add("Ship Goods", "Carrier", bizhours(10))
    else:
        add("Ship Goods", "Carrier", bizhours(10))
        auto = rng.random() < 0.7  # 30 % of orders still go through the manual billing queue
        add("Create Invoice", "Billing-Bot" if auto else "Billing Team", bizhours(1.5 if auto else 30))
    if rng.random() < 0.05:
        add("Send Dunning Letter", "Billing-Bot", timedelta(days=rng.uniform(31, 40)))
        add("Receive Payment", "Bank", timedelta(days=rng.uniform(3, 20)))
    else:
        add("Receive Payment", "Bank", timedelta(days=rng.uniform(5, 30) if segment != "Key Account" else rng.uniform(25, 45)))
    return ev, attrs | {"outcome": "paid"}


def main(n_cases: int = 5000) -> None:
    data = ROOT / "data"
    data.mkdir(exist_ok=True)
    events, cases = [], []
    t0 = datetime(2026, 1, 5, 8)
    for i in range(n_cases):
        ev, attrs = simulate_case(f"SO-{100000 + i}", t0 + timedelta(minutes=i * 47))
        events += ev
        cases.append(attrs)
    with open(data / "events.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["case_id", "activity", "timestamp", "resource"])
        w.writeheader()
        w.writerows(events)
    with open(data / "cases.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(cases[0]))
        w.writeheader()
        w.writerows(cases)
    print(f"cases={len(cases)} events={len(events)}")


if __name__ == "__main__":
    main()
