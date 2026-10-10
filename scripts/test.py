import os
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[1];os.chdir(root)
python=root/('.venv/Scripts/python.exe' if os.name=='nt' else '.venv/bin/python')
commands=[[str(python),'spec/tools/validate_bundle.py'],[str(python),'-m','unittest','discover','-s','spec/tests','-v'],[str(python),'-m','pytest','-q','--junitxml=evidence/backend-tests.xml'],['npm.cmd' if os.name=='nt' else 'npm','--prefix','web','run','build']]
if '--browser' in sys.argv:commands.append(['npm.cmd' if os.name=='nt' else 'npm','--prefix','web','test'])
commands.insert(2,[str(python),'spec/upgrades/A_Share_Spike_Radar_V1_0_2_Four_Scenarios_Closure/tools/validate_upgrade.py'])
commands.insert(2,[str(python),'spec/upgrades/A_Share_Spike_Radar_V1_0_1_Minute_Only_Closure/verify_addendum.py'])
for command in commands:subprocess.run(command,check=True)
