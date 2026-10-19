"""Cumulative NAS birthday support with Korean solar/lunar conversion."""
from hashlib import sha256
from zipfile import ZIP_DEFLATED, ZipFile
import build_hire_year_tenure_patch as previous

ROOT=previous.ROOT
NAME='xenosys-birthdays-20261019'
FILES=(*previous.FILES,
    'requirements-prototype.txt',
    'workflow/birthdays.py',
    'workflow/migrations/0015_employee_birthdays.py',
    'workflow/templates/workflow/welfare.html',
    'workflow/templates/workflow/signup.html',
    'workflow/templates/workflow/birthday_list.html',
    'workflow/templates/workflow/birthday_fields.html',
    'workflow/templates/workflow/birthday_banner.html',
    'workflow/static/workflow/birthdays.css',
    'workflow/static/workflow/birthdays.js',
    'workflow/static/workflow/images/birthday-cake.svg',
)
assert len(FILES)==len(set(FILES))
APPLY=(previous.APPLY.replace('\n'.join(previous.FILES),'\n'.join(FILES))
    .replace('APPROVAL_HIRE_YEAR_TENURE_BASE','APPROVAL_BIRTHDAYS_BASE')
    .replace('.hire-year-tenure-backup.','.birthdays-backup.')
    .replace('HIRE_YEAR_TENURE_READY','BIRTHDAYS_READY'))
INSTRUCTIONS='''Xenosys 사내결재 — 생일자·양력/음력 생일·종무식 포상 안내 (2026-10-19)

1. ZIP을 File Station /docker/company-approval에 업로드합니다.
2. 우클릭 → 여기에 압축 풀기를 선택합니다. 기존 app·data는 삭제하지 않습니다.
3. Windows PowerShell에서 실행합니다.

ssh -t admin@192.168.1.46 "sudo sh /volume1/docker/company-approval/xenosys-birthdays-20261019/APPLY_BIRTHDAYS.sh"

4. NAS 관리자 비밀번호를 입력합니다. 두 번 물을 수 있습니다.
5. 마지막 BIRTHDAYS_READY 확인 후 PC·휴대폰 사이트를 새로고침합니다.

추가 기능
- 직원복지의 첫 탭과 기본 화면을 ‘생일자’로 설정했습니다.
- 이번 달·다음 달 바로가기와 연도·1~12월 선택으로 해당 월 생일자만 조회합니다.
- 이름·부서/직급·양력 생일을 날짜순으로 표시하고, 당일은 ‘오늘 생일’을 강조합니다.
- 음력 생일은 원래 입력값도 함께 표시합니다. 출생연도와 나이는 수집하지 않습니다.
- 생일 당일 모든 직원의 홈 ‘내 업무’ 옆에 축하 문구와 케이크 그림을 표시합니다.
- 신규 회원가입에 생일 기준(양력/음력)·월·일 입력을 추가했습니다.
- 기존 직원은 생일 미등록 상태로 유지합니다. 연차 관리 담당자가 직원별 연차 관리 →
  ‘입사일·생일·연차 관리’를 펼쳐 생일만 별도로 저장할 수 있습니다.
- ‘생일 미등록 직원’ 목록은 연차 관리 담당자에게만 표시하며, 이름을 누르면 입력 화면으로 이동합니다.

음력 처리 (사용자가 확인한 방식)
- 한국 음력 기준으로 매년 다시 변환하며, 음력 12월이 다음 양력 해에 해당하는 경우도 조회합니다.
- 윤달 생일은 윤달을 체크합니다. 해당 윤달이 없는 해에는 같은 음력 평달 날짜를 사용합니다.
- 음력 30일이 그해 해당 월에 없으면 29일을 사용합니다.
- 자동 변환 라이브러리의 지원 범위는 양력 조회 1001~2050년입니다.
- 양력 2월 29일은 실제 해당 날짜가 있는 해에 표시하며 임의 대체하지 않습니다.

포상 안내
- 장기근속 포상의 ‘구분’을 ‘포상 안내’로 바꿨습니다.
- 올해·향후 연도에는 ‘연말 종무식 포상 예정’, 과거 조회에는 ‘연말 종무식 일괄 포상’으로 표시합니다.
- 대상일 도래 여부에 따라 실제 지급 여부를 자동 판단하지 않습니다.
- 근속 포상 대상자·대상일·근속연수·금액/포상표 자체는 변경하지 않습니다.

보존·백업
- 0015는 생일 기준·월·일·윤달 필드와 유효성 제약만 추가합니다. 기존 생일은 추정하지 않습니다.
- 생일 저장은 입사일·총연차·사용연차·개인/공용 사용내역을 변경하지 않습니다.
- 기존 직원·문서·비밀번호·규정과 과거 데이터는 유지합니다. .env·실제 DB·직원 생일 자료는 포함하지 않습니다.
- 앞선 공통 전결규정 및 입사연도별 산정 패치를 함께 포함합니다. 이미 적용된 마이그레이션은 반복 실행되지 않습니다.
- 선행 0011이 설치된 NAS가 필요합니다. 0014가 아직 적용되지 않았다면 기존에 승인한
  입사연도별 연차 산정 변경도 함께 반영하며 수동 총연차·사용량·과거 잔액은 보존합니다.
- 파일 체크섬 확인 → 기존 소스 .birthdays-backup.XXXXXX 보관 → nas.sh update 순서로 진행합니다.
- 기존 업데이트가 새 이미지 빌드 후 이전 이미지로 DB를 백업한 다음 스키마 변경과 웹 전환을 수행합니다.
- 한국 음력 변환 라이브러리(korean-lunar-calendar==0.4.0)를 새 이미지에 포함합니다.
  설치 후 생일 조회 시 외부 서버에 직원 정보를 전송하거나 외부 API를 호출하지 않습니다.
- 업데이트 중 접속이 잠시 중단됩니다. 오류가 나면 READY를 출력하지 않습니다.
- 다른 업데이트/복구가 진행 중이면 소스 복사 전에 중단합니다.
- 오류 시 출력과 백업 경로를 보관하고 app/data 삭제·재설치·임의 DB 복원을 하지 마세요.

실제 NAS에는 위 스크립트를 실행한 후 적용됩니다.
'''

def build():
    output=ROOT/'releases'/f'{NAME}.zip'
    payload={f'app/{name}':(ROOT/name).read_bytes() for name in FILES}
    payload['APPLY_BIRTHDAYS.sh']=APPLY.encode()
    payload['NAS_BIRTHDAYS_UPDATE.txt']=INSTRUCTIONS.encode()
    payload['SHA256SUMS']=''.join(f'{sha256(data).hexdigest()}  {name}\n' for name,data in payload.items()).encode()
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        for name,data in payload.items():archive.writestr(f'{NAME}/{name}',data)
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        for name,data in payload.items():assert archive.read(f'{NAME}/{name}')==data
    print(f'{output.name}: {output.stat().st_size} bytes; {len(FILES)} runtime files verified.')
    return output

if __name__=='__main__':build()
