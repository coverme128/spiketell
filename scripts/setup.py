import os
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[1];os.chdir(root)
subprocess.run([sys.executable,'-m','venv','.venv'],check=True)
python=root/('.venv/Scripts/python.exe' if os.name=='nt' else '.venv/bin/python')
subprocess.run([str(python),'-m','pip','install','-r','requirements.lock'],check=True)
npm='npm.cmd' if os.name=='nt' else 'npm'
subprocess.run([npm,'--prefix','web','ci'],check=True)
subprocess.run([npm,'--prefix','web','run','build'],check=True)
