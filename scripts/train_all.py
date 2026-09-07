"""Retrain every model and regenerate every generated document, in dependency order.

    python scripts/train_all.py

Writes models/*.joblib, models/metrics.json, models/profiles.json, models/input_stats.json,
docs/FINDINGS.md and the REPORT.md sections that are rendered from code (§P5, §P6).
Commit the results: the API loads the committed artifacts at startup (design decision D2).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> None:
    from ml import eda, followups, simulator, stats, train_ltv, train_profit, train_super, train_upsell
    from ml.data import clean, load_raw
    from ml.registry import MODELS_DIR, ModelRegistry

    df = clean(load_raw())

    print("== P1 findings")
    findings = eda.render_findings_md(eda.overview_stats(df))
    (ROOT / "docs" / "FINDINGS.md").write_text(findings, encoding="utf-8")
    print("== P2 lifetime")
    train_ltv.train(MODELS_DIR)
    print("== P3 upsell")
    train_upsell.train(MODELS_DIR)
    print("== P4 super customer")
    train_super.train(MODELS_DIR)
    print("== P5 follow-ups")
    followups.write_report(followups.followup_insights(df))
    print("== P6 profit + simulator")
    train_profit.train(MODELS_DIR)
    registry = ModelRegistry.load(MODELS_DIR)
    simulator.write_report(simulator.rank_presets(registry), registry.metrics["profit"])
    print("== input statistics (novelty warning)")
    stats.write_stats(MODELS_DIR)
    print("done — review `git diff models/ docs/` and commit")


if __name__ == "__main__":
    main()
