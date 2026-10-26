"""Baselines for the 'dry next month' question. Any ML model must beat these to be worth using.

Run:  python ml_baselines.py
Output: a table on the TEST years (2016 onwards), saved to data/ml_baselines.csv
"""
import os

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, confusion_matrix, precision_recall_fscore_support
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ml_features import FEATURES, build_dataset

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")


def metrics(y, pred):
    p, r, f, _ = precision_recall_fscore_support(y, pred, average="binary", pos_label=1, zero_division=0)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {"precision": p, "recall": r, "f1": f, "balanced_acc": balanced_accuracy_score(y, pred),
            "TP": tp, "FP": fp, "FN": fn, "TN": tn}


def block_bootstrap_f1(test, pred, n=1000, seed=0):
    """95% interval for F1, resampling whole YEARS (all cities share a year's monsoon, so rows are not independent)."""
    rng = np.random.default_rng(seed)
    years = test["year"].unique()
    groups = {y: np.where(test["year"].values == y)[0] for y in years}
    yv = test["y"].values
    vals = []
    for _ in range(n):
        idx = np.concatenate([groups[y] for y in rng.choice(years, len(years))])
        vals.append(precision_recall_fscore_support(yv[idx], pred[idx], average="binary",
                                                    pos_label=1, zero_division=0)[2])
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def run_baselines(ds):
    train, test = ds[ds["split"] == "train"], ds[ds["split"] == "test"]
    preds = {
        "Always 'not dry' (majority class)": np.zeros(len(test), dtype=int),
        "Always 'dry'": np.ones(len(test), dtype=int),
        "Persistence (dry now -> dry next)": test["persist_dry"].astype(int).values,
        "Rule: 3-month rain z <= -0.5": (test["rain_3m_z"].values <= -0.5).astype(int),
    }
    lr = make_pipeline(StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=1000))
    lr.fit(train[FEATURES], train["y"])
    preds["Logistic regression (simple ML)"] = lr.predict(test[FEATURES])

    rows = []
    for name, p in preds.items():
        m = metrics(test["y"].values, p)
        lo, hi = block_bootstrap_f1(test, p)
        rows.append({"model": name, **m, "f1_ci_low": lo, "f1_ci_high": hi})
    return pd.DataFrame(rows), lr


def main():
    ds = build_dataset(DATA_DIR)
    train, test = ds[ds["split"] == "train"], ds[ds["split"] == "test"]
    print(f"Rows: train {len(train)} (years {train.year.min()}-{train.year.max()}), "
          f"test {len(test)} (years {test.year.min()}-{test.year.max()})")
    print(f"'Dry next month' share: train {train.y.mean():.0%}, test {test.y.mean():.0%}")
    res, _ = run_baselines(ds)
    pd.set_option("display.width", 200, "display.max_columns", 20)
    print(res.round(2).to_string(index=False))
    res.to_csv(os.path.join(DATA_DIR, "ml_baselines.csv"), index=False)
    print("\nNote: test rows from the same year and different cities are strongly related (one monsoon), "
          "so the real number of independent test cases is about the number of test years, not rows.")


if __name__ == "__main__":
    main()
