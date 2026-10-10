import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY_PROFILE = json.loads((ROOT / "spec/contracts/rule_profile.v1.json").read_text())
PROFILE = json.loads((ROOT / "app/contracts/rule_profile.v1.0.2.json").read_text())


def evidence() -> dict:
    try:
        value = json.loads(Path(os.getenv("RADAR_EVIDENCE", "config/runtime.json")).read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def qualification_reasons(value: dict, at) -> list[str]:
    from app.domain.market import timestamp
    reasons = []
    provider = value.get("provider", {})
    if provider.get("name") != "akshare" or not provider.get("personal_use_confirmed") or not provider.get("rights_evidence"):
        reasons.append("PROVIDER_RIGHTS_UNVERIFIED")
    if provider.get("timestamp_semantics") not in ("start", "end") or len(provider.get("timestamp_samples", [])) < 2:
        reasons.append("UNKNOWN_TIMESTAMP_SEMANTICS")
    if not provider.get("finalization_verified"):
        reasons.append("FINALIZATION_UNVERIFIED")
    if not provider.get("capacity_verified"):
        reasons.append("CAPACITY_UNVERIFIED")
    clock = value.get("clock", {})
    try:
        age = (at - timestamp(clock["checked_at"])).total_seconds()
        if not clock["source"] or not 0 <= age <= 3600 or abs(float(clock["offset_seconds"])) > 2:
            reasons.append("CLOCK_UNVERIFIED")
    except (KeyError, ValueError, TypeError):
        reasons.append("CLOCK_UNVERIFIED")
    return reasons
