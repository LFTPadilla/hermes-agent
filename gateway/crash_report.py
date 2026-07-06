"""crash_report.py — last-resort external notification when a gateway process dies.

2026-07-06 finding: this codebase had NO path from "the gateway process hard-crashed"
to "a human finds out." An uncaught exception in main() prints a traceback to stderr
and the process exits; a k8s liveness probe or systemd Restart=on-failure silently
restarts it. /health simply stops responding while down — nobody is watching that in
real time. This applies identically to every client instance and to "coco" (there is
no client-specific error-reporting config anywhere in this repo).

This module is a best-effort, stdlib-only, fail-safe notifier: it must NEVER raise
(a broken reporter must not mask or replace the original crash), must NEVER block
process exit for long (short timeout), and is a SAFE NO-OP by default — it only
sends anything once CRASH_REPORT_URL (or OPS_ALERT_TOKEN, reusing the same lane
every other Blackrack ops monitor already posts to) is explicitly configured for a
given client's pod. Shipping this file changes nothing for any client until that
env var is deliberately wired in — intentional, so this can land without a
fleet-wide behavior change riding along with it.

Wire-up (not done automatically, needs a deliberate per-client or template change):
  CRASH_REPORT_URL    e.g. http://support-dispatcher.blackrack.svc.cluster.local:8787/ops-alert
                      (the exact contract used by every Ops/scripts/*_monitor.py already —
                      see Ops/scripts/ops_alert_post.py for the reference implementation)
  CRASH_REPORT_TOKEN  bearer token; falls back to OPS_ALERT_TOKEN if unset
  HERMES_CLIENT / GATEWAY_SLUG  client identity for the alert `source` field (best-effort,
                      defaults to "unknown" — never fails just because it's missing)
"""

from __future__ import annotations

import json
import os
import sys
import traceback
import urllib.error
import urllib.request

_TIMEOUT_SECONDS = 5


def _client_slug() -> str:
    return (
        os.environ.get("HERMES_CLIENT")
        or os.environ.get("GATEWAY_SLUG")
        or os.environ.get("CLIENT_SLUG")
        or "unknown"
    )


def report_crash(exc: BaseException, *, context: str = "main") -> None:
    """Best-effort: POST a critical alert describing an uncaught exception.

    Safe to call from any exception handler. Never raises. No-ops silently if
    CRASH_REPORT_URL/OPS_ALERT_TOKEN aren't configured for this pod.
    """
    try:
        url = os.environ.get("CRASH_REPORT_URL", "").strip()
        token = os.environ.get("CRASH_REPORT_TOKEN", "").strip() or os.environ.get("OPS_ALERT_TOKEN", "").strip()
        if not url or not token:
            return  # Not configured for this client yet — intentional no-op, not a failure.

        slug = _client_slug()
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-3000:]
        payload = {
            "source": f"gateway-crash:{slug}",
            "severity": "critical",
            "summary": f"Hermes gateway ({slug}) crashed in {context}: {type(exc).__name__}: {exc}"[:500],
            "details": tb,
            "key": f"gateway-crash-{slug}",
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
        try:
            urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS).read()
        except urllib.error.URLError:
            pass  # Network/DNS issue reporting the crash — nothing more we can do here.
    except Exception:
        pass  # A broken reporter must never mask the original crash.


def install_excepthook() -> None:
    """Chain a sys.excepthook that reports uncaught main-thread exceptions before
    falling through to the default handler (which still prints the traceback and
    sets the process exit code exactly as before — this is purely additive)."""
    previous = sys.excepthook

    def _hook(exc_type, exc_value, exc_tb):
        if exc_value is not None:
            report_crash(exc_value, context="uncaught (sys.excepthook)")
        previous(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook
