"""Build an immutable, data-free local integrated-preview archive."""
from pathlib import Path
from zipfile import ZipFile,ZipInfo,ZIP_DEFLATED
from hashlib import sha256
ROOT=Path(__file__).resolve().parents[1]
NAME='xenosys-local-integrated-20261023'

def build(destination=None):
    out=Path(destination) if destination else ROOT/'releases'/f'{NAME}.zip'
    files=['manage.py','local_integrated.py','requirements-prototype.txt','SETUP_LOCAL_INTEGRATED.bat','RUN_LOCAL_INTEGRATED.bat','RESET_LOCAL_INTEGRATED.bat']
    for package in ['approval_site','workflow','purchasing']:
        files.extend(str(p.relative_to(ROOT)) for p in (ROOT/package).rglob('*.py') if '__pycache__' not in p.parts and not p.name.startswith('test'))
    for folder in ['workflow/templates','workflow/static','purchasing/templates','purchasing/static']:
        files.extend(str(p.relative_to(ROOT)) for p in (ROOT/folder).rglob('*') if p.is_file())
    payload={n:(ROOT/n).read_bytes() for n in sorted(set(files))}
    payload['READ_ME_FIRST.txt']=(ROOT/'docs/LOCAL_INTEGRATED_20261023.md').read_bytes()
    examples=ROOT/'docs/integrated-local-examples'
    if examples.is_dir():payload.update({f'examples/{p.name}':p.read_bytes() for p in sorted(examples.glob('*.png'))})
    assert not any(any(part in {'var','data','.env','.git','.venv','releases','deploy','__pycache__'} for part in Path(n).parts) for n in payload)
    assert not any(n.endswith(('.sqlite3','.db','.pem','.key','.csv')) for n in payload)
    payload['SHA256SUMS']=''.join(f'{sha256(v).hexdigest()}  {n}\n' for n,v in payload.items()).encode()
    out.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(out,'w') as z:
        for name,data in sorted(payload.items()):
            info=ZipInfo(f'{NAME}/{name}',date_time=(2026,10,23,0,0,0));info.compress_type=ZIP_DEFLATED;info.external_attr=0o644<<16;z.writestr(info,data)
    with ZipFile(out) as z:
        assert z.testzip() is None
        for name,data in payload.items():assert z.read(f'{NAME}/{name}')==data
    print(f'{out.name}: {out.stat().st_size} bytes; SHA256 {sha256(out.read_bytes()).hexdigest()}')
    return out
if __name__=='__main__':build()
