"""Machine-learning surrogate for a fast orbital-lifetime preview.

This module trains a small random-forest regressor to *approximate* the orbital
lifetime that :mod:`ananke.physics.lifetime` computes exactly. Given a
spacecraft's mass, drag coefficient, area, operational altitude, and a
solar-activity multiplier, it returns an estimated natural-decay lifetime in
years almost instantly, instead of running the numerical decay integration.

IMPORTANT — scope and honesty (design blueprint Section 9.7)
------------------------------------------------------------
The surrogate is NEVER used to determine rule compliance (PASS/FAIL). The exact
physics in :mod:`ananke.physics.lifetime` and the rule engine in
:mod:`ananke.rules` remain the sole source of truth for every compliance
decision. The surrogate is a trained, hold-out-validated approximation whose
reported accuracy (R^2, MAE) is measured on data it never saw during training.

The training targets come from the real, already-tested physics functions — no
physics is reimplemented here — so the model learns to mimic Ananke's own
validated model, on Ananke's own simulated missions.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

from ananke.physics.lifetime import ballistic_coefficient, lifetime_years

# Fixed feature order shared by training and prediction, so a single-row
# prediction lines up with the columns the model was fitted on.
FEATURE_COLUMNS = ["mass_kg", "cd", "area_m2", "altitude_km", "k"]
TARGET_COLUMN = "lifetime_years"


def generate_training_data(n_samples: int = 10000, seed: int = 42) -> pd.DataFrame:
    """Simulate ``n_samples`` random missions and label each with its true lifetime.

    Draws independent uniform samples for each feature, then labels every row
    with the lifetime from the real physics engine (so the surrogate learns to
    mimic Ananke's validated model rather than an approximation of it).

    Parameters
    ----------
    n_samples : int
        Number of random missions to simulate.
    seed : int
        Seed for ``numpy.random.default_rng`` — fixed so the dataset (and hence
        the trained model and its reported metrics) is exactly reproducible.

    Returns
    -------
    pandas.DataFrame
        Columns ``[mass_kg, cd, area_m2, altitude_km, k, lifetime_years]``.
    """
    rng = np.random.default_rng(seed)
    mass_kg = rng.uniform(50.0, 500.0, n_samples)
    cd = rng.uniform(1.5, 3.0, n_samples)
    area_m2 = rng.uniform(0.3, 5.0, n_samples)
    altitude_km = rng.uniform(300.0, 1000.0, n_samples)
    k = rng.uniform(0.5, 2.0, n_samples)

    lifetimes = np.empty(n_samples, dtype=float)
    for i in range(n_samples):
        B = ballistic_coefficient(mass_kg[i], cd[i], area_m2[i])
        lifetimes[i] = lifetime_years(altitude_km[i], B, k=float(k[i]))

    return pd.DataFrame(
        {
            "mass_kg": mass_kg,
            "cd": cd,
            "area_m2": area_m2,
            "altitude_km": altitude_km,
            "k": k,
            "lifetime_years": lifetimes,
        }
    )


def train_surrogate(
    df: pd.DataFrame,
    test_size: float = 0.2,
    random_state: int = 42,
) -> tuple[RandomForestRegressor, dict]:
    """Train the lifetime surrogate and measure its hold-out accuracy.

    Splits ``df`` into a training and a held-out set with a fixed
    ``random_state`` (reproducibility matters — the numbers below must be
    reproducible on demand), fits a 200-tree random forest, and reports accuracy
    metrics computed on the HOLD-OUT set only (data the model never saw).

    The forest is fitted on ``log1p(lifetime_years)``, not the raw target.
    Decay lifetime is extremely right-skewed (it spans from ~0 to tens of
    thousands of years over this feature box), and a tree averaging raw years
    is dominated by the long tail; fitting in log-space equalises that dynamic
    range so the model resolves the common short/medium lifetimes far better.
    ``log1p`` (rather than ``log``) handles the near-zero lifetimes cleanly,
    avoiding ``log(0)``. Predictions are mapped back with ``expm1`` BEFORE any
    metric is computed, so every reported number stays in real years and is
    directly comparable to a raw-target fit (same units, same meaning — only
    the model underneath is better fitted).

    Returns
    -------
    tuple
        ``(trained_model, metrics)``. ``metrics`` keys:

        - ``r2`` — year-space R^2. Diagnostic ONLY: tail-dominated, so it
          understates accuracy on realistic missions; never a pass/fail gate.
        - ``r2_log_space`` — R^2 in the log1p space the model optimises; the
          fairer fit measure for this skewed target.
        - ``mae_years`` — mean absolute error, in years.
        - ``mae_relative_pct`` — MAE as a percent of the hold-out mean lifetime.
        - ``median_ape_pct`` / ``p90_ape_pct`` — median and 90th-percentile
          absolute percentage error in real years (the primary accuracy claim).
        - ``n_train`` / ``n_holdout`` — split sizes.
    """
    X = df[FEATURE_COLUMNS]
    y = df[TARGET_COLUMN]

    X_train, X_holdout, y_train, y_holdout = train_test_split(
        X, y, test_size=test_size, random_state=random_state
    )

    # Fit in log-space to tame the target's extreme right skew, then map
    # predictions back to real years before scoring.
    model = RandomForestRegressor(n_estimators=200, random_state=random_state)
    model.fit(X_train, np.log1p(y_train))

    # Two views of the hold-out predictions:
    #   y_pred_log — the model's raw output, in the log1p space it optimises;
    #   y_pred     — mapped back to real years (expm1) for user-facing numbers.
    y_pred_log = model.predict(X_holdout)
    y_pred = np.expm1(y_pred_log)

    # Year-space R^2: reported as a diagnostic ONLY. Being variance-based, it is
    # dominated by a few extreme-lifetime outliers and so understates accuracy on
    # realistic missions — it is not the pass/fail gate.
    r2 = float(r2_score(y_holdout, y_pred))
    # Log-space R^2: the metric the forest is actually trained against, and a
    # fairer measure of fit for a target this skewed.
    r2_log_space = float(r2_score(np.log1p(y_holdout), y_pred_log))

    mae = float(mean_absolute_error(y_holdout, y_pred))
    holdout_mean = float(np.mean(y_holdout))
    mae_relative_pct = float(mae / holdout_mean * 100.0) if holdout_mean else float("nan")

    # Proportional error in real years — robust to the long tail and the primary
    # validated accuracy claim. Guard the denominator against any near-zero
    # lifetime so one tiny value can't blow the percentage up.
    abs_pct_err = np.abs(y_pred - y_holdout) / np.maximum(y_holdout, 1e-9) * 100.0
    median_ape_pct = float(np.median(abs_pct_err))
    p90_ape_pct = float(np.percentile(abs_pct_err, 90))

    metrics = {
        "r2": r2,
        "r2_log_space": r2_log_space,
        "mae_years": mae,
        "mae_relative_pct": mae_relative_pct,
        "median_ape_pct": median_ape_pct,
        "p90_ape_pct": p90_ape_pct,
        "n_train": int(len(X_train)),
        "n_holdout": int(len(X_holdout)),
    }
    return model, metrics


def predict_lifetime_years(
    model: RandomForestRegressor,
    mass_kg: float,
    cd: float,
    area_m2: float,
    altitude_km: float,
    k: float,
) -> float:
    """Predict decay lifetime (years) for a single mission from a trained model.

    The model was fitted in log-space (``log1p``), so its raw output is mapped
    back to real years with ``expm1`` before returning.
    """
    row = pd.DataFrame(
        [[mass_kg, cd, area_m2, altitude_km, k]], columns=FEATURE_COLUMNS
    )
    return float(np.expm1(model.predict(row)[0]))
