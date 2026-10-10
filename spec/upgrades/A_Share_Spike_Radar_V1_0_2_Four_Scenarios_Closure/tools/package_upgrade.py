"""Build reproducible ZIP from single incremental package directory."""
from pathlib import Path
import json, hashlib, zipfile
ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT.parent/(ROOT.name+'.zip')

def files():
    return sorted([p for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and '.pyc' not in p.suffixes])

def package():
    manifest={'name':ROOT.name,'rule_version':'spike_rules_v1.0.2','status':'SPEC_DELTA_READY',
              'files':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in files() if p.name!='MANIFEST.json'}}
    (ROOT/'MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    with zipfile.ZipFile(OUTPUT,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for path in files():
            info=zipfile.ZipInfo(f'{ROOT.name}/{path.relative_to(ROOT).as_posix()}')
            info.date_time=(2026,10,10,12,0,0)
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=(0o644 & 0xFFFF)<<16
            z.writestr(info,path.read_bytes(),compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    print(f'WROTE {OUTPUT} ({OUTPUT.stat().st_size} bytes), {len(files())} files')

if __name__=='__main__':package()
