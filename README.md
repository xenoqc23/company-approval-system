# 사내결재시스템 — 설치 없는 Windows 시안

[이 폴더 전체 ZIP 다운로드](https://github.com/xenoqc23/company-approval-system/archive/refs/heads/portable/windows-demo.zip)

ZIP을 모두 압축 해제한 뒤 **CompanyApproval.exe**를 더블클릭합니다.
Python이나 setup.bat 실행은 필요하지 않습니다. **Windows 64비트용**입니다.

처음에는 시안 계정 초기 비밀번호를 입력합니다. 기존 데이터가 있으면 그 계정을 그대로 사용합니다.
기존 프로그램의 **var** 폴더를 EXE 옆에 복사하면 계정과 기안을 가져올 수 있습니다.

EXE만 따로 복사하지 말고 runtime, vendor 등 **프로그램 폴더 전체**를 함께 보관합니다.
자세한 방법은 START_WITHOUT_PYTHON.txt를 확인합니다.

출처: prototype/pc-demo-20261008 소스의 d3204535744d22d7c55c44027d17aedd6b574866

CPython은 Python Software Foundation 공식 NuGet 배포본을 사용하며, NuGet SHA-512와 PyPI wheel SHA-256을 확인했습니다.
54개 업무 테스트와 실행·로그인·엑셀·연차 내역 확인을 Windows 호환 환경(Wine)에서 통과했습니다.
실제 Windows PC에서의 실행은 사용자 환경에서 확인해야 합니다.
계정·기안 DB는 배포 파일에 포함하지 않습니다.
