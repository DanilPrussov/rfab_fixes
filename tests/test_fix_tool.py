"""CLI regression checks; all fixture files and ZIPs stay in temporary directories."""

import hashlib
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


TOOL = Path(__file__).resolve().parents[1] / "tools" / "fix.py"


class FixToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "tools").mkdir()
        shutil.copyfile(TOOL, self.root / "tools" / "fix.py")
        template = self.root / "templates" / "fix"
        (template / "payload").mkdir(parents=True)
        (template / "payload" / ".gitkeep").touch()
        for name in ("README.md", "TESTING.md", "UPSTREAM.md"):
            (template / name).write_text("# {{FIX_ID}}\n", encoding="utf-8")
        self.fix_id = "0001-test-fix"
        self.cli("new")
        self.fix = self.root / "fixes" / self.fix_id
        self.payload = self.fix / "payload"

    def cli(self, command, success=True, fix_id=None):
        result = subprocess.run(
            [sys.executable, str(self.root / "tools" / "fix.py"),
             command, fix_id or self.fix_id],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def write_payload(self, name="SKSE/Plugins/test.ini", content="value=1\n"):
        path = self.payload / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_new_substitutes_id_and_refuses_overwrite(self):
        self.assertEqual((self.fix / "README.md").read_text(), "# 0001-test-fix\n")
        self.assertIn("Already exists", self.cli("new", False).stderr)
        self.cli("new", False, "../escape")

    def test_empty_payload_and_missing_docs_fail(self):
        self.assertIn("no files to ship", self.cli("check", False).stderr)
        self.write_payload()
        (self.fix / "TESTING.md").unlink()
        self.assertIn("TESTING.md", self.cli("check", False).stderr)

    def test_package_has_data_contents_only_and_never_overwrites(self):
        self.write_payload()
        self.cli("check")
        result = self.cli("package")
        archive = self.root / "dist" / f"{self.fix_id}.zip"
        original = archive.read_bytes()
        with zipfile.ZipFile(archive) as package:
            self.assertEqual(package.namelist(), ["SKSE/Plugins/test.ini"])
            self.assertEqual(package.read("SKSE/Plugins/test.ini"), b"value=1\n")
        self.assertIn(hashlib.sha256(original).hexdigest(), result.stdout)
        self.assertIn("Files: 1", result.stdout)
        self.cli("package", False)
        self.assertEqual(archive.read_bytes(), original)

    def test_bad_paths_and_native_binaries_fail(self):
        cases = (
            "Data/test.ini", "DATA/test.ini", ".DS_Store", "._test.ini",
            "__MACOSX/test.ini", "plugin.DLL", "test.exe", "test.dylib",
            "test.so", "test.so.1", "bad\\name.ini", "bad:name.ini",
            "CON.txt", "COM¹.ini", "trailing.", "trailing ",
        )
        for name in cases:
            with self.subTest(name=name):
                path = self.write_payload(name)
                self.cli("package", False)
                self.assertFalse((self.root / "dist").exists())
                path.unlink()
                if path.parent != self.payload:
                    path.parent.rmdir()

    def test_symlink_to_external_file_and_directory_never_leaks(self):
        external = self.root / "external"
        external.mkdir()
        (external / "secret.ini").write_text("private", encoding="utf-8")
        for target in (external, external / "secret.ini", external / "missing"):
            with self.subTest(target=target):
                link = self.payload / "linked"
                link.symlink_to(target)
                self.assertIn("symlinks are forbidden", self.cli("package", False).stderr)
                self.assertFalse((self.root / "dist").exists())
                link.unlink()

    def test_casefold_collision(self):
        first = self.write_payload("Test.ini")
        second = self.write_payload("test.ini")
        spec = importlib.util.spec_from_file_location("fix_tool", TOOL)
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        # APFS may merge these names; simulate case-sensitive directory enumeration.
        with patch.object(tool, "entries", return_value=iter((first, second))):
            with self.assertRaisesRegex(tool.FixError, "case collision"):
                tool.check_fix(self.root, self.fix_id)


if __name__ == "__main__":
    unittest.main()
