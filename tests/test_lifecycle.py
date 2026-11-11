from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from manager.config import Store
from manager.instances import Instances
from manager.app import Manager


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.row = {"id":"test", "name":"Test instance", "path":str(Path(self.temp.name)/"upstream"),
                    "gui_port":15440,"api_port":19931,"preset":"Saved model","auto_start":False,"install_state":"ready"}
        self.store.change(lambda data:data["instances"].append(self.row))
        self.controller = Instances(self.store)

    def test_stop_never_calls_an_unowned_service_at_the_configured_port(self):
        with patch("manager.instances.process_for",return_value=None), patch.object(self.controller,"api") as api:
            self.controller.control("test","stop")
        api.assert_not_called()

    def test_panel_refuses_port_owned_by_another_application(self):
        with patch("manager.instances.process_for",return_value=None), patch("manager.instances.port_available",return_value=False):
            with self.assertRaisesRegex(ValueError,"another process"):
                self.controller.panel(self.row)

    def test_preset_identity_survives_manager_restart_but_not_another_gui_process(self):
        row=dict(self.row,last_launch={"pid":42,"generation":1,"preset":"Saved model"})
        status={"running":True,"active_process_tool":"llama-cli","active_runtime":{"generation":1}}
        with patch("manager.instances.process_for",return_value=Mock(pid=42)), patch.object(self.controller,"api",return_value=status):
            self.assertEqual(self.controller.sample(row)["loaded_preset"],"Saved model")
        with patch("manager.instances.process_for",return_value=Mock(pid=43)), patch.object(self.controller,"api",return_value=status):
            self.assertIsNone(self.controller.sample(row)["loaded_preset"])

    def test_interrupted_pending_and_installing_entries_become_retryable(self):
        self.store.update_instance("test",install_state="pending")
        app=Manager(self.store)
        with patch.object(app.discovery,"start"), patch("manager.app.threading.Thread"):
            app.start()
        self.assertEqual(self.store.instance("test")["install_state"],"error")

    def test_local_restart_stops_then_launches_selected_preset(self):
        # The first ownership lookup finds the GUI; the next observes shutdown.
        process=Mock(pid=99)
        with patch("manager.instances.process_for",side_effect=[process,None,None,process]), \
             patch.object(self.controller,"panel",return_value={"running":False}), \
             patch.object(self.controller,"compile_preset",return_value={"tool":"llama-server","args":["--port","19931"],"fingerprint_data":{}}), \
             patch.object(self.controller,"api",side_effect=[{"ok":True},{"ok":True},{"active_runtime":{"generation":1}},{"ready":True}]) as api:
            self.controller.control("test","restart")
        self.assertEqual([call.args[1] for call in api.call_args_list],["/api/shutdown","/api/launch/preflight","/api/launch","/api/llama/health"])
        self.assertEqual(self.store.instance("test")["last_launch"]["preset"],"Saved model")

    def test_manager_settings_reject_duplicate_instance_port_before_login_change(self):
        app=Manager(self.store)
        with patch("manager.app.login_start") as startup:
            with self.assertRaises(ValueError):
                app.settings({"port":15440})
            startup.assert_not_called()

    def test_upgrade_quit_preserves_instances_and_refuses_active_install(self):
        app = Manager(self.store)
        app.server = Mock()
        app.instances.active_install = True
        with self.assertRaises(ValueError):
            app.quit()
        self.assertFalse(app.stop_event.is_set())
        app.instances.active_install = False
        with patch("manager.app.threading.Timer") as timer, patch.object(app.instances,"control") as control:
            app.quit()
            timer.assert_called_once()
            control.assert_not_called()
        self.assertTrue(app.stop_event.is_set())


if __name__ == "__main__":
    unittest.main()
