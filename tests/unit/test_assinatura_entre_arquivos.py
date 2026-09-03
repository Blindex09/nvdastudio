"""NVDA-063: chamador e definicao discordando ENTRE arquivos do addon.

Regressao do defeito do AssistenteEscrita (2026-09-03). As 62 regras
anteriores olham um arquivo por vez; nenhuma via o addon entregue em que
`__init__.py` chamava `proofread(text, model, api_key, on_done, on_error)`
e `openai_service.py` definia `proofread(self, text, callback)`.

Metade dos testes aqui e sobre NAO acusar. Falso positivo nesta regra e pior
que o defeito: o pipeline entra em retry ate estourar o orcamento tentando
consertar codigo que esta certo.
"""

import os

from nvdastudio.builder.addon_builder import _check_cross_module_signatures


def _montar(tmp_path, arquivos: dict[str, str]) -> str:
	"""Escreve um addon minimo e devolve a pasta raiz."""
	pkg = tmp_path / "globalPlugins" / "MeuAddon"
	pkg.mkdir(parents=True)
	for nome, conteudo in arquivos.items():
		(pkg / nome).write_text(conteudo, encoding="utf-8")
	return str(tmp_path)


_SERVICO_DIVERGENTE = (
	"class Servico:\n"
	"\tdef revisar(self, text, callback):\n"
	"\t\treturn None\n"
)


class TestPegaADiscordancia:

	def test_caso_real_do_assistente_escrita(self, tmp_path):
		"""O defeito exato, com a forma exata: modulo irmao, construcao
		inline, cinco kwargs contra dois parametros."""
		pasta = _montar(tmp_path, {
			"__init__.py": (
				"from . import servico\n\n"
				"class GlobalPlugin:\n"
				"\tdef script_revisar(self, gesture):\n"
				"\t\tservico.Servico().revisar(\n"
				"\t\t\ttext=\"oi\", model=\"m\", api_key=\"k\",\n"
				"\t\t\ton_done=None, on_error=None,\n"
				"\t\t)\n"
			),
			"servico.py": _SERVICO_DIVERGENTE,
		})

		problemas = _check_cross_module_signatures(pasta)

		assert problemas, "a discordancia entre __init__.py e servico.py passou"
		texto = " ".join(problemas)
		assert "NVDA-063" in texto
		# A mensagem tem que servir de fix_instruction sozinha: os DOIS lados.
		assert "model" in texto
		assert "servico.py:2" in texto
		assert "text, callback" in texto

	def test_argumento_obrigatorio_que_ninguem_passa(self, tmp_path):
		pasta = _montar(tmp_path, {
			"__init__.py": (
				"from . import servico\n\n"
				"def usar():\n"
				"\tservico.Servico().revisar(text=\"oi\")\n"
			),
			"servico.py": _SERVICO_DIVERGENTE,
		})

		problemas = _check_cross_module_signatures(pasta)

		assert any("callback" in p and "obrigatorio" in p for p in problemas), problemas

	def test_posicionais_demais(self, tmp_path):
		pasta = _montar(tmp_path, {
			"__init__.py": (
				"from . import servico\n\n"
				"def usar():\n"
				"\tservico.Servico().revisar(\"a\", \"b\", \"c\")\n"
			),
			"servico.py": _SERVICO_DIVERGENTE,
		})

		problemas = _check_cross_module_signatures(pasta)

		assert any("posicional" in p for p in problemas), problemas

	def test_funcao_de_modulo_irmao(self, tmp_path):
		"""`configSpec.apply_config_spec()` e o padrao real do pipeline."""
		pasta = _montar(tmp_path, {
			"__init__.py": (
				"from . import configSpec\n\n"
				"def usar():\n"
				"\tconfigSpec.apply_config_spec(secao=\"X\")\n"
			),
			"configSpec.py": "def apply_config_spec() -> None:\n\treturn None\n",
		})

		problemas = _check_cross_module_signatures(pasta)

		assert any("secao" in p for p in problemas), problemas

	def test_metodo_da_propria_classe(self, tmp_path):
		pasta = _montar(tmp_path, {
			"__init__.py": (
				"class GlobalPlugin:\n"
				"\tdef _ler_config(self, chave):\n"
				"\t\treturn chave\n\n"
				"\tdef script_x(self, gesture):\n"
				"\t\tself._ler_config(chave=\"a\", padrao=\"b\")\n"
			),
		})

		problemas = _check_cross_module_signatures(pasta)

		assert any("padrao" in p for p in problemas), problemas

	def test_classe_importada_de_modulo_irmao(self, tmp_path):
		pasta = _montar(tmp_path, {
			"__init__.py": (
				"from .servico import Servico\n\n"
				"def usar():\n"
				"\tServico().revisar(text=\"oi\", model=\"m\")\n"
			),
			"servico.py": _SERVICO_DIVERGENTE,
		})

		problemas = _check_cross_module_signatures(pasta)

		assert any("model" in p for p in problemas), problemas


class TestNaoInventaDefeito:
	"""Cada caso aqui e um padrao presente em addon CORRETO. Se a regra
	acusar qualquer um deles, ela custa mais do que resolve."""

	def test_assinatura_que_casa_nao_acusa(self, tmp_path):
		pasta = _montar(tmp_path, {
			"__init__.py": (
				"from . import servico\n\n"
				"def usar():\n"
				"\tservico.Servico().revisar(text=\"oi\", callback=None)\n"
			),
			"servico.py": _SERVICO_DIVERGENTE,
		})

		assert _check_cross_module_signatures(pasta) == []

	def test_definicao_com_kwargs_aceita_tudo(self, tmp_path):
		pasta = _montar(tmp_path, {
			"__init__.py": (
				"from . import servico\n\n"
				"def usar():\n"
				"\tservico.Servico().revisar(text=\"oi\", qualquer=1, outro=2)\n"
			),
			"servico.py": (
				"class Servico:\n"
				"\tdef revisar(self, text, **kwargs):\n"
				"\t\treturn None\n"
			),
		})

		assert _check_cross_module_signatures(pasta) == []

	def test_chamada_com_estrela_e_ignorada(self, tmp_path):
		"""`f(*args)` / `f(**kwargs)`: o conteudo so existe em runtime.
		Palpitar aqui vira retry infinito."""
		pasta = _montar(tmp_path, {
			"__init__.py": (
				"from . import servico\n\n"
				"def usar(dados):\n"
				"\tservico.Servico().revisar(**dados)\n"
				"\tservico.Servico().revisar(*dados)\n"
			),
			"servico.py": _SERVICO_DIVERGENTE,
		})

		assert _check_cross_module_signatures(pasta) == []

	def test_parametro_com_default_pode_ser_omitido(self, tmp_path):
		pasta = _montar(tmp_path, {
			"__init__.py": (
				"from . import servico\n\n"
				"def usar():\n"
				"\tservico.Servico().revisar(text=\"oi\")\n"
			),
			"servico.py": (
				"class Servico:\n"
				"\tdef revisar(self, text, callback=None):\n"
				"\t\treturn None\n"
			),
		})

		assert _check_cross_module_signatures(pasta) == []

	def test_metodo_homonimo_de_api_do_nvda_nao_e_confundido(self, tmp_path):
		"""O addon define `get(self, chave)` E usa `config.conf.get('a','b')`
		do NVDA. Casar por NOME de metodo acusaria a chamada do NVDA contra a
		definicao do addon -- por isso a regra so resolve receptor
		inequivoco."""
		pasta = _montar(tmp_path, {
			"__init__.py": (
				"import config\n\n"
				"class GlobalPlugin:\n"
				"\tdef get(self, chave):\n"
				"\t\treturn chave\n\n"
				"\tdef usar(self):\n"
				"\t\treturn config.conf.get(\"secao\", \"padrao\")\n"
			),
		})

		assert _check_cross_module_signatures(pasta) == []

	def test_metodo_herdado_do_nvda_nao_e_acusado(self, tmp_path):
		"""`self.bindGesture(...)` vem da base do NVDA, nao do addon. A regra
		so confere metodo que o proprio addon DEFINE."""
		pasta = _montar(tmp_path, {
			"__init__.py": (
				"import globalPluginHandler\n\n"
				"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
				"\tdef __init__(self):\n"
				"\t\tself.bindGesture(\"kb:NVDA+g\", \"revisar\")\n"
			),
		})

		assert _check_cross_module_signatures(pasta) == []

	def test_variavel_intermediaria_nao_e_adivinhada(self, tmp_path):
		"""`obj = fabrica(); obj.revisar(x)` -- sem inferencia de tipo, a
		regra cala. Deliberado: melhor deixar passar do que acusar errado."""
		pasta = _montar(tmp_path, {
			"__init__.py": (
				"from . import servico\n\n"
				"def usar(fabrica):\n"
				"\tobj = fabrica()\n"
				"\tobj.revisar(text=\"oi\", model=\"m\")\n"
			),
			"servico.py": _SERVICO_DIVERGENTE,
		})

		assert _check_cross_module_signatures(pasta) == []

	def test_lib_bundlada_e_ignorada(self, tmp_path):
		"""lib/ e codigo de terceiro; nao e contrato do addon."""
		pkg = tmp_path / "globalPlugins" / "lib"
		pkg.mkdir(parents=True)
		(pkg / "terceiro.py").write_text(
			"class X:\n\tdef f(self, a):\n\t\treturn a\n", encoding="utf-8"
		)

		assert _check_cross_module_signatures(str(tmp_path)) == []

	def test_addon_sem_globalplugins_nao_quebra(self, tmp_path):
		assert _check_cross_module_signatures(str(tmp_path)) == []

	def test_arquivo_com_erro_de_sintaxe_nao_quebra(self, tmp_path):
		"""Sintaxe invalida ja e reprovada por syntax_check(); aqui nao pode
		levantar excecao e derrubar a validacao estrutural inteira."""
		pasta = _montar(tmp_path, {"__init__.py": "def (((:\n"})

		assert _check_cross_module_signatures(pasta) == []


def test_addon_correto_do_repositorio_nao_acusa():
	"""Ancora contra o codigo real do proprio NVDAStudio: ele e um addon NVDA
	e passa pelas mesmas regras. Se a NVDA-063 acusasse aqui, seria falso
	positivo garantido."""
	raiz = os.path.join(os.path.dirname(__file__), "..", "..", "addon")

	problemas = _check_cross_module_signatures(os.path.abspath(raiz))

	assert problemas == [], problemas[:5]
