from django.core.management.base import BaseCommand
from workflow.annual_grants import sync_annual_grants


class Command(BaseCommand):
    help = '현재 연도의 입사일 기준 총연차를 한 번만 갱신합니다. 기존 사용연차·수동 수정값은 보존합니다.'

    def handle(self, *args, **options):
        self.stdout.write(f'새 연도 연차 산정: {sync_annual_grants()}명')
