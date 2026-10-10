"""Package reviewable source and evidence, excluding credentials and runtime databases."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
paths=[]
for folder in ('app','scripts','tests','web/src','web/dist','web/tests','spec','evidence'):
    for p in (ROOT/folder).rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.zip','.pyc'):
            paths.append(p)
for name in ('README.md','OPERATIONS.md','启动 SpikeTell.command','启动 SpikeTell.cmd','pyproject.toml','requirements.lock','.env.example','web/package.json','web/package-lock.json','web/tsconfig.json','web/vite.config.ts','web/playwright.config.ts','web/index.html','config/runtime.example.json','config/instrument.example.json'):
    paths.append(ROOT/name)
manifest={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths))}
output=ROOT/'evidence/release-evidence.zip'
with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
    for p in sorted(set(paths)):archive.write(p,p.relative_to(ROOT))
    archive.writestr('EVIDENCE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
print(f'{output}: {len(manifest)} files')
