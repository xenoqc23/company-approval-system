import time
from django.core.management.base import BaseCommand,CommandError
from django.db import close_old_connections
from workflow.push import public_key,deliver_pending

class Command(BaseCommand):
    help='Deliver queued Web Push notifications independently from approval requests.'
    def add_arguments(self,parser):
        parser.add_argument('--once',action='store_true')
        parser.add_argument('--limit',type=int,default=50)
    def handle(self,*args,**options):
        if not public_key():raise CommandError('먼저 init_webpush를 실행해 주세요.')
        try:
            while True:
                close_old_connections()
                count=deliver_pending(max(1,min(options['limit'],500)))
                if options['once']:
                    self.stdout.write(f'발송 대기 {count}건 처리');return
                time.sleep(2)
        except KeyboardInterrupt:pass
