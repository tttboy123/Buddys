from __future__ import annotations

import os


def founder_metrics_allowed(email: str) -> bool:
    allowlist = {
        value.strip().lower()
        for value in os.getenv("BUDDYS_FOUNDER_METRICS_EMAIL_ALLOWLIST", "").split(",")
        if value.strip()
    }
    return email.strip().lower() in allowlist
