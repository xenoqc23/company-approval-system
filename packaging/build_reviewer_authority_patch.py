"""Fix reviewer final authority without changing author-specific route permissions."""
from hashlib import sha256
from zipfile import ZIP_DEFLATED, ZipFile
import build_progressive_patch as previous
ROOT=previous.ROOT
NAME='xenosys-reviewer-authority-20261019'
FILES=(*previous.FILES,'workflow/migrations/0018_reviewer_final_authority.py')
assert len(FILES)==len(set(FILES))
APPLY=(previous.APPLY.replace('\n'.join(previous.FILES),'\n'.join(FILES))
    .replace('APPROVAL_PROGRESSIVE_BASE','APPROVAL_REVIEWER_AUTHORITY_BASE')
    .replace('.progressive-backup.','.reviewer-authority-backup.')
    .replace('PROGRESSIVE_APPROVAL_READY','REVIEWER_AUTHORITY_READY'))
INSTRUCTIONS='''Xenosys 사내결재 — 체크된 검토자에게 전결 권한 부여 (2026-10-19)

설치
1. ZIP을 File Station /docker/company-approval에 업로드합니다.
2. 우클릭 → 여기에 압축 풀기를 선택합니다. 기존 app·data를 삭제하지 않습니다.
3. Windows PowerShell에서 실행합니다.

ssh -t admin@192.168.1.46 "sudo sh /volume1/docker/company-approval/xenosys-reviewer-authority-20261019/APPLY_REVIEWER_AUTHORITY.sh"

4. NAS 관리자 비밀번호를 입력합니다. 두 번 물을 수 있습니다.
5. 마지막 REVIEWER_AUTHORITY_READY 확인 후 PC·휴대폰 사이트를 새로고침합니다.

이번 보완
- ‘검토자 전결 허용’을 기안자가 아닌 실제 검토자의 권한으로 적용합니다.
- 규정에 ‘전결 가능한 검토자 (과장급 이상 · 체크한 직원만)’ 목록을 추가했습니다.
- 기안자가 누구든 체크된 직원이 해당 문서의 검토자로 배정되면 ‘검토자 전결’ 버튼을 사용할 수 있습니다.
- 버튼을 눌러 사유를 남겨야 최종 완료됩니다. 체크하거나 문서를 제출하는 것만으로 자동 승인하지 않습니다.
- 과장·팀장·부장·이사 중 활성·가입 승인·부서 확인된 일반 직원이 대상입니다.
- admin·관리자·회사 대표·과장 미만은 제외하며, 기안자가 본인인 문서는 본인 전결 방식을 사용합니다.
- 문서 종류와 구매금액 하한/상한 조건은 적용합니다. 기안자 직급·부서·특정 직원 제한은 검토자 전결 권한과 별도입니다.
- 연차3일·구매100만원 이상도 허용된 전결로 완료할 수 있습니다. 대표 결재를 강제하지 않습니다.
- 현재 검토 대기 중인 ‘단계별 결재’ 문서에도 검토자 권한 부여·해제가 반영됩니다.
- 권한을 해제하거나 규정을 사용 중지·삭제하면 대기 문서에서도 검토자 전결을 사용할 수 없습니다.
- 이미 완료된 문서와 이전 고정 결재선 문서는 변환하지 않습니다. 상위 결재 흐름도 유지합니다.
- 실제 전결 시 권한을 다시 확인하고 적용 규정·버전·처리자와 사유를 기록합니다.
- 최종 승인 시에만 연차를 차감하고 중복 처리·취소가 이중 차감·복원되지 않게 합니다.

기존 체크값 보존
- 0018은 새 검토자 목록을 추가합니다.
- 기존 ‘검토자 전결 허용’ 규정의 ‘특정 직원’ 목록에서 자격을 갖춘 과장급 이상 직원을 새 목록으로 복사합니다.
- 원래 특정 직원 목록은 지우지 않습니다. 본인 전결·검토 생략·대표 직접 요청 등 기안자별 권한을 유지합니다.
- 기존 특정 직원이 없거나 자격 조건에 맞지 않으면 자동으로 전체 직원에게 권한을 주지 않습니다. 관리자가 필요한 검토자를 직접 선택합니다.

설정 확인
1. 규정 관리 → 전결규정 → 해당 규정 수정.
2. ‘검토자 전결 허용’을 체크합니다.
3. 바로 아래 ‘전결 가능한 검토자’에서 권한을 줄 과장급 이상 직원을 체크합니다.
4. ‘규정 사용’을 체크하고 저장합니다.
5. 해당 검토자가 배정받은 검토 대기 문서를 새로고침하면 전결 버튼을 확인할 수 있습니다.
- ‘기안자 제한’ 목록은 검토자 전결 대상과 별도라고 표시합니다.
- 기안자를 새 검토자 목록에 넣거나 기존 기안자 제한을 전부 해제할 필요가 없습니다.

보존·백업
- 기존 직원·암호·문서·결재선·입사일·생일·연차 잔액·개인/공용 사용 내역을 보존합니다.
- 실제 직원 정보·생일 자료·비밀번호·.env·DB는 ZIP에 포함하지 않습니다.
- 선행0011 소스가 필요하며 이전0012~0017 패치를 누적 포함합니다. 이미 적용된 마이그레이션은 재실행하지 않습니다.
- 0014가 미적용이면 앞서 승인한 입사연도별 연차 산정도 반영하며 수동 총연차·사용량·과거 잔액은 보존합니다.
- 체크섬 확인 → 기존 소스 .reviewer-authority-backup.XXXXXX 보관 → nas.sh update 순서입니다.
- 기존 NAS 업데이트가 새 이미지를 빌드하고 이전 이미지로 DB를 백업한 다음 마이그레이션·웹 전환을 수행합니다.
- 업데이트 중 접속이 잠시 중단됩니다. 오류가 나면 READY를 출력하지 않습니다.
- 다른 업데이트·복구가 진행 중이면 복사 전에 중단합니다.
- 오류 시 출력과 백업 경로를 보관하고 app/data 삭제·재설치·임의 DB 복원을 하지 마세요.

실제 NAS에는 위 스크립트를 실행한 뒤 적용됩니다.
'''

def build():
    out=ROOT/'releases'/f'{NAME}.zip'
    payload={f'app/{name}':(ROOT/name).read_bytes() for name in FILES}
    payload['APPLY_REVIEWER_AUTHORITY.sh']=APPLY.encode()
    payload['NAS_REVIEWER_AUTHORITY_UPDATE.txt']=INSTRUCTIONS.encode()
    payload['SHA256SUMS']=''.join(f'{sha256(data).hexdigest()}  {name}\n' for name,data in payload.items()).encode()
    with ZipFile(out,'w',ZIP_DEFLATED) as a:
        for name,data in payload.items():a.writestr(f'{NAME}/{name}',data)
    with ZipFile(out) as a:
        assert a.testzip() is None
        for name,data in payload.items():assert a.read(f'{NAME}/{name}')==data
    print(f'{out.name}: {out.stat().st_size} bytes; {len(FILES)} runtime files verified.')
    return out

if __name__=='__main__':build()
