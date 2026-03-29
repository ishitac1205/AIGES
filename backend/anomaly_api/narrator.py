"""
AEGIS Incident Narrator
=======================
Converts structured incident data (feature flags, metrics, workload state,
remediation result) into plain-English narratives a non-technical user can read.

All functions are pure (no I/O, no side effects) — they take dicts and return
strings or dicts. Wire them in at report/summary generation time.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ── Service display names ─────────────────────────────────────────────────────

_SERVICE_LABELS: Dict[str, str] = {
    "frontend":              "the storefront",
    "productcatalogservice": "the product catalog",
    "cartservice":           "the shopping cart",
    "recommendationservice": "the recommendation engine",
    "checkoutservice":       "the checkout service",
    "paymentservice":        "the payment processor",
    "shippingservice":       "the shipping service",
    "emailservice":          "the email service",
    "currencyservice":       "the currency converter",
    "adservice":             "the ad service",
    "redis-cart":            "the session cache (Redis)",
}

def _label(service: str) -> str:
    return _SERVICE_LABELS.get(service, f"the {service} service")


# ── Action display names ──────────────────────────────────────────────────────

_ACTION_LABELS: Dict[str, str] = {
    "start_service":             "restarted the stopped container",
    "restart_service":           "force-restarted the service",
    "restart_dependency_chain":  "restarted the service and its dependencies in order",
    "isolate_service":           "isolated the service to stop cascading failures",
    "reroute_service":           "rerouted traffic to a healthy instance",
    "escalate_incident":         "escalated to manual review",
    "noop":                      "took no action (no automated fix available)",
}

def _action_label(action: str) -> str:
    return _ACTION_LABELS.get(action, action.replace("_", " "))


# ── Feature flag → human sentence ────────────────────────────────────────────

_FLAG_SENTENCES: Dict[str, str] = {
    "memory_high":          "memory usage was critically high",
    "memory_trending_up":   "memory was steadily climbing",
    "cpu_spike":            "CPU spiked sharply",
    "cpu_trending_up":      "CPU usage was trending upward",
    "error_rate_high":      "the error rate was elevated",
    "error_rate_rising":    "errors were increasing",
    "exceptions_detected":  "exceptions were being thrown",
    "network_drop":         "network throughput dropped",
    "log_volume_spike":     "log output spiked abnormally",
    "io_high":              "disk I/O was unusually high",
    "memory_pressure":      "the service was under memory pressure",
    "cpu_pressure":         "the service was under CPU pressure",
    "network_pressure":     "network was under pressure",
    "error_burst":          "a burst of errors occurred",
}

def _flags_to_sentences(flags: List[str]) -> List[str]:
    return [_FLAG_SENTENCES[f] for f in flags if f in _FLAG_SENTENCES]


# ── Failure type → plain English cause ───────────────────────────────────────

_FAILURE_CAUSES: Dict[str, str] = {
    "memory_leak":          "a memory leak caused the service to exhaust available RAM",
    "cpu_starvation":       "the service was starved of CPU and became unresponsive",
    "network_latency":      "network latency degraded communication between services",
    "dependency_failure":   "a dependency the service relies on became unavailable",
    "log_exception_storm":  "an exception storm flooded the logs and destabilised the service",
    "service_unhealthy":    "the service stopped responding and was no longer healthy",
    "generic_anomaly":      "an anomaly was detected that did not match a known failure pattern",
}

def _failure_cause(failure_type: str) -> str:
    return _FAILURE_CAUSES.get(failure_type, f"a {failure_type.replace('_', ' ')} condition was detected")


# ── Metric change description ─────────────────────────────────────────────────

def _metric_change(before: Dict, after: Dict) -> Optional[str]:
    """Return a sentence describing the most significant metric change, or None."""
    parts = []

    cpu_b = float(before.get("cpu_percent", 0) or 0)
    cpu_a = float(after.get("cpu_percent", 0) or 0)
    mem_b = float(before.get("mem_percent", 0) or 0)
    mem_a = float(after.get("mem_percent", 0) or 0)
    score_b = float(before.get("combined_score", 0) or before.get("score", 0) or 0)
    score_a = float(after.get("combined_score", 0) or after.get("score", 0) or 0)

    if mem_b > 0 and mem_a > 0:
        if mem_b > 60 and mem_a < mem_b - 10:
            parts.append(f"memory dropped from {mem_b:.0f}% to {mem_a:.0f}%")
        elif mem_a > 70:
            parts.append(f"memory was at {mem_a:.0f}%")

    if cpu_b > 0 and cpu_a > 0:
        if cpu_b > 50 and cpu_a < cpu_b - 15:
            parts.append(f"CPU recovered from {cpu_b:.0f}% to {cpu_a:.0f}%")
        elif cpu_a > 60:
            parts.append(f"CPU was at {cpu_a:.0f}%")

    if score_b > 0.3 and score_a < score_b - 0.1:
        parts.append(f"anomaly score fell from {score_b:.2f} to {score_a:.2f}")

    if not parts:
        return None
    return "; ".join(parts)


# ── Affected services description ─────────────────────────────────────────────

def _affected_services_sentence(affected: List[str], root_cause: str) -> Optional[str]:
    others = [s for s in affected if s != root_cause]
    if not others:
        return None
    if len(others) == 1:
        return f"This also disrupted {_label(others[0])}."
    listed = ", ".join(_label(s) for s in others[:3])
    suffix = f" and {len(others) - 3} more" if len(others) > 3 else ""
    return f"This cascaded to {listed}{suffix}."


# ── Propagation path description ──────────────────────────────────────────────

def _propagation_sentence(path: List[str]) -> Optional[str]:
    if len(path) < 2:
        return None
    labels = [_label(s) for s in path[:4]]
    arrow = " → ".join(labels)
    return f"Failure propagated: {arrow}."


# ── Elapsed time description ──────────────────────────────────────────────────

def _elapsed_sentence(detection_s: Optional[float], remediation_s: Optional[float]) -> str:
    parts = []
    if detection_s is not None and detection_s > 0:
        parts.append(f"detected in {detection_s:.1f}s")
    if remediation_s is not None and remediation_s > 0:
        parts.append(f"fixed in {remediation_s:.1f}s")
    if not parts:
        return ""
    return "AEGIS " + " and ".join(parts) + "."


# ── Main entry point ──────────────────────────────────────────────────────────

def build_narrative(
    *,
    service: str,
    failure_type: str,
    feature_flags: List[str],
    action: str,
    outcome: str,                      # "resolved" | "contained" | "degraded" | "manual_required"
    before_snapshot: Optional[Dict] = None,
    after_snapshot: Optional[Dict] = None,
    affected_services: Optional[List[str]] = None,
    propagation_path: Optional[List[str]] = None,
    detection_s: Optional[float] = None,
    remediation_s: Optional[float] = None,
    platform: str = "docker",
) -> Dict[str, str]:
    """
    Returns a dict with three plain-English fields:

      what_happened  — what went wrong and what AEGIS observed
      what_was_done  — the action taken and why
      outcome_text   — what the result was, including metrics and timing
      plain_summary  — single paragraph combining all three (for UI display)
    """
    before = before_snapshot or {}
    after  = after_snapshot  or {}

    # ── What happened ─────────────────────────────────────────────────────────
    cause = _failure_cause(failure_type)
    flag_sentences = _flags_to_sentences(feature_flags)

    what_happened_parts = [f"{_label(service).capitalize()} went down — {cause}."]
    if flag_sentences:
        indicators = "; ".join(flag_sentences[:3])
        what_happened_parts.append(f"Key indicators: {indicators}.")

    cascade = _affected_services_sentence(affected_services or [], service)
    if cascade:
        what_happened_parts.append(cascade)

    prop = _propagation_sentence(propagation_path or [])
    if prop:
        what_happened_parts.append(prop)

    what_happened = " ".join(what_happened_parts)

    # ── What was done ─────────────────────────────────────────────────────────
    action_desc = _action_label(action)
    what_was_done = f"AEGIS autonomously {action_desc}."

    # ── Outcome ───────────────────────────────────────────────────────────────
    if outcome == "resolved":
        outcome_line = f"{_label(service).capitalize()} is healthy again."
    elif outcome == "contained":
        outcome_line = f"{_label(service).capitalize()} was isolated to prevent further impact."
    elif outcome == "manual_required":
        outcome_line = "Automated recovery was insufficient — manual intervention is required."
    else:
        outcome_line = f"{_label(service).capitalize()} is still degraded."

    metric_change = _metric_change(before, after)
    if metric_change:
        outcome_line += f" ({metric_change}.)"

    timing = _elapsed_sentence(detection_s, remediation_s)
    if timing:
        outcome_line += f" {timing}"

    outcome_text = outcome_line

    # ── Plain summary (single paragraph) ─────────────────────────────────────
    plain_summary = f"{what_happened} {what_was_done} {outcome_text}"

    return {
        "what_happened": what_happened,
        "what_was_done": what_was_done,
        "outcome_text":  outcome_text,
        "plain_summary": plain_summary,
    }


def build_demo_narrative(
    *,
    service: str,
    action: str,
    outcome: str,
    elapsed_s: Optional[float] = None,
    before_snapshot: Optional[Dict] = None,
    after_snapshot: Optional[Dict] = None,
) -> str:
    """
    Shorter narrative specifically for the demo report.
    Returns a single plain-English paragraph.
    """
    before = before_snapshot or {}
    after  = after_snapshot  or {}

    action_desc = _action_label(action)

    if outcome == "resolved":
        result_line = f"{_label(service).capitalize()} came back healthy"
    else:
        result_line = f"{_label(service).capitalize()} did not fully recover"

    metric_change = _metric_change(before, after)
    if metric_change:
        result_line += f" ({metric_change})"

    timing = f" in {elapsed_s:.1f}s" if elapsed_s else ""

    return (
        f"AEGIS intentionally stopped {_label(service)} to simulate a real outage. "
        f"The runtime monitors detected the failure and AEGIS {action_desc}. "
        f"{result_line}{timing}."
    )
