"""Private purchasing files in a verified database backup (never public assets)."""
from pathlib import PurePosixPath
from hashlib import sha256
import shutil
from django.conf import settings


def safe_name(name):
    if not isinstance(name,str):raise ValueError('첨부파일 경로가 올바르지 않습니다.')
    path=PurePosixPath(name)
    if not name or '\\' in name or ':' in name or path.is_absolute() or any(part in ['.','..'] for part in path.parts) or str(path)!=name:
        raise ValueError('첨부파일 경로를 확인할 수 없습니다.')
    return path


def add_files(archive):
    root=settings.DATA_DIR/'purchase-attachments';files={}
    if not root.exists():return files
    if root.is_symlink():raise ValueError('첨부파일 저장 경로를 확인해 주세요.')
    for source in sorted(root.rglob('*')):
        if source.is_symlink():raise ValueError('첨부파일 링크는 백업할 수 없습니다.')
        if not source.is_file():continue
        name=source.relative_to(root).as_posix();safe_name(name)
        data=source.read_bytes();files[name]=dict(sha256=sha256(data).hexdigest(),size=len(data))
        archive.writestr('attachments/'+name,data)
    return files


def verify_files(archive,manifest,staging):
    files=manifest.get('files',{})
    if not isinstance(files,dict):raise ValueError('첨부파일 백업 목록이 올바르지 않습니다.')
    for name in files:safe_name(name)
    expected={'attachments/'+name for name in files}
    actual={name for name in archive.namelist() if name.startswith('attachments/')}
    if expected!=actual:raise ValueError('첨부파일 백업 목록이 일치하지 않습니다.')
    for name,info in files.items():
        path=safe_name(name)
        if not isinstance(info,dict) or type(info.get('size')) is not int or not 0<=info['size']<=10*1024*1024:raise ValueError('첨부파일 백업 크기가 올바르지 않습니다.')
        entry=archive.getinfo('attachments/'+name)
        if entry.file_size!=info['size']:raise ValueError('첨부파일 백업 크기가 일치하지 않습니다.')
        data=archive.read(entry)
        if sha256(data).hexdigest()!=info.get('sha256'):raise ValueError('첨부파일 무결성 검사에 실패했습니다.')
        target=staging.joinpath(*path.parts);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    return staging


def install_files(staging):
    root=settings.DATA_DIR/'purchase-attachments'
    if root.is_symlink():raise ValueError('첨부파일 복구 경로를 확인해 주세요.')
    root.mkdir(parents=True,exist_ok=True)
    for source in staging.rglob('*'):
        if not source.is_file():continue
        name=source.relative_to(staging);target=root/name
        if not target.resolve().is_relative_to(root.resolve()):raise ValueError('첨부파일 복구 경로가 올바르지 않습니다.')
        target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_name(target.name+'.restoring')
        shutil.copyfile(source,temporary);temporary.replace(target)
