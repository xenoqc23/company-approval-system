"""An allowlisted PC-only trial ZIP. Never includes NAS or application data."""
import argparse
import hashlib
from pathlib import Path
from zipfile import ZipFile,ZipInfo,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
NAME='xenosys-local-pc-notification-test-20261106-v2'
FILES=['server.py','launch.py','START_TEST.bat','requirements.txt','index.html','style.css','app.js','sw.js','README.md',
       'pending.py','desktop.py','login_reminder.py','DISABLE_AUTO_START.bat']


def build(destination):
    destination=Path(destination)
    if destination.exists():raise FileExistsError('Use a new filename; published archives are immutable.')
    files={name:(ROOT/'local_push_test'/name).read_bytes() for name in FILES}
    for name in files:
        if name.endswith('.bat'):files[name]=files[name].replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
    files['SHA256SUMS']=''.join(f'{hashlib.sha256(data).hexdigest()}  {name}\n' for name,data in sorted(files.items())).encode()
    destination.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(destination,'w') as archive:
        for name,data in sorted(files.items()):
            info=ZipInfo(NAME+'/'+name,date_time=(2026,11,6,0,0,0));info.compress_type=ZIP_DEFLATED;info.external_attr=0o644<<16
            archive.writestr(info,data)
    digest=hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix('.zip.sha256').write_text(f'{digest}  {destination.name}\n')
    return digest


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('destination')
    print(build(parser.parse_args().destination))
