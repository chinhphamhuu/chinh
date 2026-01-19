"""
Test Repack Partition Contract
Đảm bảo:
1. ext4 repack dùng artifacts từ builder, không validate output_path cứng
2. erofs repack naming contract: raw.img / patched.img
3. Không sinh *_patched_sparse.img
"""
import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.core.task_defs import TaskResult


class TestRepackPartitionContract(unittest.TestCase):
    """Test repack_partition_image contract"""
    
    def make_project(self, tmp: Path):
        """Create minimal project structure using Workspace"""
        from app.core.workspace import Workspace
        from app.core.project_store import Project
        
        # Create workspace at tmp
        ws = Workspace(tmp)
        
        # Create project structure
        ws.create_project_structure("test_proj")
        
        # Create Project instance
        project = Project("test_proj", workspace=ws)
        
        return project
    
    def test_ext4_repack_must_use_builder_artifacts_raw(self):
        """
        BUG #1: repack_partition_image() phải tin artifacts từ builder.
        Với output_sparse=False, builder tạo *_patched.raw.img
        => repack KHÔNG được validate output_path = *_patched.img (không tồn tại)
        => repack PHẢI return artifacts = [raw_path]
        """
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            project = self.make_project(tmp)
            
            # Create source dir
            src = project.out_source_dir / "system_a"
            src.mkdir(parents=True, exist_ok=True)
            (src / "dummy.txt").write_text("x", encoding="utf-8")
            
            # Create metadata
            meta_dir = project.extract_dir / "partition_metadata"
            meta_dir.mkdir(parents=True, exist_ok=True)
            (meta_dir / "system_a.json").write_text(
                json.dumps({"fs_type": "ext4", "partition_name": "system_a"}),
                encoding="utf-8"
            )
            
            out_img = project.out_image_dir
            out_img.mkdir(parents=True, exist_ok=True)
            
            # Mock builder to create RAW file
            def fake_builder(**kwargs):
                raw = out_img / "system_a_patched.raw.img"
                raw.write_bytes(b"\x00" * 16)
                return TaskResult.success("ok", artifacts=[str(raw)])
            
            with patch("app.core.partition_image_engine.build_ext4_image_best_effort", side_effect=fake_builder):
                from app.core.partition_image_engine import repack_partition_image
                
                r = repack_partition_image(project, "system_a", output_sparse=False)
                
                # Assertions
                self.assertTrue(r.ok, f"Expected success, got: {r.message}")
                
                expected_raw = str(out_img / "system_a_patched.raw.img")
                self.assertEqual(r.artifacts, [expected_raw], 
                    f"Expected artifacts={[expected_raw]}, got={r.artifacts}")
                
                self.assertTrue((out_img / "system_a_patched.raw.img").exists(),
                    "Raw file should exist")
                
                # Không được sinh *_patched_sparse.img
                sparse_files = list(out_img.glob("*_patched_sparse.img"))
                self.assertEqual(len(sparse_files), 0,
                    f"Không được sinh *_patched_sparse.img, found: {sparse_files}")


if __name__ == "__main__":
    unittest.main()
