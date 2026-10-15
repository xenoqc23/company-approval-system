from django.core.management.base import BaseCommand, CommandError
from workflow.nas_backup import restore_mariadb


class Command(BaseCommand):
    help = 'NAS 오프라인 복구 전용. 임시 DB 검증 후 현재 데이터도 먼저 백업합니다.'

    def add_arguments(self, parser):
        parser.add_argument('filename')

    def handle(self, *args, **options):
        try:
            safety = restore_mariadb(options['filename'])
        except Exception as exc:
            raise CommandError('복구가 완료되지 않았습니다. 웹 서비스는 중지 상태로 유지하세요. 백업 파일과 운영 로그를 확인해 주세요.') from exc
        self.stdout.write(f'복구 완료. 복구 직전 안전 백업: {safety.name}')
