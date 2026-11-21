import io
import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from manager.updates import UpdateChecker
from manager.config import Store, REPOSITORY


def release(version, assets=True):
    base = f"https://github.com/{REPOSITORY}/releases/download/v{version}/"
    return io.BytesIO(json.dumps({"tag_name": "v" + version, "html_url": f"https://github.com/{REPOSITORY}/releases/tag/v{version}",
        "assets": [{"name": f"llama-cpp-instance-manager-{version}-windows-x64-setup.exe",
                    "browser_download_url": base + f"llama-cpp-instance-manager-{version}-windows-x64-setup.exe"},
                   {"name":"SHA256SUMS.txt", "browser_download_url":base+"SHA256SUMS.txt"}] if assets else []}).encode())


class UpdateTests(unittest.TestCase):
    def test_numeric_comparison_never_offers_an_older_or_equal_release(self):
        for current, latest, available in (("0.2.1", "0.1.0", False), ("0.2.1", "0.2.1", False),
                                           ("0.2.1", "0.2.2", True), ("0.9.0", "0.10.0", True)):
            with self.subTest(current=current, latest=latest), patch("manager.updates.VERSION", current), \
                 patch("manager.updates.urllib.request.urlopen", return_value=release(latest)):
                result = UpdateChecker().check()
                self.assertEqual(result["available"], available)
                self.assertEqual(bool(result["download"]), available)

    def test_multiple_clients_share_cache_and_manual_check_refreshes(self):
        checker = UpdateChecker()
        with patch("manager.updates.urllib.request.urlopen", side_effect=[release("9.0.0"), release("9.1.0")]) as fetch:
            first = checker.check()
            self.assertEqual(checker.check(), first)
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(checker.check(force=True)["latest"], "9.1.0")
            self.assertIn("ThatMonitorCord/llama.cpp-Instance-Manager/releases/latest", fetch.call_args.args[0].full_url)

    def test_unpublished_release_is_not_an_error_and_retry_recovers_from_network_failure(self):
        checker = UpdateChecker()
        with patch("manager.updates.urllib.request.urlopen", side_effect=HTTPError("url", 404, "missing", {}, None)):
            self.assertIsNone(checker.check()["error"])
            self.assertFalse(checker.check()["available"])
        with patch("manager.updates.urllib.request.urlopen", side_effect=URLError("offline")):
            self.assertIn("connection", checker.check(force=True)["error"])
        with patch("manager.updates.urllib.request.urlopen", return_value=release("9.0.0")):
            self.assertTrue(checker.check(force=True)["available"])

    def test_release_without_installer_has_notes_but_no_download(self):
        with patch("manager.updates.urllib.request.urlopen", return_value=release("9.0.0", assets=False)):
            result = UpdateChecker().check()
            self.assertTrue(result["available"])
            self.assertIsNone(result["download"])
            self.assertTrue(result["url"])

    def test_verified_installer_runs_silently_in_registered_directory_and_reopens_same_profile(self):
        content = b"test installer bytes"
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            checker = UpdateChecker(store)
            with patch("manager.updates.installed_directory", return_value=Path(directory)/"program"), \
                 patch("manager.updates.urllib.request.urlopen", side_effect=[release("9.0.0"),
                     io.BytesIO((hashlib.sha256(content).hexdigest()+"  llama-cpp-instance-manager-9.0.0-windows-x64-setup.exe").encode()),
                     io.BytesIO(content)]), patch("manager.updates.subprocess.Popen") as launch:
                launch.return_value.wait.return_value = 0
                checker.apply("9.0.0", lambda message: None)
                command = launch.call_args.args[0]
                self.assertIn("/VERYSILENT", command)
                self.assertIn("/ACTION=update", command)
                self.assertIn("/RESTARTMANAGER=1", command)
                self.assertIn(f"/DIR={Path(directory)/'program'}", command)
                self.assertEqual(launch.call_args.kwargs["env"]["LLAMA_MANAGER_DATA"], str(store.directory))
                self.assertEqual(Path(command[0]).read_bytes(), content)

    def test_checksum_mismatch_never_executes_download(self):
        with tempfile.TemporaryDirectory() as directory:
            checker = UpdateChecker(Store(directory))
            with patch("manager.updates.installed_directory", return_value=Path(directory)/"program"), \
                 patch("manager.updates.urllib.request.urlopen", side_effect=[release("9.0.0"),
                     io.BytesIO(("0"*64+"  llama-cpp-instance-manager-9.0.0-windows-x64-setup.exe").encode()),
                     io.BytesIO(b"wrong file")]), patch("manager.updates.subprocess.Popen") as launch:
                with self.assertRaisesRegex(ValueError, "verified"):
                    checker.apply("9.0.0", lambda message: None)
                launch.assert_not_called()
            self.assertEqual(list(Path(directory).rglob("*.partial")), [])

    def test_assets_from_another_repository_are_not_installable(self):
        data = json.loads(release("9.0.0").read())
        data["assets"][0]["browser_download_url"] = "https://github.com/other/repo/setup.exe"
        with patch("manager.updates.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(data).encode())):
            result = UpdateChecker().check()
            self.assertTrue(result["error"])
            self.assertFalse(result["can_install"])
