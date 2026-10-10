"""Start the local application and open it; preserve the running single instance."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT)


def running(url):
    try:
        with urllib.request.urlopen(url+'/openapi.json',timeout=1) as response:
            return json.load(response).get('info',{}).get('title','').startswith('SpikeTell')
    except (OSError,ValueError):
        return False


def main():
    for filename in ('.env','.env.local'):
        path=ROOT/filename
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                    key,value=line.split('=',1);os.environ.setdefault(key.strip(),value.strip().strip('"\''))
    url='http://127.0.0.1:'+str(int(os.getenv('RADAR_PORT','8765')))
    if not running(url):
        python=ROOT/('.venv/Scripts/python.exe' if os.name=='nt' else '.venv/bin/python')
        if not python.exists() or not (ROOT/'web/dist/index.html').exists():
            subprocess.run([sys.executable,'scripts/setup.py'],check=True)
        (ROOT/'data').mkdir(exist_ok=True)
        with (ROOT/'data/launcher.log').open('a') as log:
            flags={'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.DETACHED_PROCESS} if os.name=='nt' else {'start_new_session':True}
            process=subprocess.Popen([str(python),'scripts/start.py'],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,**flags)
        for _ in range(60):
            if running(url):
                break
            if process.poll() is not None:
                raise SystemExit('启动失败，请查看 data/launcher.log；不要删除单实例锁文件。')
            time.sleep(.5)
        else:
            raise SystemExit('启动超时，请查看 data/launcher.log。')
    print('SpikeTell 已启动：'+url)
    webbrowser.open(url)


if __name__=='__main__':
    main()
