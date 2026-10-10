"""Run from repository root: python3 scripts/start.py (after setup)."""
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT)
for filename in ('.env','.env.local'):
    path=ROOT/filename
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key,value=line.split('=',1);os.environ.setdefault(key.strip(),value.strip().strip('"\''))
python=ROOT/('.venv/Scripts/python.exe' if os.name=='nt' else '.venv/bin/python')
if not python.exists():raise SystemExit('Run python3 scripts/setup.py first')
if not (ROOT/'web/dist/index.html').exists():subprocess.run(['npm.cmd' if os.name=='nt' else 'npm','--prefix','web','run','build'],check=True)
port=int(os.getenv('RADAR_PORT','8765'))
if not 1024<=port<=65535:raise SystemExit('RADAR_PORT must be between 1024 and 65535')
os.execv(str(python),[str(python),'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port),'--workers','1','--timeout-graceful-shutdown','10'])
