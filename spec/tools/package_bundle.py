from pathlib import Path
import hashlib,json,zipfile
root=Path(__file__).resolve().parents[1]
manifest={
  'bundle':'A-Share Multi-Stock Spike Radar V1 — 1+4',
  'version':'1.0.0',
  'date':'2026-10-09',
  'status':'SPEC_READY',
  'runtime_verified':False,
  'rules_version':'spike_rules_v1.0.0',
  'main_packages':['00_MASTER.md','01_PRODUCT','02_DOMAIN_RULES','03_IMPLEMENTATION','04_PRODUCTION_HANDOFF'],
  'sha256':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file() and p.name!='MANIFEST.json' and '__pycache__' not in str(p) and not p.name.endswith('.pyc')}
}
(root/'MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
target=root.parent/'A_Share_Multi_Stock_Spike_Radar_V1_1plus4_Bundle.zip'
with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=8) as z:
  for p in sorted(root.rglob('*')):
    if p.is_file() and '__pycache__' not in str(p) and not p.name.endswith('.pyc'):
      z.write(p,arcname=str(Path(root.name)/p.relative_to(root)))
print(f'ZIP: {target}\nFILES: {len(manifest["sha256"])+1}\nBYTES: {target.stat().st_size}')
