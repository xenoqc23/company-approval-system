"""Build the guarded NAS update with separate live reviewer permissions."""
import hashlib
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile,ZIP_DEFLATED
import build_nas_purchase_update as base

ROOT=base.ROOT
NAME='xenosys-nas-reviewer-access-update-20261106-v5'


def payload():
    files=base.payload()
    files.pop('RELEASE.json');files.pop('SHA256SUMS')
    files['README.md']=(ROOT/'docs/NAS_REVIEWER_ACCESS_UPDATE_20261106_V5.md').read_bytes()
    metadata=dict(release=NAME,base_release='xenosys-nas-stock-record-update-20261102-v4',
        source_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        contains_company_data=False,preserve_purchase_configuration=True,
        preserve_submitted_route_snapshots=True,schema_changes=True,
        schema_change='add leave reviewer authority tables; preserve all existing rows',
        live_pending_review_permissions=True,separate_leave_and_purchase_permissions=True,
        automatic_permission_grants=False,stock_finance_handover=False,
        files={name:hashlib.sha256(data).hexdigest() for name,data in sorted(files.items())})
    files['RELEASE.json']=(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n').encode()
    files['SHA256SUMS']=''.join(f'{hashlib.sha256(data).hexdigest()}  {name}\n' for name,data in sorted(files.items())).encode()
    return files


def build(destination):
    destination=Path(destination)
    if destination.exists():raise FileExistsError('Published update files are immutable; choose a new release name.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(destination,'w',ZIP_DEFLATED) as archive:
        for name,data in sorted(payload().items()):archive.writestr(NAME+'/'+name,data)
    checksum=hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix('.zip.sha256').write_text(f'{checksum}  {destination.name}\n')
    return checksum


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('destination')
    print(build(parser.parse_args().destination))
