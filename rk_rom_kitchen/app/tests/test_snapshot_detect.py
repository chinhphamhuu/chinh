"""
Test Snapshot Detection
"""
import unittest
import tempfile
import time
from pathlib import Path

from app.core.workspace import Workspace
from app.core.project_store import Project
from app.core.dirty_tracker import (
    compute_source_snapshot, save_partition_snapshot,
    check_partition_changed, auto_detect_dirty,
    set_dirty, is_dirty
)


class TestSnapshotDetection(unittest.TestCase):
    """Test snapshot detection functionality"""
    
    def make_project(self, tmp: Path):
        """Create minimal project structure"""
        ws = Workspace(tmp)
        ws.create_project_structure("test_proj")
        return Project("test_proj", workspace=ws)
    
    def test_compute_snapshot_empty_dir(self):
        """Empty dir => file_count=0"""
        with tempfile.TemporaryDirectory() as td:
            project = self.make_project(Path(td))
            source = project.out_source_dir / "system_a"
            source.mkdir(parents=True, exist_ok=True)
            
            snapshot = compute_source_snapshot(source)
            self.assertEqual(snapshot["file_count"], 0)
            self.assertEqual(snapshot["total_size"], 0)
    
    def test_compute_snapshot_with_files(self):
        """Dir with files => correct count and size"""
        with tempfile.TemporaryDirectory() as td:
            project = self.make_project(Path(td))
            source = project.out_source_dir / "system_a"
            source.mkdir(parents=True, exist_ok=True)
            
            # Create test files
            (source / "file1.txt").write_text("hello")
            (source / "file2.txt").write_text("world!")
            
            snapshot = compute_source_snapshot(source)
            self.assertEqual(snapshot["file_count"], 2)
            self.assertEqual(snapshot["total_size"], 11)  # 5 + 6
    
    def test_check_partition_changed_no_snapshot(self):
        """No snapshot => assume changed (safe)"""
        with tempfile.TemporaryDirectory() as td:
            project = self.make_project(Path(td))
            
            self.assertTrue(check_partition_changed(project, "system_a"))
    
    def test_check_partition_unchanged(self):
        """Snapshot saved, no changes => unchanged"""
        with tempfile.TemporaryDirectory() as td:
            project = self.make_project(Path(td))
            source = project.out_source_dir / "system_a"
            source.mkdir(parents=True, exist_ok=True)
            (source / "test.txt").write_text("content")
            
            # Save snapshot
            save_partition_snapshot(project, "system_a")
            
            # Check unchanged
            self.assertFalse(check_partition_changed(project, "system_a"))
    
    def test_check_partition_changed_after_modify(self):
        """File modified => changed"""
        with tempfile.TemporaryDirectory() as td:
            project = self.make_project(Path(td))
            source = project.out_source_dir / "system_a"
            source.mkdir(parents=True, exist_ok=True)
            test_file = source / "test.txt"
            test_file.write_text("content")
            
            # Save snapshot
            save_partition_snapshot(project, "system_a")
            
            # Modify file (change size)
            time.sleep(0.01)  # Ensure mtime changes
            test_file.write_text("modified content longer")
            
            # Check changed
            self.assertTrue(check_partition_changed(project, "system_a"))
    
    def test_auto_detect_dirty_marks_dirty(self):
        """auto_detect_dirty marks dirty when changed"""
        with tempfile.TemporaryDirectory() as td:
            project = self.make_project(Path(td))
            source = project.out_source_dir / "system_a"
            source.mkdir(parents=True, exist_ok=True)
            (source / "test.txt").write_text("content")
            
            # Save snapshot and mark clean
            save_partition_snapshot(project, "system_a")
            set_dirty(project, "system_a", False)
            
            # Modify
            (source / "test.txt").write_text("new content")
            
            # Auto detect - should mark dirty
            result = auto_detect_dirty(project, "system_a")
            self.assertTrue(result)
            self.assertTrue(is_dirty(project, "system_a"))


if __name__ == "__main__":
    unittest.main()
