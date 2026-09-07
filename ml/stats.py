"""Training-input statistics for the "far from the training data" warning (M8 polish).

    python -m ml.stats      # writes models/input_stats.json

The Predict form accepts any valid funnel, and the models will happily extrapolate (an all-zero
funnel still returns a plausible-looking lifetime). `novelty()` measures how unusual an input is:
the largest absolute z-score across the FUNNEL_RAW features, against the customers the models
were trained on. The API returns it with every LTV prediction; the dashboard shows a warning
above NOVELTY_WARN_Z.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ml.data import clean, customers_only, load_raw
from ml.features import FUNNEL_RAW
from ml.registry import MODELS_DIR

STATS_FILE = "input_stats.json"
NOVELTY_WARN_Z = 3.0  # beyond ~3 standard deviations on any feature the prediction is an extrapolation


def input_stats(df: pd.DataFrame) -> dict:
    """Mean, std, min and max of every FUNNEL_RAW feature over the training customers."""
    cols = df[FUNNEL_RAW].astype(float)
    return {
        "n": int(len(df)),
        "policy": "customers only (purchased = 1), the frame the P2/P3/P4 models are trained on",
        "features": {
            c: {
                "mean": round(float(cols[c].mean()), 4),
                "std": round(float(cols[c].std()), 4),
                "min": float(cols[c].min()),
                "max": float(cols[c].max()),
            }
            for c in FUNNEL_RAW
        },
        "warn_z": NOVELTY_WARN_Z,
    }


def novelty(customer: dict, stats: dict) -> dict:
    """Largest |z| over the funnel features, the feature that produced it, and whether to warn."""
    worst_feature, worst_z = None, 0.0
    outside = []
    for c in FUNNEL_RAW:
        s = stats["features"][c]
        value = float(customer[c])
        if s["std"] > 0:
            z = abs(value - s["mean"]) / s["std"]
        else:
            z = 0.0 if value == s["mean"] else float("inf")
        if z > worst_z:
            worst_feature, worst_z = c, z
        if value < s["min"] or value > s["max"]:
            outside.append(c)
    warn_z = stats.get("warn_z", NOVELTY_WARN_Z)
    flag = worst_z >= warn_z or bool(outside)
    if not flag:
        note = ""
    elif outside:
        note = (
            f"{', '.join(outside)} outside the range seen in training — the prediction is an extrapolation; "
            "treat it as a rough guess."
        )
    else:
        note = (
            f"{worst_feature} is {worst_z:.1f} standard deviations from the typical customer — "
            "few training examples look like this; treat the prediction as a rough guess."
        )
    return {
        "max_z": round(worst_z, 2) if worst_z != float("inf") else None,
        "feature": worst_feature,
        "outside_training_range": outside,
        "flag": flag,
        "note": note,
    }


def write_stats(models_dir: Path = MODELS_DIR) -> Path:
    stats = input_stats(customers_only(clean(load_raw())))
    path = Path(models_dir) / STATS_FILE
    path.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    return path


def load_stats(models_dir: Path = MODELS_DIR) -> dict | None:
    path = Path(models_dir) / STATS_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


if __name__ == "__main__":
    print(f"wrote {write_stats()}")
