"""Session storage tests for the Unix and Windows code paths. No network or login."""
import contextlib
import importlib.util
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("privacy_query", Path(__file__).with_name("privacy_query.py"))
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)

SID = "S-1-5-21-1111111111-2222222222-3333333333-1001"
WINDOWS_ROOT = r"C:\Windows"
WHOAMI = os.path.join(WINDOWS_ROOT, "System32", "whoami.exe")
ICACLS = os.path.join(WINDOWS_ROOT, "System32", "icacls.exe")
UNIX_ONLY = ("geteuid", "fchmod", "O_NOFOLLOW")


@contextlib.contextmanager
def session_paths():
    with tempfile.TemporaryDirectory() as directory:
        old = q.SESSION_DIR, q.SESSION_FILE
        q.SESSION_DIR = Path(directory) / ".session"
        q.SESSION_FILE = q.SESSION_DIR / "session.json"
        try:
            yield Path(directory)
        finally:
            q.SESSION_DIR, q.SESSION_FILE = old


class FakeWindowsCommands:
    """Stands in for whoami.exe and icacls.exe and records every call."""

    def __init__(self, whoami_output=f'"pc\\user","{SID}"\r\n', fail_icacls=False):
        self.whoami_output = whoami_output
        self.fail_icacls = fail_icacls
        self.calls = []
        self.file_sizes = {}

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[0] == WHOAMI:
            return subprocess.CompletedProcess(argv, 0, stdout=self.whoami_output, stderr="")
        if argv[0] == ICACLS:
            if self.fail_icacls:
                raise subprocess.CalledProcessError(5, argv)
            if os.path.isfile(argv[1]):
                self.file_sizes.setdefault(argv[1], os.path.getsize(argv[1]))
            return subprocess.CompletedProcess(argv, 0)
        raise AssertionError(f"unexpected command {argv[0]}")

    def grants(self):
        return [(c[1], c[4]) for c in self.calls if c[0] == ICACLS and "/grant:r" in c]


@contextlib.contextmanager
def simulated_windows(commands):
    """Take the Windows branch and hide Unix-only os functions so any use fails."""
    saved = {name: getattr(os, name) for name in UNIX_ONLY if hasattr(os, name)}
    for name in saved:
        delattr(os, name)
    try:
        with mock.patch.object(q, "IS_WINDOWS", True), \
             mock.patch.object(q.subprocess, "run", side_effect=commands), \
             mock.patch.object(q.os, "chmod", side_effect=AssertionError("chmod used on Windows path")), \
             mock.patch.dict(os.environ, {"SystemRoot": WINDOWS_ROOT}):
            yield
    finally:
        for name, value in saved.items():
            setattr(os, name, value)


def fake_lstat(target, replacement):
    real = os.lstat
    def lstat(path, *args, **kwargs):
        return replacement if Path(path) == target else real(path, *args, **kwargs)
    return lstat


class SimulatedWindowsSessionTests(unittest.TestCase):
    """Run the Windows branch on any OS with whoami/icacls replaced by fakes."""

    def test_round_trip_restricts_directory_and_file_to_current_user(self):
        commands = FakeWindowsCommands()
        with session_paths(), simulated_windows(commands):
            q.save_session({"password": "secret", "cookies": {"example": "private"}})
            self.assertNotIn("secret", q.SESSION_FILE.read_text())
            self.assertEqual(q.read_session()["cookies"], {"example": "private"})
            grants = commands.grants()
            session_dir, session_file = str(q.SESSION_DIR), str(q.SESSION_FILE)
        self.assertIn((session_dir, f"*{SID}:(OI)(CI)F"), grants)
        self.assertIn((session_file, f"*{SID}:F"), grants)
        temp_grants = [path for path, grant in grants if Path(path).name.startswith(".session-")]
        self.assertEqual(len(temp_grants), 1)
        # The temporary file is locked down before any session data is written to it.
        self.assertEqual(commands.file_sizes[temp_grants[0]], 0)
        for argv in commands.calls:
            if argv[0] == ICACLS:
                self.assertTrue(argv[2] == "/reset" or argv[2:4] == ["/inheritance:r", "/grant:r"])

    def test_every_restriction_resets_acl_then_removes_inheritance(self):
        commands = FakeWindowsCommands()
        with session_paths(), simulated_windows(commands):
            q.secure_directory()
            session_dir = str(q.SESSION_DIR)
        icacls_calls = [c for c in commands.calls if c[0] == ICACLS]
        self.assertEqual(icacls_calls, [
            [ICACLS, session_dir, "/reset", "/q"],
            [ICACLS, session_dir, "/inheritance:r", "/grant:r", f"*{SID}:(OI)(CI)F", "/q"],
        ])

    def test_icacls_failure_aborts_and_leaves_no_session_file(self):
        commands = FakeWindowsCommands(fail_icacls=True)
        with session_paths(), simulated_windows(commands):
            with self.assertRaises(q.SessionStorageError):
                q.save_session({"cookies": {"example": "private"}})
            self.assertFalse(q.SESSION_FILE.exists())
            self.assertEqual(list(q.SESSION_DIR.iterdir()), [])

    def test_unexpected_whoami_output_is_rejected(self):
        for output in ("", "not csv at all", '"pc\\user","S-1-x"', '"a","S-1-5-1"\n"b","S-1-5-2"'):
            with self.subTest(output=output), session_paths(), simulated_windows(FakeWindowsCommands(whoami_output=output)):
                with self.assertRaises(q.SessionStorageError):
                    q.secure_directory()

    def test_reparse_point_session_file_is_rejected(self):
        with session_paths(), simulated_windows(FakeWindowsCommands()):
            q.secure_directory()
            q.SESSION_FILE.write_text("{}")
            real = os.lstat(q.SESSION_FILE)
            junction = mock.Mock(st_mode=real.st_mode, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
            with mock.patch.object(q.os, "lstat", side_effect=fake_lstat(q.SESSION_FILE, junction)):
                with self.assertRaises(q.SessionStorageError):
                    q.read_session()

    def test_reparse_point_session_directory_is_rejected(self):
        with session_paths(), simulated_windows(FakeWindowsCommands()):
            q.SESSION_DIR.mkdir()
            real = os.lstat(q.SESSION_DIR)
            junction = mock.Mock(st_mode=real.st_mode, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
            with mock.patch.object(q.os, "lstat", side_effect=fake_lstat(q.SESSION_DIR, junction)):
                with self.assertRaises(q.SessionStorageError):
                    q.secure_directory()

    def test_symlinked_session_file_is_rejected(self):
        with session_paths() as root, simulated_windows(FakeWindowsCommands()):
            q.secure_directory()
            (root / "elsewhere.json").write_text("{}")
            try:
                q.SESSION_FILE.symlink_to(root / "elsewhere.json")
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaises(q.SessionStorageError):
                q.read_session()

    def test_file_swapped_between_check_and_open_is_rejected(self):
        with session_paths() as root, simulated_windows(FakeWindowsCommands()):
            q.secure_directory()
            q.SESSION_FILE.write_text("{}")
            other = root / "other.json"
            other.write_text("{}")
            with mock.patch.object(q.os, "lstat", side_effect=fake_lstat(q.SESSION_FILE, os.lstat(other))):
                with self.assertRaises(q.SessionStorageError):
                    q.read_session()

    def test_missing_session_returns_none(self):
        with session_paths(), simulated_windows(FakeWindowsCommands()):
            self.assertIsNone(q.read_session())

    def test_prompt_does_not_open_dev_tty(self):
        stderr = mock.Mock(isatty=mock.Mock(return_value=True))
        stdin = mock.Mock(isatty=mock.Mock(return_value=True))
        with mock.patch.object(q, "IS_WINDOWS", True), \
             mock.patch("builtins.open", side_effect=AssertionError("/dev/tty opened")), \
             mock.patch.object(q.sys, "stdin", stdin), mock.patch.object(q.sys, "__stderr__", stderr), \
             mock.patch.object(q.getpass, "getpass", return_value="sample") as prompt:
            self.assertEqual(q.prompt_private("Hidden: "), "sample")
        prompt.assert_called_once_with("Hidden: ", stream=stderr)


@unittest.skipIf(os.name == "nt", "Unix permission checks")
class UnixSessionTests(unittest.TestCase):
    def test_unix_path_uses_modes_and_never_runs_windows_tools(self):
        with session_paths(), mock.patch.object(q.subprocess, "run", side_effect=AssertionError("subprocess used")):
            q.save_session({"cookies": {"example": "private"}})
            self.assertEqual(stat.S_IMODE(q.SESSION_DIR.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(q.SESSION_FILE.stat().st_mode), 0o600)
            self.assertEqual(q.read_session()["cookies"], {"example": "private"})

    def test_loose_permissions_are_tightened_on_read(self):
        with session_paths():
            q.save_session({"cookies": {}})
            os.chmod(q.SESSION_DIR, 0o755)
            os.chmod(q.SESSION_FILE, 0o644)
            q.read_session()
            self.assertEqual(stat.S_IMODE(q.SESSION_DIR.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(q.SESSION_FILE.stat().st_mode), 0o600)

    def test_directory_owned_by_another_user_is_rejected(self):
        with session_paths():
            q.SESSION_DIR.mkdir()
            with mock.patch.object(q.os, "geteuid", return_value=os.geteuid() + 1):
                with self.assertRaises(q.SessionStorageError):
                    q.read_session()

    def test_file_owned_by_another_user_is_rejected(self):
        with session_paths():
            q.save_session({"cookies": {}})
            real_fstat = os.fstat
            def foreign_fstat(fd):
                info = real_fstat(fd)
                return mock.Mock(st_mode=info.st_mode, st_uid=info.st_uid + 1)
            with mock.patch.object(q.os, "fstat", side_effect=foreign_fstat):
                with self.assertRaises(q.SessionStorageError):
                    q.read_session()

    def test_symlinked_directory_is_rejected(self):
        with session_paths() as root:
            (root / "real").mkdir()
            q.SESSION_DIR.symlink_to(root / "real")
            with self.assertRaises(q.SessionStorageError):
                q.secure_directory()


@unittest.skipUnless(os.name == "nt", "requires a real Windows device")
class RealWindowsSessionTests(unittest.TestCase):
    """Calls the real whoami.exe and icacls.exe. Only runs on Windows."""

    def acl_entries(self, path):
        output = subprocess.run([q.windows_tool("icacls.exe"), str(path)], capture_output=True,
                                text=True, errors="replace", check=True).stdout
        return [line for line in output.splitlines() if re.search(r":(\([A-Z,]+\))+\s*$", line)]

    def test_round_trip_leaves_one_non_inherited_entry(self):
        with session_paths():
            q.save_session({"cookies": {"example": "private"}})
            self.assertEqual(q.read_session()["cookies"], {"example": "private"})
            for path in (q.SESSION_DIR, q.SESSION_FILE):
                entries = self.acl_entries(path)
                self.assertEqual(len(entries), 1, entries)
                self.assertNotIn("(I)", entries[0])


if __name__ == "__main__":
    unittest.main()
