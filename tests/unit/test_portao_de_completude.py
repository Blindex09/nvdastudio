"""Regressao: o addon carregava, passava em tudo, e era uma casca.

Rodada de 2026-09-03 17:26, a primeira inteira pela Factory. O pedido tinha
tres partes -- dois atalhos, um servico OpenAI e uma tela de configuracoes --
e o pacote entregue tinha UM arquivo Python:

    manifest.ini
    doc/en/userGuide.html
    doc/pt_BR/userGuide.html
    globalPlugins/AssistenteEscrita/__init__.py

O `__init__.py` importava `settings_panel` e `openai_service`, ausentes, com
try/except tolerante -- que e a pratica CORRETA da NVDA-022. Resultado: o
addon carregava, registrava os dois atalhos, e ao apertar NVDA+shift+G falava
"Chave de API nao configurada. Abra as configuracoes do Assistente de
Escrita", apontando para uma tela que nao existia.

Nenhum portao pegou, e cada um por um bom motivo: o ponto de entrada existia,
os gestos declarados existiam, a execucao real passou (o addon carrega e os
comandos rodam), e a NVDA-063 nao acusou porque import ausente vira
ImportError tratado, nao discordancia de assinatura.

Um addon que degrada com elegancia e, pela definicao de todos eles, um addon
que funciona. Faltava perguntar se ele esta COMPLETO.
"""

from nvdastudio.core.orchestrator import Orchestrator

_faltando = Orchestrator._missing_declared_files


class TestPegaOAddonIncompleto:

	def test_caso_real_um_de_tres_modulos(self):
		declarados = [
			"manifest.ini",
			"globalPlugins/AssistenteEscrita/__init__.py",
			"globalPlugins/AssistenteEscrita/settings_panel.py",
			"globalPlugins/AssistenteEscrita/openai_service.py",
			"doc/en/userGuide.html",
		]
		entregues = {"globalPlugins/AssistenteEscrita/__init__.py"}

		erro = _faltando(declarados, entregues)

		assert erro, "a casca seria entregue como addon pronto"
		assert "settings_panel.py" in erro
		assert "openai_service.py" in erro
		# A mensagem tem que explicar POR QUE nao deu erro visivel -- senao o
		# usuario cego nao entende o que aconteceu com o addon dele.
		assert "try/except" in erro
		assert "sem erro visível" in erro

	def test_mensagem_nao_acusa_o_que_chegou(self):
		declarados = [
			"globalPlugins/X/__init__.py",
			"globalPlugins/X/servico.py",
		]

		erro = _faltando(declarados, {"globalPlugins/X/__init__.py"})

		assert "servico.py" in erro
		assert "__init__.py" not in erro


class TestNaoInventaIncompletude:
	"""Falso positivo aqui recusa entrega boa -- o pior desfecho possivel."""

	def test_tudo_entregue_passa(self):
		declarados = ["globalPlugins/X/__init__.py", "globalPlugins/X/servico.py"]

		assert _faltando(declarados, set(declarados)) == ""

	def test_plano_sem_arquivos_declarados_nao_verifica_nada(self):
		"""Sem declaracao nao ha contrato a cobrar -- e inventar um seria pior
		que nao ter."""
		assert _faltando([], {"globalPlugins/X/__init__.py"}) == ""
		assert _faltando(None, {"globalPlugins/X/__init__.py"}) == ""

	def test_so_olha_python(self):
		"""manifest.ini, doc/ e recursos tem portoes proprios; cobrar aqui
		seria cobrar duas vezes pela mesma coisa."""
		declarados = [
			"manifest.ini", "doc/en/userGuide.html",
			"locale/pt_BR/gestures.ini", "globalPlugins/X/__init__.py",
		]

		assert _faltando(declarados, {"globalPlugins/X/__init__.py"}) == ""

	def test_caminho_divergente_com_mesmo_nome_nao_e_falta(self):
		"""Arquivo no lugar errado e problema de COLOCACAO, e o addon_builder
		ja reposiciona. Reprovar aqui cobraria duas vezes."""
		declarados = ["globalPlugins/X/servico.py"]

		assert _faltando(declarados, {"servico.py"}) == ""
		assert _faltando(declarados, {"globalPlugins/Outro/servico.py"}) == ""

	def test_barra_invertida_do_windows_nao_vira_arquivo_faltando(self):
		declarados = ["globalPlugins\\X\\servico.py"]

		assert _faltando(declarados, {"globalPlugins/X/servico.py"}) == ""


def test_portao_roda_depois_do_ponto_de_entrada_e_antes_do_veredito():
	"""Fitness function de ORDEM. Antes do ponto de entrada, a mensagem sobre
	arquivo faltando esconderia a causa mais grave (addon que nem carrega);
	depois do veredito, nao adiantaria nada."""
	import ast
	import inspect

	fonte = inspect.getsource(Orchestrator._validate_minimum_addon_artifacts)
	arvore = ast.parse(inspect.cleandoc(fonte).replace("@staticmethod\n", "", 1))
	# Ordenado por LINHA: ast.walk e busca em largura, nao ordem de codigo --
	# usar a ordem dele aqui compararia posicoes que nao existem no fonte.
	chamadas = [
		no.func.attr
		for no in sorted(
			(n for n in ast.walk(arvore)
			 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)),
			key=lambda n: n.lineno,
		)
	]

	assert "_missing_loadable_entry_point" in chamadas
	assert "_missing_declared_files" in chamadas
	assert chamadas.index("_missing_loadable_entry_point") < chamadas.index(
		"_missing_declared_files"
	), "arquivo faltando esconderia um addon que nem carrega"
