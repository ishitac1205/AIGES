#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"

EXPECTED_APP_SERVICES = [
    "frontend",
    "productcatalogservice",
    "cartservice",
    "recommendationservice",
    "checkoutservice",
    "paymentservice",
    "shippingservice",
    "emailservice",
    "currencyservice",
    "adservice",
    "redis-cart",
]

MODALITY_CANDIDATES = {
    "metrics": [
        "training_metrics.parquet",
        "training_metrics.csv",
        "full_metrics.parquet",
        "full_metrics.csv",
        "baseline_metrics.parquet",
        "baseline_metrics.csv",
    ],
    "logs": [
        "training_logs.parquet",
        "training_logs.csv",
        "full_logs.parquet",
        "full_logs.csv",
        "baseline_logs.parquet",
        "baseline_logs.csv",
    ],
    "log_aggregates": [
        "training_log_aggregates.parquet",
        "training_log_aggregates.csv",
        "full_log_aggregates.parquet",
        "full_log_aggregates.csv",
        "baseline_log_aggregates.parquet",
        "baseline_log_aggregates.csv",
    ],
    "traces": [
        "training_traces.parquet",
        "training_traces.csv",
        "full_traces.parquet",
        "full_traces.csv",
        "baseline_traces.parquet",
        "baseline_traces.csv",
    ],
    "observations": [
        "baseline_observations.parquet",
        "baseline_observations.csv",
    ],
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_table(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _first_existing_path(dataset_dir: Path, names: List[str]) -> Optional[Path]:
    for name in names:
        path = dataset_dir / name
        if path.exists():
            return path
    return None


def _service_column(df: pd.DataFrame) -> Optional[str]:
    for candidate in ("service_name", "service", "caller_service"):
        if candidate in df.columns:
            return candidate
    return None


def _label_distribution(df: pd.DataFrame) -> Dict[str, int]:
    result: Dict[str, int] = {}
    for col in ("failure", "pre_failure", "future_failure"):
        if col in df.columns:
            result[col] = int(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())
    if "failure_type" in df.columns:
        counts = df["failure_type"].fillna("unknown").astype(str).value_counts().to_dict()
        result["failure_type_counts"] = {str(k): int(v) for k, v in counts.items()}
    return result


def _modality_report(dataset_dir: Path, modality: str, expected_services: List[str]) -> Dict:
    path = _first_existing_path(dataset_dir, MODALITY_CANDIDATES[modality])
    if path is None:
        return {
            "present": False,
            "path": None,
            "row_count": 0,
            "service_column": None,
            "services_present": [],
            "missing_services": expected_services,
            "per_service_rows": {},
            "label_distribution": {},
        }

    df = _load_table(path)
    service_col = _service_column(df)
    services_present: List[str] = []
    per_service_rows: Dict[str, int] = {}
    if service_col:
        per_service_rows = {
            str(k): int(v)
            for k, v in df[service_col].fillna("unknown").astype(str).value_counts().sort_index().items()
        }
        services_present = sorted(service for service in per_service_rows if service in expected_services)

    missing_services = sorted(set(expected_services) - set(services_present))
    return {
        "present": True,
        "path": str(path),
        "row_count": int(len(df)),
        "service_column": service_col,
        "services_present": services_present,
        "missing_services": missing_services,
        "per_service_rows": per_service_rows,
        "label_distribution": _label_distribution(df),
    }


def _failure_run_report(payload: Dict, expected_services: List[str]) -> Dict:
    run_entries = payload.get("run_log") or payload.get("run_results") or []
    failure_targets = sorted({
        str(item.get("target_service"))
        for item in run_entries
        if item.get("target_service")
    })
    event_services = sorted({
        str(event.get("service_name"))
        for item in run_entries
        for event in item.get("failure_events", [])
        if event.get("service_name")
    })
    failed_runs = [
        {
            "run_idx": item.get("run_idx"),
            "target_service": item.get("target_service"),
            "error": item.get("error"),
        }
        for item in run_entries
        if item.get("error")
    ]
    return {
        "failure_targets": failure_targets,
        "failure_event_services": event_services,
        "missing_failure_targets": sorted(set(expected_services) - set(failure_targets)),
        "failed_runs": failed_runs,
    }


def build_audit_report(dataset_dir: Path, expected_services: Optional[List[str]] = None) -> Dict:
    expected = list(expected_services or EXPECTED_APP_SERVICES)
    summary_payload: Dict = {}
    summary_path = dataset_dir / "collection_summary.json"
    if summary_path.exists():
        summary_payload = json.loads(summary_path.read_text())
    checkpoint_path = dataset_dir / "checkpoint.json"
    if checkpoint_path.exists() and not summary_payload:
        summary_payload = json.loads(checkpoint_path.read_text())

    modalities = {
        name: _modality_report(dataset_dir, name, expected)
        for name in MODALITY_CANDIDATES
    }
    failure_report = _failure_run_report(summary_payload, expected) if summary_payload else {
        "failure_targets": [],
        "failure_event_services": [],
        "missing_failure_targets": expected,
        "failed_runs": [],
    }

    notes: List[str] = []
    for modality, report in modalities.items():
        if report["present"] and report["missing_services"]:
            notes.append(f"{modality} is missing services: {', '.join(report['missing_services'])}")
    if failure_report["failed_runs"]:
        notes.append("One or more collection runs failed before data capture completed.")
    if failure_report["failure_targets"]:
        notes.append(
            f"Failure injections cover {len(failure_report['failure_targets'])} target services: "
            f"{', '.join(failure_report['failure_targets'])}"
        )

    return {
        "generated_at": utc_now_iso(),
        "dataset_dir": str(dataset_dir),
        "expected_services": expected,
        "modalities": modalities,
        "failure_coverage": failure_report,
        "source_summary_path": str(summary_path) if summary_path.exists() else None,
        "source_checkpoint_path": str(checkpoint_path) if checkpoint_path.exists() else None,
        "notes": notes,
    }


def write_audit_report(dataset_dir: Path, expected_services: Optional[List[str]] = None) -> Path:
    report = build_audit_report(dataset_dir, expected_services=expected_services)
    output_path = dataset_dir / "dataset_audit.json"
    output_path.write_text(json.dumps(report, indent=2))
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit an AEGIS training or baseline dataset directory.")
    parser.add_argument(
        "--dataset-dir",
        default=str(REPO_ROOT / "pipeline" / "data" / "training"),
        help="Dataset directory to audit.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write dataset_audit.json into the dataset directory.",
    )
    args = parser.parse_args()

    dataset_dir = Path(args.dataset_dir).resolve()
    report = build_audit_report(dataset_dir)
    print(json.dumps(report, indent=2))
    if args.write:
        path = write_audit_report(dataset_dir)
        print(f"\nWrote audit report to {path}")


if __name__ == "__main__":
    main()
