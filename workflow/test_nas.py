from io import StringIO
import json
import runpy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile
from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from workflow.models import AnnualPolicy, Document, Profile, Notice
from workflow.nas_backup import verified_sql, restore_mariadb, prune_scheduled_backups, require_known_migrations


class NasSafetyTests(TestCase):
    def test_installer_prepares_all_bind_directories_and_preserves_existing_data(self):
        script = str(settings.BASE_DIR / 'deploy/nas/init_config.py')
        with TemporaryDirectory() as folder:
            root = Path(folder)
            def initialize():
                with patch('pathlib.Path', return_value=root), patch('os.chown'):
                    runpy.run_path(script)
            initialize()
            for name in ['data/mariadb', 'data/app', 'backups']:
                self.assertTrue((root / name).is_dir())
            config = (root / '.env').read_bytes()
            password = (root / 'data/app/initial-admin-password.txt').read_bytes()
            sentinel = root / 'data/mariadb/existing-data'
            sentinel.write_bytes(b'existing database files')
            initialize()
            self.assertEqual((root / '.env').read_bytes(), config)
            self.assertEqual((root / 'data/app/initial-admin-password.txt').read_bytes(), password)
            self.assertEqual(sentinel.read_bytes(), b'existing database files')

    def test_bootstrap_only_creates_admin_and_never_resets_existing_password(self):
        with TemporaryDirectory() as folder, override_settings(PRODUCTION=True):
            path = Path(folder) / 'secret'
            path.write_text('first-install-test-password')
            call_command('bootstrap_production', password_file=str(path), stdout=StringIO())
            user = get_user_model().objects.get()
            self.assertEqual(user.username, 'admin')
            self.assertTrue(user.profile.manage_system)
            self.assertTrue(user.profile.must_change_password)
            self.assertEqual(Document.objects.count(), 0)
            self.assertIn('배우자의 출산: 20일', AnnualPolicy.objects.first().text)
            self.assertNotIn('2026년 12월 31일', AnnualPolicy.objects.first().text)
            self.assertFalse(get_user_model().objects.filter(username='employee').exists())
            user.set_password('changed-password'); user.save()
            path.write_text('different-install-password')
            call_command('bootstrap_production', password_file=str(path), stdout=StringIO())
            user.refresh_from_db()
            self.assertTrue(user.check_password('changed-password'))

    @override_settings(PRODUCTION=True)
    def test_demo_data_refused_on_production(self):
        with self.assertRaisesMessage(CommandError, '운영 DB에는'):
            call_command('seed_demo', initial_password='1234', stdout=StringIO())
        self.assertEqual(get_user_model().objects.count(), 0)

    @override_settings(PRODUCTION=False)
    def test_bootstrap_refuses_development_and_short_initial_secret(self):
        with self.assertRaises(CommandError):
            call_command('bootstrap_production', password_file='missing', stdout=StringIO())
        with TemporaryDirectory() as folder, override_settings(PRODUCTION=True):
            path = Path(folder) / 'secret'; path.write_text('1234')
            with self.assertRaises(CommandError):
                call_command('bootstrap_production', password_file=str(path), stdout=StringIO())
        self.assertEqual(get_user_model().objects.count(), 0)

    def test_bad_archive_rejected_without_sql_execution(self):
        with TemporaryDirectory() as folder, override_settings(BACKUP_DIR=Path(folder)):
            path = Path(folder) / 'backup-tampered.zip'
            with ZipFile(path, 'w') as archive:
                archive.writestr('database.sql', 'DROP DATABASE other;')
                archive.writestr('manifest.json', json.dumps({'format':1, 'engine':'mariadb', 'sha256':'invalid'}))
            with self.assertRaisesMessage(ValueError, '무결성'):
                with verified_sql(path.name):
                    self.fail('Tampered backup accepted')
            with self.assertRaises(ValueError):
                with verified_sql('../backup-tampered.zip'):
                    self.fail('Traversal accepted')

    def test_web_cannot_call_offline_restore(self):
        with self.assertRaisesMessage(RuntimeError, '오프라인'):
            restore_mariadb('backup-any.zip')

    def test_newer_backup_schema_is_refused_before_live_restore(self):
        with patch('workflow.nas_backup.MigrationLoader') as factory:
            factory.return_value.applied_migrations = {('workflow', 'future_version'): None}
            factory.return_value.disk_migrations = {('workflow', 'current_version'): None}
            with self.assertRaisesMessage(ValueError, '새로운 DB 백업'):
                require_known_migrations(object())

    def test_retention_preserves_manual_and_update_backups(self):
        with TemporaryDirectory() as folder, override_settings(BACKUP_DIR=Path(folder)):
            root = Path(folder)
            for kind, count in [('daily', 35), ('monthly', 15), ('manual', 2), ('update', 2), ('before-restore', 2)]:
                for n in range(count):
                    (root / f'backup-{n:04d}-{kind}.zip').write_text('test')
            prune_scheduled_backups()
            for kind, count in [('daily', 30), ('monthly', 12), ('manual', 2), ('update', 2), ('before-restore', 2)]:
                self.assertEqual(len(list(root.glob(f'backup-*-{kind}.zip'))), count)

    def test_backup_failure_notifies_admin(self):
        user = get_user_model().objects.create_user('admin', password='1234')
        Profile.objects.create(user=user, department='개발팀', rank='이사', approved=True, manage_system=True)
        with patch('workflow.management.commands.backup_database.create_backup', side_effect=RuntimeError('private-error-detail')):
            with self.assertRaisesMessage(CommandError, '백업 실패'):
                call_command('backup_database')
        self.assertEqual(Notice.objects.filter(user=user).count(), 1)
        self.assertNotIn('private-error-detail', Notice.objects.get().text)
