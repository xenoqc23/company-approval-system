# 설치된 NAS용 화면 수정 파일

[월별 문서번호·기안자 연차 표시 NAS 업데이트](xenosys-nas-numbers-balance-update-20261113-v1.zip)는 새 휴가원에 `XEN-OFF-YYMM-0001`, 새 구매요청서에 `XEN-BUY-YYMM-0001`을 부여합니다. 문서별 순번을 매월 따로 관리하고 제출이 성공할 때 확정합니다. 기존 제출 문서번호는 유지합니다. 휴가원 기안자 이름 옆에는 사용 연도 기준 현재 잔여·총연차를 표시합니다. [사전점검·적용 안내](xenosys-nas-numbers-balance-update-20261113-v1.md)를 확인합니다. 기존 검토·승인 의견과 연차 이름 검색, 공지·첨부·PC 알림 연결도 유지합니다.

[검토·승인 의견 및 연차 이름 검색 NAS 업데이트](xenosys-nas-opinions-search-update-20261112-v1.zip)는 휴가원·구매요청서의 선택 의견과 직원별 연차 관리의 이름 검색을 추가합니다. 의견은 실제 검토·승인 완료와 함께 저장하며 신청 내용 아래에 작성자·단계·시간을 표시합니다. 이미 제출된 대기 문서에도 적용됩니다. 연차 조회·엑셀에 같은 검색 조건을 사용하고 기존 문서·연차·공지·첨부·PC 알림 연결은 보존합니다. [사전점검·적용 안내](xenosys-nas-opinions-search-update-20261112-v1.md)를 확인합니다. 직원 PC 프로그램은 재설치하지 않아도 됩니다.

[PC 알림 설치 공지 포함 NAS 업데이트 v4](xenosys-nas-announcements-update-20261110-v4.zip)는 **사내결재시스템 알림 설치** 공지 한 건과 직원용 EXE를 최초 한 번 등록합니다. 설치 방법은 공지 본문에서 관리자가 직접 수정할 수 있습니다. 이전에 수정하거나 삭제한 설치 공지는 다시 덮어쓰거나 되살리지 않습니다. EXE를 따로 첨부할 필요 없이 NAS ZIP 하나만 적용합니다. 실제 NAS에는 [적용 안내](../docs/NAS_ANNOUNCEMENTS_UPDATE_20261109.md)에 따라 별도 업데이트가 필요합니다.

[공지사항 NAS 업데이트 v3](xenosys-nas-announcements-update-20261109-v3.zip)는 검색 버튼을 가로로 표시하고 공지에 PC 알림 다운로드 버튼·설치 안내를 넣는 옵션을 추가합니다. [직원용 설치 EXE](xenosys-pc-notifier-a-direct-20261109-v2/XenosysApprovalSetup.exe)를 공지에 첨부하고 ‘PC 알림 프로그램 설치 안내 표시’를 켭니다. 직원은 내려받은 EXE를 실행해 설치하며 ZIP 압축 해제는 필요 없습니다. 기존 설치 직원은 재설치하지 않아도 됩니다. 클릭만으로 자동 설치되지는 않습니다. NAS에는 [적용 안내](../docs/NAS_ANNOUNCEMENTS_UPDATE_20261109.md)에 따라 별도 업데이트가 필요합니다. 이 새 압축 EXE의 실제 Windows 설치는 한 PC에서 먼저 확인합니다.

[공지사항 NAS 업데이트 v2](xenosys-nas-announcements-update-20261109-v2.zip)는 ZIP 내부 파일명을 영문으로 통일하여 예문 파일 누락 검사 오류를 피합니다. 공지사항 기능과 업데이트 검증 스크립트는 v1과 동일합니다. v1에서 `공지_예문.txt`를 찾지 못했다면 새 v2 폴더에 압축 해제하고 v2의 사전점검 명령을 실행합니다.

[공지사항 메뉴 업데이트](xenosys-nas-announcements-update-20261109-v1.zip)는 관리자 글 작성·수정·삭제와 직원 조회·첨부 다운로드를 추가합니다. 설치 ZIP을 첨부할 수 있도록 파일당 100MB를 지원하며 기존 PC 알림 연결은 유지합니다. [적용 안내](../docs/NAS_ANNOUNCEMENTS_UPDATE_20261109.md)와 공지 예문을 함께 제공합니다. NAS에는 별도 적용이 필요합니다.

직원 Windows 설치용: [A안 PC 알림 프로그램](xenosys-pc-notifier-a-20261109-v1.zip)은 Python이나 별도 .NET 설치 없이 실행하는 Windows 10 22H2/11 64비트용 설치 파일입니다. 먼저 설치 후 가상 문서 시험을 하고 실제 Windows 팝업·자동 실행을 확인합니다. 기존 START_TEST 알림 시험의 자동 실행은 해당 시험 화면에서 꺼서 중복 표시를 피합니다. [프로그램 안내](../desktop_notifier/README.md)를 확인합니다.

관리자 NAS 연결용: [PC 알림 서버 업데이트](xenosys-nas-desktop-notifier-update-20261109-v1.zip)는 계정 연결과 조회 전용 알림 API를 추가합니다. 실제 NAS에는 자동으로 적용하지 않습니다. [사전점검·업데이트 안내](../docs/NAS_DESKTOP_NOTIFIER_UPDATE_20261109.md)를 확인합니다. NAS 적용 후 직원 프로그램에서 본인 계정을 연결합니다.

로컬 PC 테스트 전용: [회사 알림 디자인 v7 덮어쓰기 파일](xenosys-local-notification-design-20261109-v7.zip)은 회사 로고, 결재 요청·완료 구분, 기안자·부서·직급·문서 종류와 문서 확인·닫기를 제공합니다. 기존 로컬 v5/v6의 실행 창을 종료하고 현재 `START_TEST.bat`이 있는 폴더에 ZIP의 파일 전부를 덮어씁니다. 기존 가상환경·문서·자동 실행 경로를 유지합니다. 문서 확인은 가상 문서를 읽기 전용으로 열며 실제 Windows 배너와 활성화 동작은 PC에서 확인합니다. NAS용 파일이 아닙니다.

로컬 PC 테스트 전용: [자동 실행 등록 v6 패치](xenosys-local-startup-fix-20261109-v6.zip)는 기존 로컬 v5의 `desktop.py`, `app.js` 두 파일만 교체합니다. 등록 오류를 계속 표시하고 긴 시작 명령의 Python 경로를 줄이며 저장한 등록값을 다시 확인합니다. 검은 실행 창을 종료한 뒤 기존 `START_TEST.bat`이 있는 폴더에 덮어쓰고 다시 실행합니다. 기존 가상 문서·실행 환경은 유지합니다. NAS에 적용하는 파일이 아닙니다.

[xenosys-nas-stock-record-update-20261102-v4.zip](xenosys-nas-stock-record-update-20261102-v4.zip)은 생산 재고 요청을 검토자 확인 후 기록 보관으로 종료하고 경리 자동 전달을 제외합니다. [적용·복구 안내](../docs/NAS_STOCK_RECORD_UPDATE_20261102_V4.md)를 확인합니다. 기존 계정·담당자·규정·문서·연차·첨부와 이미 제출된 결재선을 보존합니다.


[xenosys-login-fix-20261016.zip](xenosys-login-fix-20261016.zip)은 모바일 업데이트 후 반복되는 로그인 CSRF 오류를 보완한다. 전용 쿠키·캐시 방지·로그인 직전 토큰 갱신을 포함하며 CSRF 검사는 유지한다. [수정 내용·검증·NAS 적용 안내](../docs/LOGIN_FIX_20261016.md)를 확인한다.

생성: `python3 packaging/build_login_fix_patch.py` · 적용 시험: `python3 packaging/test_login_fix_patch.py`

[xenosys-mobile-ui-20261016.zip](xenosys-mobile-ui-20261016.zip)은 휴대폰 화면용 CSS·JavaScript·템플릿 7개와 NAS 적용 스크립트를 포함한다. 기존 화면 파일을 백업하고 `nas.sh update`로 반영한다. [모바일 화면 검증 및 적용 안내](../docs/UI_MOBILE_20261016.md)를 확인한다.

생성: `python3 packaging/build_mobile_ui_patch.py` · 적용 안전성 확인: `python3 packaging/test_mobile_ui_patch.py`

[xenosys-ui-readability-20261015.zip](xenosys-ui-readability-20261015.zip)은 CSS 3개와 적용 안내만 포함한다. 사용 중인 NAS의 app/workflow/static/workflow에 CSS 파일을 덮어쓰고 NAS 설치 스크립트의 update 명령을 실행한다. 기존 폴더를 삭제하지 않는다. 서버에 수집된 정적 파일은 이미지에 있으므로 원본 업로드만으로 화면이 바뀌지는 않는다.

생성: `python3 packaging/build_ui_readability_patch.py`
검증: [화면 가독성 확인](../docs/UI_READABILITY_20261015.md)
