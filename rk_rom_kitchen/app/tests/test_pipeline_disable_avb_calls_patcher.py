"""
Test Pipeline Disable AVB Calls Patcher
Verify that enabling disable_avb correctly calls the comprehensive patcher
and produces a size-preserved output, resolving the duplicate function ambiguity.
"""
import unittest
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.core.project_store import Project
from app.core.workspace import Workspace
from app.core.pipeline import pipeline_patch
from app.core import avb_manager

class TestPipelineDisableAVBCallsPatcher(unittest.TestCase):
    
    def setUp(self):
        self.tmp_dir = Path("temp_bug1_test")
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        self.tmp_dir.mkdir()
        
        self.ws = Workspace(self.tmp_dir)
        self.ws.create_project_structure("test_proj")
        self.project = Project("test_proj", workspace=self.ws)
        
        # Setup input vbmeta with specific size
        self.vbmeta_size = 65536
        self.vbmeta_in = self.project.in_dir / "vbmeta.img"
        self.vbmeta_in.write_bytes(b"ORIG" + b"\x00" * (self.vbmeta_size - 4))
        
    def tearDown(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    @patch("app.tools.registry.get_tool_registry")
    @patch("subprocess.run")
    def test_pipeline_calls_patcher_correctly(self, mock_run, mock_registry):
        """Pipeline 'disable_avb' -> patch_all_vbmeta -> output exists + size preserved"""
        
        # Mock registry to return a fake avbtool path to trigger subprocess path
        mock_registry.return_value.get_tool_path.return_value = "avbtool.exe"
        
        # Mock subprocess to simulate avbtool creating reasonable output
        # BUT we want to ensure fallback or padding handles size.
        # Let's say avbtool produces 4KB output (smaller than 64KB orig)
        def side_effect(args, **kwargs):
            out_path = Path(args[args.index("--output") + 1])
            out_path.write_bytes(b"PATCHED_BY_TOOL" + b"\x00" * 4000)
            return MagicMock(returncode=0, stderr="")
        mock_run.side_effect = side_effect
        
        patches = {"disable_avb": True}
        
        # Run pipeline
        res = pipeline_patch(self.project, patches=patches)
        
        self.assertTrue(res.ok, f"Pipeline failed: {res.message}")
        
        # Verify output location
        out_vbmeta = self.project.out_image_dir / "update" / "partitions" / "vbmeta.img"
        self.assertTrue(out_vbmeta.exists(), "Output vbmeta not found")
        
        # Verify size preserved (padded)
        self.assertEqual(out_vbmeta.stat().st_size, self.vbmeta_size, "Output size mismatch (padding failed?)")
        
        # Verify call flow - ensure patch_all_vbmeta logic was used (checking content)
        content = out_vbmeta.read_bytes()
        self.assertTrue(content.startswith(b"PATCHED_BY_TOOL"), "Did not use avbtool path?")

if __name__ == "__main__":
    unittest.main()
