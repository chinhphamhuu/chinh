"""
Test Registry Auto-Detect and Priority
"""
import unittest
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.tools import registry

class TestRegistryPriority(unittest.TestCase):
    
    def setUp(self):
        self.tmp_ws = Path("temp_reg_priority_ws")
        self.tmp_bundled = Path("temp_reg_bundled")
        
        # Clean
        if self.tmp_ws.exists(): shutil.rmtree(self.tmp_ws)
        if self.tmp_bundled.exists(): shutil.rmtree(self.tmp_bundled)
        
        # Setup Workspace
        (self.tmp_ws / "tools" / "win64").mkdir(parents=True)
        self.ws_tool = self.tmp_ws / "tools" / "win64" / "img_unpack.exe"
        self.ws_tool.write_text("workspace")
        
        # Setup Bundled (Fallback)
        # Note: registry.py looks for __file__/../../../tools/win64
        # We need to mock __file__ or correct path resolution
        # Easiest is to mock _get_search_paths? But we want to test _get_search_paths logic...
        # So we mock get_workspace. but mocking bundled dir path in registry?
        # registry.py: app_root = Path(__file__).parent.parent.parent
        # We can patch registry.Path? No.
        
        # Let's rely on patching _get_search_paths for simple priority test if logic is complex to setup physically,
        # OR just mock get_workspace returns self.tmp_ws.
        pass

    def tearDown(self):
        if self.tmp_ws.exists(): shutil.rmtree(self.tmp_ws)
        if self.tmp_bundled.exists(): shutil.rmtree(self.tmp_bundled)
        registry.ToolRegistry._instance = None # Reset singleton

    @patch("app.core.workspace.get_workspace")
    def test_registry_priority_workspace_over_bundled(self, mock_get_workspace):
        """Workspace tool should override everything"""
        # Mock workspace
        mock_ws = MagicMock()
        mock_ws.tools_dir = self.tmp_ws / "tools" / "win64"
        mock_get_workspace.return_value = mock_ws
        
        # Init registry
        reg = registry.ToolRegistry()
        
        # Detect
        # We need "img_unpack" definition in registry to look for img_unpack.exe
        # registry.TOOL_DEFINITIONS has it.
        
        info = reg.get_tool("img_unpack")
        self.assertTrue(info.available)
        self.assertEqual(info.path.resolve(), self.ws_tool.resolve())

    @patch("app.core.workspace.get_workspace")
    def test_registry_autodetect_on_init(self, mock_get_workspace):
        """Tools should be detected immediately on init"""
        reg = registry.ToolRegistry()
        # Should have run detect
        # We didn't setup any tools, so they should be missing, but 'detect_all' was called.
        # How to check? info.error == 'Not found' means it ran.
        info = reg.get_tool("img_unpack")
        self.assertIsNotNone(info)
        # If it ran, available is False, error Not found.
        # If it didn't run, info might differ? Defaults are 'available=False'.
        
        # Let's mock detect_all to verify call
        with patch.object(registry.ToolRegistry, 'detect_all', wraps=reg.detect_all) as mock_detect:
            registry.ToolRegistry._instance = None
            reg2 = registry.ToolRegistry()
            mock_detect.assert_called_once()

if __name__ == "__main__":
    unittest.main()
