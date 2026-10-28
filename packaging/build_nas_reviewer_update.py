"""Package the reviewer screen update without changing existing NAS data or rules."""
import hashlib
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile, ZIP_DEFLATED
import build_nas_purchase_update as base

ROOT = base.ROOT
NAME = 'xenosys-nas-reviewer-update-20261028-v3'


def payload():
    files = base.payload()
    files.pop('RELEASE.json')
    files.pop('SHA256SUMS')
    files['README.md'] = (ROOT / 'docs/NAS_REVIEWER_UPDATE_20261028_V3.md').read_bytes()
    metadata = {
        'release': NAME,
        'base_release': 'xenosys-nas-compose-update-20261026-v2',
        'source_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'contains_company_data': False,
        'preserve_purchase_configuration': True,
        'schema_changes': False,
        'files': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
    }
    files['RELEASE.json'] = (json.dumps(metadata, ensure_ascii=False, indent=2) + '\n').encode()
    files['SHA256SUMS'] = ''.join(f'{hashlib.sha256(data).hexdigest()}  {name}\n' for name, data in sorted(files.items())).encode()
    return files


def build(destination):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError('Published update files are immutable; choose a new release name.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, 'w', ZIP_DEFLATED) as archive:
        for name, data in sorted(payload().items()):
            archive.writestr(NAME + '/' + name, data)
    checksum = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix('.zip.sha256').write_text(f'{checksum}  {destination.name}\n')
    return checksum


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('destination')
    print(build(parser.parse_args().destination))
