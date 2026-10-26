"""One complete source tree for NAS and isolated local fictional testing."""
from pathlib import Path
from zipfile import ZipFile,ZipInfo,ZIP_DEFLATED
from hashlib import sha256
ROOT=Path(__file__).resolve().parents[1]
NAME='xenosys-local-newrequests-20261026'

def build(destination=None):
    out=Path(destination) if destination else ROOT/'releases'/f'{NAME}.zip'
    files=['manage.py','local_full.py','requirements-prototype.txt','requirements-nas.txt','.dockerignore','SETUP_LOCAL_FULL.bat','RUN_LOCAL_FULL.bat','RESET_LOCAL_FULL.bat']
    for package in ['approval_site','workflow','purchasing']:
        files.extend(str(p.relative_to(ROOT)) for p in (ROOT/package).rglob('*.py') if '__pycache__' not in p.parts and not p.name.startswith('test'))
    for folder in ['workflow/templates','workflow/static','purchasing/templates','purchasing/static','deploy/nas']:
        files.extend(str(p.relative_to(ROOT)) for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    payload={n:(ROOT/n).read_bytes() for n in sorted(set(files))}
    payload['READ_ME_FIRST.txt']=(ROOT/'docs/LOCAL_NEWREQUESTS_20261026.md').read_bytes()
    payload['PURCHASE_PLAN.md']=(ROOT/'docs/PURCHASE_REQUEST_PLAN_20261023.md').read_bytes()
    payload['VALIDATION.txt']=(ROOT/'docs/LOCAL_NEWREQUESTS_VALIDATION_20261026.md').read_bytes()
    examples=ROOT/'docs/newrequests-local-examples'
    if examples.is_dir():payload.update({f'examples/{p.name}':p.read_bytes() for p in sorted(examples.glob('*.png'))})
    assert not any(any(part in {'var','data','.env','.git','.venv','releases','__pycache__'} for part in Path(n).parts) for n in payload)
    assert not any(n.endswith(('.sqlite3','.db','.pem','.key','.csv')) for n in payload)
    payload['SHA256SUMS']=''.join(f'{sha256(v).hexdigest()}  {n}\n' for n,v in payload.items()).encode()
    out.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(out,'w') as z:
        for name,data in sorted(payload.items()):
            info=ZipInfo(f'{NAME}/{name}',date_time=(2026,10,26,0,0,0));info.compress_type=ZIP_DEFLATED;info.external_attr=(0o755 if name.endswith('.sh') else 0o644)<<16;z.writestr(info,data)
    with ZipFile(out) as z:
        assert z.testzip() is None
        for name,data in payload.items():assert z.read(f'{NAME}/{name}')==data
    print(f'{out.name}: {out.stat().st_size} bytes; SHA256 {sha256(out.read_bytes()).hexdigest()}');return out
if __name__=='__main__':build()
