"""Read-only AKShare diagnosis. Never emits credentials or full request URLs."""
import argparse
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.domain.market import now


def exception_types(error):
    pending, result, seen = [error], [], set()
    while pending:
        item = pending.pop(0)
        if id(item) in seen:
            continue
        seen.add(id(item))
        result.append(type(item).__name__)
        pending.extend(x for x in (getattr(item, "__cause__", None), getattr(item, "__context__", None), *item.args) if isinstance(x, BaseException))
        reason = getattr(item, "reason", None)
        if isinstance(reason, BaseException):
            pending.append(reason)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="evidence/akshare-diagnosis.json")
    args = parser.parse_args()
    started = time.monotonic()
    import akshare as ak
    import requests
    report = {"observed_at": now().isoformat(), "akshare_version": ak.__version__, "import_seconds": round(time.monotonic()-started, 3),
              "proxy_environment_present": any(os.getenv(k) for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")), "checks": []}

    def save(check):
        report["checks"].append(check)
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
        print(json.dumps(check, ensure_ascii=False), flush=True)

    host = "push2his.eastmoney.com"
    start = time.monotonic()
    try:
        addresses = sorted({r[4][0] for r in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
        save({"stage": "DNS", "status": "OK", "host": host, "addresses": addresses})
        with socket.create_connection((host, 443), timeout=10) as sock:
            with ssl.create_default_context().wrap_socket(sock, server_hostname=host) as tls:
                save({"stage": "TLS", "status": "OK", "version": tls.version(), "elapsed_seconds": round(time.monotonic()-start, 3)})
    except Exception as exc:
        save({"stage": "DNS_OR_TLS", "status": "FAILED", "error_chain": exception_types(exc)})

    for symbol in ("600000", "000001"):
        calls = []
        original = requests.sessions.Session.send

        def traced(session, request, **kwargs):
            started = time.monotonic()
            try:
                response = original(session, request, **kwargs)
                calls.append({"http_status": response.status_code, "bytes": len(response.content), "content_type": response.headers.get("Content-Type"), "seconds": round(time.monotonic()-started, 3)})
                return response
            except Exception as exc:
                calls.append({"seconds": round(time.monotonic()-started, 3), "error_chain": exception_types(exc)})
                raise

        requests.sessions.Session.send = traced
        started = time.monotonic()
        try:
            frame = ak.stock_zh_a_hist_min_em(symbol=symbol, period="1", adjust="")
            save({"stage": "AKSHARE_MINUTE", "symbol": symbol, "status": "OK", "rows": len(frame), "columns": list(frame.columns),
                  "zero_open_rows": int((frame["开盘"] == 0).sum()) if "开盘" in frame else None,
                  "latest_labels": frame["时间"].tail(2).tolist() if "时间" in frame else [], "calls": calls,
                  "elapsed_seconds": round(time.monotonic()-started, 3)})
        except Exception as exc:
            save({"stage": "AKSHARE_MINUTE", "symbol": symbol, "status": "FAILED", "error_chain": exception_types(exc), "calls": calls,
                  "elapsed_seconds": round(time.monotonic()-started, 3)})
        finally:
            requests.sessions.Session.send = original

    # A control request tests whether the failure is specific to the quote host.
    try:
        response = requests.get("https://www.akshare.xyz/", timeout=(5, 10))
        save({"stage": "HTTPS_CONTROL", "host": "www.akshare.xyz", "http_status": response.status_code, "bytes": len(response.content)})
    except Exception as exc:
        save({"stage": "HTTPS_CONTROL", "status": "FAILED", "error_chain": exception_types(exc)})


if __name__ == "__main__":
    main()
