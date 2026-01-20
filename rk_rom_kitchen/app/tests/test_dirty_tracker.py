"""
Test Dirty Tracker
"""
import unittest
import tempfile
import json
from pathlib import Path

from app.core.workspace import Workspace
from app.core.project_store import Project
from app.core.dirty_tracker import (
    load_dirty, save_dirty, set_dirty, is_dirty, 
    mark_all_clean, get_dirty_summary
)


class TestDirtyTracker(unittest.TestCase):
    """Test dirty tracking functionality"""
    
    def make_project(self, tmp: Path):
        """Create minimal project structure"""
        ws = Workspace(tmp)
        ws.create_project_structure("test_proj")
        return Project("test_proj", workspace=ws)
    
    def test_load_empty_returns_empty_dict(self):
        """Không có dirty.json => return {}"""
        with tempfile.TemporaryDirectory() as td:
            project = self.make_project(Path(td))
            result = load_dirty(project)
            self.assertEqual(result, {})
    
    def test_is_dirty_default_true_when_unknown(self):
        """Unknown partition => return True (safe default)"""
        with tempfile.TemporaryDirectory() as td:
            project = self.make_project(Path(td))
            # No dirty.json, unknown partition
            self.assertTrue(is_dirty(project, "system_a"))
    
    def test_set_dirty_and_is_dirty(self):
        """set_dirty lưu flag, is_dirty đọc đúng"""
        with tempfile.TemporaryDirectory() as td:
            project = self.make_project(Path(td))
            
            # Set dirty False
            set_dirty(project, "system_a", False)
            self.assertFalse(is_dirty(project, "system_a"))
            
            # Set dirty True
            set_dirty(project, "system_a", True)
            self.assertTrue(is_dirty(project, "system_a"))
    
    def test_mark_all_clean(self):
        """mark_all_clean sets all to False"""
        with tempfile.TemporaryDirectory() as td:
            project = self.make_project(Path(td))
            
            mark_all_clean(project, ["system_a", "vendor_a", "product_a"])
            
            self.assertFalse(is_dirty(project, "system_a"))
            self.assertFalse(is_dirty(project, "vendor_a"))
            self.assertFalse(is_dirty(project, "product_a"))
    
    def test_dirty_persists_to_file(self):
        """Dirty flags lưu vào file JSON đúng"""
        with tempfile.TemporaryDirectory() as td:
            project = self.make_project(Path(td))
            
            set_dirty(project, "system_a", False)
            set_dirty(project, "vendor_a", True)
            
            # Verify file content
            dirty_path = project.extract_dir / "dirty.json"
            self.assertTrue(dirty_path.exists())
            
            data = json.loads(dirty_path.read_text())
            self.assertEqual(data["system_a"], False)
            self.assertEqual(data["vendor_a"], True)
    
    def test_get_dirty_summary(self):
        """Summary string hiển thị đúng"""
        with tempfile.TemporaryDirectory() as td:
            project = self.make_project(Path(td))
            
            set_dirty(project, "system_a", False)
            set_dirty(project, "vendor_a", True)
            
            summary = get_dirty_summary(project)
            self.assertIn("CLEAN", summary)
            self.assertIn("DIRTY", summary)
            self.assertIn("system_a", summary)
            self.assertIn("vendor_a", summary)


if __name__ == "__main__":
    unittest.main()
