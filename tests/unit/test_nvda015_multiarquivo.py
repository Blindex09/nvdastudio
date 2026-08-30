"""
NVDA-015 avaliada no CONJUNTO de arquivos, nao arquivo a arquivo.

FALSO POSITIVO REAL, medido nos 379 relatorios de tests/e2e/relatorios/:
11 dos 14 disparos de NVDA-015 (79%) foram em addons que JA TINHAM
configSpec.py. A checagem era por ARQUIVO, entao um addon bem arquitetado --
spec num modulo proprio, consumo espalhado em settings_panel.py, client.py,
qa/service.py -- levava um aviso por arquivo mandando "Crie configSpec.py",
arquivo que existia ao lado.

Distribuicao que denunciou o defeito: 14 disparos em addon MULTI-ARQUIVO,
ZERO em addon de arquivo unico. A regra punia exatamente a classe de addon que
o projeto ja tem mais dificuldade de fazer convergir -- o modelo era mandado
corrigir o que estava certo, gastava retry, e a regra disparava igual na
tentativa seguinte.

Caso real reproduzido abaixo: AssistenteLeituraGemini, 2026-08-17 10:27.
"""

import os
import tempfile

from nvdastudio.builder.addon_builder import MODULE_VERSION, validate_addon_structure

assert MODULE_VERSION == "4.14.0"


def _monta_addon(raiz: str, arquivos: dict[str, str]) -> None:
	"""Escreve um addon minimo, com manifest e __init__.py validos."""
	base = {
		"manifest.ini": (
			"name = MeuAddon\nsummary = x\ndescription = x\nversion = 1.0.0\n"
			"author = a <a@b.c>\nurl = https://x.y\ndocFileName = userGuide.html\n"
			"minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.1.1\n"
			"changelog = x\n"
		),
		"globalPlugins/MeuAddon/__init__.py": (
			"import globalPluginHandler\nimport addonHandler\n\n"
			"addonHandler.initTranslation()\n\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef terminate(self):\n\t\tsuper().terminate()\n"
		),
		"doc/en/userGuide.html": "<html></html>",
	}
	base.update(arquivos)
	for rel, conteudo in base.items():
		caminho = os.path.join(raiz, rel.replace("/", os.sep))
		os.makedirs(os.path.dirname(caminho), exist_ok=True)
		with open(caminho, "w", encoding="utf-8") as fh:
			fh.write(conteudo)


def _nvda015(problemas: list[str]) -> list[str]:
	return [p for p in problemas if "NVDA-015" in p]


class TestNVDA015NoConjunto:
	def test_addon_com_config_spec_em_modulo_proprio_nao_e_reportado(self):
		"""REGRESSAO do caso real (AssistenteLeituraGemini 2026-08-17 10:27):
		configSpec.py existe e 4 arquivos consomem config.conf. Antes: 4 avisos
		mandando criar o arquivo que ja estava la."""
		with tempfile.TemporaryDirectory() as tmp:
			_monta_addon(tmp, {
				"globalPlugins/MeuAddon/configSpec.py": (
					"import config\n\n"
					'config.conf.spec["meuAddon"] = {"chave": "string(default=\\"\\")"}\n'
				),
				"globalPlugins/MeuAddon/settings_panel.py": (
					'import config\nvalor = config.conf["meuAddon"]["chave"]\n'
				),
				"globalPlugins/MeuAddon/client.py": (
					'import config\nchave = config.conf["meuAddon"]["chave"]\n'
				),
				"globalPlugins/MeuAddon/qa/service.py": (
					'import config\nx = config.conf["meuAddon"]["chave"]\n'
				),
			})
			assert _nvda015(validate_addon_structure(tmp)) == []

	def test_addon_sem_spec_nenhuma_continua_sendo_reportado(self):
		"""O defeito REAL nao pode deixar de ser pego: ninguem declara a spec."""
		with tempfile.TemporaryDirectory() as tmp:
			_monta_addon(tmp, {
				"globalPlugins/MeuAddon/servico.py": (
					'import config\nvalor = config.conf["meuAddon"]["chave"]\n'
				),
			})
			achados = _nvda015(validate_addon_structure(tmp))
			assert len(achados) == 1
			assert "servico.py" in achados[0]

	def test_spec_declarada_no_proprio_arquivo_continua_valendo(self):
		"""Addon de arquivo unico -- comportamento anterior preservado."""
		with tempfile.TemporaryDirectory() as tmp:
			_monta_addon(tmp, {
				"globalPlugins/MeuAddon/servico.py": (
					"import config\n"
					'config.conf.spec["meuAddon"] = {"chave": "string(default=\\"\\")"}\n'
					'valor = config.conf["meuAddon"]["chave"]\n'
				),
			})
			assert _nvda015(validate_addon_structure(tmp)) == []

	def test_arquivo_chamado_configspec_conta_como_declaracao(self):
		"""Convencao do proprio projeto: a mensagem da regra manda 'Crie
		configSpec.py', entao o arquivo com esse nome tem que satisfazer."""
		with tempfile.TemporaryDirectory() as tmp:
			_monta_addon(tmp, {
				"globalPlugins/MeuAddon/configSpec.py": "# spec definida em outro formato\n",
				"globalPlugins/MeuAddon/servico.py": (
					'import config\nvalor = config.conf["meuAddon"]["chave"]\n'
				),
			})
			assert _nvda015(validate_addon_structure(tmp)) == []

	def test_addon_que_nao_usa_config_nunca_e_reportado(self):
		with tempfile.TemporaryDirectory() as tmp:
			_monta_addon(tmp, {"globalPlugins/MeuAddon/servico.py": "x = 1\n"})
			assert _nvda015(validate_addon_structure(tmp)) == []
