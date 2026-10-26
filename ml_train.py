"""Train and compare models for 'will next month be dry?', explain the best one, and save it.

Run:  python ml_train.py
Output (folder models/):
    omnisight_model.joblib   the chosen model (trained on 1991-2015 only)
    model_card.json          target, features, scores, importance, limitations

HONEST WORKFLOW
    1. Choose settings by walk-forward cross-validation INSIDE the training years (1991-2015).
    2. Pick the model to deploy by that cross-validation, NOT by the test score.
    3. Look at the test years (2016 onwards) once, to report the result.
"""
import datetime
import json
import os

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (balanced_accuracy_score, confusion_matrix, precision_recall_fscore_support,
                             roc_auc_score)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight

from ml_features import DRY_QUANTILE, FEATURE_MEANING, FEATURES, ORIGIN_MONTHS, TRAIN_END_YEAR, build_dataset

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
MODEL_DIR = os.path.join(HERE, "models")
CV_BLOCKS = [(2004, 2007), (2008, 2011), (2012, 2015)]  # validation years; always train on earlier years


def candidates():
    """family -> {setting name: function that creates a fresh model}"""
    return {
        "Logistic regression": {
            f"C={c}": (lambda c=c: make_pipeline(StandardScaler(), LogisticRegression(
                C=c, class_weight="balanced", max_iter=1000))) for c in (0.1, 1.0)},
        "Random forest": {
            f"max_depth={d}": (lambda d=d: RandomForestClassifier(
                n_estimators=300, max_depth=d, min_samples_leaf=10, class_weight="balanced_subsample",
                random_state=0)) for d in (3, 5)},
        "Gradient boosting": {
            f"max_depth={d}": (lambda d=d: GradientBoostingClassifier(
                n_estimators=100, learning_rate=0.05, max_depth=d, subsample=0.8, random_state=0))
            for d in (1, 2)},
    }


def fit_model(model, X, y):
    if isinstance(model, GradientBoostingClassifier):  # it has no class_weight option
        model.fit(X, y, sample_weight=compute_sample_weight("balanced", y))
    else:
        model.fit(X, y)
    return model


def score_of(model, X):
    return model.predict_proba(X)[:, 1]


def walk_forward_cv(make, train):
    """Mean ROC-AUC over expanding-window folds inside the training years."""
    aucs = []
    for lo, hi in CV_BLOCKS:
        tr, va = train[train["year"] < lo], train[(train["year"] >= lo) & (train["year"] <= hi)]
        if tr["y"].nunique() < 2 or va["y"].nunique() < 2:
            continue
        m = fit_model(make(), tr[FEATURES], tr["y"])
        aucs.append(roc_auc_score(va["y"], score_of(m, va[FEATURES])))
    return float(np.mean(aucs)) if aucs else float("nan")


def year_block_bootstrap(test, score, pred, n=1000, seed=0):
    """95% intervals for AUC and F1, resampling whole years (cities in one year share a monsoon)."""
    rng = np.random.default_rng(seed)
    years = test["year"].unique()
    groups = {y: np.where(test["year"].values == y)[0] for y in years}
    y_true = test["y"].values
    aucs, f1s = [], []
    for _ in range(n):
        idx = np.concatenate([groups[y] for y in rng.choice(years, len(years))])
        if len(np.unique(y_true[idx])) < 2:
            continue
        aucs.append(roc_auc_score(y_true[idx], score[idx]))
        f1s.append(precision_recall_fscore_support(y_true[idx], pred[idx], average="binary",
                                                   pos_label=1, zero_division=0)[2])
    q = lambda v: [round(float(np.percentile(v, 2.5)), 3), round(float(np.percentile(v, 97.5)), 3)]
    return q(aucs), q(f1s)


def evaluate(model, test):
    s = score_of(model, test[FEATURES])
    pred = (s >= 0.5).astype(int)
    p, r, f, _ = precision_recall_fscore_support(test["y"], pred, average="binary", pos_label=1, zero_division=0)
    tn, fp, fn, tp = confusion_matrix(test["y"], pred, labels=[0, 1]).ravel()
    auc_ci, f1_ci = year_block_bootstrap(test, s, pred)
    return {"roc_auc": round(float(roc_auc_score(test["y"], s)), 3), "auc_ci95": auc_ci,
            "balanced_acc": round(float(balanced_accuracy_score(test["y"], pred)), 3),
            "precision": round(float(p), 3), "recall": round(float(r), 3),
            "f1": round(float(f), 3), "f1_ci95": f1_ci,
            "confusion": {"TP": int(tp), "FP": int(fp), "FN": int(fn), "TN": int(tn)}}


def main(data_dir=DATA_DIR, model_dir=MODEL_DIR):
    ds = build_dataset(data_dir)
    train, test = ds[ds["split"] == "train"], ds[ds["split"] == "test"]
    print(f"train {len(train)} rows ({train.year.min()}-{train.year.max()}), "
          f"test {len(test)} rows ({test.year.min()}-{test.year.max()})")
    print(f"'dry next month' share: train {train.y.mean():.0%}, test {test.y.mean():.0%}\n")

    best_per_family, cv_rows = {}, []
    for family, settings in candidates().items():
        scored = {name: walk_forward_cv(make, train) for name, make in settings.items()}
        for name, auc in scored.items():
            cv_rows.append({"family": family, "setting": name, "cv_auc": round(auc, 3)})
        best = max(scored, key=lambda k: -1 if np.isnan(scored[k]) else scored[k])
        best_per_family[family] = (best, scored[best], settings[best])
    print("Walk-forward cross-validation inside the training years (ROC-AUC, 0.5 = guessing):")
    print(pd.DataFrame(cv_rows).to_string(index=False), "\n")

    fitted, test_rows = {}, {}
    for family, (setting, cv_auc, make) in best_per_family.items():
        fitted[family] = fit_model(make(), train[FEATURES], train["y"])
        test_rows[family] = {"setting": setting, "cv_auc": round(cv_auc, 3), **evaluate(fitted[family], test)}
    table = pd.DataFrame({k: {c: v[c] for c in ("setting", "cv_auc", "roc_auc", "auc_ci95", "balanced_acc",
                                                 "precision", "recall", "f1", "f1_ci95")}
                          for k, v in test_rows.items()}).T
    print("TEST years (looked at once):")
    pd.set_option("display.width", 220, "display.max_columns", 20)
    print(table.to_string(), "\n")

    chosen = max(best_per_family, key=lambda k: -1 if np.isnan(best_per_family[k][1]) else best_per_family[k][1])
    print(f"Model chosen for the app (by cross-validation, not by test score): {chosen} "
          f"({best_per_family[chosen][0]})")
    model = fitted[chosen]

    pi = permutation_importance(model, test[FEATURES], test["y"], scoring="roc_auc",
                                n_repeats=50, random_state=0)
    imp = pd.DataFrame({"feature": FEATURES, "meaning": [FEATURE_MEANING[f] for f in FEATURES],
                        "auc_drop": pi.importances_mean.round(4), "std": pi.importances_std.round(4)}
                       ).sort_values("auc_drop", ascending=False)
    print("\nPermutation importance on the test years (how much AUC drops when a feature is shuffled):")
    print(imp.to_string(index=False))

    os.makedirs(model_dir, exist_ok=True)
    joblib.dump(model, os.path.join(model_dir, "omnisight_model.joblib"))
    card = {
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "sklearn_version": sklearn.__version__,
        "target": (f"Next month's rainfall is in the lowest third of that calendar month in "
                   f"1991-{TRAIN_END_YEAR} (per city). Forecast made at the end of months {list(ORIGIN_MONTHS)}."),
        "dry_quantile": round(DRY_QUANTILE, 3), "features": FEATURES,
        "train_years": [int(train.year.min()), int(train.year.max())],
        "test_years": [int(test.year.min()), int(test.year.max())],
        "train_rows": len(train), "test_rows": len(test),
        "dry_share_train": round(float(train.y.mean()), 3), "dry_share_test": round(float(test.y.mean()), 3),
        "chosen_model": chosen, "chosen_setting": best_per_family[chosen][0],
        "cross_validation": cv_rows, "test_results": test_rows,
        "permutation_importance": imp.to_dict(orient="records"),
        "limitations": [
            "Rainfall data is ERA5 reanalysis (a gridded model estimate), not station measurements.",
            "Only 5 cities and 10-11 test years; cities in one year share a monsoon, so real sample size is small.",
            "The score is a model score, not a calibrated probability that the month will be dry.",
            "'Dry' is relative to 1991-2015 normals; it is not an official drought declaration.",
            "Predicts rainfall only. It does not predict groundwater, crop yield or actual water shortage.",
        ],
    }
    with open(os.path.join(model_dir, "model_card.json"), "w", encoding="utf-8") as f:
        json.dump(card, f, indent=2, default=str)
    print(f"\nSaved models/omnisight_model.joblib and models/model_card.json")
    return card


if __name__ == "__main__":
    main()
