"""O pip do bundle nao pode herdar o stdin do servidor MCP nem rodar no pythonw."""

import subprocess
from unittest.mock import MagicMock, patch

from nvdastudio_mcp.addon_builder import bundle_addon_dependencies
from nvdastudio_mcp.addon_builder import write_addon_file
from nvdastudio_mcp.scaffold import build_scaffold


def test_pip_roda_sem_stdin_e_com_python_exe(tmp_path):
    for rel, content in build_scaffold("Ola").files.items():
        write_addon_file(str(tmp_path), rel, content)
    ok = MagicMock(returncode=0, stderr="")
    with patch("subprocess.run", return_value=ok) as run:
        bundle_addon_dependencies(str(tmp_path), ["six"], "Ola", _pypi_checker=lambda _p: True)
    assert run.call_args.kwargs["stdin"] is subprocess.DEVNULL
    assert "pythonw" not in run.call_args.args[0][0].lower()
