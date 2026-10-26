from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from workflow import rollout


class Command(BaseCommand):
    help = 'NAS 업데이트 계정·진행 문서 점검 / 기존 데이터 보존 비교 / 확정된 담당자 연결'

    def add_arguments(self, parser):
        modes = parser.add_mutually_exclusive_group(required=True)
        for name in ('check', 'capture', 'verify', 'apply'):
            modes.add_argument('--' + name, action='store_true')
        for role in rollout.ROLES:
            parser.add_argument('--' + role.replace('_','-'))
        parser.add_argument('--operator', default='admin')

    def handle(self, *args, **options):
        path = Path(settings.DATA_DIR) / 'nas-purchase-update-plan.json'
        try:
            if options['check']:
                plan = rollout.prepare(options)
                rollout.write_private(path, plan)
                self.stdout.write('사전 점검 통과. 기존 계정 ID: ' + str(plan['ids']))
                self.stdout.write('계정·암호·기존 데이터는 변경하지 않았습니다.')
                return
            plan = rollout.read_plan(path)
            if options['capture']:
                rollout.check_unchanged(plan)
                plan['baseline'] = rollout.capture_baseline()
                plan['attachments'] = rollout.attachments()
                rollout.write_private(path, plan)
                self.stdout.write('정지 시점 데이터·첨부 기준값 저장 완료.')
            elif options['verify']:
                rollout.check_unchanged(plan, migrated=True)
                rollout.verify_baseline(plan)
                self.stdout.write('기존 계정·암호·연차·규정·문서·첨부 보존 비교 통과.')
            else:
                rollout.apply_plan(plan)
                plan['applied'] = True
                rollout.write_private(path, plan)
                self.stdout.write('기존 계정에 구매 업무 담당자를 연결했습니다. 기존 문서의 담당자·이력은 유지합니다.')
        except ValidationError as exc:
            raise CommandError(' '.join(exc.messages)) from exc
