import os
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from django.core.management.base import BaseCommand
from workflow.push import key_path,public_key

class Command(BaseCommand):
    help='Create this installation\'s VAPID key once. Never prints the private key.'
    def handle(self,*args,**options):
        path=key_path();path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():
            key=ec.generate_private_key(ec.SECP256R1())
            value=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
            try:
                with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as f:f.write(value)
            except FileExistsError:pass
        public_key()
        self.stdout.write('웹 푸시 키 준비 완료. 기존 키와 구독은 유지됩니다.')
