import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ascendra.browser_sandbox import build_command, SandboxUnavailable


class BrowserSandboxTests(unittest.TestCase):
    def test_unavailable_fails_closed(self):
        with patch('ascendra.browser_sandbox.shutil.which', return_value=None):
            with self.assertRaises(SandboxUnavailable):
                build_command('.', 'contract.json', 'report.json')

    def test_real_namespace_browser_and_network_isolation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / 'project'
            project.mkdir()
            output = root / 'evidence'
            output.mkdir()
            (project / 'index.html').write_text('<!doctype html><html><body><button onclick="this.textContent=\'Verified\'">Run</button></body></html>')
            contract = root / 'contract.json'
            contract.write_text(json.dumps({'version': 1, 'scenarios': [{'name': 'real browser', 'steps': [{'action': 'click', 'selector': 'button'}, {'action': 'expect_text', 'selector': 'button', 'text': 'Verified'}]}]}))
            report = output / 'report.json'
            command = build_command(project, contract, report)
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue(json.loads(report.read_text())['passed'])
            # Replace only the trusted verifier invocation with a trusted probe:
            # same exact namespace/mount/environment configuration.
            split = command.index('--')
            script = """const fs=require('fs'); const net=require('net');
if(process.env.ASCENDRA_TEST_SECRET)process.exit(10);
if(fs.existsSync('/workspace')||fs.existsSync('/root'))process.exit(11);
try{fs.writeFileSync('/project/write','x');process.exit(12)}catch{}
const s=net.connect({host:'1.1.1.1',port:443});
s.on('connect',()=>process.exit(13));s.on('error',()=>process.exit(0));
setTimeout(()=>process.exit(14),2000);"""
            probe = command[:split+1] + [command[split+1], '-e', script]
            env = dict(os.environ, ASCENDRA_TEST_SECRET='must-not-enter')
            result = subprocess.run(probe, capture_output=True, text=True, timeout=10, env=env)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


if __name__ == '__main__':
    unittest.main()
