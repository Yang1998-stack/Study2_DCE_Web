"""Build a complete source release without private databases, credentials or exports."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
extensions={'.py','.json','.md','.bat','.cmd','.txt'}
files=[p for p in ROOT.iterdir() if p.is_file() and p.name not in {'quickform.local.json','quickform.env','quickform.env.local','quickform.env.cmd','.env'} and not p.name.endswith('.local.json') and (p.suffix in extensions or p.name=='.gitignore')]
for folder in ('app','config','static','tests','scripts','docs','designs','管理工具'):
    files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
target=ROOT/'dist'/'Study2_DCE_Web_升级源码.zip'
target.parent.mkdir(exist_ok=True)
manifest={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
    for name in manifest: z.write(ROOT/name,'Study2_DCE_Web/'+name)
    z.writestr('Study2_DCE_Web/RELEASE_FILES.json',json.dumps(manifest,ensure_ascii=False,indent=2))
with zipfile.ZipFile(target) as z:
    assert z.testzip() is None
    assert not any('/data/' in n or '/exports/' in n or '__pycache__' in n for n in z.namelist())
print(target)
print(f'{len(files)} source files; private research data stays in the original workspace.')
