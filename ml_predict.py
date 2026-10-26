"""Use the saved model on the latest data: prediction, per-prediction explanation, data checks.

The answer it gives: "will NEXT month be dry?" (rain in the lowest third of 1991-2015 normals).
The score is a MODEL SCORE between 0 and 1. It is not a calibrated probability.
"""
import json
import os
from datetime import date

import joblib
import numpy as np
import pandas as pd

from indicators import last_complete_month_end
from ml_features import FEATURE_MEANING, FEATURES, ORIGIN_MONTHS, build_city_frame, build_dataset

STALE_DAYS = 45  # warn if the newest saved day is older than this
SEASON = ["month_sin", "month_cos"]  # shown together as one factor, "time of year"


class ModelBundle:
    def __init__(self, model_dir, data_dir):
        self.model = joblib.load(os.path.join(model_dir, "omnisight_model.joblib"))
        with open(os.path.join(model_dir, "model_card.json"), encoding="utf-8") as f:
            self.card = json.load(f)
        self.data_dir = data_dir
        self._reference = None

    @property
    def reference(self):
        """Typical (median) training-year value of each feature, used to explain one prediction."""
        if self._reference is None:
            ds = build_dataset(self.data_dir)
            self._reference = ds[ds["split"] == "train"][FEATURES].median()
        return self._reference

    def skill_note(self):
        res = self.card["test_results"][self.card["chosen_model"]]
        lo, hi = res["auc_ci95"]
        if lo > 0.5:
            verdict = "The interval is above 0.5, so there is some evidence of real skill."
        else:
            verdict = "The interval includes 0.5 (pure guessing), so skill is NOT proven."
        return (f"On held-out years {self.card['test_years'][0]}-{self.card['test_years'][1]} this model "
                f"scored AUC {res['roc_auc']} (95% interval {lo} to {hi}; 0.5 = guessing). {verdict}")

    def _explain(self, row):
        """How much each factor moves the score compared with a typical value (positive = towards 'dry')."""
        x = row[FEATURES].to_frame().T.astype(float)
        base = float(self.model.predict_proba(x)[0, 1])
        out = []
        groups = [[f] for f in FEATURES if f not in SEASON] + [SEASON]
        for g in groups:
            x2 = x.copy()
            for f in g:
                x2[f] = self.reference[f]
            effect = base - float(self.model.predict_proba(x2)[0, 1])
            name = g[0]
            out.append({
                "feature": "season" if g == SEASON else name,
                "meaning": "Time of year" if g == SEASON else FEATURE_MEANING[name],
                "value": None if g == SEASON else round(float(row[name]), 2),
                "typical": None if g == SEASON else round(float(self.reference[name]), 2),
                "effect": round(effect, 3),
                "direction": "towards dry" if effect > 0.0005 else ("towards not dry" if effect < -0.0005 else "none"),
            })
        return sorted(out, key=lambda d: -abs(d["effect"]))

    def predict_city(self, df, city, rain_factor=1.0, temp_add=0.0, today=None):
        """df: daily data (date, tmax_c, rain_mm). rain_factor/temp_add make it a SCENARIO
        (last 3 months' rain x factor, last 30 days' temperature + temp_add), the same way risk_engine does."""
        today = today or date.today()
        data_last = pd.Timestamp(df["date"].max())
        end = last_complete_month_end(pd.DatetimeIndex(df["date"]))
        scenario = (rain_factor != 1.0) or (temp_add != 0.0)
        info = {
            "city": city, "as_of": str(end.date()), "data_last_date": str(data_last.date()),
            "days_since_data": (today - data_last.date()).days,
            "kind": "SCENARIO (mathematical simulation, hypothetical)" if scenario else "ML prediction",
            "is_scenario": scenario, "rain_factor": rain_factor, "temp_add": temp_add,
            "target_month": (end + pd.Timedelta(days=1)).strftime("%B %Y"),
            "warnings": [],
        }
        if info["days_since_data"] > STALE_DAYS:
            info["warnings"].append(f"Newest saved data is {info['days_since_data']} days old. "
                                    "Use 'Update data' if you are online.")
        if end.month not in ORIGIN_MONTHS:
            return {**info, "status": "out_of_season",
                    "message": "The model was trained for forecasts made at the end of April to September "
                               "(for May to October). It makes no prediction outside that season."}

        d = df[df["date"] <= end][["date", "tmax_c", "rain_mm"]].copy().set_index("date")
        if scenario:
            start3 = end.replace(day=1) - pd.DateOffset(months=2)
            start30 = end - pd.Timedelta(days=29)
            d.loc[start3:, "rain_mm"] = d.loc[start3:, "rain_mm"] * rain_factor
            d.loc[start30:, "tmax_c"] = d.loc[start30:, "tmax_c"] + temp_add
        frame = build_city_frame(d.reset_index(), city)
        row = frame[frame["origin"] == end]
        if row.empty or row[FEATURES].iloc[0].isna().any():
            missing = FEATURES if row.empty else [f for f in FEATURES if np.isnan(row[f].iloc[0])]
            return {**info, "status": "insufficient_data",
                    "message": f"Not enough clean data to compute: {', '.join(missing)}."}
        row = row.iloc[0]

        score = float(self.model.predict_proba(row[FEATURES].to_frame().T.astype(float))[0, 1])
        info.update({
            "status": "ok", "score": round(score, 3), "predicted_dry": score >= 0.5,
            "answer": (f"Model leans 'dry' for {info['target_month']}" if score >= 0.5
                       else f"Model leans 'not dry' for {info['target_month']}"),
            "score_note": "A model score from 0 to 1. It is NOT the probability that the month will be dry.",
            "base_rate_train": self.card["dry_share_train"],
            "features": {f: round(float(row[f]), 3) for f in FEATURES},
            "explanation": self._explain(row),
            "skill_note": self.skill_note(),
            "model": f"{self.card['chosen_model']} ({self.card['chosen_setting']})",
            "limitations": self.card["limitations"],
        })
        return info
