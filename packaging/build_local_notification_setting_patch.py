"""Small overlay for existing local trial v2/v3/v4 folders; preserve runtime data."""
import argparse
import hashlib
from pathlib import Path
from zipfile import ZipFile,ZipInfo,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
NAME='xenosys-local-notification-setting-fix-20261109-v5'
FILES=('desktop.py','toast_content.py')
README='''로컬 알림 설정값 오류 수정 · v5

기존 테스트 프로그램 창을 닫은 뒤 진행합니다. NAS 업데이트 파일이 아닙니다.

1. 이 ZIP 안의 desktop.py와 toast_content.py를 복사합니다.
2. 기존 START_TEST.bat이 있는 로컬 테스트 폴더에 붙여넣고 같은 이름 파일을 덮어씁니다.
3. 기존 폴더의 START_TEST.bat을 다시 실행합니다.
4. 4번의 가상 미결 2건 만들기 → PC 켜기 알림 지금 시험을 누릅니다.

빈 알림 설정값을 차단으로 잘못 판단해 표시 요청 전에 중단하던 오류를 수정합니다.
설정값을 읽지 못하면 확인 불가로 표시하고 Windows에 실제 표시를 요청합니다.
명확한 차단 값과 실제 API 오류는 계속 표시하며, Windows 알림·보안 정책을 바꾸지 않습니다.
자동 실행 등록 경로, .venv, .local-test-data, 저장한 가상 문서는 변경하지 않습니다.
알림 실행 파일만 수정하므로 화면 상단의 기존 버전 문구는 그대로 남을 수 있습니다.

폴더 안에 이 두 파일만 새 폴더로 풀고 실행하는 방식이 아닙니다.
기존 START_TEST.bat과 서버 파일이 있는 폴더에 덮어써야 합니다.
v2/v3/v4 로컬 테스트 폴더에 적용할 수 있습니다. 실제 Windows 표시 여부는 PC에서 확인해야 합니다.
'''


def build(destination):
    destination=Path(destination)
    if destination.exists():raise FileExistsError('Published archives are immutable.')
    files={name:(ROOT/'local_push_test'/name).read_bytes() for name in FILES}
    files['READ_ME_PATCH.txt']=README.encode('utf-8-sig')
    files['PATCH_SHA256SUMS.txt']=''.join(f'{hashlib.sha256(data).hexdigest()}  {name}\n' for name,data in sorted(files.items())).encode()
    destination.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(destination,'w') as z:
        for name,data in sorted(files.items()):
            info=ZipInfo(name,date_time=(2026,11,9,0,0,0));info.compress_type=ZIP_DEFLATED;info.external_attr=0o644<<16
            z.writestr(info,data)
    digest=hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix('.zip.sha256').write_text(f'{digest}  {destination.name}\n')
    return digest


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('destination')
    print(build(parser.parse_args().destination))
