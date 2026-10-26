"""OMNISIGHT backend: serves the website in web/ and JSON endpoints. No extra packages needed.

Run:  python server.py            then open http://127.0.0.1:8000
Needs: data/*.csv (python fetch_data.py) and models/ (python ml_train.py).

ENDPOINTS (all return JSON)
  GET  /api/health                         data dates, model info
  GET  /api/overview                       every city: risk score + ML prediction (for the map)
  GET  /api/city/<name>/risk               risk score; optional ?rain_factor=0.7&temp_add=2
  GET  /api/city/<name>/prediction         ML prediction; same optional scenario inputs
  GET  /api/city/<name>/history            monthly rain vs normal, newest 45 days
  GET  /api/city/<name>/anomalies          unusual months: last 24 + the biggest ever, with reasons and evidence
  GET  /api/city/<name>/compare            baseline vs scenario (?rain_factor=0.7&temp_add=2), risk + ML score
  GET  /api/city/<name>/sensitivity        risk score on a grid of rain and temperature changes
  GET  /api/city/<name>/report             full evidence report as Markdown text
  GET  /api/validation                     known-dry-year check and the model's test results
  GET  /api/model                          model card: target, scores, importance, limitations
  POST /api/update                         fetch the newest days from Open-Meteo (needs internet)
Errors look like {"error": "..."} with status 400, 404 or 500.
"""
import argparse
import json
import mimetypes
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd

import dashboard_logic as dl
from fetch_data import CITIES
from indicators import BASE_END, BASE_START, fit_spi_params, last_complete_month_end, monthly_accumulated
from ml_anomaly import AnomalyDetector
from ml_predict import ModelBundle
from risk_engine import WEIGHTS, assess_city
from update_data import update_all

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(HERE, "web")
RAIN_FACTOR_RANGE = (0.0, 3.0)
TEMP_ADD_RANGE = (-5.0, 10.0)


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


class App:
    """Holds the data and model in memory; reloads data after an update."""

    def __init__(self, data_dir, model_dir):
        self.data_dir, self.model_dir = data_dir, model_dir
        self.lock = threading.Lock()
        self.updater = update_all  # replaceable in tests
        self.bundle = ModelBundle(model_dir, data_dir)
        self.reload()

    def reload(self):
        with self.lock:
            self.data = dl.load_cities(self.data_dir)
            self.params = {}
            for c, df in self.data.items():
                rain = df.set_index("date")["rain_mm"]
                self.params[c] = fit_spi_params(rain[:last_complete_month_end(rain.index)])
            self.anomalies = AnomalyDetector().fit(self.data)

    # ---- helpers ----
    def city(self, name):
        for c in self.data:
            if c.lower() == name.lower():
                return c
        raise ApiError(404, f"Unknown city '{name}'. Available: {', '.join(self.data)}")

    @staticmethod
    def scenario(query):
        def num(key, default, lo, hi):
            if key not in query:
                return default
            try:
                v = float(query[key][0])
            except ValueError:
                raise ApiError(400, f"'{key}' must be a number")
            if not (lo <= v <= hi):
                raise ApiError(400, f"'{key}' must be between {lo} and {hi}")
            return v
        return num("rain_factor", 1.0, *RAIN_FACTOR_RANGE), num("temp_add", 0.0, *TEMP_ADD_RANGE)

    # ---- endpoints ----
    def health(self):
        last = {c: str(df["date"].max().date()) for c, df in self.data.items()}
        return {"status": "ok", "cities": list(self.data), "data_last_date": last,
                "model": f"{self.bundle.card['chosen_model']} ({self.bundle.card['chosen_setting']})",
                "model_created": self.bundle.card["created"]}

    def rain_3m(self, city, end):
        """Observed rain in the last 3 months (mm) and the 1991-2020 average for the same 3 months."""
        rain = self.data[city].set_index("date")["rain_mm"]
        start3 = end.replace(day=1) - pd.DateOffset(months=2)
        observed = float(rain[start3:end].sum())
        acc = monthly_accumulated(rain[:end], 3).dropna()
        base = acc[(acc.index.year >= BASE_START) & (acc.index.year <= BASE_END) & (acc.index.month == end.month)]
        return observed, float(base.mean())

    def risk(self, name, query):
        city = self.city(name)
        rf, ta = self.scenario(query)
        try:
            r = assess_city(self.data[city], rain_factor=rf, temp_add=ta, params=self.params[city])
        except ValueError as e:  # e.g. dry-season month: the SPI cannot be fitted
            raise ApiError(422, f"Risk score not available for {city}: {e}")
        pts = dl.contributions(r, WEIGHTS)
        lat, lon = CITIES[city]
        rain_obs, rain_normal = self.rain_3m(city, pd.Timestamp(r["as_of"]))
        return {"city": city, "lat": lat, "lon": lon, "as_of": str(r["as_of"]), "score": r["score"],
                "level": r["level"], "spi3": round(r["spi3"], 2), "spi3_label": dl.spi_label(r["spi3"]),
                "heat_z": round(r["heat_z"], 2), "heat_label": dl.heat_label(r["heat_z"]),
                "dry_run_days": r["dry_run_days"], "points": pts, "weights": WEIGHTS,
                "rain_3m_mm": round(rain_obs * rf, 1), "rain_3m_normal_mm": round(rain_normal, 1),
                "rain_3m_pct": round(100 * rain_obs * rf / rain_normal) if rain_normal > 0 else None,
                "kind": "SCENARIO (mathematical simulation, hypothetical)" if (rf != 1.0 or ta != 0.0)
                else "Computed from observed (ERA5) data",
                "note": "Risk score = current conditions vs 1991-2020 normal. Weights are design assumptions. "
                        "Not a forecast and not an official warning."}

    def prediction(self, name, query):
        city = self.city(name)
        rf, ta = self.scenario(query)
        return self.bundle.predict_city(self.data[city], city, rain_factor=rf, temp_add=ta)

    def overview(self):
        rows = []
        for c in self.data:
            lat, lon = CITIES[c]
            try:
                risk = self.risk(c, {})
            except ApiError as e:  # one city failing must not hide the others
                risk = {"city": c, "lat": lat, "lon": lon, "status": "unavailable", "message": e.message}
            pred = self.prediction(c, {})
            rows.append({**risk, "prediction": {k: pred.get(k) for k in
                         ("status", "score", "predicted_dry", "answer", "target_month", "message", "warnings")}})
        return {"cities": rows, "model_skill": self.bundle.skill_note()}

    def history(self, name):
        city = self.city(name)
        df = self.data[city]
        end = last_complete_month_end(pd.DatetimeIndex(df["date"]))
        monthly = dl.monthly_vs_normal(df, end, 12)
        recent = dl.recent_days(df, 45)
        return {"city": city, "as_of": str(end.date()), "monthly": monthly.to_dict(orient="records"),
                "recent_days": [{"date": str(r.date.date()), "tmax_c": float(r.tmax_c), "rain_mm": float(r.rain_mm)}
                                for r in recent.itertuples()]}

    def compare(self, name, query):
        """Baseline (observed data) next to a scenario (your assumptions), for the risk score and the ML score."""
        rf, ta = self.scenario(query)
        base_risk, scen_risk = self.risk(name, {}), self.risk(name, query)
        base_pred, scen_pred = self.prediction(name, {}), self.prediction(name, query)
        delta = {"risk_score": round(scen_risk["score"] - base_risk["score"], 1),
                 "spi3": round(scen_risk["spi3"] - base_risk["spi3"], 2),
                 "heat_z": round(scen_risk["heat_z"] - base_risk["heat_z"], 2),
                 "ml_score": (round(scen_pred["score"] - base_pred["score"], 3)
                              if base_pred.get("status") == "ok" and scen_pred.get("status") == "ok" else None)}
        reading = (f"If rain over the last 3 months had been {rf:.0%} of what was observed and the last 30 days "
                   f"were {ta:+.1f} C different, the risk score would move from {base_risk['score']:.0f} "
                   f"({base_risk['level']}) to {scen_risk['score']:.0f} ({scen_risk['level']}).")
        return {
            "city": base_risk["city"], "as_of": base_risk["as_of"],
            "assumptions": {"rain_factor": rf, "temp_add": ta},
            "baseline": {"risk": base_risk, "prediction": base_pred},
            "scenario": {"risk": scen_risk, "prediction": scen_pred},
            "delta": delta, "reading": reading,
            "layers": {
                "observed": f"ERA5 weather data up to {base_risk['as_of']} (a gridded estimate, not a station measurement)",
                "ml_prediction": "Trained model score for next month; fed the scenario inputs only as a what-if",
                "simulation": "Risk score recomputed with the changed rain and temperature (simple arithmetic, not a physical model)",
                "assumption": "The rain factor and temperature change are YOUR hypothetical inputs, not forecasts",
            },
            "warning": "Scenarios are hypothetical. They are not forecasts and not a validated model of any district.",
        }

    def sensitivity(self, name, query):
        """Risk score for a grid of rain and temperature changes (shows how the score responds)."""
        city = self.city(name)
        rains = [0.4, 0.6, 0.8, 1.0, 1.2, 1.4]
        temps = [0.0, 1.0, 2.0, 3.0, 4.0]
        include_ml = query.get("include_ml", ["0"])[0] == "1"
        risk_grid, ml_grid = [], []
        for t in temps:
            row, ml_row = [], []
            for r in rains:
                try:
                    row.append(assess_city(self.data[city], rain_factor=r, temp_add=t,
                                           params=self.params[city])["score"])
                except ValueError as e:
                    raise ApiError(422, f"Risk score not available for {city}: {e}")
                if include_ml:
                    p = self.bundle.predict_city(self.data[city], city, rain_factor=r, temp_add=t)
                    ml_row.append(p.get("score"))
            risk_grid.append(row)
            ml_grid.append(ml_row)
        return {"city": city, "rain_factors": rains, "temp_adds": temps,
                "risk_score": risk_grid, "ml_score": ml_grid if include_ml else None,
                "kind": "SCENARIO (mathematical simulation, hypothetical)",
                "note": "Rows = temperature change in C, columns = rain factor for the last 3 months."}

    # ---- evidence report and validation ----
    def history_df(self):
        path = os.path.join(self.data_dir, "history_scores.csv")
        return pd.read_csv(path) if os.path.exists(path) else None

    def report(self, name):
        city = self.city(name)
        try:
            r = assess_city(self.data[city], params=self.params[city])
        except ValueError as e:
            raise ApiError(422, f"Report not available for {city}: {e}")
        hist = self.history_df()
        top = dl.top_history(hist, city, 5) if hist is not None else None
        lines = [dl.report_text(city, r, WEIGHTS, top), ""]

        pred = self.prediction(city, {})
        lines.append("## Next-month model (experimental)")
        if pred.get("status") == "ok":
            factors = "; ".join(f"{e['meaning']}: {e['direction']}" for e in pred["explanation"][:3]
                                if e["direction"] != "none") or "no single factor stands out"
            lines += [f"- Question: will {pred['target_month']} rain fall in the driest third of years for that month?",
                      f"- {pred['answer']} (model score {pred['score']:.2f}). "
                      "This is a model score, not the probability that the month will be dry.",
                      f"- Main factors: {factors}.", f"- Test result: {pred['skill_note']}"]
        else:
            lines.append(f"- {pred.get('message', 'No prediction is available for this month.')}")

        an = self.anomalies.city_report(city, recent_months=24, top_n=5)
        flagged = [a for a in an["recent"] if a["flagged"]]
        lines += ["", "## Unusual months",
                  "- Last 24 months: " + (", ".join(f"{a['month']} ({a['kind'].lower()})" for a in flagged)
                                         if flagged else "none flagged."),
                  "- Most unusual since 1991:"]
        lines += [f"  - {a['month']}: {a['kind']}; evidence {a['evidence']}" for a in an["top_historic"]]
        lines += ["", f"_Generated from saved data through {self.data[city]['date'].max().date()}._"]
        return {"city": city, "filename": f"omnisight_report_{city.lower()}.md", "markdown": "\n".join(lines)}

    def validation(self):
        card = self.bundle.card
        rows = []
        for fam, res in card["test_results"].items():
            rows.append({"model": fam, "setting": res["setting"], "used_in_app": fam == card["chosen_model"],
                         "roc_auc": res["roc_auc"], "auc_ci95": res["auc_ci95"],
                         "balanced_acc": res["balanced_acc"], "f1": res["f1"], "f1_ci95": res["f1_ci95"]})
        out = {"model": {"test_years": card["test_years"], "train_years": card["train_years"], "rows": rows,
                         "dry_share_train": card["dry_share_train"], "dry_share_test": card["dry_share_test"]},
               "caveats": ["The 1991-2020 normal is also the period being scored, so this is a sanity check, "
                           "not a test on unseen data.",
                           "The monsoon figures are for all of India; a single city can differ.",
                           "Other years also rank high (for example 2000, 2001 and 2004). We have not checked "
                           "them against a source."]}
        hist = self.history_df()
        if hist is None:
            return {**out, "available": False,
                    "message": "The yearly scores are not computed yet. Run: python history.py"}
        y = dl.yearly_average(hist)
        n = len(y)
        table = []
        for year, note in dl.DEFICIENT_YEARS.items():
            hit = y[y["year"] == year]
            if hit.empty:
                continue
            rank = int(hit["rank"].iloc[0])
            table.append({"year": year, "monsoon": note, "avg_score": float(hit["avg_score"].iloc[0]),
                          "rank": rank, "of": n, "top6": rank <= 6})
        years = [{"year": int(r.year), "avg_score": float(r.avg_score), "rank": int(r.rank),
                  "deficient": int(r.year) in dl.DEFICIENT_YEARS} for r in y.itertuples()]
        return {**out, "available": True, "table": table, "years": years}

    def anomalies_for(self, name):
        return self.anomalies.city_report(self.city(name))

    def model_card(self):
        return self.bundle.card

    def update(self):
        results = self.updater(self.data_dir)
        self.reload()
        return {"message": dl.summarize_update(results), "results": results}


def route(app, method, path, query):
    parts = [unquote(p) for p in path.strip("/").split("/")]
    if parts[:1] != ["api"]:
        raise ApiError(404, "Not found")
    p = parts[1:]
    if method == "GET":
        if p == ["health"]:
            return app.health()
        if p == ["overview"]:
            return app.overview()
        if p == ["model"]:
            return app.model_card()
        if p == ["validation"]:
            return app.validation()
        if len(p) == 3 and p[0] == "city":
            if p[2] == "risk":
                return app.risk(p[1], query)
            if p[2] == "prediction":
                return app.prediction(p[1], query)
            if p[2] == "history":
                return app.history(p[1])
            if p[2] == "anomalies":
                return app.anomalies_for(p[1])
            if p[2] == "report":
                return app.report(p[1])
            if p[2] == "compare":
                return app.compare(p[1], query)
            if p[2] == "sensitivity":
                return app.sensitivity(p[1], query)
    if method == "POST" and p == ["update"]:
        return app.update()
    raise ApiError(404, "Not found")


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the terminal quiet
            pass

        def _send(self, status, body, ctype="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, obj):
            self._send(status, json.dumps(obj, default=str).encode("utf-8"))

        def _static(self, path):
            rel = "index.html" if path in ("", "/") else unquote(path).lstrip("/")
            full = os.path.realpath(os.path.join(WEB_DIR, rel))
            if not full.startswith(os.path.realpath(WEB_DIR) + os.sep) or not os.path.isfile(full):
                return self._json(404, {"error": "Not found"})
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            with open(full, "rb") as f:
                self._send(200, f.read(), ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))

        def _handle(self, method):
            u = urlparse(self.path)
            if not u.path.startswith("/api/"):
                return self._static(u.path) if method == "GET" else self._json(404, {"error": "Not found"})
            try:
                self._json(200, route(app, method, u.path, parse_qs(u.query)))
            except ApiError as e:
                self._json(e.status, {"error": e.message})
            except Exception as e:  # never crash the server on one bad request
                self._json(500, {"error": f"Server error: {type(e).__name__}: {e}"[:300]})

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

    return Handler


def serve(app, host="127.0.0.1", port=8000):
    return ThreadingHTTPServer((host, port), make_handler(app))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    application = App(os.path.join(HERE, "data"), os.path.join(HERE, "models"))
    httpd = serve(application, a.host, a.port)
    print(f"OMNISIGHT running at http://{a.host}:{a.port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("stopped")
