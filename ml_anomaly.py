"""Find unusual months by comparing each month with its own seasonal normal (1991-2020).

TWO DETECTORS, so each can check the other
  1. Statistical: any seasonal z-score beyond +-2.
  2. Isolation Forest: looks at the COMBINATION of four z-scores (rain, temperature, longest dry spell,
     number of rainy days) and flags months that are unusual as a combination.
The Isolation Forest is trained only on the 1991-2020 months (the normal period) and flags the most unusual 5%.

WHAT A FLAG MEANS
  An unusual month compared with that city's own history. It is NOT a drought declaration and not a disaster.
  Dry-season months (normal rain under 25 mm) are not scored for rain: with a tiny normal, a little rain gives
  a huge z-score, and an unseasonal shower is not a water-stress signal.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from indicators import BASE_END, BASE_START

MIN_NORMAL_RAIN_MM = 25.0  # below this the normal is tiny and z-scores become unstable
FEATS = ["rain_z", "tmax_z", "dry_z", "days_z"]
RAW = {"rain_z": "rain_sqrt", "tmax_z": "tmax_c", "dry_z": "dry_run", "days_z": "rain_days"}
Z_NOTABLE = 1.5
Z_STAT = 2.0
FLAG_SHARE = 0.05
BIG_DAY_MM = 150.0


def _days(n):
    n = int(round(n))
    return f"{n} day" if n == 1 else f"{n} days"


def _longest_dry_run(vals, threshold_mm=1.0):
    best = cur = 0
    for v in vals:
        cur = cur + 1 if v < threshold_mm else 0
        best = max(best, cur)
    return best


def monthly_table(df, city):
    """One row per complete month with the raw measurements."""
    d = df.set_index("date")
    rows = []
    for start, g in d.groupby(pd.Grouper(freq="MS")):
        if len(g) < start.days_in_month:
            continue
        rain = g["rain_mm"].values
        rows.append({"city": city, "month": start, "rain_mm": float(rain.sum()), "tmax_c": float(g["tmax_c"].mean()),
                     "dry_run": _longest_dry_run(rain), "rain_days": int((rain >= 1).sum()),
                     "max_day_mm": float(rain.max())})
    t = pd.DataFrame(rows)
    t["rain_sqrt"] = np.sqrt(t["rain_mm"])  # square root tames the long right tail of rainfall
    t["cal_month"] = t["month"].dt.month
    return t


class AnomalyDetector:
    def fit(self, data):
        """data: {city: daily DataFrame}"""
        t = pd.concat([monthly_table(df, c) for c, df in data.items()], ignore_index=True)
        base = t[(t["month"].dt.year >= BASE_START) & (t["month"].dt.year <= BASE_END)]
        keys = ["city", "cal_month"]
        raw_cols = list(RAW.values()) + ["rain_mm"]
        self.mean = base.groupby(keys)[raw_cols].mean()
        self.std = base.groupby(keys)[list(RAW.values())].std()

        m = t.join(self.mean.add_suffix("_mean"), on=keys).join(self.std.add_suffix("_std"), on=keys)
        for z, raw in RAW.items():
            sd = m[raw + "_std"].replace(0, np.nan)
            m[z] = ((m[raw] - m[raw + "_mean"]) / sd).fillna(0.0)
        dry_season = m["rain_mm_mean"] < MIN_NORMAL_RAIN_MM  # normal rain ~0: rain-based z-scores are meaningless
        for z in ("rain_z", "dry_z", "days_z"):
            m.loc[dry_season, z] = 0.0
        m["scored_for_rain"] = ~dry_season

        in_base = (m["month"].dt.year >= BASE_START) & (m["month"].dt.year <= BASE_END)
        self.forest = IsolationForest(n_estimators=300, random_state=0).fit(m.loc[in_base, FEATS])
        m["anomaly_score"] = -self.forest.score_samples(m[FEATS])  # higher = more unusual
        self.threshold = float(np.quantile(m.loc[in_base, "anomaly_score"], 1 - FLAG_SHARE))
        m["if_flag"] = m["anomaly_score"] > self.threshold
        m["stat_flag"] = (m[FEATS].abs() >= Z_STAT).any(axis=1)
        self.table = m
        return self

    # ---- explanation ----
    def _row_record(self, r):
        triggers = []
        for z, raw in RAW.items():
            if abs(r[z]) < Z_NOTABLE:
                continue
            normal = r[raw + "_mean"]
            if z == "rain_z":
                text = f"Rain {r['rain_mm']:.0f} mm vs normal {r['rain_mm_mean']:.0f} mm"
            elif z == "tmax_z":
                text = f"Mean max temperature {r['tmax_c']:.1f} C vs normal {normal:.1f} C"
            elif z == "dry_z":
                text = f"Longest dry spell {_days(r['dry_run'])} vs normal {_days(normal)}"
            else:
                text = f"Rain on {_days(r['rain_days'])} vs normal {_days(normal)}"
            triggers.append({"feature": z, "z": round(float(r[z]), 2), "detail": text})

        rz, tz = r["rain_z"], r["tmax_z"]
        if rz <= -Z_NOTABLE and tz >= Z_NOTABLE:
            kind = "Hot and dry combination"
        elif rz <= -Z_NOTABLE:
            kind = "Unusually dry month"
        elif rz >= Z_NOTABLE:
            kind = "Unusually wet month"
        elif tz >= Z_NOTABLE:
            kind = "Unusually hot month"
        elif tz <= -Z_NOTABLE:
            kind = "Unusually cool month"
        elif r["if_flag"]:
            kind = "Unusual combination (no single extreme value)"
        else:
            kind = "Within normal range"

        notes = ["Gridded ERA5 estimate, not a station measurement."]
        big_day = r["max_day_mm"] >= BIG_DAY_MM and r["max_day_mm"] >= 0.5 * max(r["rain_mm"], 1e-9)
        if big_day:
            notes.append(f"Dominated by one very large daily value ({r['max_day_mm']:.0f} mm in a day). "
                         "ERA5 can overstate extreme days; verify with a rain-gauge record.")
        agree = bool(r["if_flag"] and r["stat_flag"])
        if not r["if_flag"] and not r["stat_flag"] and not triggers:
            evidence = "not flagged"
        elif big_day:
            evidence = "weak (single extreme day, unverified)"
        elif len(triggers) >= 2 and agree:
            evidence = "strong (several signals, both methods agree)"
        elif len(triggers) >= 1:
            evidence = "moderate (one signal)" if not agree else "moderate"
        else:
            evidence = "weak (no single signal stands out)"
        return {"city": r["city"], "month": r["month"].strftime("%Y-%m"), "kind": kind,
                "anomaly_score": round(float(r["anomaly_score"]), 3), "flagged": bool(r["if_flag"]),
                "stat_flag": bool(r["stat_flag"]), "methods_agree": agree, "triggers": triggers,
                "evidence": evidence, "notes": notes,
                "meaning": "An unusual month compared with this city's own 1991-2020 history. "
                           "Not a drought declaration and not a disaster."}

    def city_report(self, city, recent_months=24, top_n=10):
        t = self.table[self.table["city"] == city].sort_values("month")
        if t.empty:
            raise KeyError(city)
        recent = t.tail(recent_months)
        top = t[t["if_flag"]].nlargest(top_n, "anomaly_score")
        return {"city": city, "threshold": round(self.threshold, 3),
                "method": ("Isolation Forest on four seasonal z-scores (rain, temperature, dry spell, rainy days), "
                           "trained on 1991-2020; flags the most unusual 5%. A simple |z|>=2 check is shown alongside."),
                "recent": [self._row_record(r) for _, r in recent.iterrows()],
                "top_historic": [self._row_record(r) for _, r in top.iterrows()]}
