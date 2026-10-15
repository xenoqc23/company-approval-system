"""Build the small, CSS-only update for an already installed NAS application."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parent.parent
files = ['style.css', 'xenosys.css', 'workspace.css']
instructions = '''Xenosys 사내결재시스템 — 넓은 화면 가독성 수정

1. ZIP 압축을 풉니다.
2. CSS 파일 3개(style.css, xenosys.css, workspace.css)만 NAS의 아래 폴더에 올립니다.
   /volume1/docker/company-approval/app/workflow/static/workflow
3. 같은 이름의 파일은 덮어씁니다. 기존 폴더나 다른 파일은 삭제하지 않습니다.
4. NAS에 접속한 PowerShell 창에서 아래 명령을 실행합니다.

sudo sh /volume1/docker/company-approval/app/deploy/nas/nas.sh update

5. Update complete 문구를 확인하고 브라우저에서 Ctrl+Shift+R로 새로고침합니다.
   브라우저 배율은 100%로 두세요.

이 파일은 화면 스타일만 변경합니다. DB·직원·문서·권한·연차 계산은 변경하지 않습니다.
업데이트 명령은 반영 전 DB를 백업하고 웹 서비스를 잠시 다시 시작합니다.
기존 테스트 화면 크기는 유지하며, 넓은 화면에서는 글자·메뉴·카드를 최대 25% 확대합니다.
'''
output = root / 'releases/xenosys-ui-readability-20261015.zip'
output.parent.mkdir(parents=True, exist_ok=True)
with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
    for name in files:
        archive.write(root / 'workflow/static/workflow' / name, name)
    archive.writestr('NAS_UI_UPDATE.txt', instructions)
with ZipFile(output) as archive:
    assert archive.testzip() is None
    for name in files:
        assert archive.read(name) == (root / 'workflow/static/workflow' / name).read_bytes()
print(f'{output.name}: {output.stat().st_size} bytes; verified against source CSS.')
