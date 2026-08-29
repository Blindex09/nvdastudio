import os
import re

import pytest

# ---------------------------------------------------------------------------
# Chave e skip
# ---------------------------------------------------------------------------

HAS_OLLAMA = os.environ.get("OLLAMA_API_KEY", "").strip()
# 2026-08-17: critic.py 3.19.0 -- o Critic agora SEMPRE usa OpenCode Go
# (prompt caching), independente do provider ativo. Sem essa chave, TODA
# avaliacao de step falha com "Chave API para opencode_go nao configurada"
# -- achado real ao vivo (madrugada 2026-08-17/18, rodada 1 do loop): os
# 2 casos deste arquivo rodaram e "passaram" no pytest (test_e36 nao exige
# success=True) mas o pipeline inteiro falhou em segundos, 0 tokens gastos,
# nenhum sinal real coletado -- so desperdicou tempo/custo do Ollama sem
# testar nada. Adicionado ao skip guard pra nao rodar (e enganar) sem as
# 2 chaves.
HAS_OPENCODE_GO = os.environ.get("OPENCODE_GO_API_KEY", "").strip()
skip_unless_ollama = pytest.mark.skipif(
	not HAS_OLLAMA or not HAS_OPENCODE_GO,
	reason=("Ollama Cloud token nao disponivel" if not HAS_OLLAMA else "OpenCode Go token nao disponivel (necessario pro Critic, ver critic.py 3.19.0)"),
)

# ---------------------------------------------------------------------------
# Output dir
# ---------------------------------------------------------------------------

_E2E_OUTPUT_DIR = os.path.join(
	os.path.expanduser("~"), "Documents", "NVDAStudio", "addons_gerados", "e2e_qualidade_codigo"
)
_REPORT_DIR = os.path.join(os.path.dirname(__file__), "relatorios")


# ---------------------------------------------------------------------------
# Motor E2E (reutilizado do fluxo_completo)
# ---------------------------------------------------------------------------

def _executar_fluxo_qualidade(
	addon_name: str,
	query: str,
	output_dir: str = _E2E_OUTPUT_DIR,
):
	"""
	Executa o fluxo inteiro e retorna FluxoReport.
	Importa as classes do fluxo_completo para reutilizar a logica.
	Regra 9: codigo gerado nunca executado.
	"""
	# Importa FluxoReport e motor do modulo de referencia
	import sys
	e2e_dir = os.path.dirname(__file__)
	if e2e_dir not in sys.path:
		sys.path.insert(0, e2e_dir)

	from test_fluxo_completo_nvda import _executar_fluxo_completo
	return _executar_fluxo_completo(addon_name=addon_name, query=query, output_dir=output_dir)


# ---------------------------------------------------------------------------
# Helpers de validacao (Regra 9: apenas leitura de string, sem exec)
# ---------------------------------------------------------------------------

def _ler_init_py(addon_folder: str) -> str:
	"""Retorna o conteudo do __init__.py principal (Regra 9: apenas string)."""
	gp = os.path.join(addon_folder, "globalPlugins")
	if not os.path.isdir(gp):
		return ""
	for subdir in os.listdir(gp):
		init = os.path.join(gp, subdir, "__init__.py")
		if os.path.isfile(init):
			with open(init, encoding="utf-8", errors="replace") as fh:
				return fh.read()
	return ""


# ---------------------------------------------------------------------------
# FIXTURE
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def fluxo_report():
	"""
	Executa o fluxo completo UMA VEZ para toda a classe.
	Todos os testes da classe consomem o mesmo FluxoReport.
	Economiza tokens e tempo de API.
	"""
	return _executar_fluxo_qualidade(
		addon_name="QualidadeCodigo_e2e",
		query=(
			"Crie um GlobalPlugin NVDA chamado 'MonitorRecursos' que monitora uso de CPU "
			"e memoria RAM, anunciando ao pressionar NVDA+shift+M. "
			"O plugin deve: "
			"1) Usar logHandler.log para registrar eventos — nunca print(); "
			"2) Implementar GlobalPlugin com @script decorator e type hints; "
			"3) Usar wx.CallAfter() ao atualizar UI a partir de thread worker; "
			"4) Chamar addonHandler.initTranslation() no topo; "
			"5) Implementar terminate() que chama super().terminate() e cancela threads; "
			"6) Registrar extensionPoints e desregistrar em terminate(); "
			"7) Usar try/except Exception (nunca bare except:); "
			"8) Ter manifest.ini com version=1.0.0, minimumNVDAVersion=2026.1.1, "
			"lastTestedNVDAVersion=2026.1.1; "
			"9) Salvar arquivos com LF line endings (Unix), nao CRLF."
		),
	)


# ---------------------------------------------------------------------------
# Classe de testes: regras de qualidade de codigo
# ---------------------------------------------------------------------------

@skip_unless_ollama
class TestRegrasQualidadeCodigo:
	"""
	5.1.0: skip_unless_ollama era definido neste arquivo mas nunca aplicado
	-- achado real de auditoria 2026-08-25. fluxo_report (fixture de modulo,
	linha ~82) rodava o pipeline completo (LLM real) incondicionalmente,
	mesmo sem OLLAMA_API_KEY/OPENCODE_GO_API_KEY configuradas: em vez de
	pular com skip limpo, o teste ficava pendurado indefinidamente na
	chamada de rede sem timeout, travando a suite inteira. Decorar a CLASSE
	(nao so metodos individuais) garante que pytest pule ANTES de resolver
	fluxo_report -- mesmo padrao ja usado em test_e35/e36/e37/e38.

	Valida 9 regras de qualidade de codigo aplicadas ao output do pipeline NVDA.

	Todos os testes compartilham o mesmo FluxoReport (fixture de modulo).
	Regra 9: nenhum codigo e executado em nenhuma validacao — apenas analise textual/AST.
	"""

	# ------------------------------------------------------------------
	# NVDA-030: logHandler.log obrigatorio (nao print)
	# ------------------------------------------------------------------

	def test_nvda030_sem_print_usa_loghandler(self, fluxo_report):
		"""
		NVDA-030: codigo deve usar logHandler.log para logging, nunca print().

		print() nao aparece no log do NVDA e nao e acessivel em producao.
		Todo log de debug/info/warning deve passar por logHandler.log ou log.debug/info/warning.

		Assert leniente: se tem blocos de codigo substanciais, nao pode usar print().
		Se usa logging, deve ser via logHandler (nao print).
		"""
		if not fluxo_report.success or not fluxo_report.has_init_py:
			pytest.skip("Pipeline nao concluiu ou __init__.py nao disponivel")

		code = _ler_init_py(fluxo_report.addon_folder)

		# Detecta uso de print() (exceto em strings e comentarios)
		linhas_com_print = []
		for i, linha in enumerate(code.splitlines(), 1):
			stripped = linha.strip()
			if stripped.startswith("#"):
				continue
			# Regex: print( nao precedido de _ (nao e _print)
			if re.search(r'(?<!\w)print\s*\(', linha):
				linhas_com_print.append(f"Linha {i}: {stripped[:80]}")

		assert not linhas_com_print, (
			f"NVDA-030: print() encontrado no codigo — use logHandler.log em vez disso.\n"
			f"Ocorrencias: {linhas_com_print}\n"
			"Ref: nvda_developer_guide_2025.html — logHandler.log para todos os logs."
		)

	def test_nvda030_loghandler_presente_se_tem_logging(self, fluxo_report):
		"""
		NVDA-030 (complementar): se o codigo tem blocos de logging, deve importar logHandler.

		Verifica que 'from logHandler import log' ou 'logHandler.log' esta presente
		quando o plugin tem mais de 20 linhas de codigo Python substancial.
		"""
		if not fluxo_report.success or not fluxo_report.has_init_py:
			pytest.skip("Pipeline nao concluiu ou __init__.py nao disponivel")

		code = _ler_init_py(fluxo_report.addon_folder)

		# Conta linhas substanciais (excluindo comentarios e linhas vazias)
		linhas_substanciais = [
			line for line in code.splitlines()
			if line.strip() and not line.strip().startswith("#")
		]

		# Apenas valida se plugin tem tamanho substancial
		if len(linhas_substanciais) < 20:
			pytest.skip("Plugin muito simples — regra de logging nao aplicavel")

		tem_loghandler = (
			"from logHandler import log" in code
			or "logHandler.log" in code
			or "import logHandler" in code
		)

		# Assert leniente: ao menos o import esta presente
		assert tem_loghandler, (
			"NVDA-030: plugin substancial sem logHandler importado.\n"
			"Use 'from logHandler import log' e log.debug()/log.info()/log.warning().\n"
			"Ref: nvda_developer_guide_2025.html — logHandler e o sistema de log do NVDA."
		)

	# ------------------------------------------------------------------
	# NVDA-034: UTF-8 + LF line endings
	# ------------------------------------------------------------------

	def test_nvda034_sem_crlf_line_endings(self, fluxo_report):
		"""
		NVDA-034: codigo gerado nao pode ter line endings CRLF (\\r\\n).

		NVDA e seus addons usam LF (Unix). CRLF causa IndentationError em alguns
		interpretadores Python e e rejeitado pelo repositorio oficial de addons.

		Assert: '\\r\\n' nao esta presente no codigo gerado.
		"""
		if not fluxo_report.success or not fluxo_report.has_init_py:
			pytest.skip("Pipeline nao concluiu ou __init__.py nao disponivel")

		code = _ler_init_py(fluxo_report.addon_folder)

		assert "\r\n" not in code, (
			"NVDA-034: codigo gerado usa CRLF (\\r\\n) como line ending.\n"
			"O NVDA e seus addons devem usar LF (\\n) — Unix line endings.\n"
			"CRLF pode causar IndentationError e e rejeitado pelo repositorio oficial."
		)

	# ------------------------------------------------------------------
	# NVDA-006: Sem monkey-patching de modulos NVDA core
	# ------------------------------------------------------------------

	def test_nvda006_sem_monkey_patching_core(self, fluxo_report):
		"""
		NVDA-006: nenhum modulo core do NVDA pode ser monkey-patched.

		Padroes proibidos:
		  - speech.speak = ...
		  - braille.handler = ...
		  - inputCore.manager = ...

		Monkey-patching de modulos core causa comportamento indefinido, conflitos
		entre addons e pode travar o NVDA completamente.

		Assert: nenhum padrao de monkey-patch de modulo core encontrado no nivel de modulo.
		"""
		if not fluxo_report.success or not fluxo_report.has_init_py:
			pytest.skip("Pipeline nao concluiu ou __init__.py nao disponivel")

		code = _ler_init_py(fluxo_report.addon_folder)

		# Padroes proibidos: atribuicao direta a atributos de modulos core
		_MONKEY_PATCH_PATTERNS = [
			r"speech\.\w+\s*=\s*",
			r"braille\.handler\s*=\s*",
			r"inputCore\.manager\s*=\s*",
			r"globalVars\.\w+\s*=\s*",
			r"api\.\w+\s*=\s*",
		]

		violacoes: list[str] = []
		for i, linha in enumerate(code.splitlines(), 1):
			stripped = linha.strip()
			if stripped.startswith("#"):
				continue
			for padrao in _MONKEY_PATCH_PATTERNS:
				if re.search(padrao, linha):
					violacoes.append(f"Linha {i}: {stripped[:80]}")
					break

		assert not violacoes, (
			f"NVDA-006: monkey-patching de modulos core detectado:\n"
			f"{chr(10).join(violacoes)}\n"
			"Monkey-patching de modulos core e proibido — causa conflitos entre addons "
			"e comportamento indefinido no NVDA."
		)

	# ------------------------------------------------------------------
	# NVDA-010: wx.CallAfter() para UI de thread worker
	# ------------------------------------------------------------------

	def test_nvda010_wxcallafter_se_tem_thread(self, fluxo_report):
		"""
		NVDA-010: se o plugin usa threads ou timers, toda atualizacao de UI
		deve usar wx.CallAfter().

		wx.CallAfter() garante que a chamada seja executada na thread principal
		do wx, evitando crashes e comportamento indefinido.

		Assert condicional: se tem threading.Thread/wx.Timer/queue.Queue,
		deve ter wx.CallAfter( presente no codigo.
		"""
		if not fluxo_report.success or not fluxo_report.has_init_py:
			pytest.skip("Pipeline nao concluiu ou __init__.py nao disponivel")

		code = _ler_init_py(fluxo_report.addon_folder)

		# Detecta uso de concorrencia
		tem_thread = bool(re.search(r"threading\.Thread", code))
		tem_timer = bool(re.search(r"wx\.Timer", code))
		tem_queue = bool(re.search(r"queue\.Queue", code))

		usa_concorrencia = tem_thread or tem_timer or tem_queue

		if not usa_concorrencia:
			pytest.skip(
				"Plugin nao usa threading/timer/queue — NVDA-010 nao aplicavel"
			)

		tem_callafter = "wx.CallAfter(" in code

		assert tem_callafter, (
			"NVDA-010: plugin usa thread/timer mas nao usa wx.CallAfter() para UI.\n"
			"Toda atualizacao de UI a partir de thread worker DEVE usar wx.CallAfter().\n"
			"Sem wx.CallAfter(), chamadas de UI em threads causam crashes no NVDA.\n"
			"Ref: nvda_developer_guide_2025.html — Thread Safety."
		)

	# ------------------------------------------------------------------
	# NVDA-012: Sem except bare (sem tipo de excecao)
	# ------------------------------------------------------------------

	def test_nvda012_sem_bare_except(self, fluxo_report):
		"""
		NVDA-012: o codigo nao pode usar 'except:' sem especificar o tipo de excecao.

		Bare except captura ate SystemExit e KeyboardInterrupt, impedindo o NVDA
		de encerrar corretamente. Sempre usar 'except Exception:' ou tipo especifico.

		Assert: nenhuma ocorrencia de except bare (regex: r'except\\s*:').
		"""
		if not fluxo_report.success or not fluxo_report.has_init_py:
			pytest.skip("Pipeline nao concluiu ou __init__.py nao disponivel")

		code = _ler_init_py(fluxo_report.addon_folder)

		violacoes: list[str] = []
		for i, linha in enumerate(code.splitlines(), 1):
			stripped = linha.strip()
			if stripped.startswith("#"):
				continue
			# except: sem tipo — bare except
			if re.search(r"\bexcept\s*:", linha):
				violacoes.append(f"Linha {i}: {stripped[:80]}")

		assert not violacoes, (
			f"NVDA-012: bare except encontrado — especifique sempre o tipo de excecao:\n"
			f"{chr(10).join(violacoes)}\n"
			"Use 'except Exception:' ou 'except (TypeError, ValueError):' em vez de 'except:'.\n"
			"Bare except captura SystemExit e KeyboardInterrupt, impedindo o NVDA de encerrar."
		)

	# ------------------------------------------------------------------
	# NVDA-020: Imports do modulo ORIGINAL, nao re-exports
	# ------------------------------------------------------------------

	def test_nvda020_imports_de_modulo_original(self, fluxo_report):
		"""
		NVDA-020: imports devem vir do modulo ORIGINAL, nao de re-exports.

		Padroes proibidos (re-exports conhecidos):
		  - 'from NVDAObjects import IAccessible'
		    -> correto: 'from NVDAObjects.IAccessible import IAccessible'
		  - 'from NVDAObjects import UIA'
		    -> correto: 'from NVDAObjects.UIA import UIA'

		Re-exports podem ser removidos em futuras versoes do NVDA sem aviso.

		Assert condicional: se usa IAccessible/UIA, o import e do modulo original.
		"""
		if not fluxo_report.success or not fluxo_report.has_init_py:
			pytest.skip("Pipeline nao concluiu ou __init__.py nao disponivel")

		code = _ler_init_py(fluxo_report.addon_folder)

		# Padroes de re-export proibidos
		_REEXPORT_PATTERNS = [
			(
				r"from\s+NVDAObjects\s+import\s+IAccessible\b",
				"'from NVDAObjects import IAccessible' — use 'from NVDAObjects.IAccessible import IAccessible'",
			),
			(
				r"from\s+NVDAObjects\s+import\s+UIA\b",
				"'from NVDAObjects import UIA' — use 'from NVDAObjects.UIA import UIA'",
			),
		]

		# Verifica se usa IAccessible ou UIA no codigo
		usa_iaccessible = "IAccessible" in code
		usa_uia = "UIA" in code

		if not usa_iaccessible and not usa_uia:
			pytest.skip("Plugin nao usa IAccessible nem UIA — NVDA-020 nao aplicavel")

		violacoes: list[str] = []
		for padrao, descricao in _REEXPORT_PATTERNS:
			if re.search(padrao, code, re.MULTILINE):
				violacoes.append(descricao)

		assert not violacoes, (
			f"NVDA-020: imports via re-exports detectados:\n"
			f"{chr(10).join(violacoes)}\n"
			"Use sempre o modulo original — re-exports podem ser removidos sem aviso."
		)

	# ------------------------------------------------------------------
	# NVDA-022: Type hints em funcoes publicas
	# ------------------------------------------------------------------

	def test_nvda022_type_hints_em_funcoes_publicas(self, fluxo_report):
		"""
		NVDA-022: funcoes publicas script_* e event_* devem ter type hints de retorno.

		Type hints melhoram legibilidade, permitem ferramentas de analise estatica
		e sao exigidos pelo projeto conforme regras universais de qualidade.

		Assert leniente: ao menos metade das funcoes publicas tem type hint de retorno
		OU o codigo tem pelo menos uma '-> ' annotation.
		"""
		if not fluxo_report.success or not fluxo_report.has_init_py:
			pytest.skip("Pipeline nao concluiu ou __init__.py nao disponivel")

		code = _ler_init_py(fluxo_report.addon_folder)

		# Encontra todas as funcoes script_* e event_*
		funcoes_publicas = re.findall(
			r"def\s+(script_\w+|event_\w+)\s*\([^)]*\)",
			code,
		)

		if not funcoes_publicas:
			pytest.skip("Plugin nao tem funcoes script_* ou event_* — NVDA-022 nao aplicavel")

		# Verifica se tem pelo menos uma annotation de retorno
		tem_type_hint = "->" in code

		# Conta funcoes com type hint de retorno (padrao mais preciso)
		funcoes_com_hint = re.findall(
			r"def\s+(?:script_|event_)\w+\s*\([^)]*\)\s*->",
			code,
		)

		total = len(funcoes_publicas)
		com_hint = len(funcoes_com_hint)

		# Assert leniente: metade com hint OU ao menos uma annotation presente
		assert tem_type_hint or (total > 0 and com_hint >= total // 2), (
			f"NVDA-022: type hints insuficientes em funcoes publicas.\n"
			f"Funcoes publicas encontradas: {funcoes_publicas}\n"
			f"Com type hint de retorno: {com_hint}/{total}\n"
			"Adicione '-> None' ou tipo de retorno em funcoes script_* e event_*.\n"
			"Ref: regras universais de qualidade — type hints obrigatorios em funcoes publicas."
		)

	# ------------------------------------------------------------------
	# NVDA-023: gui.message.MessageDialog (nao wx.MessageDialog)
	# ------------------------------------------------------------------

	def test_nvda023_message_dialog_de_gui_message(self, fluxo_report):
		"""
		NVDA-023: se o plugin usa MessageDialog, deve vir de gui.message, nao wx.

		wx.MessageDialog nao e acessivel para screen readers.
		gui.message.MessageDialog e a versao acessivel e compativel com NVDA.

		Assert condicional: se tem MessageDialog -> nao e wx.MessageDialog.
		"""
		if not fluxo_report.success or not fluxo_report.has_init_py:
			pytest.skip("Pipeline nao concluiu ou __init__.py nao disponivel")

		code = _ler_init_py(fluxo_report.addon_folder)

		# Verifica se usa MessageDialog
		if "MessageDialog" not in code:
			pytest.skip("Plugin nao usa MessageDialog — NVDA-023 nao aplicavel")

		# Verifica se usa wx.MessageDialog (proibido)
		violacoes_wx = re.findall(r"wx\.MessageDialog\s*\(", code)

		assert not violacoes_wx, (
			f"NVDA-023: wx.MessageDialog encontrado — {len(violacoes_wx)} ocorrencia(s).\n"
			"wx.MessageDialog nao e acessivel para screen readers.\n"
			"Use 'gui.message.MessageDialog' que e a versao acessivel e compativel com NVDA.\n"
			"Ref: nvda_developer_guide_2025.html — Accessible Dialog Patterns."
		)

	# ------------------------------------------------------------------
	# NVDA-036: unregister() para todo register() em extensionPoints
	# ------------------------------------------------------------------

	def test_nvda036_unregister_para_cada_register(self, fluxo_report):
		"""
		NVDA-036: cada .register() em extensionPoints deve ter um .unregister() correspondente,
		tipicamente no metodo terminate().

		Sem unregister(), os handlers continuam ativos mesmo apos desinstalar o addon,
		causando memory leaks e comportamento indefinido.

		Assert condicional: se tem .register( -> tem .unregister(.
		"""
		if not fluxo_report.success or not fluxo_report.has_init_py:
			pytest.skip("Pipeline nao concluiu ou __init__.py nao disponivel")

		code = _ler_init_py(fluxo_report.addon_folder)

		# Verifica se usa .register(
		registros = re.findall(r"\.register\s*\(", code)

		if not registros:
			pytest.skip("Plugin nao usa .register() — NVDA-036 nao aplicavel")

		# Verifica se tem .unregister(
		tem_unregister = bool(re.search(r"\.unregister\s*\(", code))

		assert tem_unregister, (
			f"NVDA-036: {len(registros)} chamada(s) a .register() sem .unregister() correspondente.\n"
			"Handlers registrados em extensionPoints devem ser desregistrados em terminate().\n"
			"Sem unregister(), handlers ficam ativos apos desinstalar o addon — memory leak.\n"
			"Ref: nvda_developer_guide_2025.html — Extension Points."
		)
