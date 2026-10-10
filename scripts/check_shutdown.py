"""Exercise shutdown with a live SSE client, using an isolated database/port."""
import argparse
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.lock import InstanceLock


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18766)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='spiketell-shutdown-') as folder:
        db = Path(folder) / 'test.sqlite3'
        env = {**os.environ, 'RADAR_DB':str(db), 'RADAR_EVIDENCE':str(Path(folder)/'absent.json')}
        with open(Path(folder)/'server.log', 'w+') as log:
            proc = subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1',
                                     '--port',str(args.port),'--workers','1','--timeout-graceful-shutdown','10'],
                                    cwd=ROOT,env=env,stdout=log,stderr=log)
            stream = None
            try:
                for _ in range(50):
                    if proc.poll() is not None:
                        raise RuntimeError('Test server failed to start')
                    try:
                        stream = urllib.request.urlopen(f'http://127.0.0.1:{args.port}/api/v1/events/stream',timeout=3)
                        break
                    except OSError:
                        time.sleep(.1)
                if stream is None or not stream.readline().startswith(b'event: feed'):
                    raise RuntimeError('No SSE feed received')
                started = time.monotonic()
                proc.terminate()
                code = proc.wait(timeout=15)
                elapsed = time.monotonic()-started
                log.seek(0)
                lifecycle_complete = 'Application shutdown complete.' in log.read()
                lock = InstanceLock(str(db)+'.lock')
                lock.acquire(); lock.release()
                connection = sqlite3.connect(db)
                integrity = connection.execute('PRAGMA quick_check').fetchone()[0]
                connection.close()
                # Uvicorn re-raises the original signal after lifecycle cleanup.
                passed = code in (0,-signal.SIGTERM) and lifecycle_complete and integrity == 'ok' and elapsed < 15
                report = {'scenario':'SIGTERM with active SSE client, isolated database',
                          'graceful_shutdown_timeout_seconds':10,'exit_code':code,'elapsed_seconds':round(elapsed,3),
                          'application_shutdown_complete':lifecycle_complete,'instance_lock_released':True,
                          'database_check':integrity,'status':'PASS' if passed else 'FAIL'}
                (ROOT/'evidence/sse-shutdown-check.json').write_text(json.dumps(report,indent=2)+'\n')
                print(json.dumps(report))
                if not passed:
                    raise SystemExit(1)
            finally:
                if stream:
                    stream.close()
                if proc.poll() is None:
                    proc.kill(); proc.wait()


if __name__ == '__main__':
    main()
