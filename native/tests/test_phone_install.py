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

    def test_republish_generates_dark_mobile_page_sorted_newest_first(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / 'home'
            store = home / 'Library/Application Support/phone-install'
            (store / 'com.example.old').mkdir(parents=True)
            (store / 'com.example.new').mkdir(parents=True)
            (store / '.token').write_text('test-token')
            (store / 'com.example.old/info.tsv').write_text('Old App\t100\t2026-11-20 10:00\n')
            (store / 'com.example.new/info.tsv').write_text('New & Cool\t200\t2026-11-23 22:35\n')
            fake_bin = root / 'bin'
            fake_bin.mkdir()
            fake_ssh = fake_bin / 'ssh'
            fake_ssh.write_text('#!/bin/sh\ncat >/dev/null\n')
            fake_ssh.chmod(0o755)
            installer = root / 'phone-install'
            text = SCRIPT.read_text()
            text = text.replace('/usr/bin/ssh', str(fake_ssh))
            text = text.replace('/usr/bin/tar', 'tar')
            text = text.replace('/bin/cp', 'cp')
            installer.write_text(text)
            installer.chmod(0o755)
            result = subprocess.run([str(installer), '--republish'], env=dict(os.environ, HOME=str(home)),
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            page = (store / 'index.html').read_text()
            self.assertIn('<meta name="color-scheme" content="dark">', page)
            self.assertIn('New &amp; Cool', page)
            self.assertIn('itms-services://?action=download-manifest&amp;url=https://ios-apps.veron3.space/test-token/com.example.new/manifest.plist%3Fv%3D200', page)
            self.assertLess(page.index('New &amp; Cool'), page.index('Old App'))


if __name__ == '__main__':
    unittest.main()
