"""Check the complete clean package and the offline NAS update order with fake Docker."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from zipfile import ZipFile
import build_nas_purchase_update as release


class NasPurchasePackageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='nas-purchase-release-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.archive=self.root/'update.zip';release.build(self.archive)
        with ZipFile(self.archive) as archive:
            self.assertIsNone(archive.testzip());archive.extractall(self.root/'upload')
        self.stage=self.root/'upload'/release.NAME

    def test_allowlist_manifest_and_no_local_data_or_employee_names(self):
        files=[p for p in self.stage.rglob('*') if p.is_file()]
        for p in files:
            rel=p.relative_to(self.stage).as_posix()
            self.assertNotIn('seed_',rel);self.assertNotIn('__pycache__',rel)
            self.assertNotIn('releases/',rel);self.assertNotIn('.sqlite3',rel)
            self.assertNotIn('journal',rel);self.assertNotIn('test_',p.name)
        meta=json.loads((self.stage/'RELEASE.json').read_text())
        for name,digest in meta['files'].items():self.assertEqual(hashlib.sha256((self.stage/name).read_bytes()).hexdigest(),digest)
        self.assertFalse(meta['contains_company_data'])
        self.assertTrue((self.stage/'app/purchasing/services.py').exists())
        self.assertTrue((self.stage/'app/workflow/management/commands/prepare_purchase_update.py').exists())
        result=subprocess.run(['sha256sum','-c','SHA256SUMS'],cwd=self.stage,capture_output=True)
        self.assertEqual(result.returncode,0)
        with self.assertRaises(FileExistsError):release.build(self.archive)

    def harness(self, fail=''):
        base=self.root/'existing';base.mkdir()
        (base/'.env').write_text('DB_NAME=approval_qa\n')
        (base/'.current-image').write_text('previous-image\n')
        (base/'data').mkdir();(base/'data/sentinel').write_text('EXISTING DATA')
        binpath=self.root/'bin';binpath.mkdir()
        docker=binpath/'docker'
        docker.write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$QA_LOG"
case "$*" in
 *"$QA_FAIL"*) if [ -n "$QA_FAIL" ]; then exit 1; fi;;
esac
case "$*" in
 *"backup_database --kind update"*) echo 'backup-20261026-update.zip';;
 *" ps -q web"*) echo qa-web;;
 "inspect --format"*) case "$*" in *RestartCount*) echo 0;; *) echo healthy;; esac;;
esac
exit 0
''');docker.chmod(0o755)
        env={**os.environ,'PATH':str(binpath)+':'+os.environ['PATH'],'APPROVAL_BASE':str(base),
             'QA_LOG':str(self.root/'docker.log'),'QA_FAIL':fail}
        nasfile=self.stage/'app/deploy/nas/nas.sh'
        script=nasfile.read_text()
        script='\n'.join('PATH="$PATH"' if line.startswith('PATH=') else line for line in script.splitlines())+'\n'
        nasfile.write_text(script)  # Test-only Docker stub; package integrity is checked separately.
        result=subprocess.run(['sh',str(nasfile),'update','--development-checker','username:dev',
            '--other-checker','username:other','--purchaser','username:buyer','--representative','username:ceo'],env=env,capture_output=True,text=True)
        log=(self.root/'docker.log').read_text()
        self.assertEqual((base/'.env').read_text(),'DB_NAME=approval_qa\n')
        self.assertEqual((base/'data/sentinel').read_text(),'EXISTING DATA')
        self.assertNotIn('bootstrap_production',log);self.assertNotIn('sync_annual_grants',log)
        self.assertNotIn('down',log)
        return result,log,base

    def test_update_order_and_retains_rollback(self):
        result,log,base=self.harness();self.assertEqual(result.returncode,0,result.stderr)
        needles=['build -t','prepare_purchase_update --check',' stop web','prepare_purchase_update --capture',
                 'backup_database --kind update','migrate --noinput','prepare_purchase_update --verify',
                 'prepare_purchase_update --apply','manage.py check',' up -d web']
        positions=[log.index(n) for n in needles];self.assertEqual(positions,sorted(positions))
        self.assertEqual((base/'.rollback-image').read_text(),'previous-image\n')
        self.assertFalse((base/'.pending-image').exists())

    def test_failed_precheck_does_not_stop_current_web(self):
        result,log,base=self.harness('prepare_purchase_update --check')
        self.assertNotEqual(result.returncode,0);self.assertNotIn(' stop web',log);self.assertNotIn('migrate',log)
        self.assertEqual((base/'.current-image').read_text(),'previous-image\n')

    def test_failed_preservation_keeps_web_stopped_and_rollback_markers(self):
        result,log,base=self.harness('prepare_purchase_update --verify')
        self.assertNotEqual(result.returncode,0);self.assertNotIn(' up -d web',log)
        self.assertTrue((base/'.pending-image').exists());self.assertTrue((base/'.rollback-backup').exists())
        self.assertEqual((base/'.current-image').read_text(),'previous-image\n')

    def test_modified_release_is_rejected_before_docker(self):
        (self.stage/'app/manage.py').write_text('changed')
        result=subprocess.run(['sh',str(self.stage/'UPDATE_NAS.sh'),'update'],capture_output=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'Release file verification failed',result.stderr)


if __name__=='__main__':unittest.main()
