"""Build the purchase-only fictional PC laboratory. No NAS updater or actual data."""
from pathlib import Path
from hashlib import sha256
from zipfile import ZipFile,ZipInfo,ZIP_DEFLATED
ROOT=Path(__file__).resolve().parents[1]
NAME='xenosys-local-purchases-20261022'
ARCHIVE='xenosys-local-purchases-20261022-ui-fix'


def build(destination=None):
    out=Path(destination) if destination else ROOT/'releases'/f'{ARCHIVE}.zip'
    names=['manage.py','local_purchases.py','requirements-prototype.txt','SETUP_LOCAL_PURCHASES.bat','RUN_LOCAL_PURCHASES.bat']
    names.extend(str(p.relative_to(ROOT)) for package in ['approval_site','workflow','purchasing'] for p in (ROOT/package).rglob('*.py')
                 if '__pycache__' not in p.parts and not p.name.startswith('test'))
    names.extend(str(p.relative_to(ROOT)) for directory in ['purchasing/templates','purchasing/static'] for p in (ROOT/directory).rglob('*') if p.is_file())
    names.extend(['workflow/static/workflow/'+n for n in ['style.css','xenosys.css','workspace.css','fonts/PretendardVariable.woff2','fonts/OFL.txt','images/xenosys-logo-refined.png']])
    payload={name:(ROOT/name).read_bytes() for name in sorted(set(names))}
    payload['READ_ME_FIRST.txt']=(ROOT/'docs/LOCAL_PURCHASES_20261022.md').read_bytes()
    examples=ROOT/'docs/purchase-test-examples'
    if examples.is_dir():
        payload.update({f'examples/{p.name}':p.read_bytes() for p in sorted(examples.glob('*.png'))})
    assert not any(any(part in {'var','data','.env','.git','.venv','releases','deploy','__pycache__'} for part in Path(n).parts) for n in payload)
    assert not any(n.endswith(('.sqlite3','.db','.pem','.key','.csv')) for n in payload)
    assert not any('seed_demo' in payload[n].decode(errors='ignore') for n in ['local_purchases.py','SETUP_LOCAL_PURCHASES.bat','RUN_LOCAL_PURCHASES.bat'])
    payload['SHA256SUMS']=''.join(f'{sha256(v).hexdigest()}  {n}\n' for n,v in payload.items()).encode()
    out.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(out,'w') as z:
        for n,v in sorted(payload.items()):
            info=ZipInfo(f'{NAME}/{n}',date_time=(2026,10,22,0,0,0));info.compress_type=ZIP_DEFLATED;info.external_attr=0o644<<16;z.writestr(info,v)
    with ZipFile(out) as z:
        assert z.testzip() is None
        for n,v in payload.items():assert z.read(f'{NAME}/{n}')==v
    print(f'{out.name}: {out.stat().st_size} bytes; SHA256 {sha256(out.read_bytes()).hexdigest()}')
    return out

if __name__=='__main__':build()
