"""
Test AVB Scanner with Slot Mode
"""
import unittest
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.project_store import Project
from app.core.workspace import Workspace
from app.core.avb_manager import scan_vbmeta_targets

class TestVbmetaScannerSlotMode(unittest.TestCase):
    
    def setUp(self):
        self.tmp_dir = Path("temp_scanner_test")
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        self.tmp_dir.mkdir()
        
        self.ws = Workspace(self.tmp_dir)
        self.ws.create_project_structure("test_proj")
        self.project = Project("test_proj", workspace=self.ws)
        
        # Create Dummy Files in IN dir (or out/update/partitions)
        self.parts_dir = self.project.out_image_dir / "update" / "partitions"
        self.parts_dir.mkdir(parents=True, exist_ok=True)
        
        files = [
            "vbmeta.img",
            "vbmeta_a.img",
            "vbmeta_b.img",
            "vbmeta_system.img",
            "vbmeta_system_a.img",
            "vbmeta_vendor_b.img"
        ]
        for f in files:
            (self.parts_dir / f).write_text("DUMMY")

    def tearDown(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    def test_auto_prefer_a(self):
        """Auto mode: prefer _a, then _b, then base"""
        self.project.update_config(slot_mode="auto")
        results = scan_vbmeta_targets(self.project)
        names = {p.name for p in results}
        
        # Expect: vbmeta_a.img (over vbmeta.img, vbmeta_b.img)
        # vbmeta_system_a.img (over vbmeta_system.img if it existed)
        # vbmeta_vendor_b.img (only b exists)
        
        self.assertIn("vbmeta_a.img", names)
        self.assertNotIn("vbmeta.img", names) 
        self.assertNotIn("vbmeta_b.img", names)
        
        self.assertIn("vbmeta_system_a.img", names)
        self.assertIn("vbmeta_vendor_b.img", names)

    def test_mode_A_strict(self):
        """Mode A: Only _a or base (if no _a?)"""
        self.project.update_config(slot_mode="A")
        results = scan_vbmeta_targets(self.project)
        names = {p.name for p in results}
        
        self.assertIn("vbmeta_a.img", names)
        # vbmeta_vendor_b should NOT be included? Rules say "A: chỉ *_a, fallback base nếu thiếu *_a"
        # base of vbmeta_vendor_b is vbmeta_vendor. No _a, no base -> Exclude?
        self.assertNotIn("vbmeta_vendor_b.img", names) 
        self.assertIn("vbmeta_system_a.img", names)

    def test_mode_both(self):
        """Mode Both: Include both A and B"""
        self.project.update_config(slot_mode="both")
        results = scan_vbmeta_targets(self.project)
        names = {p.name for p in results}
        
        self.assertIn("vbmeta_a.img", names)
        self.assertIn("vbmeta_b.img", names)
        self.assertIn("vbmeta_system_a.img", names)
        self.assertIn("vbmeta_vendor_b.img", names)
        self.assertNotIn("vbmeta.img", names) # Base excluded if slots exist

if __name__ == "__main__":
    unittest.main()
