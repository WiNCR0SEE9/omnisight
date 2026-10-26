"""Tests the prediction code and the backend end to end with SYNTHETIC data (code correctness only).

Run:  python test_server.py
"""
import http.client
import json
import os
import tempfile
import threading
from datetime import date

import joblib
import pandas as pd

import ml_train
import server
from test_ml import synthetic_city


def make_workspace():
    tmp = tempfile.mkdtemp()
    data, models = os.path.join(tmp, "data"), os.path.join(tmp, "models")
    os.makedirs(data)
    for i, city in enumerate(server.CITIES):
        df = synthetic_city(seed=i)
        # Indore & friends stop mid-September (a forecast origin in season); Bhopal runs to December (off season)
        df = df[df["date"] <= ("2025-12-31" if city == "Bhopal" else "2025-09-14")]
        df.insert(0, "city", city)
        df.to_csv(os.path.join(data, f"{city.lower()}_daily.csv"), index=False)
    import history  # yearly scores for the validation section
    hist = pd.concat([history.history_for_city(pd.read_csv(os.path.join(data, f"{c.lower()}_daily.csv"),
                      parse_dates=["date"])) for c in server.CITIES if c != "Bhopal"], ignore_index=True)
    hist.to_csv(os.path.join(data, "history_scores.csv"), index=False)
    full = ml_train.candidates  # keep the test fast: logistic regression only
    ml_train.candidates = lambda: {"Logistic regression": full()["Logistic regression"]}
    ml_train.main(data, models)
    ml_train.candidates = full
    return data, models


def get(port, path, method="GET"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    c.request(method, path)
    r = c.getresponse()
    body = r.read()
    try:
        return r.status, json.loads(body)
    except ValueError:
        return r.status, body


def main():
    data, models = make_workspace()
    app = server.App(data, models)
    httpd = server.serve(app, "127.0.0.1", 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    s, h = get(port, "/api/health")
    assert s == 200 and h["status"] == "ok" and "Indore" in h["cities"], h

    s, p = get(port, "/api/city/Indore/prediction")
    assert s == 200 and p["status"] == "ok", p
    assert 0 <= p["score"] <= 1 and p["target_month"] == "September 2025" and p["is_scenario"] is False
    assert p["explanation"] and p["skill_note"] and p["limitations"]
    assert p["as_of"] == "2025-08-31", p["as_of"]

    s, q = get(port, "/api/city/indore/prediction?rain_factor=0.3&temp_add=3")
    assert s == 200 and q["is_scenario"] and q["features"]["rain_3m_z"] < p["features"]["rain_3m_z"], q
    assert q["features"]["tmax_30d_z"] > p["features"]["tmax_30d_z"]
    s, same = get(port, "/api/city/Indore/prediction?rain_factor=1&temp_add=0")
    assert same["score"] == p["score"] and not same["is_scenario"]

    s, b = get(port, "/api/city/Bhopal/prediction")
    assert s == 200 and b["status"] == "out_of_season", b

    s, r = get(port, "/api/city/Indore/risk")
    assert s == 200 and 0 <= r["score"] <= 100 and r["level"] in ("Low", "Moderate", "High", "Very high")
    s, r2 = get(port, "/api/city/Indore/risk?rain_factor=0.2")
    assert r2["score"] >= r["score"] and "SCENARIO" in r2["kind"]

    assert r["rain_3m_normal_mm"] > 0 and r["rain_3m_pct"] is not None
    assert abs(r2["rain_3m_mm"] - 0.2 * r["rain_3m_mm"]) < 0.2, (r2["rain_3m_mm"], r["rain_3m_mm"])
    s, bad = get(port, "/api/city/Bhopal/risk")        # data ends in December: SPI cannot be fitted
    assert s == 422 and "not available" in bad["error"], bad
    s, o = get(port, "/api/overview")
    assert s == 200 and len(o["cities"]) == 5 and o["model_skill"]
    assert [c["status"] for c in o["cities"] if c["city"] == "Bhopal"] == ["unavailable"]
    assert all("score" in c for c in o["cities"] if c["city"] != "Bhopal")
    s, hist = get(port, "/api/city/Indore/history")
    assert s == 200 and len(hist["monthly"]) == 12 and len(hist["recent_days"]) == 45
    s, an = get(port, "/api/city/Indore/anomalies")
    assert s == 200 and len(an["recent"]) == 24 and an["method"] and "top_historic" in an, an
    assert get(port, "/api/city/Atlantis/anomalies")[0] == 404
    s, cmp_ = get(port, "/api/city/Indore/compare?rain_factor=0.5&temp_add=2")
    assert s == 200 and cmp_["delta"]["risk_score"] >= 0 and "hypothetical" in cmp_["warning"]
    assert cmp_["baseline"]["risk"]["score"] == r["score"] and set(cmp_["layers"]) == {
        "observed", "ml_prediction", "simulation", "assumption"}
    assert cmp_["scenario"]["prediction"]["is_scenario"] and cmp_["delta"]["ml_score"] is not None
    s, nochange = get(port, "/api/city/Indore/compare")
    assert nochange["delta"]["risk_score"] == 0 and nochange["delta"]["ml_score"] == 0
    assert get(port, "/api/city/Indore/compare?rain_factor=9")[0] == 400
    assert get(port, "/api/city/Bhopal/compare")[0] == 422

    s, g = get(port, "/api/city/Indore/sensitivity")     # more rain -> lower score; more heat -> higher score
    assert s == 200 and len(g["risk_score"]) == 5 and len(g["risk_score"][0]) == 6 and g["ml_score"] is None
    for row in g["risk_score"]:
        assert all(a >= b for a, b in zip(row, row[1:])), row
    for col in zip(*g["risk_score"]):
        assert all(a <= b for a, b in zip(col, col[1:])), col
    s, gm = get(port, "/api/city/Indore/sensitivity?include_ml=1")
    assert s == 200 and len(gm["ml_score"]) == 5 and all(v is not None for v in gm["ml_score"][0])

    s, rep = get(port, "/api/city/Indore/report")
    md = rep["markdown"]
    assert s == 200 and rep["filename"] == "omnisight_report_indore.md"
    for needle in ("# OMNISIGHT evidence report: Indore", "## Next-month model", "## Unusual months",
                   "not a forecast", "not the probability"):
        assert needle in md, needle
    assert get(port, "/api/city/Bhopal/report")[0] == 422

    s, v = get(port, "/api/validation")
    assert s == 200 and v["available"] and v["model"]["rows"] and v["caveats"] and len(v["years"]) > 20
    assert all(set(r) >= {"year", "monsoon", "rank", "of", "top6"} for r in v["table"])
    hp = os.path.join(data, "history_scores.csv")
    os.rename(hp, hp + ".bak")
    s, v2 = get(port, "/api/validation")
    assert s == 200 and v2["available"] is False and "history.py" in v2["message"] and v2["model"]["rows"]
    os.rename(hp + ".bak", hp)

    s, m = get(port, "/api/model")
    assert s == 200 and m["limitations"] and "test_results" in m

    # input validation and errors
    assert get(port, "/api/city/Indore/prediction?rain_factor=abc")[0] == 400
    assert get(port, "/api/city/Indore/prediction?rain_factor=10")[0] == 400
    assert get(port, "/api/city/Indore/risk?temp_add=-50")[0] == 400
    assert get(port, "/api/city/Atlantis/risk")[0] == 404
    assert get(port, "/api/nothing")[0] == 404
    assert get(port, "/..%2Fserver.py")[0] == 404          # no path traversal
    assert get(port, "/")[0] in (200, 404)

    # stale-data warning
    from ml_predict import ModelBundle
    import dashboard_logic as dl
    df = dl.load_cities(data)["Indore"]
    old = ModelBundle(models, data).predict_city(df, "Indore", today=date(2026, 10, 25))
    assert any("days old" in w for w in old["warnings"]), old["warnings"]

    # update endpoint (network replaced by a fake updater)
    app.updater = lambda d: [{"city": "Indore", "status": "updated", "added": 3, "last_date": "2025-09-17"}]
    s, u = get(port, "/api/update", method="POST")
    assert s == 200 and "3 new day" in u["message"], u
    assert get(port, "/api/update")[0] == 404              # GET is not allowed on /update

    httpd.shutdown()
    print("ALL SERVER TESTS PASSED")


if __name__ == "__main__":
    main()
