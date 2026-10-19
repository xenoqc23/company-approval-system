"""Build a standalone fictional PC test bundle, never a NAS update."""
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile,ZipInfo,ZIP_DEFLATED
ROOT=Path(__file__).resolve().parents[1]
NAME='xenosys-local-notifications-20261020'
ARCHIVE_NAME='xenosys-local-notifications-fix-20261020'

def build(destination=None):
    out=Path(destination) if destination else ROOT.parent/'artifacts'/f'{ARCHIVE_NAME}.zip'
    names=['manage.py','local_notifications.py','requirements-prototype.txt','requirements-webpush.txt',
           'SETUP_LOCAL_NOTIFICATIONS.bat','RUN_LOCAL_NOTIFICATIONS.bat']
    names.extend(str(p.relative_to(ROOT)) for package in ['approval_site','workflow'] for p in (ROOT/package).rglob('*.py')
        if '__pycache__' not in p.parts and not p.name.startswith('test'))
    names.extend(str(p.relative_to(ROOT)) for directory in ['workflow/templates','workflow/static']
        for p in (ROOT/directory).rglob('*') if p.is_file())
    names=sorted(set(names));payload={name:(ROOT/name).read_bytes() for name in names}
    payload['READ_ME_FIRST.txt']=(ROOT/'docs/LOCAL_NOTIFICATIONS_20261020.md').read_bytes()
    assert not any(any(part in {'var','.env','.git','.venv','releases','data','__pycache__','deploy'} for part in Path(name).parts) for name in payload)
    assert not any(name.endswith(('.sqlite3','.db','.pem','.key','.csv')) for name in payload)
    payload['SHA256SUMS']=''.join(f'{sha256(value).hexdigest()}  {name}\n' for name,value in payload.items()).encode()
    out.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(out,'w') as z:
        for name,value in sorted(payload.items()):
            info=ZipInfo(f'{NAME}/{name}',date_time=(2026,10,20,0,0,0));info.compress_type=ZIP_DEFLATED;info.external_attr=0o644<<16;z.writestr(info,value)
    with ZipFile(out) as z:assert z.testzip() is None
    print(f'{out}\n{out.stat().st_size} bytes\nSHA256 {sha256(out.read_bytes()).hexdigest()}')
    return out

if __name__=='__main__':build()
