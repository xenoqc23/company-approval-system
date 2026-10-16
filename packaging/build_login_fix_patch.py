"""Build the NAS re-login fix, reusing the checked file-backup/update procedure."""
from hashlib import sha256
from zipfile import ZIP_DEFLATED, ZipFile

import build_mobile_ui_patch as mobile


ROOT = mobile.ROOT
NAME = 'xenosys-login-fix-20261016'
FILES = (
    'approval_site/settings.py',
    'workflow/views.py',
    'workflow/urls.py',
    'workflow/middleware.py',
    'workflow/templates/workflow/base.html',
    'workflow/templates/workflow/login.html',
    'workflow/static/workflow/auth.js',
)
assert mobile.APPLY.count('\n'.join(mobile.FILES)) == 1
APPLY = (mobile.APPLY.replace('\n'.join(mobile.FILES), '\n'.join(FILES))
         .replace('.mobile-ui-backup.', '.login-fix-backup.')
         .replace('MOBILE_UI_READY', 'LOGIN_FIX_READY'))

INSTRUCTIONS = '''Xenosys 사내결재 — 로그아웃 후 재로그인 403 방지 (2026-10-16)

1. 이 ZIP을 NAS File Station의 /docker/company-approval 폴더에 올립니다.
2. ZIP을 우클릭해 "여기에 압축 풀기"를 실행합니다.
   기존 app 폴더나 DB 폴더를 삭제하지 않습니다.
3. Windows PowerShell에서 실행합니다.

ssh -t admin@192.168.1.46 "sudo sh /volume1/docker/company-approval/xenosys-login-fix-20261016/APPLY_LOGIN_FIX.sh"

4. NAS 관리자 비밀번호를 묻는 경우 입력합니다.
5. 마지막 LOGIN_FIX_READY를 확인합니다.
6. 일반 브라우저의 새 탭에서 아래 주소를 열어 로그인합니다.

https://xenonas.synology.me:18443/login/?v=20261016authfix1

7. 로그아웃 후 다시 로그인하는 과정을 두 번 이상 확인합니다.
   PC와 휴대폰에서 모두 확인합니다. 쿠키를 반복해서 지울 필요는 없습니다.

수정 내용:
- 사내결재 전용 세션·CSRF 쿠키 이름으로 다른 앱의 기본 쿠키와 분리.
- 로그인·로그아웃과 동적 화면을 브라우저 캐시에 저장하지 않도록 지정.
- 로그인 버튼을 누르면 같은 서버에서 최신 CSRF 토큰을 받은 뒤 제출.
- CSRF 검사와 HTTPS 보안 쿠키 설정 유지. 잘못된 Origin·누락/오래된
  토큰의 직접 POST는 여전히 거절하며, 실패한 POST를 자동 재실행하지 않음.

업데이트 후 쿠키 이름 변경으로 기존 로그인은 한 번 해제됩니다.
모바일 화면, 계정·비밀번호·권한·문서·연차 규칙과 .env는 그대로 유지합니다.
기존 소스는 .login-fix-backup.XXXXXX에 보관합니다.
기존 nas.sh update가 DB 백업과 웹 이미지 재빌드를 수행하므로 잠시 중단됩니다.
오류 발생 시 출력과 백업 경로를 보관하고 삭제·재설치·DB 복원을 실행하지 않습니다.

133개 Django 시험: 129개 통과, MariaDB 전용 4개 건너뜀.
운영 NAS 자체의 재로그인 확인은 적용 후 별도로 진행해야 합니다.
'''


def build():
    output = ROOT / 'releases' / f'{NAME}.zip'
    payload = {f'app/{name}': (ROOT / name).read_bytes() for name in FILES}
    payload['APPLY_LOGIN_FIX.sh'] = APPLY.encode()
    payload['NAS_LOGIN_FIX.txt'] = INSTRUCTIONS.encode()
    payload['SHA256SUMS'] = ''.join(
        f'{sha256(data).hexdigest()}  {name}\n' for name, data in payload.items()
    ).encode()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for name, data in payload.items():
            archive.writestr(f'{NAME}/{name}', data)
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        for name, data in payload.items():
            assert archive.read(f'{NAME}/{name}') == data
    print(f'{output.name}: {output.stat().st_size} bytes; {len(FILES)} files verified.')
    return output


if __name__ == '__main__':
    build()
