"""Assemble a Windows x64 portable bundle from verified official runtime/wheels.

The runtime input is the PSF `python` 3.12.10 NuGet package. Verify its
SHA-512 against the NuGet catalog before invoking this builder. Download
the pinned requirements as binary wheels, plus tzdata==2025.2 for Windows.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime-package', type=Path, required=True)
    parser.add_argument('--wheels', type=Path, required=True)
    parser.add_argument('--cc', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parent.parent
    runtime_pin = json.loads((source / 'packaging/python_runtime.json').read_text(encoding='utf-8'))
    actual_hash = base64.b64encode(hashlib.sha512(args.runtime_package.read_bytes()).digest()).decode()
    if actual_hash != runtime_pin['sha512_base64']:
        raise SystemExit('Python runtime checksum does not match the official NuGet catalog.')
    pins = dict(line.strip().split('==') for line in (source / 'requirements-prototype.txt').read_text().splitlines() if '==' in line)
    pins['tzdata'] = '2025.2'
    pins = {name.lower().replace('-', '_'): version for name, version in pins.items()}
    wheels = sorted(args.wheels.glob('*.whl'))
    found = {}
    for wheel in wheels:
        name, version = wheel.name.split('-')[:2]
        name = name.lower().replace('-', '_')
        if pins.get(name) != version:
            raise SystemExit(f'Unexpected dependency wheel: {wheel.name}')
        with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json', timeout=30) as response:
            catalog = json.load(response)
        expected = next((entry['digests']['sha256'] for entry in catalog['urls'] if entry['filename'] == wheel.name), None)
        if not expected or hashlib.sha256(wheel.read_bytes()).hexdigest() != expected:
            raise SystemExit(f'Wheel checksum does not match PyPI: {wheel.name}')
        found[name] = version
    if found != pins or len(wheels) != len(pins):
        raise SystemExit('The portable dependency wheel set is incomplete.')
    output = args.output.resolve()
    if output.exists():
        raise SystemExit('Use a new output folder; existing application/data folders are never overwritten.')
    output.mkdir(parents=True)
    with zipfile.ZipFile(args.runtime_package) as archive:
        for member in archive.infolist():
            path = Path(member.filename)
            if path.parts and path.parts[0] == 'tools' and not member.is_dir():
                target = output / 'runtime' / Path(*path.parts[1:])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))
    if not (output / 'runtime/python.exe').is_file():
        raise SystemExit('The supplied package does not contain the Windows Python executable.')
    (output / 'runtime/python312._pth').write_text('.\nLib\nDLLs\n..\n../vendor\nimport site\n', encoding='utf-8')
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(output / 'vendor')
    for folder in ['approval_site', 'workflow']:
        shutil.copytree(source / folder, output / folder,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    for name in ['manage.py', 'launcher.py', 'portable.py', 'START_WITHOUT_PYTHON.txt']:
        shutil.copyfile(source / name, output / name)
    executable = output / 'CompanyApproval.exe'
    subprocess.run([args.cc, '-municode', '-O2', '-static', '-s', '-Wl,--no-insert-timestamp',
        str(source / 'packaging/windows_launcher.c'), '-o', str(executable), '-luser32'], check=True)
    inputs = [args.runtime_package, *sorted(args.wheels.glob('*.whl'))]
    manifest = {'platform': 'Windows x64', 'python': '3.12.10', 'data_included': False,
        'runtime_checksum_verification': runtime_pin,
        'inputs': [{'name': item.name, 'sha256': hashlib.sha256(item.read_bytes()).hexdigest()} for item in inputs],
        'exe_sha256': hashlib.sha256(executable.read_bytes()).hexdigest()}
    (output / 'BUILD_INFO.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f'Windows portable bundle assembled: {output}')


if __name__ == '__main__':
    main()
