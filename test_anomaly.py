"""Tests the anomaly detector with SYNTHETIC data and planted anomalies (code correctness only).

Run:  python test_anomaly.py
"""
import numpy as np

from ml_anomaly import AnomalyDetector
from test_ml import synthetic_city


def main():
    data = {"Indore": synthetic_city(1), "Bhopal": synthetic_city(2)}
    for df in data.values():   # make the synthetic monsoon as wet as a real MP monsoon (normals well above 25 mm)
        df["rain_mm"] = df["rain_mm"] * 8
    ind = data["Indore"]

    # plant 1: July 2010 almost no rain and very hot  -> should be a "Hot and dry combination"
    m = (ind["date"].dt.year == 2010) & (ind["date"].dt.month == 7)
    ind.loc[m, "rain_mm"] = 0.0
    ind.loc[m, "tmax_c"] = ind.loc[m, "tmax_c"] + 8
    # plant 2: one 600 mm day in August 2022 -> flagged but marked as a single-day, weak-evidence case
    d = ind.index[(ind["date"] == "2022-08-10")][0]
    ind.loc[d, "rain_mm"] = 600.0

    det = AnomalyDetector().fit(data)
    rep = det.city_report("Indore", recent_months=60, top_n=200)
    flagged = {r["month"]: r for r in rep["top_historic"]}

    assert "2010-07" in flagged, "planted hot+dry month was not flagged"
    assert flagged["2010-07"]["kind"] == "Hot and dry combination", flagged["2010-07"]["kind"]
    assert any(t["feature"] == "rain_z" for t in flagged["2010-07"]["triggers"])
    assert flagged["2010-07"]["stat_flag"] and flagged["2010-07"]["meaning"].startswith("An unusual month")

    assert "2022-08" in flagged, "planted single big day not flagged"
    assert flagged["2022-08"]["evidence"].startswith("weak"), flagged["2022-08"]["evidence"]
    assert any("one very large daily value" in n for n in flagged["2022-08"]["notes"])

    # the detector must not flag everything: roughly 5% of baseline months
    t = det.table
    base = t[(t["month"].dt.year >= 1991) & (t["month"].dt.year <= 2020)]
    share = base["if_flag"].mean()
    assert 0.03 <= share <= 0.08, share
    # dry-season months are not scored for rain
    dec = t[t["cal_month"] == 12]
    assert (dec["rain_z"] == 0).all() and not dec["scored_for_rain"].any()
    # every recent record has the fields the website needs
    for r in rep["recent"]:   # a month that nothing flags must not be called unusual
        if not r["flagged"] and not r["stat_flag"] and not r["triggers"]:
            assert r["kind"] == "Within normal range" and r["evidence"] == "not flagged", r
    for r in rep["recent"]:
        assert {"month", "kind", "anomaly_score", "flagged", "evidence", "notes", "triggers"} <= set(r)
    print(f"baseline flagged share {share:.1%}")
    print("ALL ANOMALY TESTS PASSED")


if __name__ == "__main__":
    main()
