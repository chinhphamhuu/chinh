"""
Test Copy-Through / No-Op Build (Partition)
Verify: Clean partition => Copy/Convert original image instead of rebuild
"""
import unittest
import shutil
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.project_store import Project
from app.core.workspace import Workspace
from app.core.partition_image_engine import repack_partition_image
from app.core.task_defs import TaskResult
from app.core.dirty_tracker import set_dirty


class TestCopyThroughPartition(unittest.TestCase):
    
    def setUp(self):
        self.tmp_dir = Path("temp_copy_test")
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        self.tmp_dir.mkdir()
        
        # Setup workspace & project
        self.ws = Workspace(self.tmp_dir)
        self.ws.create_project_structure("test_proj")
        self.project = Project("test_proj", workspace=self.ws)
        
        # Mock paths
        self.in_dir = self.project.in_dir
        self.out_source = self.project.out_source_dir
        self.out_img = self.project.out_image_dir
        self.meta_dir = self.project.extract_dir / "partition_metadata"
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        
        # Mock source dir (required to exist)
        (self.out_source / "system_a").mkdir(parents=True)
        
        # Helper to create original image
        self.orig_raw = self.in_dir / "system_a.img"
        self.orig_raw.write_bytes(b"DATA" * 100) # Dummy raw
        
        self.orig_sparse = self.in_dir / "vendor_a.img"
        # Magic bytes for sparse: 0x3a 0xff 0x26 0xed (little endian) -> \x3a\xff\x26\xed
        self.orig_sparse.write_bytes(b"\x3a\xff\x26\xed" + b"DATA" * 100)

    def tearDown(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    def create_metadata(self, name, orig_path, is_sparse, fs_type="ext4"):
        meta = {
            "partition_name": name,
            "original_image": str(orig_path.relative_to(self.project.root_dir)),
            "original_is_sparse": is_sparse,
            "fs_type": fs_type
        }
        (self.meta_dir / f"{name}.json").write_text(json.dumps(meta))

    @patch("app.core.partition_image_engine.get_tool_registry")
    @patch("app.core.partition_image_engine.run_tool")
    @patch("app.core.partition_image_engine.auto_detect_dirty")
    @patch("app.core.partition_image_engine.is_dirty")
    def test_clean_raw_to_raw_copy(self, mock_is_dirty, mock_auto, mock_run, mock_registry):
        """Clean + Orig Raw + Output Raw => Direct Copy"""
        mock_is_dirty.return_value = False
        self.create_metadata("system_a", self.orig_raw, is_sparse=False)
        
        # Mock registry
        mock_registry.return_value.get_tool_path.return_value = "tool"
        
        res = repack_partition_image(self.project, "system_a", output_sparse=False)
        
        self.assertTrue(res.ok)
        final_path = self.out_img / "system_a_patched.raw.img"
        self.assertTrue(final_path.exists())
        self.assertEqual(final_path.read_bytes(), self.orig_raw.read_bytes())
        
        # Rebuild NOT called (we didn't mock rebuild, so if it continued it would fail or try to run tools)
        # But to be sure, check logs or artifact correctness.
        # Here we rely on success and artifact exist.

    @patch("app.core.partition_image_engine.get_tool_registry")
    @patch("app.core.partition_image_engine.run_tool")
    @patch("app.core.partition_image_engine.auto_detect_dirty")
    @patch("app.core.partition_image_engine.is_dirty")
    def test_clean_raw_to_sparse_convert(self, mock_is_dirty, mock_auto, mock_run, mock_registry):
        """Clean + Orig Raw + Output Sparse => Convert with img2simg"""
        mock_is_dirty.return_value = False
        self.create_metadata("system_a", self.orig_raw, is_sparse=False)
        
        mock_registry.return_value.get_tool_path.return_value = "img2simg"
        
        # Mock run_tool to simulate conversion: create output file
        def side_effect(cmd, timeout):
            # cmd: [tool, input, output]
            out_file = Path(cmd[2])
            out_file.write_bytes(b"\x3a\xff\x26\xed_CONVERTED")
            return 0, "", ""
        mock_run.side_effect = side_effect
        
        res = repack_partition_image(self.project, "system_a", output_sparse=True)
        
        self.assertTrue(res.ok)
        final_path = self.out_img / "system_a_patched.img"
        self.assertTrue(final_path.exists())
        self.assertIn(b"_CONVERTED", final_path.read_bytes())
        
        # Ensure raw temp deleted
        raw_tmp = self.out_img / "system_a_patched.raw.img"
        self.assertFalse(raw_tmp.exists())

    @patch("app.core.partition_image_engine.get_tool_registry")
    @patch("app.core.partition_image_engine.run_tool")
    @patch("app.core.partition_image_engine.auto_detect_dirty")
    @patch("app.core.partition_image_engine.is_dirty")
    @patch("app.core.partition_image_engine.build_ext4_image_best_effort")
    def test_dirty_rebuilds(self, mock_build, mock_is_dirty, mock_auto, mock_run, mock_registry):
        """Dirty => Rebuild called"""
        mock_is_dirty.return_value = True
        self.create_metadata("system_a", self.orig_raw, is_sparse=False)
        
        # Mock builder returning success
        mock_build.return_value = TaskResult.success(artifacts=["built.img"])
        
        repack_partition_image(self.project, "system_a", output_sparse=False)
        
        mock_build.assert_called_once()


if __name__ == "__main__":
    unittest.main()
