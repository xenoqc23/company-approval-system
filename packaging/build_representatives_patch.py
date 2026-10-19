"""Cumulative NAS release: relative birthday navigation and admin-only representative role."""
from hashlib import sha256
from zipfile import ZIP_DEFLATED, ZipFile
import build_birthdays_patch as previous

ROOT=previous.ROOT
NAME='xenosys-representatives-20261019'
FILES=(*previous.FILES,
    'workflow/representatives.py',
    'workflow/migrations/0016_representative_account.py',
    'workflow/people.py',
    'workflow/middleware.py',
    'workflow/manual_leave.py',
    'workflow/templates/workflow/base.html',
    'workflow/templates/workflow/sidebar.html',
    'workflow/templates/workflow/staff.html',
    'workflow/templates/workflow/staff_card.html',
    'workflow/templates/workflow/representative_form.html',
    'workflow/templates/workflow/account.html',
    'workflow/static/workflow/representatives.css',
)
assert len(FILES)==len(set(FILES))
APPLY=(previous.APPLY.replace('\n'.join(previous.FILES),'\n'.join(FILES))
    .replace('APPROVAL_BIRTHDAYS_BASE','APPROVAL_REPRESENTATIVES_BASE')
    .replace('.birthdays-backup.','.representatives-backup.')
    .replace('BIRTHDAYS_READY','REPRESENTATIVES_READY'))
INSTRUCTIONS='''Xenosys 사내결재 — 생일 월 이동·회사 대표 계정 (2026-10-19)

1. ZIP을 File Station /docker/company-approval에 업로드합니다.
2. 우클릭 → 여기에 압축 풀기를 선택합니다. 기존 app·data 폴더는 삭제하지 않습니다.
3. Windows PowerShell에서 실행합니다.

ssh -t admin@192.168.1.46 "sudo sh /volume1/docker/company-approval/xenosys-representatives-20261019/APPLY_REPRESENTATIVES.sh"

4. NAS 관리자 비밀번호를 입력합니다. 두 번 물을 수 있습니다.
5. 마지막 REPRESENTATIVES_READY 확인 후 PC·휴대폰 사이트를 새로고침합니다.

생일자 조회
- 처음에는 이번 달을 표시합니다.
- ‘이전 달 생일 / 이번 달 생일 / 다음 달 생일’ 버튼을 제공합니다.
- 이전·다음 달은 현재 조회 중인 월에서 한 달씩 이동합니다. 연도가 넘어가도 계속 이동합니다.
- ‘이번 달 생일’은 실제 이번 달로 돌아갑니다. 연도·월 직접 선택도 유지합니다.
- 기존 양력/음력 변환·윤달/30일 대체 기준·당일 홈 축하 카드도 유지합니다.

회원가입
- 기존 부서·직급 선택과 가입 승인 절차를 유지합니다.
- ‘대표이사실 / 대표’는 일반 가입 화면에 표시하지 않으며 직접 요청해도 선택할 수 없습니다.
- 대표 계정도 먼저 일반 가입 신청을 합니다. 이름·부서·직급은 admin이 대표 지정 시 변경할 수 있습니다.
- 비밀번호를 임의로 만들거나 실제 대표 계정을 자동 생성하지 않습니다.

회사 대표 지정 (로그인 아이디 admin 전용)
- 직원·권한 관리에서 해당 계정의 ‘회사 대표 지정’을 펼칩니다.
- 생일(양력/음력·월·일), 생일 표시 여부, 전체 제출 문서 조회 여부를 확인하고 지정합니다.
- 부서 ‘대표이사실’, 직책 ‘대표’, 가입 승인·부서 확인 상태로 설정합니다.
- 회사 대표는 한 명만 지정할 수 있습니다. 기존 대표가 있으면 교체 확인을 체크해야 합니다.
- 다른 직원에게 admin 업무 권한을 부여해도 대표 지정·교체·설정·해제 권한은 생기지 않습니다.
- 지정 후 ‘대표이사실’ 탭에서 설정을 바꾸고, 필요하면 지정 전 부서·직급·승인 상태로 해제할 수 있습니다.
- 해제·교체 후 업무 관리 권한은 자동 복원하지 않습니다. 필요한 권한만 별도로 다시 지정합니다.
- 지정·교체·설정·해제는 처리 이력을 남깁니다.

대표 계정의 현재 이용 범위
- 현재 조회 전용입니다. 문서 기안·검토·승인·발주·수령·직원 부재 등록 및 수정은 제한합니다.
- 검토자·승인자·수령자 선택과 간소결재, 전결규정 기안 대상자 선택에서 제외합니다.
- 대기 중 결재·물품 수령이나 사용 중 전결규정의 고정 담당자로 남아 있으면 먼저 정리해야 지정할 수 있습니다.
- 생일자·직원 일정·직원복지·내 계정·본인 비밀번호 변경은 이용할 수 있습니다.
- 생일 표시는 기본 켜짐이며 생일 당일 목록·홈 축하 카드에 함께 표시합니다. admin이 끌 수 있습니다.
- 전체 제출 문서 조회는 기본 꺼짐입니다. admin이 별도로 켜면 임시저장·삭제를 제외한 제출 문서를 조회할 수 있습니다.
- 기본 상태에서도 본인과 관련된 기존 문서 이력은 조회할 수 있습니다. 관리자 권한은 부여하지 않습니다.
- 연차·공용연차·장기근속 포상 자동 산정 대상에서는 제외합니다.
- 기존에 있던 문서·연차 잔액·개인/공용 사용 이력은 삭제하거나 다시 계산하지 않습니다.

보존·백업
- 0016은 대표 구분·설정·지정 전 정보 보관 필드와 제약만 추가합니다. 기존 직원을 자동 대표 지정하지 않습니다.
- 기존 직원·생일·입사일·암호·문서·규정·연차 기록을 유지합니다. .env·실제 DB·직원 자료는 포함하지 않습니다.
- 직전 생일자·공통 전결규정·입사연도별 연차 산정 패치를 함께 포함합니다. 적용된 마이그레이션은 재실행하지 않습니다.
- 선행 0011 소스가 설치된 NAS가 필요합니다. 0014가 미적용이면 앞서 승인한 입사연도별 산정도 함께 반영되며 수동 총연차·사용량·과거 잔액은 보존합니다.
- 체크섬 검증 → 기존 소스 .representatives-backup.XXXXXX 보관 → nas.sh update 순서입니다.
- 새 이미지 빌드 후 이전 이미지로 DB 백업을 완료한 다음 스키마 변경·웹 전환을 진행합니다.
- 업데이트 중 접속이 잠시 중단됩니다. 실패 시 READY를 출력하지 않습니다.
- 다른 업데이트·복구가 진행 중이면 소스 복사 전에 중단합니다.
- 오류가 나면 출력과 백업 경로를 보관하고 app/data 삭제·재설치·임의 DB 복원을 하지 마세요.

실제 NAS에는 위 스크립트를 실행한 후 적용됩니다.
'''

def build():
    output=ROOT/'releases'/f'{NAME}.zip'
    payload={f'app/{name}':(ROOT/name).read_bytes() for name in FILES}
    payload['APPLY_REPRESENTATIVES.sh']=APPLY.encode()
    payload['NAS_REPRESENTATIVES_UPDATE.txt']=INSTRUCTIONS.encode()
    payload['SHA256SUMS']=''.join(f'{sha256(data).hexdigest()}  {name}\n' for name,data in payload.items()).encode()
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        for name,data in payload.items():archive.writestr(f'{NAME}/{name}',data)
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        for name,data in payload.items():assert archive.read(f'{NAME}/{name}')==data
    print(f'{output.name}: {output.stat().st_size} bytes; {len(FILES)} runtime files verified.')
    return output

if __name__=='__main__':build()
