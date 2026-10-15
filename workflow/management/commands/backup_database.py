from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from workflow.backups import create_backup, directory
from workflow.models import Notice, Profile
from workflow.nas_backup import prune_scheduled_backups


class Command(BaseCommand):
    help = '운영 DB 백업. --scheduled는 일별·월별 백업과 보관 정리를 실행합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--kind', default='manual', choices=['manual', 'daily', 'monthly', 'update'])
        parser.add_argument('--scheduled', action='store_true')

    def handle(self, *args, **options):
        try:
            if options['scheduled']:
                day = timezone.localtime().strftime('%Y%m%d')
                if not list(directory().glob(f'backup-{day}*-daily.zip')):
                    create_backup('daily')
                month = timezone.localtime().strftime('%Y%m')
                if not list(directory().glob(f'backup-{month}*-monthly.zip')):
                    create_backup('monthly')
                prune_scheduled_backups()
            else:
                path = create_backup(options['kind'])
                self.stdout.write(path.name)
        except Exception as exc:
            # Do not include exception strings containing subprocess/DB details.
            try:
                for profile in Profile.objects.filter(manage_system=True, user__is_active=True):
                    Notice.objects.create(user=profile.user, text='예약 또는 수동 백업에 실패했습니다. 백업 경로와 DB 연결을 확인해 주세요.')
            except Exception:
                pass
            raise CommandError('백업 실패. 서비스 상태·저장 공간·백업 폴더 권한을 확인해 주세요.') from exc
