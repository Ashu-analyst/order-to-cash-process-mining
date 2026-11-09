"""Event log loading and validation.

Uses the standard process mining columns (case_id, activity, timestamp, resource), the same shape
pm4py, Celonis or Disco expect, so the log can be exported from any ERP/CRM and analysed here.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

REQUIRED = ("case_id", "activity", "timestamp")


@dataclass
class EventLog:
    events: pd.DataFrame
    cases: pd.DataFrame

    @classmethod
    def from_csv(cls, events_path: str | Path, cases_path: str | Path | None = None) -> "EventLog":
        ev = pd.read_csv(events_path)
        cs = pd.read_csv(cases_path) if cases_path else pd.DataFrame({"case_id": ev["case_id"].unique()})
        return cls.from_frames(ev, cs)

    @classmethod
    def from_frames(cls, events: pd.DataFrame, cases: pd.DataFrame | None = None) -> "EventLog":
        missing = [c for c in REQUIRED if c not in events.columns]
        if missing:
            raise ValueError(f"event log is missing columns: {missing}")
        ev = events.copy()
        ev["timestamp"] = pd.to_datetime(ev["timestamp"])
        ev = ev.dropna(subset=list(REQUIRED))
        # stable sort keeps the recorded order for events with identical timestamps
        ev = ev.sort_values(["case_id", "timestamp"], kind="stable").reset_index(drop=True)
        ev["next_activity"] = ev.groupby("case_id")["activity"].shift(-1)
        ev["next_timestamp"] = ev.groupby("case_id")["timestamp"].shift(-1)
        ev["wait_h"] = (ev["next_timestamp"] - ev["timestamp"]).dt.total_seconds() / 3600
        cs = cases.copy() if cases is not None else pd.DataFrame({"case_id": ev["case_id"].unique()})
        return cls(ev, cs)

    @property
    def n_cases(self) -> int:
        return int(self.events["case_id"].nunique())

    def traces(self) -> pd.Series:
        """case_id -> tuple of activities in order."""
        return self.events.groupby("case_id", sort=False)["activity"].agg(tuple)

    def case_table(self) -> pd.DataFrame:
        g = self.events.groupby("case_id")
        t = pd.DataFrame({
            "start": g["timestamp"].min(),
            "end": g["timestamp"].max(),
            "n_events": g.size(),
            "variant": g["activity"].agg(" → ".join),
        })
        t["throughput_days"] = (t["end"] - t["start"]).dt.total_seconds() / 86400
        return t.reset_index().merge(self.cases, on="case_id", how="left")
