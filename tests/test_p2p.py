import gzip
import shutil

import pandas as pd

from o2cmining import p2p
from o2cmining.eventlog import EventLog
from o2cmining.xes import read_xes

from fixtures_p2p import write


def _log(tmp_path, gz=False):
    p = tmp_path / "bpi_sample.xes"
    write(p)
    if gz:
        with open(p, "rb") as a, gzip.open(str(p) + ".gz", "wb") as b:
            shutil.copyfileobj(a, b)
        p = str(p) + ".gz"
    ev, cs = read_xes(p)
    return EventLog.from_frames(ev, cs)


def test_xes_reader_reads_traces_and_attributes(tmp_path):
    log = _log(tmp_path, gz=True)
    assert log.n_cases == 6 and len(log.events) == 26
    assert {"Item Category", "Vendor"} <= set(log.cases.columns)
    assert log.events["timestamp"].dt.tz is None
    assert "Cumulative net worth (EUR)" in log.events.columns


def test_controls_find_planted_violations(tmp_path):
    f = p2p.case_facts(_log(tmp_path))
    c = p2p.controls(f).set_index("rule")
    assert c.loc["invoice_after_goods_receipt", "violations"] == 2        # cases 2 and 6
    assert c.loc["paid_only_after_goods_receipt", "violations"] == 1      # case 3
    assert c.loc["not_paid_more_often_than_invoiced", "violations"] == 1  # case 4
    assert c.loc["po_before_invoice", "violations"] == 1                  # case 6
    assert c.loc["consignment_not_invoiced", "violations"] == 0


def test_kpis_and_automation(tmp_path):
    log = _log(tmp_path)
    k = p2p.kpis(p2p.case_facts(log))
    assert k["items"] == 6 and k["flows"]["3-way after GR"] == 3
    assert k["payment_block_rate"] == round(1 / 6, 4)
    a = p2p.automation(log)
    assert a.loc["Clear Invoice", "batch_share"] == 1.0
    assert a.loc["Record Invoice Receipt", "batch_share"] == 0.0
