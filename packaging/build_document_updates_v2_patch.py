"""Same cumulative four-feature NAS update plus a private home birthday greeting."""
from hashlib import sha256
from zipfile import ZipFile, ZIP_DEFLATED
import build_document_updates_patch as previous
ROOT=previous.ROOT
NAME='xenosys-document-updates-v2-20261020'
FILES=previous.FILES
APPLY=(previous.APPLY.replace('APPROVAL_DOCUMENT_UPDATES_BASE','APPROVAL_DOCUMENT_UPDATES_V2_BASE')
       .replace('.document-updates-backup.','.document-updates-v2-backup.')
       .replace('DOCUMENT_UPDATES_READY','DOCUMENT_UPDATES_V2_READY'))
INSTRUCTIONS=(previous.INSTRUCTIONS.replace('문서·연차 개선 4종 NAS 업데이트','문서·연차 개선 4종 + 생일 축하 본인 표시 NAS 업데이트')
       .replace('xenosys-document-updates-20261020','xenosys-document-updates-v2-20261020')
       .replace('APPLY_DOCUMENT_UPDATES.sh','APPLY_DOCUMENT_UPDATES_V2.sh')
       .replace('DOCUMENT_UPDATES_READY','DOCUMENT_UPDATES_V2_READY')
       .replace('.document-updates-backup.','.document-updates-v2-backup.')
       .replace('1. 내 기안 결재완료 확인','추가 수정: 홈 오른쪽 상단 생일 축하\n- 생일 당사자 본인에게만 케이크 이미지와 축하 문구를 보여줍니다.\n- 같은 날 생일자가 여럿이어도 각자 본인의 축하만 볼 수 있습니다.\n- 다른 직원·경리·관리자는 다른 사람의 홈 생일 축하를 볼 수 없습니다.\n- 양력/음력 자동 변환과 한국 날짜 기준을 유지합니다.\n- 직원복지의 월별 생일자 목록은 기존대로 유지합니다.\n- 생일 정보나 다른 데이터를 수정하지 않으며, 이번 표시 변경을 위한 추가 마이그레이션은 없습니다.\n- 아래 네 기능을 누적 포함하므로 이전 4종 ZIP을 아직 설치하지 않았어도 이 ZIP으로 적용할 수 있습니다.\n\n1. 내 기안 결재완료 확인'))


def build():
    out=ROOT/'releases'/f'{NAME}.zip'
    payload={f'app/{name}':(ROOT/name).read_bytes() for name in FILES}
    payload['APPLY_DOCUMENT_UPDATES_V2.sh']=APPLY.encode()
    payload['NAS_DOCUMENT_UPDATES_V2.txt']=INSTRUCTIONS.encode()
    payload['SHA256SUMS']=''.join(f'{sha256(data).hexdigest()}  {name}\n' for name,data in payload.items()).encode()
    with ZipFile(out,'w',ZIP_DEFLATED) as z:
        for name,data in payload.items():z.writestr(f'{NAME}/{name}',data)
    with ZipFile(out) as z:
        assert z.testzip() is None
        for name,data in payload.items():assert z.read(f'{NAME}/{name}')==data
    (ROOT/'docs'/'NAS_DOCUMENT_UPDATES_V2_20261020.md').write_text(INSTRUCTIONS)
    print(f'{out.name}: {out.stat().st_size} bytes; {len(FILES)} runtime files verified.')
    return out

if __name__=='__main__':build()
