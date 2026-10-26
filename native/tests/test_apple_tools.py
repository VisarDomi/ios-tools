import importlib.util
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('apple_tools_test',Path(__file__).parents[1]/'scripts/apple_tools.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        p=patch.object(m,'FRAMEWORKS',self.root);p.start();self.addCleanup(p.stop)

    def tool(self,name,content):
        resources=self.root/(m.COMPONENTS[name]+'.framework/Versions/A/Resources')
        p=resources/'bin'/name;p.parent.mkdir(parents=True)
        p.write_bytes(content);p.chmod(0o755)
        (resources/'Info.plist').write_bytes(plistlib.dumps({'CFBundleVersion':'1051.17.11'}))
        return p

    def test_installed_native_cli_is_used_without_a_launcher(self):
        p=self.tool('simctl',b'\xcf\xfa\xed\xfe' + b'fixture')
        self.assertEqual(m.tool_path('simctl'),str(p))

    def test_script_cannot_be_used_as_the_native_implementation(self):
        self.tool('simctl',b'#!/bin/sh\nxcodebuild -runFirstLaunch\n')
        with self.assertRaisesRegex(RuntimeError,'not an installer script'):m.tool_path('simctl')

    def test_missing_tool_fails_without_running_setup(self):
        with self.assertRaisesRegex(RuntimeError,'Initialize Xcode once'):m.tool_path('devicectl')

    def test_status_reports_the_actual_hotfix_version(self):
        p=self.tool('simctl',b'\xca\xfe\xba\xbe' + b'fixture')
        status=m.status()
        self.assertEqual(status['simctl']['version'],'1051.17.11')
        self.assertEqual(status['simctl']['path'],str(p))
        self.assertIn('error',status['devicectl'])

    def test_only_the_two_known_apple_tools_are_resolved(self):
        with self.assertRaises(ValueError):m.tool_path('../../bin/sh')


if __name__=='__main__':unittest.main()
