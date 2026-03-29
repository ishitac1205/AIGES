#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import torch
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
for path in (REPO_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from anomaly_api.ingestion import ALL_SERVICES, Observation  # noqa: E402
from anomaly_api.model_features import (  # noqa: E402
    IF_FEATURES,
    LSTM_SEQUENCE_WINDOW,
    build_if_feature_vector,
    build_sequence_rows,
    normalize_sequence_array,
    rows_to_sequence_array,
)
from ml.lstm.inference import LSTMInference  # noqa: E402

APP_SERVICES = list(ALL_SERVICES)
BASELINE_ROOT = REPO_ROOT / "pipeline" / "data" / "baselines"
CURRENT_MODEL_DIR = REPO_ROOT / "new_models" / "aegis_models"
IF_ARTIFACT_ROOT = REPO_ROOT / "new_models" / "if_artifacts"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slug_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def latest_baseline_dir(root: Path) -> Path:
    candidates = sorted(
        (path for path in root.glob("if_baseline_*") if (path / "baseline_observations.parquet").exists()),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"No baseline dataset found under {root}")
    return candidates[0]


def load_observations(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path)
    if "service" not in df.columns:
        raise ValueError(f"{path} is missing the 'service' column required for IF retraining")
    return df[df["service"].isin(APP_SERVICES)].copy()


def row_to_observation(row: pd.Series) -> Observation:
    return Observation(
        timestamp=float(row.get("timestamp", 0.0) or 0.0),
        service=str(row.get("service")),
        cpu_percent=float(row.get("cpu_percent", 0.0) or 0.0),
        mem_percent=float(row.get("mem_percent", 0.0) or 0.0),
        mem_bytes=float(row.get("mem_bytes", 0.0) or 0.0),
        mem_limit_bytes=float(row.get("mem_limit_bytes", 0.0) or 0.0),
        net_rx_mbps=float(row.get("net_rx_mbps", 0.0) or 0.0),
        net_tx_mbps=float(row.get("net_tx_mbps", 0.0) or 0.0),
        block_read_mbps=float(row.get("block_read_mbps", 0.0) or 0.0),
        block_write_mbps=float(row.get("block_write_mbps", 0.0) or 0.0),
        log_count=int(row.get("log_count", 0) or 0),
        error_count=int(row.get("error_count", 0) or 0),
        warn_count=int(row.get("warn_count", 0) or 0),
        info_count=int(row.get("info_count", 0) or 0),
        error_rate=float(row.get("error_rate", 0.0) or 0.0),
        warn_rate=float(row.get("warn_rate", 0.0) or 0.0),
        exception_count=int(row.get("exception_count", 0) or 0),
        timeout_count=int(row.get("timeout_count", 0) or 0),
        template_entropy=float(row.get("template_entropy", 0.0) or 0.0),
        unique_templates=int(row.get("unique_templates", 0) or 0),
        new_templates_seen=int(row.get("new_templates_seen", 0) or 0),
        oom_mention_count=int(row.get("oom_mention_count", 0) or 0),
        avg_message_length=float(row.get("avg_message_length", 0.0) or 0.0),
        log_volume_change_pct=float(row.get("log_volume_change_pct", 0.0) or 0.0),
        trace_count=int(row.get("trace_count", 0) or 0),
        trace_error_count=int(row.get("trace_error_count", 0) or 0),
        trace_duration_mean=float(row.get("trace_duration_mean", 0.0) or 0.0),
    )


def build_if_training_windows(df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, List[Dict[str, object]]]:
    feature_rows: List[List[float]] = []
    normalized_sequences: List[np.ndarray] = []
    metadata: List[Dict[str, object]] = []

    sort_column = "timestamp"
    grouped = df.sort_values(["service", sort_column]).groupby("service")
    for service, group in grouped:
        observations = [row_to_observation(row) for _, row in group.iterrows()]
        if len(observations) < LSTM_SEQUENCE_WINDOW:
            continue
        for end_idx in range(LSTM_SEQUENCE_WINDOW, len(observations) + 1):
            window = observations[end_idx - LSTM_SEQUENCE_WINDOW:end_idx]
            rows = build_sequence_rows(window, sequence_window=LSTM_SEQUENCE_WINDOW)
            sequence_array = rows_to_sequence_array(rows)
            if_vector = build_if_feature_vector(sequence_array)
            feature_rows.append([float(if_vector[name]) for name in IF_FEATURES])
            normalized_sequences.append(normalize_sequence_array(sequence_array))
            metadata.append(
                {
                    "service": service,
                    "window_end": float(window[-1].timestamp),
                }
            )

    if not feature_rows:
        raise RuntimeError("No IF training windows could be built from the baseline dataset.")
    return (
        np.array(feature_rows, dtype=np.float32),
        np.array(normalized_sequences, dtype=np.float32),
        metadata,
    )


def batch_lstm_scores(lstm: LSTMInference, sequences: np.ndarray, batch_size: int = 256) -> np.ndarray:
    outputs: List[np.ndarray] = []
    with torch.inference_mode():
        for start in range(0, len(sequences), batch_size):
            batch = torch.from_numpy(sequences[start:start + batch_size].astype(np.float32))
            result = lstm.model(batch)  # type: ignore[arg-type]
            outputs.append(result["failure_probability"].cpu().numpy().reshape(-1))
    return np.concatenate(outputs) if outputs else np.array([], dtype=np.float32)


def score_with_if(model, scaler, threshold: float, features: np.ndarray) -> np.ndarray:
    scaled = scaler.transform(features)
    raw = model.decision_function(scaled)
    delta = threshold - raw
    scores = 1.0 / (1.0 + np.exp(-6.0 * delta))
    return np.clip(scores.astype(np.float32), 0.0, 1.0)


def load_if_payload(model_dir: Path):
    with open(model_dir / "if_model.pkl", "rb") as handle:
        payload = pickle.load(handle)
    model = payload["model"] if isinstance(payload, dict) else payload
    threshold = float(payload.get("threshold", 0.0)) if isinstance(payload, dict) else 0.0
    with open(model_dir / "scaler.pkl", "rb") as handle:
        scaler = pickle.load(handle)
    return model, scaler, threshold


def safe_auc(labels: np.ndarray, scores: np.ndarray) -> float | None:
    if len(np.unique(labels)) < 2:
        return None
    return float(roc_auc_score(labels, scores))


def safe_ap(labels: np.ndarray, scores: np.ndarray) -> float | None:
    if len(np.unique(labels)) < 2:
        return None
    return float(average_precision_score(labels, scores))


def stats(values: np.ndarray) -> Dict[str, float]:
    return {
        "mean": round(float(np.mean(values)), 4),
        "median": round(float(np.median(values)), 4),
        "p95": round(float(np.percentile(values, 95)), 4),
        "p99": round(float(np.percentile(values, 99)), 4),
        "max": round(float(np.max(values)), 4),
        "min": round(float(np.min(values)), 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrain the Isolation Forest on a clean baseline dataset.")
    parser.add_argument(
        "--baseline-dir",
        default="",
        help="Baseline dataset directory. Defaults to the latest under pipeline/data/baselines.",
    )
    parser.add_argument(
        "--artifact-root",
        default=str(IF_ARTIFACT_ROOT),
        help="Directory where versioned IF artifacts should be written.",
    )
    parser.add_argument(
        "--artifact-name",
        default="",
        help="Optional artifact directory name. Defaults to if_baseline_<timestamp>.",
    )
    args = parser.parse_args()

    baseline_dir = Path(args.baseline_dir).resolve() if args.baseline_dir else latest_baseline_dir(BASELINE_ROOT)
    observations_path = baseline_dir / "baseline_observations.parquet"
    if not observations_path.exists():
        observations_path = baseline_dir / "baseline_observations.csv"
    if not observations_path.exists():
        raise FileNotFoundError(f"No baseline observations file found in {baseline_dir}")

    observations_df = load_observations(observations_path)
    X_baseline, sequences_baseline, window_meta = build_if_training_windows(observations_df)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_baseline)
    model = IsolationForest(
        n_estimators=200,
        contamination=0.05,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_scaled)

    training_raw = model.decision_function(X_scaled)
    threshold = float(np.percentile(training_raw, 5))
    score_range = (float(np.min(training_raw)), float(np.max(training_raw)))

    artifact_root = Path(args.artifact_root).resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    artifact_name = args.artifact_name or f"if_baseline_{slug_now()}"
    artifact_dir = artifact_root / artifact_name
    artifact_dir.mkdir(parents=True, exist_ok=True)

    with open(artifact_dir / "if_model.pkl", "wb") as handle:
        pickle.dump(
            {
                "model": model,
                "threshold": threshold,
                "score_range": score_range,
            },
            handle,
        )
    with open(artifact_dir / "scaler.pkl", "wb") as handle:
        pickle.dump(scaler, handle)

    old_model, old_scaler, old_threshold = load_if_payload(CURRENT_MODEL_DIR)
    new_model, new_scaler, new_threshold = load_if_payload(artifact_dir)

    lstm = LSTMInference()
    lstm.load()
    baseline_lstm_scores = batch_lstm_scores(lstm, sequences_baseline)
    baseline_old_if_scores = score_with_if(old_model, old_scaler, old_threshold, X_baseline)
    baseline_new_if_scores = score_with_if(new_model, new_scaler, new_threshold, X_baseline)
    baseline_old_combined = 0.45 * baseline_old_if_scores + 0.55 * baseline_lstm_scores
    baseline_new_combined = 0.45 * baseline_new_if_scores + 0.55 * baseline_lstm_scores

    labeled_features = np.load(CURRENT_MODEL_DIR / "X_features_2d.npy").astype(np.float32)
    y_failure = np.load(CURRENT_MODEL_DIR / "y_failure.npy").astype(np.int32)
    y_pre_failure = np.load(CURRENT_MODEL_DIR / "y_pre_failure.npy").astype(np.int32)
    old_labeled_if_scores = score_with_if(old_model, old_scaler, old_threshold, labeled_features)
    new_labeled_if_scores = score_with_if(new_model, new_scaler, new_threshold, labeled_features)

    metadata = {
        "generated_at": utc_now(),
        "baseline_dir": str(baseline_dir),
        "feature_count": int(X_baseline.shape[1]),
        "window_count": int(X_baseline.shape[0]),
        "window_size": int(LSTM_SEQUENCE_WINDOW),
        "services": sorted({item["service"] for item in window_meta}),
        "threshold": round(threshold, 6),
        "score_range": [round(score_range[0], 6), round(score_range[1], 6)],
        "lstm_model_dir": str(CURRENT_MODEL_DIR),
        "if_switch_env": f"AEGIS_IF_MODEL_DIR={artifact_dir.relative_to(REPO_ROOT)}",
    }
    (artifact_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    evaluation = {
        "generated_at": utc_now(),
        "baseline": {
            "window_count": int(X_baseline.shape[0]),
            "services": sorted({item["service"] for item in window_meta}),
            "old_if_score": stats(baseline_old_if_scores),
            "new_if_score": stats(baseline_new_if_scores),
            "lstm_score": stats(baseline_lstm_scores),
            "old_combined_score": stats(baseline_old_combined),
            "new_combined_score": stats(baseline_new_combined),
        },
        "labeled_corpus": {
            "sample_count": int(len(labeled_features)),
            "failure_positive_rate": round(float(np.mean(y_failure)), 4),
            "pre_failure_positive_rate": round(float(np.mean(y_pre_failure)), 4),
            "old_if_failure_auc": safe_auc(y_failure, old_labeled_if_scores),
            "new_if_failure_auc": safe_auc(y_failure, new_labeled_if_scores),
            "old_if_failure_ap": safe_ap(y_failure, old_labeled_if_scores),
            "new_if_failure_ap": safe_ap(y_failure, new_labeled_if_scores),
            "old_if_pre_failure_auc": safe_auc(y_pre_failure, old_labeled_if_scores),
            "new_if_pre_failure_auc": safe_auc(y_pre_failure, new_labeled_if_scores),
            "old_if_pre_failure_ap": safe_ap(y_pre_failure, old_labeled_if_scores),
            "new_if_pre_failure_ap": safe_ap(y_pre_failure, new_labeled_if_scores),
        },
    }
    (artifact_dir / "evaluation.json").write_text(json.dumps(evaluation, indent=2))

    print("=" * 72)
    print("Retrained IF baseline artifact")
    print(f"Baseline dataset : {baseline_dir}")
    print(f"Artifact dir     : {artifact_dir}")
    print(f"Window count     : {X_baseline.shape[0]}")
    print(f"Baseline old IF  : mean={evaluation['baseline']['old_if_score']['mean']}")
    print(f"Baseline new IF  : mean={evaluation['baseline']['new_if_score']['mean']}")
    print(f"Baseline old cmb : mean={evaluation['baseline']['old_combined_score']['mean']}")
    print(f"Baseline new cmb : mean={evaluation['baseline']['new_combined_score']['mean']}")
    print(f"Failure AUC old/new IF : {evaluation['labeled_corpus']['old_if_failure_auc']} / {evaluation['labeled_corpus']['new_if_failure_auc']}")
    print(f"Suggested switch : export AEGIS_IF_MODEL_DIR={artifact_dir.relative_to(REPO_ROOT)}")
    print("=" * 72)


if __name__ == "__main__":
    main()
