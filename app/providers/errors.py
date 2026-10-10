"""Safe structured provider errors; exception text may contain credentials."""
import json


def classify_error(error, stage="fetch"):
    pending, names, seen = [error], [], set()
    while pending:
        item = pending.pop(0)
        if id(item) in seen:
            continue
        seen.add(id(item)); names.append(type(item).__name__)
        pending.extend(x for x in (getattr(item, "__cause__", None), getattr(item, "__context__", None), getattr(item, "reason", None), *item.args) if isinstance(x, BaseException))
    if "ModuleNotFoundError" in names:
        code = "PROVIDER_DEPENDENCY_MISSING"
    elif "RemoteDisconnected" in names:
        code = "PROVIDER_REMOTE_DISCONNECTED"
    elif any("Timeout" in name for name in names):
        code = "PROVIDER_TIMEOUT"
    elif any("SSLError" in name for name in names):
        code = "PROVIDER_TLS_ERROR"
    elif any("JSONDecodeError" in name for name in names):
        code = "PROVIDER_INVALID_JSON"
    else:
        code = "PROVIDER_REQUEST_FAILED"
    return {"error": code, "stage": stage, "error_chain": names}


def read_worker_error(stderr):
    allowed = {"PROVIDER_DEPENDENCY_MISSING", "PROVIDER_REMOTE_DISCONNECTED", "PROVIDER_TIMEOUT", "PROVIDER_TLS_ERROR", "PROVIDER_INVALID_JSON", "PROVIDER_REQUEST_FAILED", "PROVIDER_INVALID_TRANSPORT"}
    for line in reversed(stderr.decode("utf-8", errors="replace").splitlines()):
        try:
            value = json.loads(line)
            if isinstance(value, dict) and value.get("error") in allowed:
                return value["error"]
        except ValueError:
            pass
    return "PROVIDER_REQUEST_FAILED"
