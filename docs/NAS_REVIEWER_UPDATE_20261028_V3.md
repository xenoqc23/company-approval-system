# 검토자 화면 수정 · NAS 업데이트 v3 · 2026-10-28

2026-10-26 v2가 적용된 사내결재시스템용 수정본입니다. 기존 담당자·권한·규정, 문서·결재 이력·구매집계·연차·첨부를 유지합니다. DB 구조 변경은 없습니다. 초기 설치나 데이터 초기화를 실행하지 않습니다. 삭제한 테스트 문서를 다시 생성하지 않습니다.

## 화면 변경

- 휴가원과 구매요청의 검토자 화면에서 승인자 부서·직원 선택을 처음부터 펼쳐 표시합니다.
- 기본 버튼은 **선택한 승인자에게 전달**입니다.
- 전결은 반려 아래의 **전결 처리** 영역에 별도로 배치합니다. 버튼 이름은 **전결로 승인완료**이며 기존 전결 권한이 있는 검토자에게만 표시합니다.
- 구매요청 전결은 기존과 같이 내부 승인 완료입니다. 이후 구매확인·결제 절차가 이어집니다.

기존 승인자 후보·전결 권한·사유 입력 조건과 처리 서비스는 유지합니다. 아이디 저장, 같은 화면에서 문서 종류 전환, 구매확인 담당자 변경 기능도 유지합니다.

## ZIP 업로드

1. 받은 `xenosys-nas-reviewer-update-20261028-v3.zip`을 최신 백신으로 검사합니다. 탐지·차단이 있으면 허용이나 검사 제외를 설정하지 말고 탐지 내용을 확인합니다. 기능·무결성 검증은 백신 검사와 별개입니다.
2. ZIP 자체를 NAS File Station의 `docker/company-approval/updates`에 올립니다.
3. NAS에서 ZIP을 직접 압축 해제합니다. `updates` 아래에 다음 경로가 생기는지 확인합니다. 기존 운영 폴더에 직접 덮어쓰지 않습니다.

```text
docker/company-approval/updates/xenosys-nas-reviewer-update-20261028-v3/
├─ app/
├─ README.md
├─ RELEASE.json
├─ SHA256SUMS
└─ UPDATE_NAS.sh
```

## NAS 접속과 사전 점검

Windows PowerShell의 `PS C:\Users\...>` 상태라면 먼저 NAS에 접속합니다. 아래 IP는 기존에 사용한 NAS 주소입니다. 주소가 바뀌었다면 현재 주소를 사용합니다.

```powershell
ssh admin@192.168.1.46
```

NAS admin 계정 비밀번호를 입력합니다. 입력 중 문자가 표시되지 않는 것은 정상입니다. 앞부분이 **`admin@xenonas`**로 바뀐 NAS SSH 창에서 다음을 실행합니다.

```sh
cd /volume1/docker/company-approval/updates/xenosys-nas-reviewer-update-20261028-v3
sudo sh UPDATE_NAS.sh precheck --operator admin
```

`--operator admin`은 사내결재시스템 관리자 아이디입니다. 별도 관리자 아이디를 사용한다면 해당 값으로 바꿉니다. 직원 이름과 구매 담당자 지정 옵션은 다시 입력하지 않습니다.

사전 점검은 배포 파일 검증·이미지 준비·기존 계정·문서·담당자 확인을 수행합니다. 통과하면 `Precheck complete. Existing web service is still running.`이 표시됩니다. 이 단계에서는 현재 웹 서비스가 계속 실행됩니다.

## 적용

직원들이 문서를 작성·저장하지 않는 시간에, 사전 점검을 통과한 같은 NAS SSH 창에서 실행합니다. 적용 중에는 서비스가 잠시 중단됩니다.

```sh
sudo sh UPDATE_NAS.sh update --operator admin
```

웹 중지 → 기존 DB·첨부 기준값 저장 → 백업 → DB 변경 확인 → 기존 데이터 보존 비교 → 기존 구매 설정 유지 → 시스템 검사 → 새 웹 기동·상태 확인 순서입니다.

정상 완료 시 `Update complete. Staff can refresh their browser. Previous image and backup are retained.`이 표시됩니다. 기존 설정 유지 메시지와 데이터 보존 비교 통과도 확인합니다. 오류가 나면 다음 명령을 임의로 이어 실행하지 말고 결과를 확인합니다.

`Release file verification failed`나 `No such file or directory`가 나오면 원본 ZIP을 NAS에서 다시 압축 해제합니다. `SHA256SUMS` 검증을 삭제하거나 생략하지 않습니다.

## 적용 후 확인

기존 접속 주소에서 Ctrl+F5로 새로고침합니다.

1. 검토 대기인 휴가원과 구매요청을 열었을 때 승인자 부서·직원 선택이 바로 보이는지 확인합니다.
2. 승인자를 선택해 전달하면 해당 승인자에게 넘어가는지 확인합니다.
3. 전결 권한이 있는 검토자에게만 하단의 `전결로 승인완료`가 보이는지 확인합니다.
4. 승인자 화면의 일반 `승인완료`, 기존 문서·연차·구매집계·담당자 설정을 확인합니다.

실제 NAS 적용과 현장 확인은 관리자가 수행합니다. 이 ZIP에는 실제 직원·DB·암호·가상 직원 생성기·테스트 문서·협업일지를 넣지 않습니다.

## 복구

문제가 있으면 같은 업데이트 폴더의 NAS SSH 창에서 직전 이미지와 백업으로 복구할 수 있습니다. 복구는 업데이트 직전 상태로 돌아가므로 백업 이후 새로 입력한 내용도 되돌아갑니다. 업무 재개 전에 판단합니다.

```sh
sudo sh UPDATE_NAS.sh rollback
```

업데이트 폴더와 백업은 정상 사용을 확인할 때까지 보관합니다.
