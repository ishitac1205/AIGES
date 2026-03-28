import os
import sys
import unittest
from collections import deque
from unittest.mock import patch

from starlette.requests import Request


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BACKEND_ROOT = os.path.join(REPO_ROOT, "backend")
for path in [REPO_ROOT, BACKEND_ROOT]:
    if path not in sys.path:
        sys.path.insert(0, path)

from remediation.models import WorkloadState

from anomaly_api.main import (
    _has_usable_telemetry,
    _predictive_auto_action_allowed,
    _public_demo_cooldown_remaining,
    _public_demo_rate_limit_snapshot,
    _public_demo_status,
    state,
    _runtime_failure_context,
)


class MainRuntimeTests(unittest.TestCase):
    def test_telemetry_gate_blocks_empty_rows(self):
        self.assertFalse(
            _has_usable_telemetry(
                {"cpu_percent_mean": 0.0, "mem_percent_mean": 0.0, "log_count_mean": 0.0},
                [
                    {
                        "cpu_usage_percent": 0.0,
                        "memory_usage_bytes": 0.0,
                        "memory_limit_bytes": 0.0,
                        "memory_usage_percent": 0.0,
                        "network_rx_bytes_per_sec": 0.0,
                        "network_tx_bytes_per_sec": 0.0,
                        "fs_reads_per_sec": 0.0,
                        "fs_writes_per_sec": 0.0,
                        "request_rate": 0.0,
                        "error_rate": 0.0,
                        "total_log_lines": 0.0,
                        "trace_count": 0.0,
                    }
                ],
            )
        )

    def test_telemetry_gate_accepts_real_resource_signal(self):
        self.assertTrue(
            _has_usable_telemetry(
                {"cpu_percent_mean": 0.0, "mem_percent_mean": 0.0, "log_count_mean": 0.0},
                [
                    {
                        "cpu_usage_percent": 0.0,
                        "memory_usage_bytes": 67108864.0,
                        "memory_limit_bytes": 268435456.0,
                        "memory_usage_percent": 25.0,
                        "network_rx_bytes_per_sec": 0.0,
                        "network_tx_bytes_per_sec": 0.0,
                        "fs_reads_per_sec": 0.0,
                        "fs_writes_per_sec": 0.0,
                        "request_rate": 0.0,
                        "error_rate": 0.0,
                        "total_log_lines": 0.0,
                        "trace_count": 0.0,
                    }
                ],
            )
        )

    def test_runtime_failure_context_prefers_dependency_failure_for_shared_service(self):
        context = _runtime_failure_context(
            "redis-cart",
            WorkloadState(
                service="redis-cart",
                exists=True,
                running=False,
                healthy=False,
                status="degraded",
                restart_count=4,
            ),
            {
                "redis-cart": {
                    "feature_flags": [],
                }
            },
        )
        self.assertIsNotNone(context)
        self.assertEqual(context["failure_type"], "dependency_failure")
        self.assertIn("cartservice", context["affected_services"])

    def test_runtime_failure_context_detects_memory_leak_from_oom(self):
        context = _runtime_failure_context(
            "recommendationservice",
            WorkloadState(
                service="recommendationservice",
                exists=True,
                running=True,
                healthy=False,
                status="degraded",
                oom_killed=True,
            ),
            {
                "recommendationservice": {
                    "feature_flags": [],
                }
            },
        )
        self.assertIsNotNone(context)
        self.assertEqual(context["failure_type"], "memory_leak")
        self.assertEqual(context["trigger_count"], 2)

    def test_runtime_failure_context_applies_startup_grace_during_rollout(self):
        context = _runtime_failure_context(
            "recommendationservice",
            WorkloadState(
                service="recommendationservice",
                exists=True,
                running=True,
                healthy=False,
                status="degraded",
                restart_count=0,
                metadata={
                    "desired_replicas": 1,
                    "ready_replicas": 0,
                    "available_replicas": 0,
                },
            ),
            {
                "recommendationservice": {
                    "feature_flags": [],
                }
            },
        )
        self.assertIsNotNone(context)
        self.assertTrue(context["startup_grace"])
        self.assertEqual(context["trigger_count"], 10)

    def test_predictive_auto_action_requires_specific_corroborated_failure(self):
        self.assertFalse(
            _predictive_auto_action_allowed(
                {
                    "combined_score": 0.72,
                    "feature_flags": ["memory_trending_up", "network_drop"],
                },
                "generic_anomaly",
                0.96,
            )
        )
        self.assertTrue(
            _predictive_auto_action_allowed(
                {
                    "combined_score": 0.79,
                    "feature_flags": ["memory_pressure"],
                },
                "memory_leak",
                0.96,
            )
        )

    def test_public_demo_cooldown_uses_latest_demo_timestamp(self):
        with patch("anomaly_api.main.latest_demo_run", return_value={"updated_at": "2099-01-01T00:00:00+00:00"}):
            remaining = _public_demo_cooldown_remaining(now=0.0)
            self.assertGreaterEqual(remaining, 0.0)

    def test_public_demo_status_reports_active_run(self):
        done_task = type("DoneTask", (), {"done": lambda self: True})()
        prior_task = state.demo_task
        state.demo_task = done_task
        try:
            with patch("anomaly_api.main.latest_demo_run", return_value={"id": 7, "status": "running"}):
                status = _public_demo_status()
                self.assertTrue(status["active"])
                self.assertEqual(status["latest_run_id"], 7)
        finally:
            state.demo_task = prior_task

    def test_public_demo_rate_limit_snapshot_tracks_forwarded_ip(self):
        prior_requests = state.public_demo_requests
        state.public_demo_requests = {"198.51.100.4": deque([100.0, 150.0])}
        request = Request(
            {
                "type": "http",
                "headers": [(b"x-forwarded-for", b"198.51.100.4")],
                "client": ("127.0.0.1", 4321),
            }
        )
        try:
            snapshot = _public_demo_rate_limit_snapshot(request, now=200.0)
            self.assertEqual(snapshot["client_id"], "198.51.100.4")
            self.assertGreaterEqual(snapshot["limit"], snapshot["recent_count"])
        finally:
            state.public_demo_requests = prior_requests


if __name__ == "__main__":
    unittest.main()
