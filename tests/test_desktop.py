import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

from manager.desktop import Desktop, DesktopSession


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.app = Mock()
        self.app.stop_event = threading.Event()
        self.session = Mock()
        self.desktop = Desktop(self.app, self.session)
        self.desktop.window = Mock()
        self.desktop.tray = Mock()

    def test_close_hides_without_quitting_or_stopping_instances(self):
        self.assertFalse(self.desktop.closing())
        self.desktop.window.hide.assert_called_once()
        self.app.quit.assert_not_called()
        self.app.instances.control.assert_not_called()

    def test_reopen_restores_the_existing_window(self):
        self.desktop.show()
        self.desktop.window.restore.assert_called_once()
        self.desktop.window.show.assert_called_once()

    def test_tray_quit_respects_active_installation(self):
        self.app.quit.side_effect = ValueError("Wait for installation")
        self.desktop.quit()
        self.desktop.tray.notify.assert_called_once()
        self.desktop.window.destroy.assert_not_called()
        self.assertFalse(self.app.stop_event.is_set())

    def test_api_shutdown_closes_desktop_and_allows_actual_window_close(self):
        self.app.stop_event.set()
        self.desktop.watch()
        self.desktop.window.destroy.assert_called_once()
        self.assertTrue(self.desktop.closing())
        self.desktop.window.hide.assert_not_called()
        self.app.instances.control.assert_not_called()

    def test_tray_startup_toggle_uses_the_existing_settings_path(self):
        self.app.store.read.return_value = {"login_start": True}
        self.desktop.toggle_login()
        self.app.settings.assert_called_once_with({"login_start": False})

    @unittest.skipUnless(os.name == "nt", "Windows activation handles")
    def test_second_launch_signals_first_and_profiles_remain_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            sessions = []
            try:
                first = DesktopSession(directory)
                sessions.append(first)
                second = DesktopSession(directory)
                sessions.append(second)
                other = DesktopSession(Path(directory) / "other")
                sessions.append(other)
                self.assertTrue(first.primary)
                self.assertFalse(second.primary)
                self.assertTrue(other.primary)
                second.activate()
                self.assertTrue(first.requested())
                self.assertFalse(first.requested())
                self.assertFalse(other.requested())
            finally:
                for session in reversed(sessions):
                    session.close()
            replacement = DesktopSession(directory)
            try:
                self.assertTrue(replacement.primary)
                self.assertFalse(replacement.requested())
            finally:
                replacement.close()
