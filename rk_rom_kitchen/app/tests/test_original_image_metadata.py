"""
Test Metadata Original Image
"""
import unittest
import shutil
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.project_store import Project
from app.core.workspace import Workspace
from app.core.partition_image_engine import extract_partition_image


class TestOriginalImageMetadata(unittest.TestCase):
    
    def setUp(self):
        self.tmp_dir = Path("temp_meta_test")
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        self.tmp_dir.mkdir()
        
        self.ws = Workspace(self.tmp_dir)
        self.ws.create_project_structure("test_proj")
        self.project = Project("test_proj", workspace=self.ws)
        
        self.in_img = self.project.in_dir / "system_a.img"
        self.in_img.write_text("DUMMY")

    def tearDown(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    @patch("app.core.partition_image_engine.detect_fs_type")
    @patch("app.core.partition_image_engine.is_sparse_image")
    @patch("app.core.partition_image_engine.read_file_header")
    @patch("app.core.partition_image_engine.run_tool")
    @patch("app.core.partition_image_engine.validate_extract_output")
    def test_extract_saves_original_image_metadata(self, mock_validate, mock_run, mock_header, mock_is_sparse, mock_detect):
        """Test extract saves original_image relative path"""
        
        # Mock behaviors
        mock_is_sparse.return_value = False
        mock_detect.return_value = "ext4"
        mock_validate.return_value = (True, "OK") # Validation pass
        
        # Mock extract tool logic to avoid errors
        # (img -> raw -> extract)
        # Mock raw path logic...
        
        # Call extract
        # We need to mock extract_ext4_real
        with patch("app.core.partition_image_engine.extract_ext4_real") as mock_extract_real:
            res = extract_partition_image(self.project, self.in_img)
            
        self.assertTrue(res.ok)
        
        # Check metadata
        meta_file = self.project.extract_dir / "partition_metadata" / "system_a.json"
        self.assertTrue(meta_file.exists())
        
        meta = json.loads(meta_file.read_text())
        
        # Verify keys
        self.assertIn("original_image", meta)
        self.assertIn("original_is_sparse", meta)
        
        # Verify relative path format
        expected_rel = str(self.in_img.relative_to(self.project.root_dir))
        self.assertEqual(meta["original_image"], expected_rel)
        self.assertFalse(meta["original_is_sparse"])


if __name__ == "__main__":
    unittest.main()
