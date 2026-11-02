import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/phone-install'


class PhoneInstallTests(unittest.TestCase):
    def run_installer(self, *, disconnected=False, install_exit=0):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools = root / 'native/scripts'
            tools.mkdir(parents=True)
            app = root / 'Example.app'
            app.mkdir()
            log = root / 'calls'
            state = root / 'connected'
            if not disconnected:
                state.touch()
            buddy = root / 'plist-buddy'
            buddy.write_text('#!/bin/sh\necho com.example.video\n')
            cli = tools / 'apple-tool'
            cli.write_text('''#!/bin/sh
echo "$*" >> "$CALLS"
case "$*" in
  *"info apps"*) test -f "$CONNECTED" ;;
  *"info processes"*) echo 'The developer disk image is not mounted' >&2; exit 1 ;;
  *"install app"*) echo 'signature fixture'; exit "$INSTALL_EXIT" ;;
  *) exit 99 ;;
esac
''')
            pairing = tools / 'phone-pairing'
            pairing.write_text('''#!/bin/sh
echo "pairing $*" >> "$CALLS"
touch "$CONNECTED"
''')
            installer = tools / 'phone-install'
            installer.write_text(SCRIPT.read_text().replace('/usr/libexec/PlistBuddy', str(buddy)))
            for path in [buddy, cli, pairing, installer]:
                path.chmod(0o755)
            environment = dict(os.environ, CALLS=str(log), CONNECTED=str(state), INSTALL_EXIT=str(install_exit))
            result = subprocess.run([str(installer), '--device', 'paired-phone', str(app)], env=environment,
                                    capture_output=True, text=True, timeout=10)
            return result, log.read_text()

    def test_app_service_can_install_without_process_enumeration(self):
        result, calls = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('info apps', calls)
        self.assertIn('install app', calls)
        self.assertNotIn('info processes', calls)
        self.assertNotIn('pairing', calls)

    def test_real_disconnect_recovers_before_installation(self):
        result, calls = self.run_installer(disconnected=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('pairing --now', calls)
        self.assertLess(calls.index('pairing --now'), calls.index('install app'))

    def test_signature_error_is_not_treated_as_a_disconnect(self):
        result, calls = self.run_installer(install_exit=33)
        self.assertEqual(result.returncode, 33, result.stderr)
        self.assertNotIn('pairing', calls)


if __name__ == '__main__':
    unittest.main()
