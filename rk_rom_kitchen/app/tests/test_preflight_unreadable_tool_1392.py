"""
Test Preflight Check for WinError 1392
"""
import unittest
from pathlib import Path
from unittest.mock import patch, mock_open

from app.core import rockchip_update_engine

class TestPreflight1392(unittest.TestCase):
    
    def test_preflight_catch_1392(self):
        """Should raise RuntimeError with specific message for Error 1392"""
        # Create a mock error
        win_error = OSError("Corrupt")
        win_error.winerror = 1392
        
        path = Path("fake.img")
        
        # Mock file open to raise the error
        with patch("builtins.open", side_effect=win_error), \
             patch.object(Path, "exists", return_value=True):
            
            with self.assertRaises(RuntimeError) as cm:
                rockchip_update_engine.preflight_read_file(path, 1024)
            
            self.assertIn("LỖI Ổ CỨNG", str(cm.exception))
            self.assertIn("1392", str(cm.exception))

    def test_preflight_pass_normal(self):
        """Should pass if file readable"""
        path = Path("good.img")
        m = mock_open(read_data=b"0"*1024)
        
        with patch("builtins.open", m), \
             patch.object(Path, "exists", return_value=True):
             
             rockchip_update_engine.preflight_read_file(path, 1024)
             # No raise

if __name__ == "__main__":
    unittest.main()
