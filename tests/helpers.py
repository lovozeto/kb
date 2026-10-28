import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
KB_BIN = os.path.join(ROOT, "bin", "kb")


class CliTestCase(unittest.TestCase):
    """Runs the real `kb` command against a private copy of the fixture KB."""

    today = "2026-10-27"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kb_root = os.path.join(self.tmp, "kb")
        self.projects = os.path.join(self.tmp, "projects")
        shutil.copytree(os.path.join(FIXTURES, "kb"), self.kb_root)
        shutil.copytree(os.path.join(FIXTURES, "projects"), self.projects)
        self.cwd = self.tmp

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_kb(self, *args, cwd=None, expect=0):
        env = dict(os.environ, KB_ROOT=self.kb_root, KB_PROJECTS_ROOT=self.projects,
                   KB_INDEX=os.path.join(self.tmp, "index.db"), KB_TODAY=self.today)
        proc = subprocess.run([sys.executable, KB_BIN, *args], cwd=cwd or self.cwd,
                              env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, expect, proc.stderr + proc.stdout)
        return proc

    def kb_json(self, *args, **kw):
        return json.loads(self.run_kb(*args, "--json", **kw).stdout)
