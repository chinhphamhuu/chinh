"""
Test Super Copy-Through Missing Tools
Verify fail fast behavior when required tools are missing for copy-through
"""
import unittest
import shutil
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.project_store import Project
from app.core.workspace import Workspace
from app.core.super_image_engine import build_super_img, SPARSE_MAGIC

class TestSuperCopyThroughMissingTools(unittest.TestCase):
    
    def setUp(self):
        self.tmp_dir = Path("temp_super_missing_tool")
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        self.tmp_dir.mkdir()
        
        self.ws = Workspace(self.tmp_dir)
        self.ws.create_project_structure("test_proj")
        self.project = Project("test_proj", workspace=self.ws)
        
        self.out_dummy = self.project.out_image_dir / "super"
        self.out_dummy.mkdir(parents=True, exist_ok=True)
        
        # Original super SPARSE
        self.orig_super = self.project.in_dir / "super.img"
        self.orig_super.write_bytes(SPARSE_MAGIC + b"DATA" * 50)
        
        # Metadata
        self.meta_dict = {
            "partitions": [{"name": "system_a", "size": 1000}],
            "original_super": "in/super.img"
        }
        (self.out_dummy / "super_metadata.json").write_text(json.dumps(self.meta_dict))

    def tearDown(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    @patch("app.core.super_image_engine.get_tool_registry")
    @patch("app.core.super_image_engine.is_dirty")
    @patch("app.core.super_image_engine.run_tool")
    def test_missing_simg2img_fails_raw_request(self, mock_run, mock_is_dirty, mock_registry):
        """Request RAW from SPARSE original + missing simg2img => FAIL"""
        mock_registry.return_value.get_tool_path.side_effect = lambda name: None if name == "simg2img" else "tool"
        
        mock_is_dirty.return_value = False # All Clean
        
        # Output sparse=False (Request RAW)
        res = build_super_img(self.project, output_sparse=False)
        
        self.assertFalse(res.ok)
        self.assertIn("Thiếu simg2img", res.message)
        # Verify NO rebuild happened (message shouldn't be generic error)

    @patch("app.core.super_image_engine.get_tool_registry")
    @patch("app.core.super_image_engine.is_dirty")
    @patch("app.core.super_image_engine.run_tool")
    def test_missing_img2simg_fallback_raw(self, mock_run, mock_is_dirty, mock_registry):
        """Request SPARSE from RAW original + missing img2simg => SUCCESS (Fallback RAW)"""
        # Rewrite orig to RAW
        self.orig_super.write_bytes(b"RAW_DATA_ONLY")
        
        mock_registry.return_value.get_tool_path.side_effect = lambda name: None if name == "img2simg" else "tool"
        mock_is_dirty.return_value = False
        
        # Process output_sparse=True
        res = build_super_img(self.project, output_sparse=True)
        
        # Should succeed but output raw artifact
        self.assertTrue(res.ok)
        self.assertIn("Super copy-through", res.message)
        # Artifact should be raw because fallback
        produced = res.artifacts[0]
        self.assertTrue(produced.endswith(".raw.img"))


if __name__ == "__main__":
    unittest.main()
