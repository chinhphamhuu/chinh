"""
Test Workspace Required Logic
Verify that WorkspaceNotConfiguredError is raised and layout is created correctly.
"""
import unittest
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.core import workspace
from app.core.errors import WorkspaceNotConfiguredError

class TestWorkspaceRequired(unittest.TestCase):
    
    def setUp(self):
        self.tmp_root = Path("temp_ws_test")
        if self.tmp_root.exists():
            shutil.rmtree(self.tmp_root)
            
        # Mock settings store to return nothing by default
        self.mock_settings = MagicMock()
        self.mock_settings.get.return_value = None
        
        self.patcher = patch("app.core.workspace._get_settings", return_value=self.mock_settings)
        self.patcher.start()
        
        # Reset singleton
        workspace._workspace = None

    def tearDown(self):
        self.patcher.stop()
        if self.tmp_root.exists():
            shutil.rmtree(self.tmp_root)

    def test_get_root_raises_error_if_empty(self):
        """get_workspace_root raises if setting empty"""
        with self.assertRaises(WorkspaceNotConfiguredError):
            workspace.get_workspace_root()

    def test_init_raises_if_config_missing(self):
        """Workspace() raises if no root avail"""
        with self.assertRaises(WorkspaceNotConfiguredError):
            workspace.Workspace()

    def test_ensure_layout_created(self):
        """set_workspace_root -> creates Projects, tools/win64, logs"""
        # Mock save
        workspace.set_workspace_root(self.tmp_root)
        
        self.mock_settings.set.assert_called_with("workspace_root", str(self.tmp_root))
        
        # Simulate getting it back
        self.mock_settings.get.return_value = str(self.tmp_root)
        
        ws = workspace.Workspace()
        self.assertEqual(ws.root, self.tmp_root)
        self.assertTrue(ws.projects_dir.exists())
        self.assertTrue(ws.tools_dir.exists())
        self.assertTrue((ws.tools_dir).name == "win64")
        self.assertTrue(ws.logs_dir.exists())

if __name__ == "__main__":
    unittest.main()
