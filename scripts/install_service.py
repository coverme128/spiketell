"""Explicitly install/uninstall this user's macOS launch agent."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
LABEL='local.spiketell.radar'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['render','install','uninstall'])
    args=parser.parse_args()
    if sys.platform!='darwin':raise SystemExit('This installer targets macOS. Use the launcher on other platforms.')
    target=Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
    domain=f'gui/{os.getuid()}'
    data={'Label':LABEL,'ProgramArguments':[str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/start.py')],
          'WorkingDirectory':str(ROOT),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':15,
          'EnvironmentVariables':{'PATH':os.environ.get('PATH','/usr/bin:/bin')},
          'StandardOutPath':str(ROOT/'data/service.log'),'StandardErrorPath':str(ROOT/'data/service.log')}
    if args.action=='render':
        sys.stdout.buffer.write(plistlib.dumps(data));return
    if args.action=='uninstall':
        subprocess.run(['launchctl','bootout',domain+'/'+LABEL],check=False)
        if target.exists():target.unlink()
        print('已移除 SpikeTell 开机服务；数据库保留。');return
    if not (ROOT/'.venv/bin/python').exists() or not (ROOT/'web/dist/index.html').exists():
        raise SystemExit('Run setup first.')
    if target.exists():raise SystemExit('Service already installed; uninstall before replacing it.')
    (ROOT/'data').mkdir(exist_ok=True)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(plistlib.dumps(data))
    try:
        subprocess.run(['launchctl','bootstrap',domain,str(target)],check=True)
    except Exception:
        target.unlink();raise
    print('已安装当前用户登录后自动运行服务。请确保未同时运行另一实例。')


if __name__=='__main__':main()
