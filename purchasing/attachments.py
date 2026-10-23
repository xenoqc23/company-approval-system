"""Private purchase documents. Files are served only after a document permission check."""
from pathlib import Path
from uuid import uuid4
from django.conf import settings
from django.core.exceptions import PermissionDenied,ValidationError
from django.core.files.storage import FileSystemStorage
from django.db import transaction

MAX_BYTES=10*1024*1024
MAX_FILES=10
EXTENSIONS={'.pdf','.png','.jpg','.jpeg','.gif','.webp','.xlsx','.xls','.docx','.doc','.hwp','.hwpx','.txt'}


def private_storage():return FileSystemStorage(location=settings.DATA_DIR/'purchase-attachments',base_url=None)

def attachment_path(instance,filename):return f'{instance.request_id}/{uuid4().hex}{Path(filename).suffix.lower()}'

def validated_files(files):
    files=list(files)
    if len(files)>MAX_FILES:raise ValidationError('한 문서에는 첨부파일을 최대 10개까지 등록할 수 있습니다.')
    for f in files:
        if Path(f.name).suffix.lower() not in EXTENSIONS:raise ValidationError('PDF·이미지·엑셀·워드·한글·텍스트 파일을 첨부해 주세요.')
        if not 0<f.size<=MAX_BYTES:raise ValidationError('빈 파일은 첨부할 수 없으며 파일당 최대 10MB입니다.')
        if len(f.name)>200:raise ValidationError('첨부파일 이름은 200자 이내로 지정해 주세요.')
    return files


def visible_attachments(user,d):
    from .access import can_view_purchase
    qs=d.attachments.select_related('uploaded_by')
    return qs if can_view_purchase(user,d) else qs.filter(kind='request')


def can_upload(user,d):
    from .access import active,can_view_purchase
    return active(user) and not user.profile.is_representative and (d.owner_id==user.pk and d.status=='draft' or can_view_purchase(user,d))


class StoredFiles:
    """Remove newly written files if a later database operation rolls back."""
    def __init__(self):self.saved=[]
    def __enter__(self):return self
    def __exit__(self,exc_type,exc,tb):
        if exc_type:
            for storage,name in self.saved:storage.delete(name)
    def add(self,d,user,files,kind):
        from .models import PurchaseAttachment
        from .services import event
        files=validated_files(files)
        if d.attachments.count()+len(files)>MAX_FILES:raise ValidationError('한 문서에는 첨부파일을 최대 10개까지 등록할 수 있습니다.')
        for file in files:
            a=PurchaseAttachment(request=d,uploaded_by=user,kind=kind,original_name=file.name,size=file.size)
            a.file.save(file.name,file,save=False);self.saved.append((a.file.storage,a.file.name));a.save()
            # Purchase-file events stay private alongside purchase progress.
            event(user,'첨부파일 등록' if kind=='request' else '구매 증빙 첨부',request=d,detail=file.name)
