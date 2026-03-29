#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import docker
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
for path in (REPO_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from anomaly_api.ingestion import (  # noqa: E402
    ALL_SERVICES,
    DOCKER_POLL_INTERVAL,
    LOKI_POLL_INTERVAL,
    TRACE_POLL_INTERVAL,
    DockerStatsCollector,
    JaegerCollector,
    LokiCollector,
    Observation,
)
from pipeline.scripts.dataset_audit import write_audit_report  # noqa: E402

APP_SERVICES = list(ALL_SERVICES)
BASELINE_ROOT = REPO_ROOT / "pipeline" / "data" / "baselines"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def slug(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def ensure_docker_stack() -> Dict[str, bool]:
    client = docker.from_env()
    running = {container.name.lstrip("/"): True for container in client.containers.list()}
    return {
        "loadgenerator_running": running.get("loadgenerator", False),
        "promtail_running": running.get("promtail", False),
        "loki_running": running.get("loki", False),
        "jaeger_running": running.get("jaeger", False),
    }


def save_table(output_dir: Path, name: str, rows: List[Dict]) -> int:
    if not rows:
        return 0
    df = pd.DataFrame(rows)
    df.to_parquet(output_dir / f"{name}.parquet", index=False)
    df.to_csv(output_dir / f"{name}.csv", index=False)
    return len(df)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect a clean baseline IF dataset from the live Docker runtime.")
    parser.add_argument("--duration-seconds", type=int, default=3600, help="Collection duration in seconds.")
    parser.add_argument(
        "--output-root",
        default=str(BASELINE_ROOT),
        help="Root directory for baseline datasets.",
    )
    parser.add_argument(
        "--name",
        default="",
        help="Optional directory name. Defaults to if_baseline_<timestamp>.",
    )
    args = parser.parse_args()

    docker_status = ensure_docker_stack()
    metrics_collector = DockerStatsCollector()
    if not getattr(metrics_collector, "_available", False):
        raise SystemExit("Docker is not available. Start Docker Desktop and the Compose stack first.")
    loki_collector = LokiCollector()
    jaeger_collector = JaegerCollector()

    started_at = utc_now()
    output_root = Path(args.output_root).resolve()
    dataset_name = args.name or f"if_baseline_{slug(started_at)}"
    output_dir = output_root / dataset_name
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("Collecting clean IF baseline telemetry")
    print(f"Output directory: {output_dir}")
    print(f"Duration: {args.duration_seconds}s")
    print(f"Target services: {', '.join(APP_SERVICES)}")
    print("=" * 72)

    metrics_rows: List[Dict] = []
    log_rows: List[Dict] = []
    trace_rows: List[Dict] = []
    observation_rows: List[Dict] = []

    last_loki_poll = 0.0
    last_trace_poll = 0.0
    loki_cache: Dict[str, Dict] = {service: {} for service in APP_SERVICES}
    trace_cache: Dict[str, Dict] = {service: {} for service in APP_SERVICES}
    tick_count = 0

    deadline = time.time() + float(args.duration_seconds)
    next_tick = time.time()
    while time.time() < deadline:
        timestamp = utc_now()
        tick_count += 1
        metrics_map = metrics_collector.poll()

        now = time.time()
        if now - last_loki_poll >= LOKI_POLL_INTERVAL:
            loki_cache = loki_collector.poll(lookback_seconds=LOKI_POLL_INTERVAL + 2)
            last_loki_poll = now
        if now - last_trace_poll >= TRACE_POLL_INTERVAL:
            trace_cache = jaeger_collector.poll(lookback_seconds=TRACE_POLL_INTERVAL + 2)
            last_trace_poll = now

        for service in APP_SERVICES:
            ds = metrics_map.get(service, {})
            ls = loki_cache.get(service, {})
            ts = trace_cache.get(service, {})

            metrics_rows.append({
                "timestamp": iso(timestamp),
                "timestamp_epoch": timestamp.timestamp(),
                "service_name": service,
                "cpu_percent": float(ds.get("cpu_percent", 0.0) or 0.0),
                "mem_percent": float(ds.get("mem_percent", 0.0) or 0.0),
                "mem_bytes": float(ds.get("mem_bytes", 0.0) or 0.0),
                "mem_limit_bytes": float(ds.get("mem_limit_bytes", 0.0) or 0.0),
                "net_rx_mbps": float(ds.get("net_rx_mbps", 0.0) or 0.0),
                "net_tx_mbps": float(ds.get("net_tx_mbps", 0.0) or 0.0),
                "block_read_mbps": float(ds.get("block_read_mbps", 0.0) or 0.0),
                "block_write_mbps": float(ds.get("block_write_mbps", 0.0) or 0.0),
            })
            log_rows.append({
                "timestamp": iso(timestamp),
                "timestamp_epoch": timestamp.timestamp(),
                "service_name": service,
                "log_count": int(ls.get("log_count", 0) or 0),
                "error_count": int(ls.get("error_count", 0) or 0),
                "warn_count": int(ls.get("warn_count", 0) or 0),
                "info_count": int(ls.get("info_count", 0) or 0),
                "exception_count": int(ls.get("exception_count", 0) or 0),
                "timeout_count": int(ls.get("timeout_count", 0) or 0),
                "oom_mention_count": int(ls.get("oom_mention_count", 0) or 0),
                "template_entropy": float(ls.get("template_entropy", 0.0) or 0.0),
                "unique_templates": int(ls.get("unique_templates", 0) or 0),
                "new_templates_seen": int(ls.get("new_templates_seen", 0) or 0),
                "avg_message_length": float(ls.get("avg_message_length", 0.0) or 0.0),
                "log_volume_change_pct": float(ls.get("log_volume_change_pct", 0.0) or 0.0),
            })
            trace_rows.append({
                "timestamp": iso(timestamp),
                "timestamp_epoch": timestamp.timestamp(),
                "service_name": service,
                "trace_count": int(ts.get("trace_count", 0) or 0),
                "trace_error_count": int(ts.get("trace_error_count", 0) or 0),
                "trace_duration_mean": float(ts.get("trace_duration_mean", 0.0) or 0.0),
            })

            log_count = int(ls.get("log_count", 0) or 0)
            error_count = int(ls.get("error_count", 0) or 0)
            warn_count = int(ls.get("warn_count", 0) or 0)
            obs = Observation(
                timestamp=timestamp.timestamp(),
                service=service,
                cpu_percent=float(ds.get("cpu_percent", 0.0) or 0.0),
                mem_percent=float(ds.get("mem_percent", 0.0) or 0.0),
                mem_bytes=float(ds.get("mem_bytes", 0.0) or 0.0),
                mem_limit_bytes=float(ds.get("mem_limit_bytes", 0.0) or 0.0),
                net_rx_mbps=float(ds.get("net_rx_mbps", 0.0) or 0.0),
                net_tx_mbps=float(ds.get("net_tx_mbps", 0.0) or 0.0),
                block_read_mbps=float(ds.get("block_read_mbps", 0.0) or 0.0),
                block_write_mbps=float(ds.get("block_write_mbps", 0.0) or 0.0),
                log_count=log_count,
                error_count=error_count,
                warn_count=warn_count,
                info_count=int(ls.get("info_count", 0) or 0),
                error_rate=error_count / max(log_count, 1),
                warn_rate=warn_count / max(log_count, 1),
                exception_count=int(ls.get("exception_count", 0) or 0),
                timeout_count=int(ls.get("timeout_count", 0) or 0),
                template_entropy=float(ls.get("template_entropy", 0.0) or 0.0),
                log_volume_per_sec=log_count / float(LOKI_POLL_INTERVAL),
                unique_templates=int(ls.get("unique_templates", 0) or 0),
                new_templates_seen=int(ls.get("new_templates_seen", 0) or 0),
                oom_mention_count=int(ls.get("oom_mention_count", 0) or 0),
                avg_message_length=float(ls.get("avg_message_length", 0.0) or 0.0),
                log_volume_change_pct=float(ls.get("log_volume_change_pct", 0.0) or 0.0),
                trace_count=int(ts.get("trace_count", 0) or 0),
                trace_error_count=int(ts.get("trace_error_count", 0) or 0),
                trace_duration_mean=float(ts.get("trace_duration_mean", 0.0) or 0.0),
            )
            obs_row = asdict(obs)
            obs_row["timestamp_iso"] = iso(timestamp)
            observation_rows.append(obs_row)

        if tick_count % max(int(60 / max(DOCKER_POLL_INTERVAL, 1)), 1) == 0:
            remaining = max(int(deadline - time.time()), 0)
            print(f"[baseline] tick={tick_count} remaining={remaining}s")

        next_tick += DOCKER_POLL_INTERVAL
        sleep_for = max(0.0, next_tick - time.time())
        if sleep_for:
            time.sleep(sleep_for)

    finished_at = utc_now()
    metrics_count = save_table(output_dir, "baseline_metrics", metrics_rows)
    logs_count = save_table(output_dir, "baseline_logs", log_rows)
    log_agg_count = save_table(output_dir, "baseline_log_aggregates", log_rows)
    traces_count = save_table(output_dir, "baseline_traces", trace_rows)
    obs_count = save_table(output_dir, "baseline_observations", observation_rows)

    summary = {
        "generated_at": iso(finished_at),
        "collection_start": iso(started_at),
        "collection_end": iso(finished_at),
        "duration_seconds_requested": int(args.duration_seconds),
        "duration_seconds_actual": round((finished_at - started_at).total_seconds(), 2),
        "poll_interval_seconds": DOCKER_POLL_INTERVAL,
        "loki_poll_interval_seconds": LOKI_POLL_INTERVAL,
        "trace_poll_interval_seconds": TRACE_POLL_INTERVAL,
        "target_services": APP_SERVICES,
        "tick_count": tick_count,
        "rows": {
            "baseline_metrics": metrics_count,
            "baseline_logs": logs_count,
            "baseline_log_aggregates": log_agg_count,
            "baseline_traces": traces_count,
            "baseline_observations": obs_count,
        },
        "runtime_checks": docker_status,
        "notes": [
            "This collection is clean baseline traffic only; no failure injections are performed.",
            "Application services only are included in the saved baseline dataset.",
        ],
    }
    (output_dir / "collection_summary.json").write_text(json.dumps(summary, indent=2))
    audit_path = write_audit_report(output_dir, expected_services=APP_SERVICES)

    print(f"\nSaved clean IF baseline dataset to {output_dir}")
    print(f"Audit written to {audit_path}")


if __name__ == "__main__":
    main()
