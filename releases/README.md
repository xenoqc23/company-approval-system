# 설치된 NAS용 화면 수정 파일

[xenosys-ui-readability-20261015.zip](xenosys-ui-readability-20261015.zip)은 CSS 3개와 적용 안내만 포함한다. 사용 중인 NAS의 app/workflow/static/workflow에 CSS 파일을 덮어쓰고 NAS 설치 스크립트의 update 명령을 실행한다. 기존 폴더를 삭제하지 않는다. 서버에 수집된 정적 파일은 이미지에 있으므로 원본 업로드만으로 화면이 바뀌지는 않는다.

생성: `python3 packaging/build_ui_readability_patch.py`
검증: [화면 가독성 확인](../docs/UI_READABILITY_20261015.md)
