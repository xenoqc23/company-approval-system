# 설치된 NAS용 화면 수정 파일

[xenosys-mobile-ui-20261016.zip](xenosys-mobile-ui-20261016.zip)은 휴대폰 화면용 CSS·JavaScript·템플릿 7개와 NAS 적용 스크립트를 포함한다. 기존 화면 파일을 백업하고 `nas.sh update`로 반영한다. [모바일 화면 검증 및 적용 안내](../docs/UI_MOBILE_20261016.md)를 확인한다.

생성: `python3 packaging/build_mobile_ui_patch.py` · 적용 안전성 확인: `python3 packaging/test_mobile_ui_patch.py`

[xenosys-ui-readability-20261015.zip](xenosys-ui-readability-20261015.zip)은 CSS 3개와 적용 안내만 포함한다. 사용 중인 NAS의 app/workflow/static/workflow에 CSS 파일을 덮어쓰고 NAS 설치 스크립트의 update 명령을 실행한다. 기존 폴더를 삭제하지 않는다. 서버에 수집된 정적 파일은 이미지에 있으므로 원본 업로드만으로 화면이 바뀌지는 않는다.

생성: `python3 packaging/build_ui_readability_patch.py`
검증: [화면 가독성 확인](../docs/UI_READABILITY_20261015.md)
