"""
A suite de testes escrevia no banco de memoria REAL do usuario.

Achado em 2026-09-01: em %APPDATA%/NVDAStudio/memory.json havia uma entrada de
web_knowledge com topic="prompt" e content="output valido" -- string de mock
desta propria suite (tests/integration/test_sub_agents.py:28), gravada como se
fosse conhecimento pesquisado.

Duas consequencias, e a segunda e a grave:

1. Rodar teste alterava o estado do usuario -- efeito colateral que teste nenhum
   deveria ter.
2. Esse banco alimenta get_similar_sessions(), get_common_mistakes() e a busca
   proativa do code_generator. Dado sintetico ali vira contexto de uma geracao
   REAL: o pipeline aprendia com mock.

A fixture `_memoria_isolada` (conftest, autouse de sessao) redireciona o banco.
Estes testes travam o mecanismo -- o problema nao esta nos testes que lembram de
isolar, esta nos que nao lembram.
"""

import os
import pathlib

from nvdastudio.memory.session_memory import (
	MODULE_VERSION,
	memory,
	resolver_dir_do_banco,
)


def test_versao():
	assert MODULE_VERSION == "3.6.0"


def test_variavel_de_ambiente_esta_definida():
	assert os.environ.get("NVDASTUDIO_MEMORY_DIR"), (
		"a fixture autouse de isolamento nao rodou"
	)


def test_banco_nao_aponta_para_o_appdata_do_usuario():
	import nvdastudio.memory.session_memory as sm

	caminho = pathlib.Path(sm._DB_PATH).resolve()
	real = (pathlib.Path.home() / "AppData" / "Roaming" / "NVDAStudio").resolve()
	assert real not in caminho.parents, (
		f"a suite escreveria no banco real do usuario: {caminho}"
	)


def test_escrita_de_teste_nao_chega_ao_banco_real():
	"""O caso concreto: um mock salvo como conhecimento pesquisado."""
	memory.save_web_knowledge(
		topic="topico-sintetico-de-teste",
		content="output valido",
		source_url="",
		year=2026,
	)
	real = pathlib.Path.home() / "AppData" / "Roaming" / "NVDAStudio" / "memory.json"
	if not real.is_file():
		return
	assert "topico-sintetico-de-teste" not in real.read_text(
		encoding="utf-8", errors="replace"
	), "conteudo de teste vazou para o banco real do usuario"


def test_redirecionamento_e_lido_do_ambiente(tmp_path, monkeypatch):
	"""O mecanismo tem que funcionar por variavel de ambiente, nao so por
	monkeypatch do modulo -- subprocessos herdam ambiente, nao atributos.

	Testado pela funcao de resolucao, sem `importlib.reload`: recarregar o
	modulo troca a identidade das classes (SessionRecord vira outro objeto) e
	quebra o `isinstance` de testes que rodam depois -- foi o que aconteceu na
	primeira versao deste arquivo.
	"""
	monkeypatch.setenv("NVDASTUDIO_MEMORY_DIR", str(tmp_path / "outro"))
	assert resolver_dir_do_banco() == str(tmp_path / "outro")


def test_sem_a_variavel_o_padrao_continua_sendo_o_do_usuario(monkeypatch):
	"""O redirecionamento e para teste; em producao o NVDA precisa achar o banco
	no lugar de sempre."""
	monkeypatch.delenv("NVDASTUDIO_MEMORY_DIR", raising=False)
	assert resolver_dir_do_banco().endswith(os.path.join("Roaming", "NVDAStudio"))


def test_valor_em_branco_nao_vira_diretorio_vazio(monkeypatch):
	"""Variavel definida como string vazia gravaria o banco na raiz do processo."""
	monkeypatch.setenv("NVDASTUDIO_MEMORY_DIR", "   ")
	assert resolver_dir_do_banco().endswith(os.path.join("Roaming", "NVDAStudio"))
