# Windows portable build

This distribution starts through a native x64 `CompanyApproval.exe` and includes
the official PSF CPython runtime and the pinned Django dependencies. It does not
install Python, change PATH, or include user databases. Keep the entire folder;
copy `var` separately when transferring existing accounts/documents.

The builder accepts the official `python` 3.12.10 NuGet package:

`https://api.nuget.org/v3-flatcontainer/python/3.12.10/python.3.12.10.nupkg`

Its SHA-512 is pinned from the official NuGet catalog in `python_runtime.json`.
The builder checks that pin and checks each wheel against its published PyPI
SHA-256. Keep TLS and package signature/checksum verification enabled.

Download the Windows wheel set with:

```sh
python -m pip download --only-binary=:all: --platform win_amd64 --python-version 3.12 --implementation cp --dest wheels -r requirements-prototype.txt tzdata==2025.2
```

Use a MinGW-w64 x64 compiler and a new output directory:

```sh
python packaging/build_windows_portable.py --runtime-package python.3.12.10.nupkg --wheels wheels --cc x86_64-w64-mingw32-gcc --output release
```

The standard source-based Windows launcher remains available. `portable.py`
uses the bundled executable for all child processes, applies pending migrations
after a SQLite backup, preserves existing users/data, and prompts for an initial
password only when the DB has no accounts. The server stays on loopback.

Validation for this build used Wine 10 with the real Windows CPython binary:
54 workflow tests passed, native launcher startup worked in a Korean directory
with spaces, and Chromium verified login, Excel download, and leave history.
It has not been run on a physical Windows PC in this cloud environment.
