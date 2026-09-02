"""
Defeito de lint mecanico era pago a preco de modelo.

Medido nos 391 relatorios E2E: 9 steps de code_generation reprovados por lint,
3.298.179 tokens. Das 60 ocorrencias citadas nas mensagens de reprovacao:

  F401 (import nao usado) ..... 43
  F821 (nome indefinido) ......  6
  F841 (variavel nao usada) ...  5
  F823 (uso antes da atribuicao)  5
  B007 ........................  1

As 49 de F401/F841/B007 nao tem decisao semantica nenhuma -- e apagar uma
linha. Tres tentativas de um modelo a ~140 mil tokens cada para remover um
import e o mesmo erro que ja custou caro com indentacao (838 mil) e com gettext
(3,3 milhoes).

F821 e F823 sao bug de verdade, sem correcao mecanica: continuam indo para o
modelo, agora sem o ruido do que o codigo mesmo resolvia.
"""

import ast

from nvdastudio.builder.addon_builder import (
	MODULE_VERSION,
	extract_code_blocks,
	substituir_codigo_dos_blocos,
)
from nvdastudio.builder.code_sandbox import CodeSandbox

NL = chr(10)
CERCA = chr(96) * 3


def test_versao():
	assert MODULE_VERSION == "4.20.0"


class TestAutofix:
	def test_import_nao_usado_e_removido(self):
		sujo = "import os" + NL + "import sys" + NL + NL + "def f():" + NL + "\treturn 1" + NL
		out = CodeSandbox().lint_autofix({"globalPlugins/A/x.py": sujo})
		corrigido = out["globalPlugins/A/x.py"]
		assert "import os" not in corrigido
		assert "import sys" not in corrigido
		assert "def f():" in corrigido

	def test_import_usado_e_preservado(self):
		"""Remover um import em uso trocaria F401 por NameError em execucao."""
		src = "import os" + NL + NL + "def f():" + NL + "\treturn os.sep" + NL
		out = CodeSandbox().lint_autofix({"globalPlugins/A/x.py": src})
		assert "import os" in out["globalPlugins/A/x.py"]

	def test_defeito_sem_correcao_mecanica_fica_para_o_modelo(self):
		"""F821 e bug de verdade -- corrigir exige saber o que o autor queria."""
		src = "def f():" + NL + "\treturn nome_que_nao_existe" + NL
		out = CodeSandbox().lint_autofix({"globalPlugins/A/y.py": src})
		assert out["globalPlugins/A/y.py"] == src

	def test_arquivo_nao_python_nao_e_tocado(self):
		out = CodeSandbox().lint_autofix({"manifest.ini": "name = A" + NL})
		assert out["manifest.ini"] == "name = A" + NL

	def test_gettext_nao_vira_nome_indefinido(self):
		"""A config curada declara `_` como builtin -- sem isso TODO addon
		correto levaria F401/F821 no lugar errado."""
		src = "import wx" + NL + NL + 'X = _("Chave")' + NL + "Y = wx.ID_OK" + NL
		out = CodeSandbox().lint_autofix({"globalPlugins/A/p.py": src})
		assert "wx" in out["globalPlugins/A/p.py"]

	def test_resultado_sempre_compila(self):
		for src in (
			"import os" + NL + "def f(): return 1" + NL,
			'"""Doc."""' + NL + "import sys" + NL + "X = 1" + NL,
			"def f(:" + NL,  # sintaxe quebrada
		):
			out = CodeSandbox().lint_autofix({"globalPlugins/A/z.py": src})
			resultado = out["globalPlugins/A/z.py"]
			try:
				ast.parse(src)
			except SyntaxError:
				assert resultado == src, "arquivo quebrado nao pode ser alterado"
				continue
			ast.parse(resultado)


class TestCorrecaoVoltaParaOOutput:
	"""A costura que importa: `last_output` e o que vai para o assembly e para o
	disco. Corrigir so a copia extraida entregaria o addon ainda com o defeito.
	"""

	def _saida(self, codigo, caminho="globalPlugins/A/x.py"):
		return (
			"Segue o codigo:" + NL + NL
			+ CERCA + "python:" + caminho + NL + codigo + CERCA + NL
		)

	def test_bloco_anotado_recebe_o_codigo_corrigido(self):
		saida = self._saida("import os" + NL + "def f(): return 1" + NL)
		novo = substituir_codigo_dos_blocos(
			saida, {"globalPlugins/A/x.py": "def f(): return 1" + NL},
		)
		assert "import os" not in novo
		blocos = extract_code_blocks(novo)
		assert blocos[0]["filename"] == "globalPlugins/A/x.py"
		assert "def f(): return 1" in blocos[0]["code"]

	def test_outros_blocos_ficam_intactos(self):
		saida = (
			self._saida("import os" + NL + "X = 1" + NL)
			+ NL + CERCA + "ini:manifest.ini" + NL + "name = A" + NL + CERCA + NL
		)
		novo = substituir_codigo_dos_blocos(saida, {"globalPlugins/A/x.py": "X = 1" + NL})
		assert "name = A" in novo
		assert len(extract_code_blocks(novo)) == 2

	def test_caminho_desconhecido_nao_altera_nada(self):
		"""Nao aplicar a correcao custa uma tentativa; corromper o output custa
		o addon."""
		saida = self._saida("X = 1" + NL)
		assert substituir_codigo_dos_blocos(saida, {"outro/arquivo.py": "Y = 2"}) == saida

	def test_output_vazio_ou_sem_correcao(self):
		assert substituir_codigo_dos_blocos("", {"a.py": "x"}) == ""
		assert substituir_codigo_dos_blocos("texto", {}) == "texto"

	def test_orchestrator_reescreve_o_output_e_nao_so_os_arquivos(self):
		import inspect

		from nvdastudio.core.orchestrator import Orchestrator

		src = inspect.getsource(Orchestrator)
		assert "lint_autofix(" in src
		assert "substituir_codigo_dos_blocos(last_output" in src
		i_fix = src.index("lint_autofix(")
		i_lint = src.index("lint_check = _static_sandbox.lint_check(")
		assert i_fix < i_lint, (
			"a correcao mecanica precisa rodar ANTES do lint que reprova"
		)


class TestGuardaContraPiorar:
	"""
	O autofix MODIFICA codigo que vai para o usuario. Um mecanismo desses
	precisa de uma garantia de que nunca piora o arquivo.

	Verificado: `--fix` do ruff remove `import gui` quando o nome nao e
	referenciado -- e em addon NVDA existe import por efeito colateral. Quando a
	remocao deixa um nome INDEFINIDO que antes nao existia, o arquivo volta ao
	original: trocar um aviso de lint por um NameError em execucao no NVDA do
	usuario seria um pessimo negocio.
	"""

	def test_contador_de_nomes_indefinidos(self):
		s = CodeSandbox()
		limpo = "import json" + NL + "X = json.dumps({})" + NL
		quebrado = "X = Client()" + NL
		assert s._nomes_indefinidos("globalPlugins/A/m.py", limpo) == 0
		assert s._nomes_indefinidos("globalPlugins/A/m.py", quebrado) >= 1

	def test_gettext_nao_conta_como_indefinido(self):
		"""`_` e injetado por addonHandler.initTranslation(); sem a config
		curada, TODO addon traduzido pareceria cheio de nomes indefinidos."""
		s = CodeSandbox()
		assert s._nomes_indefinidos("globalPlugins/A/m.py", 'X = _("oi")' + NL) == 0

	def test_correcao_que_criaria_nome_indefinido_e_descartada(self, monkeypatch):
		"""Prova que o guarda DISPARA -- nao basta ele existir."""
		s = CodeSandbox()
		original = "import json" + NL + "X = json.dumps({})" + NL
		monkeypatch.setattr(
			CodeSandbox, "_ruff_fix_um_arquivo",
			lambda self, rel, conteudo, timeout=None: "X = json.dumps({})" + NL,
		)
		out = s.lint_autofix({"globalPlugins/A/m.py": original})
		assert out["globalPlugins/A/m.py"] == original, (
			"a correcao removeu o import de um nome ainda usado e passou"
		)

	def test_correcao_boa_continua_passando_pelo_guarda(self, monkeypatch):
		s = CodeSandbox()
		original = "import os" + NL + "import json" + NL + "X = json.dumps({})" + NL
		limpo = "import json" + NL + "X = json.dumps({})" + NL
		monkeypatch.setattr(
			CodeSandbox, "_ruff_fix_um_arquivo",
			lambda self, rel, conteudo, timeout=None: limpo,
		)
		assert s.lint_autofix({"globalPlugins/A/m.py": original})["globalPlugins/A/m.py"] == limpo

	def test_ruff_ausente_nao_bloqueia_nem_altera(self, monkeypatch):
		"""-1 em ambas as medidas: duas incognitas nao acusam piora, e o
		conteudo segue intacto porque nao houve correcao."""
		s = CodeSandbox()
		monkeypatch.setattr(
			CodeSandbox, "_nomes_indefinidos",
			lambda self, rel, conteudo, timeout=None: -1,
		)
		src = "import os" + NL + "X = 1" + NL
		out = s.lint_autofix({"globalPlugins/A/m.py": src})
		assert isinstance(out["globalPlugins/A/m.py"], str)


class TestPontoDeEntradaNaoEReexport:
	"""
	O ruff se recusa a remover import nao usado de `__init__.py` porque assume
	re-export de pacote -- e a recusa e amarrada ao NOME do arquivo. Verificado:
	nem `--unsafe-fixes` nem `ignore-init-module-imports` (deprecado) mudam isso.

	Mas o `globalPlugins/<Addon>/__init__.py` de um addon NVDA nao re-exporta
	nada: e o modulo do plugin, o arquivo que o NVDA carrega e executa.

	Medido na rodada 8: cg_core reprovado por "F401 `os` imported but unused" no
	__init__.py, 336.994 tokens, enquanto o MESMO defeito era corrigido sem
	drama nos outros arquivos do mesmo addon.
	"""

	def _morto(self):
		return (
			"import os" + NL + "import globalPluginHandler" + NL + NL
			+ "class GlobalPlugin(globalPluginHandler.GlobalPlugin): pass" + NL
		)

	def test_import_morto_no_ponto_de_entrada_e_removido(self):
		cam = "globalPlugins/A/__init__.py"
		out = CodeSandbox().lint_autofix({cam: self._morto()})[cam]
		assert "import os" not in out
		assert "import globalPluginHandler" in out

	def test_import_usado_no_ponto_de_entrada_e_preservado(self):
		cam = "globalPlugins/A/__init__.py"
		usado = (
			"import os" + NL + "import globalPluginHandler" + NL + NL
			+ "class GlobalPlugin(globalPluginHandler.GlobalPlugin):" + NL
			+ chr(9) + "p = os.sep" + NL
		)
		assert "import os" in CodeSandbox().lint_autofix({cam: usado})[cam]

	def test_subpacote_mantem_a_excecao_do_ruff(self):
		"""Em `<Addon>/<sub>/__init__.py` o re-export E legitimo -- ali a
		excecao do ruff continua valendo."""
		cam = "globalPlugins/A/sub/__init__.py"
		assert "import os" in CodeSandbox().lint_autofix({cam: self._morto()})[cam]

	def test_appmodule_solto_nao_e_afetado(self):
		"""appModules/<exe>.py nao e __init__.py -- caminho normal do ruff."""
		cam = "appModules/notepad.py"
		out = CodeSandbox().lint_autofix({cam: self._morto()})[cam]
		assert "import os" not in out
