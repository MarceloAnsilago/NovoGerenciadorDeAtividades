"""Isolated Git/Bash integration tests; systemd, HTTP, pip and Django are simulated.
Run: python -m unittest discover -s deploy/tests -v
Windows: Git Bash is used; flock itself requires validation on Ubuntu.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'oracle.sh'
BASH = shutil.which('bash') or 'C:/Program Files/Git/bin/bash.exe'


class DeployTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='oracle-deploy-test-')
        self.root = Path(self.tmp.name).resolve()
        self.app = self.root / 'app'
        self.app.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Deploy Test')
        self.git('config', 'core.autocrlf', 'false')
        (self.app / '.gitignore').write_text('.env\nmedia/\nstaticfiles/\n')
        (self.app / 'requirements.txt').write_text('original\n')
        (self.app / 'version').write_text('old\n')
        (self.app / 'old-only').write_text('restore me\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'baseline')
        self.old = self.git('rev-parse', 'HEAD').strip()
        self.remote = self.root / 'remote.git'
        self.git('clone', '-q', '--bare', str(self.app), str(self.remote))
        self.git('remote', 'add', 'origin', self.remote.as_posix())
        self.git('push', '-q', 'origin', 'HEAD:refs/heads/oracle-production')
        (self.app / '.env').write_text('secret-test-only\n')
        (self.app / 'media').mkdir()
        (self.app / 'media' / 'upload').write_text('keep\n')
        (self.app / 'staticfiles').mkdir()
        (self.app / 'staticfiles' / 'asset').write_text('old asset\n')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.venv = self.root / 'venv'
        (self.venv / 'bin').mkdir(parents=True)
        self.write_executable(self.venv / 'bin' / 'python', '''#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$TEST_ROOT/python.log"
if [[ "$*" == *'pip install'* ]]; then
    echo changed > "$TEST_ROOT/venv/dependency"
fi
if [[ "$*" == *'migrate --check'* && -f "$TEST_ROOT/migration-fail" ]]; then exit 1; fi
if [[ "$*" == *'collectstatic'* ]]; then echo new > "$TEST_ROOT/app/staticfiles/asset"; fi
''')
        (self.venv / 'dependency').write_text('original\n')
        self.write_executable(self.bin / 'sudo', '#!/usr/bin/env bash\necho "$*" >> "$TEST_ROOT/sudo.log"\nexit 0\n')
        self.write_executable(self.bin / 'systemctl', '#!/usr/bin/env bash\nexit 0\n')
        self.write_executable(self.bin / 'sleep', '#!/usr/bin/env bash\nexit 0\n')
        self.write_executable(self.bin / 'curl', '''#!/usr/bin/env bash
if [[ -f "$TEST_ROOT/health-always-fail" ]]; then printf 503; exit 0; fi
if [[ -f "$TEST_ROOT/health-fail" && $(cat "$TEST_ROOT/app/version") == new ]]; then
    printf 503
else
    printf 200
fi
''')
        script = SOURCE.read_text(encoding='utf-8')
        for name, value in [('project', self.app), ('venv', self.venv),
                            ('backups', self.root / 'backups'), ('state', self.root / 'state')]:
            import re
            script = re.sub(r'^' + name + '=.*$', name + "='" + value.as_posix() + "'", script, flags=re.M)
        script = script.replace('remote=https://github.com/MarceloAnsilago/NovoGerenciadorDeAtividades.git',
                                "remote='" + self.remote.as_posix() + "'")
        if os.name == 'nt':
            # Git Bash has no flock; directory descriptors are not portable to Windows.
            script = script.replace('exec 9< .git', ':')
            self.write_executable(self.bin / 'flock', '#!/usr/bin/env bash\nexit 0\n')
        self.runner = self.root / 'oracle.sh'
        self.write_executable(self.runner, script)
        self.env = dict(os.environ, TEST_ROOT=self.root.as_posix())
        # Git Bash converts this Windows path to its native PATH on startup.
        self.env['PATH'] = str(self.bin) + os.pathsep + self.env['PATH']

    def tearDown(self):
        # Windows Git objects can be read-only.
        def fix(func, path, exc):
            os.chmod(path, 0o700)
            func(path)
        shutil.rmtree(self.root, onerror=fix)
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.app), *args], text=True, stderr=subprocess.STDOUT)

    def write_executable(self, path, content):
        path.write_bytes(content.encode('utf-8'))
        path.chmod(0o755)

    def candidate(self, deps=False):
        (self.app / 'version').write_text('new\n')
        (self.app / 'old-only').unlink()
        (self.app / 'new-only').write_text('candidate addition\n')
        if deps:
            (self.app / 'requirements.txt').write_text('changed\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'candidate')
        target = self.git('rev-parse', 'HEAD').strip()
        self.git('push', '-q', 'origin', 'HEAD:refs/heads/oracle-production')
        # Test setup only, never part of the production mechanism.
        self.git('reset', '--hard', self.old)
        return target

    def run_deploy(self, *args, ok=True):
        result = subprocess.run([BASH, '-c',
                                 'test_bin=$(cd "$TEST_ROOT/bin" && pwd); export PATH="$test_bin:$PATH"; exec bash "$TEST_ROOT/oracle.sh" "$@"',
                                 'oracle-test', *args], env=self.env,
                                text=True, capture_output=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.app / '.env').read_text(), 'secret-test-only\n')
        self.assertEqual((self.app / 'media' / 'upload').read_text(), 'keep\n')
        return result

    def test_unchanged(self):
        self.run_deploy()
        self.assertFalse((self.root / 'state').exists())
        self.assertFalse((self.root / 'sudo.log').exists())

    def test_dry_run(self):
        self.candidate(deps=True)
        self.run_deploy('--dry-run')
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.old)
        self.assertFalse((self.root / 'state').exists())
        self.assertFalse((self.root / 'python.log').exists())
        self.assertFalse((self.app / '.git' / 'FETCH_HEAD').exists())

    def test_success_without_pip(self):
        target = self.candidate()
        self.run_deploy()
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), target)
        self.assertNotIn('pip install', (self.root / 'python.log').read_text())
        self.assertIn(target, (self.root / 'state' / 'deployed').read_text())
        self.assertFalse((self.root / 'state' / 'in-progress').exists())

    def test_success_with_pip(self):
        self.candidate(deps=True)
        self.run_deploy()
        self.assertIn('pip install', (self.root / 'python.log').read_text())

    def test_migration_failure_and_no_retry(self):
        target = self.candidate(deps=True)
        (self.root / 'migration-fail').touch()
        self.run_deploy(ok=False)
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.old)
        self.assertEqual((self.venv / 'dependency').read_text(), 'original\n')
        self.assertTrue((self.root / 'state' / 'failed' / target).exists())
        self.assertNotIn('restart gerenciador.service\n', (self.root / 'sudo.log').read_text().replace('-l /usr/bin/systemctl restart gerenciador.service\n', ''))
        before = (self.root / 'python.log').read_text()
        self.run_deploy()
        self.assertEqual((self.root / 'python.log').read_text(), before)
        (self.root / 'migration-fail').unlink()
        self.run_deploy('--retry-failed')
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), target)

    def test_health_failure_rolls_back(self):
        self.candidate()
        (self.root / 'health-fail').touch()
        self.run_deploy(ok=False)
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.old)
        self.assertEqual((self.app / 'staticfiles' / 'asset').read_text(), 'old asset\n')
        self.assertTrue((self.app / 'old-only').exists())
        self.assertFalse((self.app / 'new-only').exists())
        self.assertEqual((self.root / 'sudo.log').read_text().count('-n /usr/bin/systemctl restart'), 2)
        self.assertIn(self.old, (self.root / 'state' / 'deployed').read_text())

    def test_divergence(self):
        self.candidate()
        (self.app / 'different').write_text('local\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'divergent')
        self.run_deploy(ok=False)
        self.assertFalse((self.root / 'state').exists())

    def test_interrupted_transaction_blocks(self):
        self.candidate()
        (self.root / 'state').mkdir()
        (self.root / 'state' / 'in-progress').write_text('interrupted\n')
        self.run_deploy(ok=False)
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.old)

    def test_protected_paths(self):
        (self.app / '.env').write_text('candidate fake secret\n')
        self.git('add', '-f', '.env')
        self.git('commit', '-qm', 'invalid candidate')
        self.git('push', '-q', 'origin', 'HEAD:refs/heads/oracle-production')
        self.git('reset', '--hard', self.old)
        (self.app / '.env').write_text('secret-test-only\n')
        self.run_deploy(ok=False)
        self.assertFalse((self.root / 'state').exists())

    def test_rollback_failure_blocks_next_attempt(self):
        self.candidate()
        (self.root / 'health-always-fail').touch()
        self.run_deploy(ok=False)
        self.assertTrue((self.root / 'state' / 'in-progress').exists())
        self.run_deploy(ok=False)

    def test_dirty_checkout(self):
        self.candidate()
        (self.app / 'version').write_text('local edit\n')
        self.run_deploy(ok=False)
        self.assertEqual((self.app / 'version').read_text(), 'local edit\n')
        self.assertFalse((self.root / 'state').exists())

    @unittest.skipIf(os.name == 'nt', 'Real flock requires Linux')
    def test_real_lock(self):
        self.candidate()
        holder = subprocess.Popen([BASH, '-c', 'exec 9< "$1/.git"; flock 9; echo ready; sleep 30',
                                   'lock-test', self.app.as_posix()], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), 'ready')
            result = self.run_deploy()
            self.assertIn('Outra execucao', result.stdout)
            self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.old)
        finally:
            holder.terminate()
            holder.wait()
            holder.stdout.close()


if __name__ == '__main__':
    unittest.main()
