import nvdastudio.memory.memory_manager as mm_module


def _make_manager(tmp_path, monkeypatch):
	monkeypatch.setattr(mm_module, "_MEMORY_FILE", tmp_path / "MEMORY.md")
	monkeypatch.setattr(mm_module, "_USER_FILE", tmp_path / "USER.md")
	return mm_module.MemoryManager()


def test_replace_rejeita_conteudo_acima_do_limite(tmp_path, monkeypatch):
	manager = _make_manager(tmp_path, monkeypatch)
	manager.add("entrada pequena")

	conteudo_gigante = "x" * (mm_module._MEMORY_CHAR_LIMIT + 100)
	result = manager.replace("entrada pequena", conteudo_gigante)

	assert result["success"] is False
	assert "Limite excedido" in result["error"]
	assert manager._memory_entries == ["entrada pequena"], (
		"Entrada original nao deveria ter sido sobrescrita quando o limite e excedido"
	)


def test_replace_aceita_conteudo_dentro_do_limite(tmp_path, monkeypatch):
	manager = _make_manager(tmp_path, monkeypatch)
	manager.add("entrada antiga")

	result = manager.replace("entrada antiga", "entrada nova")

	assert result["success"] is True
	assert manager._memory_entries == ["entrada nova"]
