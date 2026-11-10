"""Streaming XES reader.

Real logs are large (BPI Challenge 2019 is 728 MB / 1.6 M events), so the file is parsed with
iterparse and each trace is cleared from memory as soon as it is read. Output is two pandas
frames in the shape EventLog expects: events (case_id, activity, timestamp, resource, + event
attributes) and cases (case_id + trace attributes).
"""
from __future__ import annotations

import gzip
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET

import pandas as pd

TYPED = {"string", "date", "int", "float", "boolean", "id"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _value(el: ET.Element):
    t, v = _local(el.tag), el.get("value")
    if t == "int":
        return int(v)
    if t == "float":
        return float(v)
    if t == "boolean":
        return v.lower() == "true"
    return v


def read_xes(path: str | Path, event_keys: Iterable[str] | None = None,
             case_keys: Iterable[str] | None = None, limit_cases: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parse an XES (or .xes.gz) file into (events, cases).

    event_keys / case_keys restrict which attributes are kept (saves memory on wide logs).
    """
    ek = set(event_keys) if event_keys else None
    ck = set(case_keys) if case_keys else None
    opener = gzip.open if str(path).endswith(".gz") else open
    events: list[dict] = []
    cases: list[dict] = []
    with opener(path, "rb") as f:
        ctx = ET.iterparse(f, events=("start", "end"))
        depth_trace = False
        trace_attrs: dict = {}
        trace_events: list[dict] = []
        cur_event: dict | None = None
        for kind, el in ctx:
            tag = _local(el.tag)
            if kind == "start":
                if tag == "trace":
                    depth_trace, trace_attrs, trace_events = True, {}, []
                elif tag == "event" and depth_trace:
                    cur_event = {}
                continue
            # end
            if tag in TYPED and depth_trace:
                key = el.get("key")
                if cur_event is not None:
                    if ek is None or key in ek or key in ("concept:name", "time:timestamp", "org:resource"):
                        cur_event[key] = _value(el)
                elif ck is None or key in ck or key == "concept:name":
                    trace_attrs[key] = _value(el)
            elif tag == "event" and cur_event is not None:
                trace_events.append(cur_event)
                cur_event = None
                el.clear()
            elif tag == "trace":
                cid = trace_attrs.get("concept:name")
                for e in trace_events:
                    e["case_id"] = cid
                events.extend(trace_events)
                cases.append({"case_id": cid, **{k: v for k, v in trace_attrs.items() if k != "concept:name"}})
                depth_trace = False
                el.clear()
                if limit_cases and len(cases) >= limit_cases:
                    break
    # build column-wise to keep memory low on million-event logs
    keys = sorted({k for e in events[:5000] for k in e} | {"case_id"})
    cols = {k: [e.get(k) for e in events] for k in keys}
    del events
    ev = pd.DataFrame(cols).rename(columns={"concept:name": "activity", "time:timestamp": "timestamp",
                                            "org:resource": "resource"})
    for c in ("activity", "resource", "User"):
        if c in ev.columns:  # intern repeated labels: one string object per distinct value
            ev[c] = ev[c].map(lambda v, _seen={}: _seen.setdefault(v, v))
    ev["timestamp"] = pd.to_datetime(ev["timestamp"], utc=True, format="ISO8601").dt.tz_localize(None)
    cs = pd.DataFrame(cases)
    cs.columns = [c.replace("(case)_", "").removeprefix("case ") for c in cs.columns]
    return ev, cs
