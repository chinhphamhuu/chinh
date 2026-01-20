"""
Test Subprocess CWD is Output Dir
"""
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.core import rockchip_update_engine
from app.core.task_defs import TaskResult

class TestUnpackCwd(unittest.TestCase):
    
    @patch("app.core.rockchip_update_engine.run_tool")
    @patch("app.core.rockchip_update_engine.preflight_read_file")
    @patch("app.core.rockchip_update_engine.get_tool_registry")
    def test_img_unpack_uses_cwd(self, mock_registry, mock_preflight, mock_run_tool):
        # Setup
        mock_reg_instance = MagicMock()
        mock_reg_instance.get_tool_path.return_value = Path("tools/img_unpack.exe")
        mock_registry.return_value = mock_reg_instance
        
        mock_run_tool.return_value = (0, "", "")
        
        input_path = Path("in/update.img")
        output_dir = Path("out/partitions")
        
        # Patch output dir glob to fake success
        with patch.object(Path, "glob", return_value=[Path("a.img")]):
            rockchip_update_engine.unpack_with_img_unpack(input_path, output_dir)
        
        # Check calling args
        # run_tool(args, cwd=output_dir, timeout=1800)
        # Verify cwd keyword arg
        args, kwargs = mock_run_tool.call_args
        self.assertEqual(kwargs.get('cwd'), output_dir)

if __name__ == "__main__":
    unittest.main()
