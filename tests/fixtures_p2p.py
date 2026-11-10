"""Writes a small XES file in the BPI Challenge 2019 schema, with known control violations."""
from __future__ import annotations

from datetime import datetime, timedelta
from xml.sax.saxutils import quoteattr

CASES = {
    # case id: (item category, vendor, [(activity, day offset, user)])
    "4500000001_00010": ("3-way match, invoice after GR", "vendorA", [
        ("Create Purchase Order Item", 0, "user_001"), ("Record Goods Receipt", 5, "user_002"),
        ("Vendor creates invoice", 6, "NONE"), ("Record Invoice Receipt", 7, "user_003"), ("Clear Invoice", 30, "batch_01")]),
    "4500000002_00010": ("3-way match, invoice after GR", "vendorA", [   # invoice before GR -> violation
        ("Create Purchase Order Item", 0, "user_001"), ("Record Invoice Receipt", 2, "user_003"),
        ("Record Goods Receipt", 4, "user_002"), ("Clear Invoice", 25, "batch_01")]),
    "4500000003_00010": ("3-way match, invoice before GR", "vendorB", [  # paid before GR -> violation
        ("Create Purchase Order Item", 0, "user_004"), ("Record Invoice Receipt", 3, "user_003"),
        ("Clear Invoice", 10, "batch_01"), ("Record Goods Receipt", 12, "user_002")]),
    "4500000004_00010": ("2-way match", "vendorB", [                       # cleared twice, invoiced once
        ("Create Purchase Order Item", 0, "user_004"), ("Change Price", 1, "user_004"),
        ("Record Invoice Receipt", 3, "user_003"), ("Clear Invoice", 20, "batch_01"), ("Clear Invoice", 21, "batch_01")]),
    "4500000005_00010": ("Consignment", "vendorC", [
        ("Create Purchase Order Item", 0, "user_005"), ("Record Goods Receipt", 2, "user_002")]),
    "4500000006_00010": ("3-way match, invoice after GR", "vendorC", [   # invoice before PO -> violation
        ("Record Invoice Receipt", 0, "user_003"), ("Create Purchase Order Item", 1, "user_005"),
        ("Record Goods Receipt", 3, "user_002"), ("Set Payment Block", 4, "user_006"),
        ("Remove Payment Block", 9, "user_006"), ("Clear Invoice", 40, "batch_02")]),
}


def write(path) -> None:
    t0 = datetime(2018, 1, 2, 9, 0)
    lines = ['<?xml version="1.0" encoding="UTF-8" ?>', '<log xes.version="1849-2016" xmlns="http://www.xes-standard.org/">']
    for cid, (cat, vendor, evs) in CASES.items():
        lines.append("<trace>")
        for k, v in [("concept:name", cid), ("Item Category", cat), ("Vendor", vendor), ("Spend area text", "Packaging"),
                     ("Company", "companyID_0000"), ("Item Type", "Standard"), ("Document Type", "Standard PO")]:
            lines.append(f"<string key={quoteattr(k)} value={quoteattr(v)}/>")
        lines.append('<boolean key="GR-Based Inv. Verif." value="false"/>')
        for act, d, user in evs:
            ts = (t0 + timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%S.000+01:00")
            lines += ["<event>", f"<string key=\"concept:name\" value={quoteattr(act)}/>",
                      f'<string key="org:resource" value="{user}"/>', f'<string key="User" value="{user}"/>',
                      '<float key="Cumulative net worth (EUR)" value="250.0"/>',
                      f'<date key="time:timestamp" value="{ts}"/>', "</event>"]
        lines.append("</trace>")
    lines.append("</log>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
