"""Killed on timeout by parent. Provider exceptions never expose request tokens."""
import json
import sys
import os
from types import SimpleNamespace
from datetime import datetime, timedelta
from app.providers.errors import classify_error


def fetch_frame(ak, symbol, start, transport):
    function = ak.stock_zh_a_hist_min_em
    if transport == "requests":
        return function(symbol=symbol, period="1", adjust="", start_date=start)
    if transport != "curl":
        raise ValueError("PROVIDER_INVALID_TRANSPORT")
    from curl_cffi import requests as curl_requests
    # Isolated worker: change only this AKShare module's HTTP dependency.
    # No TLS impersonation, proxy rotation, or global requests monkeypatch.
    original = function.__globals__["requests"]
    function.__globals__["requests"] = SimpleNamespace(get=curl_requests.get)
    try:
        return function(symbol=symbol, period="1", adjust="", start_date=start)
    finally:
        function.__globals__["requests"] = original


def main():
    import akshare as ak
    from app.domain.market import symbol_id
    symbol = symbol_id(sys.argv[1]).split(".")[1]
    cursor = sys.argv[2] if len(sys.argv) > 2 else ""
    # Re-fetch a small overlap to detect revisions. The upstream may still fetch
    # its fixed five-day payload internally; measure that cost in qualification.
    start = (datetime.fromisoformat(cursor) - timedelta(minutes=25)).strftime("%Y-%m-%d %H:%M:%S") if cursor else "1979-09-01 09:32:00"
    frame = fetch_frame(ak, symbol, start, os.getenv("RADAR_HTTP_TRANSPORT", "curl"))
    print(frame.to_json(orient="records", force_ascii=False, date_format="iso"))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps(classify_error(exc)), file=sys.stderr)
        raise SystemExit(1)
