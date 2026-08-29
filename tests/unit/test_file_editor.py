import json

from nvdastudio.tool_system.builtins import file_editor
from nvdastudio.tools.tool_gateway import ToolGateway


def test_edit_file_substitui_exatamente_e_retorna_hash(tmp_path, monkeypatch):
	monkeypatch.setattr(file_editor, "_WORKSPACE_ROOT", tmp_path)
	target = tmp_path / "addon.py"
	target.write_text("alpha\nbeta\n", encoding="utf-8", newline="")
	old_hash = file_editor._sha256(target)

	result = json.loads(file_editor.edit_file(
		str(target), "beta", "gamma", expected_sha256=old_hash,
	))

	assert result["success"] is True
	assert result["output"]["replacements"] == 1
	assert target.read_text(encoding="utf-8") == "alpha\ngamma\n"


def test_edit_file_recusa_hash_stale_e_traversal(tmp_path, monkeypatch):
	monkeypatch.setattr(file_editor, "_WORKSPACE_ROOT", tmp_path)
	target = tmp_path / "addon.py"
	target.write_text("alpha\n", encoding="utf-8")

	stale = json.loads(file_editor.edit_file(str(target), "alpha", "beta", expected_sha256="0" * 64))
	assert "mudou" in stale["error"]

	outside = json.loads(file_editor.edit_file(str(tmp_path.parent / "outside.py"), "a", "b"))
	assert "error" in outside
	assert "workspace" in outside["error"]


def test_gateway_registra_editor_com_aprovacao():
	gateway = ToolGateway()
	gateway.register_builtin_tools()
	assert "file_editor" in gateway._tools
	result, error = gateway.call("file_editor", {"path": "x", "old_text": "a", "new_text": "b"})
	assert result is None
	assert "recusada" in error.lower()


def test_editor_cria_move_compara_e_desfaz(tmp_path, monkeypatch):
	monkeypatch.setattr(file_editor, "_WORKSPACE_ROOT", tmp_path)
	target = tmp_path / "a.py"

	assert json.loads(file_editor.edit_file(str(target), action="create", content="x\n"))["success"] is True
	assert target.read_text(encoding="utf-8") == "x\n"

	moved = json.loads(file_editor.edit_file(
		str(target), action="move", destination_path=str(tmp_path / "b.py"),
	))
	assert not target.exists()
	assert (tmp_path / "b.py").exists()

	undone = json.loads(file_editor.edit_file(action="undo", operation_id=moved["output"]["operation_id"]))
	assert undone["success"] is True
	assert target.exists()

	comparison = json.loads(file_editor.edit_file(
		str(target), action="diff", content="y\n",
	))
	assert "-x" in comparison["output"]["diff"]

	removed = json.loads(file_editor.edit_file(str(target), action="delete"))
	assert not target.exists()
	json.loads(file_editor.edit_file(action="undo", operation_id=removed["output"]["operation_id"]))
	assert target.exists()
