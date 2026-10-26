"""Checks that the ML data pipeline has no look-ahead leakage. Uses synthetic data (code correctness only).

Run:  python test_ml.py
"""
import numpy as np
import pandas as pd

from ml_features import FEATURES, build_city_frame


def synthetic_city(seed=0):
    rng = np.random.default_rng(seed)
    d = pd.date_range("1991-01-01", "2025-12-31")
    doy = d.dayofyear.values
    monsoon = np.exp(-((doy - 200) / 40) ** 2)
    rain = rng.gamma(0.3, 10, len(d)) * monsoon * (rng.random(len(d)) < 0.5 * monsoon + 0.03)
    tmax = 30 + 8 * np.sin((doy - 90) / 365 * 2 * np.pi) + rng.normal(0, 1.5, len(d))
    return pd.DataFrame({"date": d, "tmax_c": tmax, "rain_mm": rain})


def test_features_ignore_the_future():
    df = synthetic_city()
    full = build_city_frame(df, "X")
    origin = pd.Timestamp("2021-07-31")
    row_full = full[full["origin"] == origin][FEATURES].iloc[0]

    cut = df[df["date"] <= origin]                      # data stops at the origin date
    row_cut = build_city_frame(cut, "X").query("origin == @origin")[FEATURES].iloc[0]
    assert np.allclose(row_full.values, row_cut.values, equal_nan=True), "features use future data"

    changed = df.copy()                                 # wreck everything after the origin
    changed.loc[changed["date"] > origin, ["rain_mm", "tmax_c"]] = [500.0, 60.0]
    row_chg = build_city_frame(changed, "X").query("origin == @origin")[FEATURES].iloc[0]
    assert np.allclose(row_full.values, row_chg.values, equal_nan=True), "features change when the future changes"


def test_normals_use_only_training_years():
    df = synthetic_city()
    base = build_city_frame(df, "X")
    changed = df.copy()                                 # wreck the TEST years only
    changed.loc[changed["date"].dt.year >= 2016, ["rain_mm", "tmax_c"]] = [0.0, 20.0]
    after = build_city_frame(changed, "X")
    tr = base["split"] == "train"
    assert np.allclose(base.loc[tr, FEATURES].values, after.loc[tr, FEATURES].values, equal_nan=True)
    assert (base.loc[tr, "y"].fillna(-1).values == after.loc[tr, "y"].fillna(-1).values).all()


def test_split_is_chronological_and_target_is_next_month():
    df = synthetic_city()
    fr = build_city_frame(df, "X")
    assert fr.loc[fr.split == "train", "year"].max() < fr.loc[fr.split == "test", "year"].min()
    monthly = df.set_index("date")["rain_mm"].resample("MS").sum()
    r = fr.dropna(subset=["rain_next_mm"]).iloc[10]
    nxt = (r["origin"] + pd.offsets.MonthBegin(1))
    assert abs(monthly[nxt] - r["rain_next_mm"]) < 1e-9


if __name__ == "__main__":
    test_features_ignore_the_future()
    test_normals_use_only_training_years()
    test_split_is_chronological_and_target_is_next_month()
    print("ALL ML TESTS PASSED")
