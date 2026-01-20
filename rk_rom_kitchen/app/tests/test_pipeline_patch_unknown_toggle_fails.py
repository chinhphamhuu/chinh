"""
Test Pipeline Patch Unknown Toggle
"""
import unittest
import shutil
from pathlib import Path

from app.core.project_store import Project
from app.core.workspace import Workspace
from app.core.pipeline import pipeline_patch

class TestPipelinePatchUnknown(unittest.TestCase):
    
    def setUp(self):
        self.tmp_dir = Path("temp_pipe_test")
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        self.tmp_dir.mkdir()
        
        self.ws = Workspace(self.tmp_dir)
        self.ws.create_project_structure("test_proj")
        self.project = Project("test_proj", workspace=self.ws)

    def tearDown(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    def test_unknown_toggle_fails(self):
        """Unsupported toggle should return error"""
        patches = {
            "disable_avb": True,
            "super_magical_hack": True  # Unsupported
        }
        
        res = pipeline_patch(self.project, patches=patches)
        
        self.assertFalse(res.ok)
        self.assertIn("chưa được hỗ trợ", res.message or str(res.error))

if __name__ == "__main__":
    unittest.main()
