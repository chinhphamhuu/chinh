"""
Test Original Path Resolution (Windows Safe)
"""
import unittest
from pathlib import Path
from app.core.utils import resolve_relative_path

class TestOriginalPathResolve(unittest.TestCase):
    """Test resolve_relative_path"""
    
    def test_relative_path_resolution(self):
        """Relative path -> joined with project root"""
        root = Path("C:/fake/project")
        rel = "in/system.img"
        resolved = resolve_relative_path(root, rel)
        
        # Should be absolute C:/fake/project/in/system.img
        expected = root / rel
        self.assertEqual(resolved, expected)
        self.assertTrue(resolved.is_absolute())

    def test_absolute_path_resolution_windows(self):
        """Absolute path (Windows) -> returned as is"""
        root = Path("C:/fake/project")
        abs_path = "D:/tmp/system.img"
        resolved = resolve_relative_path(root, abs_path)
        
        self.assertEqual(str(resolved).replace("\\", "/").lower(), "d:/tmp/system.img")
        self.assertTrue(resolved.is_absolute())
        



if __name__ == "__main__":
    unittest.main()
