import pytest

import nvdastudio.ai.anthropic_memory_tool as memtool_mod
from nvdastudio.ai.anthropic_memory_tool import handle_memory_command


@pytest.fixture(autouse=True)
def _isolated_memory_root(tmp_path, monkeypatch):
	monkeypatch.setattr(memtool_mod, "_MEMORY_ROOT", tmp_path / "claude_memory")
	yield


class TestView:
	def test_view_diretorio_vazio_nao_e_erro(self):
		result = handle_memory_command({"command": "view", "path": "/memories"})
		assert result["is_error"] is False
		assert "/memories" in result["content"]

	def test_view_arquivo_inexistente_e_erro(self):
		result = handle_memory_command({"command": "view", "path": "/memories/nao_existe.txt"})
		assert result["is_error"] is True
		assert "does not exist" in result["content"]

	def test_view_arquivo_apos_create_mostra_conteudo_numerado(self):
		handle_memory_command({"command": "create", "path": "/memories/notas.txt", "file_text": "linha um\nlinha dois"})
		result = handle_memory_command({"command": "view", "path": "/memories/notas.txt"})
		assert result["is_error"] is False
		assert "linha um" in result["content"]
		assert "1\t" in result["content"] or "     1\t" in result["content"]

	def test_view_diretorio_lista_arquivo_criado(self):
		handle_memory_command({"command": "create", "path": "/memories/notas.txt", "file_text": "x"})
		result = handle_memory_command({"command": "view", "path": "/memories"})
		assert "/memories/notas.txt" in result["content"]


class TestCreate:
	def test_create_sucesso(self):
		result = handle_memory_command({"command": "create", "path": "/memories/a.txt", "file_text": "conteudo"})
		assert result["is_error"] is False
		assert "File created successfully" in result["content"]

	def test_create_arquivo_ja_existente_e_erro(self):
		handle_memory_command({"command": "create", "path": "/memories/a.txt", "file_text": "x"})
		result = handle_memory_command({"command": "create", "path": "/memories/a.txt", "file_text": "y"})
		assert result["is_error"] is True
		assert "already exists" in result["content"]


class TestStrReplace:
	def test_str_replace_sucesso(self):
		handle_memory_command({"command": "create", "path": "/memories/p.txt", "file_text": "cor favorita: azul"})
		result = handle_memory_command({
			"command": "str_replace", "path": "/memories/p.txt",
			"old_str": "azul", "new_str": "verde",
		})
		assert result["is_error"] is False
		view = handle_memory_command({"command": "view", "path": "/memories/p.txt"})
		assert "verde" in view["content"]

	def test_str_replace_texto_nao_encontrado_e_erro(self):
		handle_memory_command({"command": "create", "path": "/memories/p.txt", "file_text": "abc"})
		result = handle_memory_command({
			"command": "str_replace", "path": "/memories/p.txt",
			"old_str": "xyz", "new_str": "123",
		})
		assert result["is_error"] is True
		assert "did not appear verbatim" in result["content"]

	def test_str_replace_ocorrencia_duplicada_e_erro(self):
		handle_memory_command({"command": "create", "path": "/memories/p.txt", "file_text": "a\na\na"})
		result = handle_memory_command({
			"command": "str_replace", "path": "/memories/p.txt",
			"old_str": "a", "new_str": "b",
		})
		assert result["is_error"] is True
		assert "Multiple occurrences" in result["content"]


class TestInsert:
	def test_insert_sucesso(self):
		handle_memory_command({"command": "create", "path": "/memories/t.txt", "file_text": "um\ndois\ntres"})
		result = handle_memory_command({
			"command": "insert", "path": "/memories/t.txt",
			"insert_line": 1, "insert_text": "um-e-meio",
		})
		assert result["is_error"] is False
		view = handle_memory_command({"command": "view", "path": "/memories/t.txt"})
		assert "um-e-meio" in view["content"]

	def test_insert_linha_invalida_e_erro(self):
		handle_memory_command({"command": "create", "path": "/memories/t.txt", "file_text": "um"})
		result = handle_memory_command({
			"command": "insert", "path": "/memories/t.txt",
			"insert_line": 99, "insert_text": "x",
		})
		assert result["is_error"] is True
		assert "Invalid `insert_line`" in result["content"]


class TestDelete:
	def test_delete_sucesso(self):
		handle_memory_command({"command": "create", "path": "/memories/d.txt", "file_text": "x"})
		result = handle_memory_command({"command": "delete", "path": "/memories/d.txt"})
		assert result["is_error"] is False
		assert "Successfully deleted" in result["content"]

	def test_delete_inexistente_e_erro(self):
		result = handle_memory_command({"command": "delete", "path": "/memories/nao_existe.txt"})
		assert result["is_error"] is True

	def test_delete_raiz_memories_e_bloqueado(self):
		result = handle_memory_command({"command": "delete", "path": "/memories"})
		assert result["is_error"] is True


class TestRename:
	def test_rename_sucesso(self):
		handle_memory_command({"command": "create", "path": "/memories/rascunho.txt", "file_text": "x"})
		result = handle_memory_command({
			"command": "rename", "old_path": "/memories/rascunho.txt", "new_path": "/memories/final.txt",
		})
		assert result["is_error"] is False
		view = handle_memory_command({"command": "view", "path": "/memories/final.txt"})
		assert view["is_error"] is False

	def test_rename_destino_existente_e_erro(self):
		handle_memory_command({"command": "create", "path": "/memories/a.txt", "file_text": "1"})
		handle_memory_command({"command": "create", "path": "/memories/b.txt", "file_text": "2"})
		result = handle_memory_command({"command": "rename", "old_path": "/memories/a.txt", "new_path": "/memories/b.txt"})
		assert result["is_error"] is True
		assert "already exists" in result["content"]


class TestPathTraversal:
	"""Protecao obrigatoria contra CWE-22 -- path fora de /memories deve
	sempre ser rejeitado, nunca acessar arquivos reais do sistema."""

	def test_path_fora_de_memories_e_rejeitado(self):
		result = handle_memory_command({"command": "view", "path": "/etc/passwd"})
		assert result["is_error"] is True

	def test_path_traversal_com_dotdot_e_rejeitado(self):
		result = handle_memory_command({"command": "create", "path": "/memories/../../secrets.env", "file_text": "x"})
		assert result["is_error"] is True

	def test_comando_desconhecido_e_erro(self):
		result = handle_memory_command({"command": "format_disk", "path": "/memories"})
		assert result["is_error"] is True
		assert "unknown command" in result["content"]


class TestWiredNoCodeGenerator:
	def test_anthropic_recebe_tool_memory(self):
		import inspect
		import nvdastudio.sub_agents.code_generator as mod
		src = inspect.getsource(mod)
		assert '"type": "memory_20250818"' in src
		assert "handle_memory_command" in src
