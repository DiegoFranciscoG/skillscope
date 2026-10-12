"""Monthly npm downloads for packages published by indexed repositories (adoption factor a4)."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from collector.budget import Budget
from collector.http import HttpClient, RequestFailedError
from pipeline.report import SourceReport
from pipeline.signals import SignalStore

URL = "https://api.npmjs.org/downloads/point/last-month/"


def collect_npm(
    http: HttpClient,
    signals: SignalStore,
    packages: list[str],
    *,
    budget_limit: int,
    now: datetime,
) -> SourceReport:
    report = SourceReport(id="npm", budget=budget_limit)
    budget = Budget("npm", budget_limit)
    due = sorted({p for p in packages if p and signals.npm_due(p, now)})
    errors = 0
    for package in due:
        if not budget.can_spend():
            break
        try:
            result = http.get(
                URL + quote(package, safe="@/"), source="npm", budget=budget, conditional=False
            )
            signals.set_npm(package, int((result.data or {}).get("downloads") or 0), now)
        except RequestFailedError as exc:
            if exc.status == 404:
                signals.set_npm(package, None, now)  # not published: stop asking for a day
            else:
                errors += 1
    report.calls = budget.calls
    report.details = {"packages": len(due), "errors": errors}
    if errors:
        report.status = "partial"
    if not due:
        report.status, report.reason = "skipped", "sin paquetes pendientes"
    return report
