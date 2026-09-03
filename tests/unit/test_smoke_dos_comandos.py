"""Regressao do defeito do AssistenteEscrita (2026-09-03): o addon carregava
e os dois atalhos morriam na primeira tecla.

`__init__.py` chamava `proofread(text, model, api_key, on_done, on_error)` --
a assinatura que ele mesmo tinha DECLARADO num comentario de contrato -- e
`openai_service.py` definia `proofread(self, text, callback)`. Resultado:
TypeError na primeira tecla, engolido pelo `except Exception` do proprio
addon e falado como "Nao foi possivel iniciar a revisao do texto".

O que deixou passar: `validate_addon_execution()` fazia import ->
instanciacao -> terminate e parava ali. Os tres passos funcionavam. O
defeito morava uma chamada adiante, e os 62 checks do catalogo NVDA sao
todos INTRA-arquivo.

Cada teste aqui responde uma pergunta diferente:
  - o defeito real e pego mesmo o addon engolindo a excecao?
  - o addon correto continua passando (sem falso positivo)?
  - o `try: import X / except ImportError` da NVDA-022, que TODO addon bem
    escrito tem, continua passando?
  - o guard de modo seguro (NVDA-062) nao faz o smoke passar sem executar
    nada?
"""

import pytest

from nvdastudio.builder.code_sandbox import CodeSandbox


def _rodar(files: dict[str, str]):
	return CodeSandbox(timeout_sec=25).validate_addon_execution(files)


_CABECALHO = (
	"import addonHandler\n"
	"import globalPluginHandler\n"
	"import ui\n"
	"import globalVars\n"
	"from logHandler import log\n"
	"from scriptHandler import script\n"
	"from . import servico\n\n"
	"addonHandler.initTranslation()\n\n"
)


def _plugin(corpo_do_script: str) -> str:
	return (
		_CABECALHO
		+ "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
		"\t@script(description=\"Revisa\")\n"
		"\tdef script_revisar(self, gesture):\n"
		"\t\tif globalVars.appArgs.secure:\n"
		"\t\t\tui.message(\"indisponivel no modo seguro\")\n"
		"\t\t\treturn\n"
		+ corpo_do_script
		# terminate() e exigido pela NVDA-004. Sem ele, o portao estrutural
		# reprova por OUTRO motivo e o teste do caminho feliz nao provaria
		# nada sobre a costura, que e o que ele existe para medir.
		+ "\n\tdef terminate(self):\n\t\tsuper().terminate()\n"
	)


# O addon NVDA correto NUNCA deixa excecao subir para o leitor de tela --
# e esse except, que e boa pratica, que escondeu o defeito por completo.
_CHAMADA_ENGOLIDA = (
	"\t\ttry:\n"
	"\t\t\tservico.Servico().revisar(\n"
	"\t\t\t\ttext=\"oi\",\n"
	"\t\t\t\tmodel=\"gpt-4o-mini\",\n"
	"\t\t\t\tapi_key=\"sk-x\",\n"
	"\t\t\t\ton_done=lambda r: None,\n"
	"\t\t\t\ton_error=lambda e: None,\n"
	"\t\t\t)\n"
	"\t\texcept Exception as exc:\n"
	"\t\t\tlog.error(\"falhou: %s\", exc)\n"
	"\t\t\tui.message(\"Nao foi possivel iniciar a revisao do texto.\")\n"
)

_SERVICO_DIVERGENTE = (
	"class Servico:\n"
	"\tdef revisar(self, text, callback):\n"
	"\t\treturn None\n"
)

_SERVICO_FIEL_AO_CONTRATO = (
	"class Servico:\n"
	"\tdef revisar(self, text, model, api_key, on_done, on_error):\n"
	"\t\treturn None\n"
)


class TestSmokeDosComandosPegaAcostura:
	"""O defeito e de COSTURA: cada arquivo esta certo sozinho."""

	def test_assinatura_divergente_reprova_mesmo_engolida(self):
		"""O caso exato do AssistenteEscrita, incluindo o except que o
		escondeu. Sem o testemunho por settrace este teste passaria."""
		resultado = _rodar({
			"globalPlugins/MeuAddon/__init__.py": _plugin(_CHAMADA_ENGOLIDA),
			"globalPlugins/MeuAddon/servico.py": _SERVICO_DIVERGENTE,
		})

		assert resultado.success is False, (
			"addon com chamador e definicao discordando foi aprovado -- "
			f"stdout={resultado.stdout!r}"
		)
		assert "SMOKE_FALHOU" in resultado.stdout
		# A mensagem tem que servir de fix_instruction sozinha.
		assert "unexpected keyword argument" in resultado.stdout
		assert "model" in resultado.stdout

	def test_cada_arquivo_sozinho_e_valido(self):
		"""Prova que o defeito e da costura e nao de um dos lados: os dois
		arquivos passam em tudo que olha um arquivo por vez."""
		sandbox = CodeSandbox(timeout_sec=25)
		for nome, codigo in (
			("__init__.py", _plugin(_CHAMADA_ENGOLIDA)),
			("servico.py", _SERVICO_DIVERGENTE),
		):
			assert sandbox.syntax_check(codigo).success is True, nome


class TestSmokeDosComandosNaoInventaDefeito:
	"""Falso positivo aqui custa retry infinito -- cada caso e um padrao
	que TODO addon correto tem."""

	def test_assinatura_fiel_ao_contrato_passa(self):
		resultado = _rodar({
			"globalPlugins/MeuAddon/__init__.py": _plugin(_CHAMADA_ENGOLIDA),
			"globalPlugins/MeuAddon/servico.py": _SERVICO_FIEL_AO_CONTRATO,
		})

		assert resultado.success is True, (
			f"addon correto reprovado: {resultado.stdout!r} {resultado.stderr!r}"
		)

	def test_import_lazy_da_nvda022_nao_e_defeito(self):
		"""`try: import openai / except ImportError` e o padrao EXIGIDO pela
		NVDA-022. Se o smoke contasse ImportError, todo addon correto que
		depende de pacote pip seria reprovado."""
		corpo = (
			"\t\ttry:\n"
			"\t\t\timport pacote_que_nao_existe_em_lugar_nenhum\n"
			"\t\texcept ImportError:\n"
			"\t\t\tui.message(\"funcionalidade indisponivel\")\n"
		)
		resultado = _rodar({
			"globalPlugins/MeuAddon/__init__.py": _plugin(corpo),
			"globalPlugins/MeuAddon/servico.py": _SERVICO_FIEL_AO_CONTRATO,
		})

		assert resultado.success is True, (
			f"import lazy tratado como defeito: {resultado.stdout!r}"
		)

	def test_addon_sem_comando_nenhum_passa(self):
		"""Nem todo addon tem @script (ex: so AppModule ou so painel)."""
		resultado = _rodar({
			"globalPlugins/MeuAddon/__init__.py": (
				"import globalPluginHandler\n\n"
				"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
				"\tpass\n"
			),
		})

		assert resultado.success is True


class TestSmokeExecutaDeVerdade:
	"""Um smoke que nao chega a rodar o corpo do script e pior que nenhum:
	da o verde sem ter olhado."""

	def test_guard_de_modo_seguro_nao_curto_circuita_o_smoke(self):
		"""Sob o stub permissivo, `globalVars.appArgs.secure` e verdadeiro.
		Se o smoke nao desligasse isso, TODO script guardado pela NVDA-062
		(que e o correto) retornaria na primeira linha e o defeito depois
		do guard nunca seria executado. O _plugin() usado aqui tem o guard.
		"""
		resultado = _rodar({
			"globalPlugins/MeuAddon/__init__.py": _plugin(_CHAMADA_ENGOLIDA),
			"globalPlugins/MeuAddon/servico.py": _SERVICO_DIVERGENTE,
		})

		assert resultado.success is False, (
			"o guard de modo seguro engoliu o smoke -- o corpo do script "
			"nunca executou"
		)

	def test_defeito_em_thread_de_background_e_testemunhado(self):
		"""NVDA-002 obriga trabalho pesado fora da thread da UI. Se o
		testemunho nao valesse para threads, o defeito mais comum de addon
		que chama API externa passaria batido."""
		corpo = (
			"\t\timport threading\n"
			"\t\tdef _worker():\n"
			"\t\t\tservico.Servico().revisar(text=\"oi\", model=\"m\")\n"
			"\t\tt = threading.Thread(target=_worker, daemon=True)\n"
			"\t\tt.start()\n"
			"\t\tt.join(timeout=2)\n"
		)
		resultado = _rodar({
			"globalPlugins/MeuAddon/__init__.py": _plugin(corpo),
			"globalPlugins/MeuAddon/servico.py": _SERVICO_DIVERGENTE,
		})

		assert resultado.success is False, (
			"defeito dentro de threading.Thread nao foi testemunhado"
		)


@pytest.mark.parametrize("cenario", ["api_401", "timeout", "missing_file"])
def test_smoke_nao_roda_sob_falha_injetada(cenario):
	"""A resiliencia mede o CARREGAMENTO sob ambiente hostil, com orcamento
	de 3s. Rodar o smoke ali misturaria dois sinais e gastaria o tempo."""
	resultado = CodeSandbox(timeout_sec=25).validate_addon_execution(
		{
			"globalPlugins/MeuAddon/__init__.py": _plugin(_CHAMADA_ENGOLIDA),
			"globalPlugins/MeuAddon/servico.py": _SERVICO_DIVERGENTE,
		},
		fault_scenario=cenario,
	)

	assert "SMOKE_FALHOU" not in resultado.stdout


class TestPortaoFinalSobreOPacote:
	"""`validate_final_package()` e o ultimo portao antes da entrega -- o
	que a GUI ja aplicava e o E2E nunca rodava. Aqui ele e exercitado sobre
	um .nvda-addon de verdade (ZIP), nao sobre a pasta intermediaria."""

	def _empacotar(self, tmp_path, arquivos: dict[str, str]) -> str:
		import zipfile

		caminho = str(tmp_path / "MeuAddon.nvda-addon")
		with zipfile.ZipFile(caminho, "w") as zf:
			zf.writestr(
				"manifest.ini",
				"name = MeuAddon\nsummary = X\ndescription = X\nauthor = A <a@b.c>\n"
				"url = https://example.com\nversion = 1.0.0\ndocFileName = userGuide.html\n"
				"minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.2.0\n",
			)
			zf.writestr("doc/en/userGuide.html", "<html><body>guia</body></html>")
			for nome, conteudo in arquivos.items():
				zf.writestr("globalPlugins/MeuAddon/" + nome, conteudo)
		return caminho

	def test_pacote_com_costura_quebrada_e_barrado(self, tmp_path):
		pacote = self._empacotar(tmp_path, {
			"__init__.py": _plugin(_CHAMADA_ENGOLIDA),
			"servico.py": _SERVICO_DIVERGENTE,
		})

		resultado = CodeSandbox(timeout_sec=30).validate_final_package(pacote)

		assert resultado.success is False, (
			"pacote com chamador e definicao discordando seria entregue ao usuario"
		)
		evidencia = (resultado.error or "") + (resultado.stdout or "")
		# Barrado pela NVDA-063 (estatica) OU pelo smoke (execucao): as duas
		# defesas cobrem o mesmo defeito de proposito, e basta uma barrar.
		assert "NVDA-063" in evidencia or "SMOKE_FALHOU" in evidencia, evidencia[:400]

	def test_pacote_correto_passa(self, tmp_path):
		pacote = self._empacotar(tmp_path, {
			"__init__.py": _plugin(_CHAMADA_ENGOLIDA),
			"servico.py": _SERVICO_FIEL_AO_CONTRATO,
		})

		resultado = CodeSandbox(timeout_sec=30).validate_final_package(pacote)

		assert resultado.success is True, (
			f"pacote correto barrado: {resultado.error!r} {resultado.stdout!r}"
		)


class TestSmokePorStepNaoAcusaArquivoQueAindaNaoExiste:
	"""Costura com o orchestrator: durante `code_generation`, os arquivos que
	OUTROS steps ainda vao gerar entram como `_MODULO_PENDENTE`.

	Se o smoke acusasse contra esses placeholders, TODO code_generation de
	addon multi-arquivo reprovaria 3x e queimaria o orcamento -- o defeito
	seria pior que o que ele conserta. Este teste usa o placeholder REAL do
	orchestrator, nao uma copia: se ele mudar, este teste tem que saber.
	"""

	def test_placeholder_de_step_futuro_nao_vira_defeito(self):
		from nvdastudio.core.orchestrator import _MODULO_PENDENTE

		resultado = _rodar({
			"globalPlugins/MeuAddon/__init__.py": _plugin(_CHAMADA_ENGOLIDA),
			# servico.py ainda nao foi gerado: e o placeholder que o
			# orchestrator injeta para o import resolver.
			"globalPlugins/MeuAddon/servico.py": _MODULO_PENDENTE,
		})

		assert resultado.success is True, (
			"o smoke acusou contra um arquivo que outro step ainda vai gerar -- "
			f"todo addon multi-arquivo reprovaria: {resultado.stdout!r}"
		)
