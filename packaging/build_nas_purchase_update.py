"""Build a clean full NAS update, never a copy of a local demonstration bundle."""
import hashlib
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
NAME='xenosys-nas-purchase-update-20261026-v1'
EXCLUDED_COMMANDS={'seed_demo.py','seed_purchase_demo.py','seed_full_demo.py','seed_integrated_demo.py','notification_demo_permissions.py'}


def payload():
    files={}
    for folder in ['approval_site','workflow','purchasing','deploy/nas']:
        for p in sorted((ROOT/folder).rglob('*')):
            if not p.is_file():continue
            relative=p.relative_to(ROOT)
            if p.is_symlink():raise ValueError('Symlinks are not release files.')
            if any(part in {'__pycache__','.git','tests'} for part in relative.parts):continue
            if p.name.startswith('test') and p.suffix in {'.py','.html'}:continue
            if relative.as_posix() in {'purchasing/templates/purchasing/standalone_base.html','purchasing/templates/purchasing/login.html'}:continue
            if p.name in EXCLUDED_COMMANDS or p.suffix in {'.pyc','.sqlite3','.zip','.env'}:continue
            files['app/'+relative.as_posix()]=p.read_bytes()
    for name in ['manage.py','requirements-prototype.txt','requirements-nas.txt','.dockerignore']:
        files['app/'+name]=(ROOT/name).read_bytes()
    files['README.md']=(ROOT/'docs/NAS_PURCHASE_UPDATE_20261026.md').read_bytes()
    files['UPDATE_NAS.sh']=b'''#!/bin/sh
set -eu
umask 077
RELEASE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$RELEASE_DIR"
case "${1:-help}" in
  precheck|update|rollback|status|logs|backup) ;;
  *) echo 'Usage: sudo sh UPDATE_NAS.sh precheck|update [role options] | status | logs | rollback | backup'; exit 1;;
esac
sha256sum -c SHA256SUMS > /dev/null || { echo 'Release file verification failed. Extract the original ZIP again.' >&2; exit 1; }
exec sh "$RELEASE_DIR/app/deploy/nas/nas.sh" "$@"
'''
    metadata={'release':NAME,'base_source_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'contains_company_data':False,'files':{name:hashlib.sha256(data).hexdigest() for name,data in sorted(files.items())}}
    files['RELEASE.json']=(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n').encode()
    files['SHA256SUMS']=''.join(f'{hashlib.sha256(data).hexdigest()}  {name}\n' for name,data in sorted(files.items())).encode()
    return files


def build(destination):
    destination=Path(destination)
    if destination.exists():raise FileExistsError('Published update files are immutable; choose a new release name.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    files=payload()
    with ZipFile(destination,'w',ZIP_DEFLATED) as archive:
        for name,data in sorted(files.items()):archive.writestr(NAME+'/'+name,data)
    checksum=hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix('.zip.sha256').write_text(f'{checksum}  {destination.name}\n')
    return checksum


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('destination');args=parser.parse_args()
    print(build(args.destination))
