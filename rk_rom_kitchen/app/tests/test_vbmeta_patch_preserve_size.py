"""
Test AVB Patcher Size Preservation
"""
import unittest
import shutil
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.project_store import Project
from app.core.workspace import Workspace
from app.core.avb_manager import patch_all_vbmeta

class TestVbmetaPatchPreserveSize(unittest.TestCase):
    
    def setUp(self):
        self.tmp_dir = Path("temp_patcher_test")
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        self.tmp_dir.mkdir()
        
        self.ws = Workspace(self.tmp_dir)
        self.ws.create_project_structure("test_proj")
        self.project = Project("test_proj", workspace=self.ws)
        
        # Create a "Big" vbmeta (64KB)
        self.in_dir = self.project.in_dir
        self.target = self.in_dir / "vbmeta.img"
        self.target_size = 65536
        self.target.write_bytes(b"ORIG" * (self.target_size // 4))

    def tearDown(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    @patch("app.tools.registry.get_tool_registry")
    @patch("app.core.avb_manager.scan_vbmeta_targets")
    @patch("subprocess.run")
    def test_patch_preserves_size(self, mock_run, mock_scan, mock_registry):
        """Ensure patched file is padded to original size"""
        mock_scan.return_value = [self.target]
        
        # Mock registry to return a fake avbtool path
        mock_registry.return_value.get_tool_path.return_value = "avbtool.exe"
        
        # Mock avbtool failing/unavailable -> Fallback to internally generated 4KB file
        # Or mock success but small file
        # Let's mock subprocess run to create a small file (4KB)
        def side_effect(args, **kwargs):
            # args has --output path
            out_path = Path(args[-1])
            out_path.write_bytes(b"PATCHED" + b"\x00" * 4000)
            return MagicMock(returncode=0)
            
        mock_run.side_effect = side_effect
        
        # Run patch
        res = patch_all_vbmeta(self.project)
        
        self.assertTrue(res.ok)
        
        # Check output
        out_file = self.project.out_image_dir / "update" / "partitions" / "vbmeta.img"
        self.assertTrue(out_file.exists())
        self.assertEqual(out_file.stat().st_size, self.target_size)
        
        # Check content start
        content = out_file.read_bytes()
        self.assertTrue(content.startswith(b"PATCHED"))

if __name__ == "__main__":
    unittest.main()
