"""
Test Workspace Migration (Move/Copy/Skip)
"""
import unittest
import shutil
from pathlib import Path
from app.core import workspace

class TestWorkspaceMigrate(unittest.TestCase):
    
    def setUp(self):
        self.src_root = Path("temp_mig_src")
        self.dst_root = Path("temp_mig_dst")
        
        # Clean up
        if self.src_root.exists(): shutil.rmtree(self.src_root)
        if self.dst_root.exists(): shutil.rmtree(self.dst_root)
        
        # Setup source
        (self.src_root / "Projects" / "ProjA").mkdir(parents=True)
        (self.src_root / "Projects" / "ProjA" / "config").mkdir()
        
        (self.src_root / "tools" / "win64").mkdir(parents=True)
        (self.src_root / "tools" / "win64" / "tool.exe").write_text("t")
        
        # Reset workspace
        workspace._workspace = None

    def tearDown(self):
        if self.src_root.exists(): shutil.rmtree(self.src_root)
        if self.dst_root.exists(): shutil.rmtree(self.dst_root)

    def test_migrate_copy(self):
        """Mode COPY: Src remains, Dst created matching Src"""
        workspace.migrate_workspace(self.src_root, self.dst_root, 'COPY')
        
        # Verify Dst
        self.assertTrue((self.dst_root / "Projects" / "ProjA").is_dir())
        self.assertTrue((self.dst_root / "tools" / "win64" / "tool.exe").exists())
        
        # Verify Src remains
        self.assertTrue((self.src_root / "Projects" / "ProjA").is_dir())
        self.assertTrue((self.src_root / "tools" / "win64" / "tool.exe").exists())

    def test_migrate_move(self):
        """Mode MOVE: Src gone, Dst created"""
        workspace.migrate_workspace(self.src_root, self.dst_root, 'MOVE')
        
        # Verify Dst
        self.assertTrue((self.dst_root / "Projects" / "ProjA").is_dir())
        self.assertTrue((self.dst_root / "tools" / "win64" / "tool.exe").exists())
        
        # Verify Src "Projects" and "tools/win64" gone (or empty if parent remains)
        # migrate_workspace removes src dir recursively
        self.assertFalse((self.src_root / "Projects").exists())
        # tools/win64 deleted, but tools might remain if other files there? 
        # Implementation: shutil.rmtree(self.src_root / relative)
        self.assertFalse((self.src_root / "tools" / "win64").exists())

    def test_migrate_skip(self):
        """Mode SKIP: Nothing happens"""
        # Create DST partially to ensure no touch
        (self.dst_root).mkdir()
        workspace.migrate_workspace(self.src_root, self.dst_root, 'SKIP')
        
        # Verify Src remains
        self.assertTrue((self.src_root / "Projects").exists())
        
        # Verify Dst Projects DOES NOT EXIST (unless ensure_layout created it? 
        # logic: Workspace(new_root) calls ensure_layout. So Projects empty exists.)
        # But ProjA should NOT exist.
        self.assertFalse((self.dst_root / "Projects" / "ProjA").exists())

if __name__ == "__main__":
    unittest.main()
