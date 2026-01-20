"""
Test AVB Patch Subprocess Fail Fallback
Verify that if avbtool fails (returncode!=0), we fallback to manual minimal creation.
"""
import unittest
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.project_store import Project
from app.core.workspace import Workspace
from app.core.avb_manager import patch_all_vbmeta

class TestVbmetaPatchSubprocessFailFallback(unittest.TestCase):
    
    def setUp(self):
        self.tmp_dir = Path("temp_fallback_test")
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        self.tmp_dir.mkdir()
        
        self.ws = Workspace(self.tmp_dir)
        self.ws.create_project_structure("test_proj")
        self.project = Project("test_proj", workspace=self.ws)
        
        # Create input vbmeta
        self.target = self.project.in_dir / "vbmeta.img"
        self.target.write_bytes(b"ORIG" * 1024) # 4KB
        self.target_size = self.target.stat().st_size

    def tearDown(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    @patch("app.tools.registry.get_tool_registry")
    @patch("app.core.avb_manager.scan_vbmeta_targets")
    @patch("subprocess.run")
    def test_fallback_on_tool_failure(self, mock_run, mock_scan, mock_registry):
        """Mock avbtool fails -> Check fallback content"""
        mock_scan.return_value = [self.target]
        
        # Mock registry has tool
        mock_registry.return_value.get_tool_path.return_value = "avbtool_fake"
        
        # Mock subprocess fail
        # Even if it wrote something, if returncode!=0, we should discard it
        def side_effect(args, **kwargs):
            return MagicMock(returncode=1, stderr=b"Some error")
        mock_run.side_effect = side_effect
        
        # Run
        res = patch_all_vbmeta(self.project)
        
        self.assertTrue(res.ok)
        
        # Check output
        out_file = self.project.out_image_dir / "update" / "partitions" / "vbmeta.img"
        self.assertTrue(out_file.exists())
        
        # Content should NOT be what avbtool produces (if any), but the minimal fallback
        # Minimal fallback starts with AVB0
        content = out_file.read_bytes()
        self.assertTrue(content.startswith(b"AVB0"), "Fallback content not found")
        self.assertEqual(len(content), self.target_size, "Size not preserved/padded")

if __name__ == "__main__":
    unittest.main()
