# Xenosys 사내결재시스템 — NAS 설치·운영 안내

대상: Synology DS218+ / DSM 7.1.1 / Docker / Intel amd64 / RAM 2GB.
NAS 실제 설치는 사용자가 진행한다. 클라우드 시험 결과와 실제 NAS 설치 여부는 별도로 기록한다.

## 파일과 데이터의 위치

```text
/volume1/docker/company-approval/
  app/                    프로그램 원본 (manage.py, deploy, workflow 등이 바로 위치)
  data/app/               프로그램의 영속 운영 자료
  data/mariadb/           전용 DB (직원·기안·결재·연차·규정)
  backups/                DB 논리 백업 ZIP
  .env                    비밀키·DB 연결·접속 주소 (자동 생성, 외부 공유 금지)
  initial-login.txt       최초 관리자 로그인 정보 (비밀번호 변경 후 삭제)
  .current-image          현재 운영 이미지
  .rollback-image         직전 업데이트의 이미지
  .rollback-backup        직전 업데이트 전 백업 파일명
```

프로그램을 교체할 때 `data`, `backups`, `.env`는 건드리지 않는다. 기존 `nexflow_app1`, 문서 뷰어, NAS의 MariaDB 10/3306은 그대로 둔다. 결재 DB는 별도 Docker 네트워크에서만 연결하고 외부 포트를 열지 않는다. 앱 포트만 기본 `192.168.1.46:18080`으로 사용한다. 포트가 충돌하면 기존 서비스를 끄지 말고 `.env`의 APP_PORT를 다른 미사용 포트로 바꾼다.

## 처음 설치 — 한 단계씩 진행

1. 제공받은 ZIP을 PC에서 압축 해제한다. 안쪽 폴더의 **내용물**을 File Station의 `docker/company-approval/app`에 올린다. `app/manage.py`, `app/deploy/nas/nas.sh`가 보여야 한다. 압축 파일명과 같은 폴더를 한 겹 더 만들지 않는다.
2. DSM **제어판 → 터미널 및 SNMP → 터미널 → SSH 서비스 활성화**를 켠다. 포트는 화면에 표시된 값을 사용한다. 공유기에서 SSH 포트를 외부로 개방하지 않는다.
3. Windows **PowerShell**을 연다. 아래 명령의 `NAS관리자아이디`는 DSM에 로그인하는 관리자 아이디로 바꾼다. 첫 접속의 장치 지문은 사내 NAS 주소가 맞는지 확인하고 진행한다. 입력하는 비밀번호가 화면에 표시되지 않는 것은 정상이다.

```powershell
ssh NAS관리자아이디@192.168.1.46
```

4. NAS에 접속된 창에서 설치한다. `sudo` 비밀번호도 DSM 관리자 비밀번호다. NAS에 Python을 설치할 필요가 없다.

```sh
sudo sh /volume1/docker/company-approval/app/deploy/nas/nas.sh install
```

처음에는 Python·MariaDB 이미지와 패키지를 내려받고 빌드하므로 시간이 걸린다. NAS의 인터넷 연결이 필요하다. 창을 닫지 않고 완료 문구를 기다린다. 다운로드/인증서 오류가 나면 TLS 검증을 끄지 말고 출력된 마지막 오류를 확인한다. 비밀키나 `.env` 내용은 캡처해 보내지 않는다.

5. 같은 사내 네트워크의 PC에서 `http://192.168.1.46:18080`을 연다. **초기 사내 연결 확인용 HTTP 주소**다. File Station에서 `company-approval/initial-login.txt`를 본인만 열어 임시 비밀번호를 확인한다. 읽기 권한이 없으면 NAS 관리자 SSH에서 `sudo cat /volume1/docker/company-approval/initial-login.txt`로 확인한다. 아이디는 `admin`이며 첫 로그인에서 비밀번호를 변경한다. 변경 후 이 파일을 삭제한다.
6. 실제 직원이 가입 신청 → 관리자가 승인·부서·직급·권한 설정 → 연차 담당자가 입사일·기초 연차·규정을 확인한다. 샘플 계정·문서는 생성하지 않는다. PC 검토 DB도 가져오지 않는다.
7. **정식 사용 전** 아래 HTTPS·주소 유지·자동 백업·외부 사본·실제 PC 점검을 완료한다. SSH가 더 필요 없으면 끌 수 있다.

초기화 명령은 기존 계정이 있으면 암호나 규정을 덮어쓰지 않는다. 설치가 중단되면 원인을 고친 후 `install`을 다시 실행할 수 있다. `.env`가 사라졌는데 DB 자료가 남아 있으면 새 암호를 생성해 해결하지 말고 원래 `.env`부터 복구한다.

## 자동 백업과 연초 갱신

DSM **제어판 → 작업 스케줄러 → 생성 → 예약된 작업 → 사용자 정의 스크립트**:

- 작업명: `Xenosys 결재시스템 일일 백업`
- 사용자: `root`
- 일정: 매일 오전 3시 등 업무가 없는 시간 (NAS 시간대 서울 확인)
- 작업 설정 → 사용자 정의 스크립트:

```sh
sh /volume1/docker/company-approval/app/deploy/nas/nas.sh scheduled-backup
```

작업 스케줄러의 **실행**으로 한 번 시험하고 `backups` 및 관리자 백업 화면을 확인한다. 작업 결과 이메일 알림은 DSM의 알림 기능을 사용하는 경우 실패 시 알림으로 연결한다. DB가 통째로 중단되면 앱 알림도 저장할 수 없으므로 DSM 작업 결과 확인이 필요하다.

매일 백업은 하루 하나·최근 30개, 월별 백업은 해당 월 최초 실행 시 하나·최근 12개를 유지한다. 수동·업데이트 전·복구 직전 백업은 자동 삭제하지 않는다. 데이터가 많아지면 해당 파일은 담당자가 별도로 정리한다. 예약 명령은 연초 자동 연차 산정도 반복 실행하며 기존 사용연차·수동 조정값을 보존한다. 설정 전에는 자동 예약이 켜졌다고 간주하지 않는다.

수동 백업:

```sh
sudo sh /volume1/docker/company-approval/app/deploy/nas/nas.sh backup
```

백업 ZIP은 SQL과 SHA-256 확인 자료를 함께 담고 있다. 파일에 직원 개인정보가 있으므로 권한은 제한한다. DB 복구 시 기존 앱 자료도 필요할 수 있으므로 `.env`, 프로그램 릴리스 원본과 사용 이미지도 보관한다. 현재는 첨부파일 업로드 기능이 없어 DB가 주 업무 자료이며, 이후 첨부파일을 추가하면 별도 파일 백업을 함께 설계한다.

## NAS 외부 사본

같은 NAS의 백업만으로는 NAS 장애에 대비할 수 없다. Hyper Backup에서 `company-approval/backups`, `.env`, 사용 릴리스 원본을 USB 디스크 또는 별도 장치에 정기 백업한다. 암호화 키와 복구 암호는 안전한 별도 장소에 보관한다. 실행 중인 `data/mariadb` 폴더 단순 복사만으로 DB 복구를 대신하지 않는다. 설정 후 별도 장치의 실제 사본으로 시험 복구한다.

## 프로그램 업데이트

직원 PC에는 재설치하지 않는다. 업데이트 담당자가 NAS 한 곳만 교체한다.

1. 새 ZIP을 `app.new`에 풀고 `manage.py`와 `deploy/nas/nas.sh` 위치를 확인한다.
2. 기존 `app`을 `app.previous`로 보관하고 `app.new`를 `app`으로 바꾼다. 실행 중인 컨테이너는 이미지에서 동작하므로 이 폴더 교체만으로 업무가 끊기지 않는다. 이전 `app.previous`가 있으면 별도 날짜 폴더로 옮겨 보관한다.
3. 직원에게 작업 시간을 알리고 아래 명령을 실행한다.

```sh
sudo sh /volume1/docker/company-approval/app/deploy/nas/nas.sh update
```

새 이미지 빌드 → 웹 서비스 중지 → 업데이트 직전 DB 백업 → 스키마 반영·연차 갱신 → 새 앱 시작·DB 연결 검사 순서다. 빌드 실패는 현재 서비스를 멈추지 않는다. 백업·DB 변경·시작 검사 실패는 서비스를 중지한 채 끝나며 원인을 확인한다. 성공 후 직원은 브라우저를 새로고침한다. 빌드 소스가 실제로 적용됐는지는 화면 점검도 진행한다.

DB 스키마가 바뀔 수 있으므로 코드 이미지만 되돌리지 않는다. 최신 변경을 버리고 **업데이트 직전 자료와 이미지로** 돌아가려면:

```sh
sudo sh /volume1/docker/company-approval/app/deploy/nas/nas.sh rollback
```

직전 업데이트 이미지를 삭제하면 이 명령으로 복구할 수 없다. `docker image prune -a`나 데이터 볼륨 삭제 명령은 사용하지 않는다. 복구 후 원본 폴더도 대응하는 `app.previous` 버전으로 보관·정리한다. 더 이전 버전으로의 복구는 해당 버전 이미지와 같은 시점 백업을 확보한 뒤 별도 점검한다.

## 특정 백업 복구

현재 업무 변경분은 선택한 시점으로 대체되므로 작업 전에 직원에게 알린다. 파일명은 백업 화면 또는 NAS 폴더에서 확인한다.

```sh
sudo sh /volume1/docker/company-approval/app/deploy/nas/nas.sh restore backup-여기에실제파일명.zip
```

서비스 중지 → ZIP·SHA-256 확인 → 임시 DB에 복원·필수 테이블·마이그레이션 검증 → 현재 DB 안전 백업 → 실제 DB 복구 → 앱 재시작·연결 검사 순서다. 복구 실패 시 앱은 중지 상태로 둔다. 실패 단계에 따라 실제 DB 반영 전일 수도, 반영 도중일 수도 있으므로 무조건 기존 DB가 그대로라고 가정하지 않는다. `before-restore` 안전 백업을 유지하고 로그로 단계를 확인한다. 관리자 웹 화면에서는 운영 DB를 복구하지 않는다.

현재 프로그램에 없는 새로운 DB 변경 이력이 포함된 백업은 거부한다. 해당 백업과 대응하는 프로그램 버전으로 복구해 주세요.

복구 뒤에는 직원 수·문서 수·승인 이력·연차 합계를 해당 백업 시점과 비교한다. 분기별 또는 중요 업데이트 전에 별도 시험 환경에서 복구 연습을 한다.

## 상태 확인과 재시작

```sh
sudo sh /volume1/docker/company-approval/app/deploy/nas/nas.sh status
sudo sh /volume1/docker/company-approval/app/deploy/nas/nas.sh logs
sudo sh /volume1/docker/company-approval/app/deploy/nas/nas.sh stop
sudo sh /volume1/docker/company-approval/app/deploy/nas/nas.sh start
```

`stop`은 결재 웹 서비스만 멈춘다. NAS의 다른 컨테이너와 DB 자료는 삭제하지 않는다. 정상 설치 후 앱·DB 컨테이너는 Docker의 `unless-stopped` 정책으로 재시작한다. 실패한 업데이트를 표시하는 `.pending-image` 또는 미완료 복구의 `.recovery-in-progress`가 있으면 무작정 시작하지 않고 복구를 완료하거나 rollback한다. 작업 중 전원이 꺼져 `.operation.lock`만 남았다면 다른 설치·백업·복구가 실행 중인지 먼저 확인한 뒤 그 빈 폴더만 제거한다.

## 정식 사용 전: 주소 유지와 HTTPS

현재 IP는 DHCP다. 공유기에서 NAS의 기존 주소 `192.168.1.46`을 DHCP 예약하는 방식을 우선 적용한다. NAS IP를 임의 변경해 다른 서비스 연결을 끊지 않는다.

사내 DNS 이름 또는 실제 인증서를 발급할 수 있는 회사 도메인을 정하고 DSM **제어판 → 로그인 포털 → 고급 → 역방향 프록시**에서 HTTPS 주소를 `http://127.0.0.1:18080`으로 연결한다. 인증서를 배정하고 아래 `.env` 값을 실제 주소에 맞게 수정한다. 예시는 실제 도메인이 정해진 뒤 대체하며 그대로 복사하지 않는다.

```text
BIND_IP=127.0.0.1
DJANGO_ALLOWED_HOSTS=실제도메인,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=https://실제도메인
DJANGO_SECURE_COOKIES=1
DJANGO_SSL_REDIRECT=1
DJANGO_TRUST_PROXY=1
```

프록시의 `X-Forwarded-Proto`가 HTTPS 원본을 올바르게 전달하는지 확인한다. HTTPS 구성에서는 앱 포트를 NAS 루프백에만 바인딩해 임의의 사내 클라이언트가 프록시 헤더를 직접 지정하지 않도록 한다. 설정 후 `nas.sh start`로 컨테이너 설정을 반영하고 HTTPS 로그인·가입 POST·기안 제출·Excel을 시험한다. 인증서 경고를 무시하는 방식으로 정식 운영하지 않는다. 사외 사용이 필요해지면 별도로 설계하고 우선 공유기 포트 포워딩은 추가하지 않는다.

화면은 사내 PC 가로 1080px 이상을 기준으로 구성되어 있다. 1280·1366·1920px에서 점검하며 모바일 전용 레이아웃은 별도 범위다.

## 자원과 운영 점검

웹 384MB(1 worker/2 threads), DB 512MB 제한이며 DB 버퍼 128MB·최대 연결 25개로 시작한다. 제한값 합계는 실제 사용량이 아니며 여유를 보장하지 않는다. NAS는 이미 약 1GB를 사용하고 있었으므로 여러 실제 PC 동시 사용·Excel·백업 때 RAM/스왑/응답 시간을 확인한다. 부족하면 기존 서비스를 끄지 말고 메모리 증설 또는 DB/앱 별도 서버를 검토한다. 설치 중 빌드 자원은 컨테이너 실행 제한과 별개다.

고정한 MariaDB/Python 이미지와 패키지는 재현을 위한 기준이다. 보안 업데이트는 릴리스 점검 후 시험·백업·명시적 버전 변경을 통해 반영하며 DB 이미지를 자동으로 최신 버전으로 바꾸지 않는다. 앱 업데이트 스크립트도 DB 버전을 자동 변경하지 않는다.

## 남은 업무 규칙 확인

- 10만원 초과~100만원 이하 규정은 기존과 같이 비활성 상태로 준비되어 있다. 실제 허용 직급을 확인하고 관리 화면에서 활성화한다.
- 100만원 초과 규정과 적격 승인자가 없는 경우의 별도 예외는 확정되지 않았다. 기존 기본 결재 경로와 허용 직급을 확인한 뒤 정식 사용한다.
- 경조사 구간의 경계(근속 2년/10년)는 제공된 표의 표현을 유지한다. 실제 지급 판단은 담당자 확인이 필요하다.
- 사용자가 확정한 숫자만 포함한 4자 이상 비밀번호, 같은 직급 이상 결재선, 본인 최종 승인 허용 등의 정책은 유지한다.

## 설치 중 data/mariadb 폴더 오류가 나온 경우

초기 배포본에서 Synology 기존 Docker의 `Bind mount failed ... data/mariadb does not exist` 오류가 나면 다음 두 명령을 차례로 실행한다. 기존 DB 파일·`.env`·계정 암호는 삭제하지 않는다. 수정된 배포본에서는 해당 폴더를 미리 생성한다.

```sh
sudo mkdir -p /volume1/docker/company-approval/data/mariadb
sudo sh /volume1/docker/company-approval/app/deploy/nas/nas.sh install
```
