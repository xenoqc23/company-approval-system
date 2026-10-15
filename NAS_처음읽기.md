# Xenosys 사내결재시스템 NAS 설치

이 폴더의 내용물을 NAS의 `/volume1/docker/company-approval/app`에 올립니다.
`app/manage.py`와 `app/deploy/nas/nas.sh`가 보여야 합니다.

그다음 [NAS 설치 안내](docs/NAS_INSTALL.md)의 **처음 설치** 순서를 따라 진행합니다.
기존 NAS 서비스·MariaDB는 그대로 유지합니다. 샘플 계정·문서는 생성하지 않습니다.

업데이트할 때는 `app`의 프로그램만 교체하며 `data`, `backups`, `.env`는 보존합니다.
NAS에서는 PC용 setup/run 파일을 실행하지 않습니다. 직원 PC는 브라우저로 접속합니다.
