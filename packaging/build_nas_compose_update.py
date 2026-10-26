"""Immutable follow-up to the NAS purchase update; keep existing configuration."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
import build_nas_purchase_update as base

ROOT=base.ROOT
NAME='xenosys-nas-compose-update-20261026-v2'


def payload():
    files=base.payload()
    files.pop('RELEASE.json');files.pop('SHA256SUMS')
    files['README.md']=(ROOT/'docs/NAS_COMPOSE_UPDATE_20261026_V2.md').read_bytes()
    metadata={'release':NAME,'contains_company_data':False,'preserve_purchase_configuration':True,
              'files':{name:hashlib.sha256(data).hexdigest() for name,data in sorted(files.items())}}
    files['RELEASE.json']=(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n').encode()
    files['SHA256SUMS']=''.join(f'{hashlib.sha256(data).hexdigest()}  {name}\n' for name,data in sorted(files.items())).encode()
    return files


def build(destination):
    destination=Path(destination)
    if destination.exists():raise FileExistsError('Use a new release name; existing ZIPs are immutable.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(destination,'w',ZIP_DEFLATED) as archive:
        for name,data in sorted(payload().items()):archive.writestr(NAME+'/'+name,data)
    checksum=hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix('.zip.sha256').write_text(f'{checksum}  {destination.name}\n')
    return checksum


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('destination');args=parser.parse_args()
    print(build(args.destination))
