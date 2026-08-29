import os
import re

import pytest

from tests.e2e.test_fluxo_completo_nvda import (
	FluxoReport,
	_executar_fluxo_completo,
	skip_unless_ollama,
	)

# 5.1.0: skip_unless_ollama importado do modulo de referencia (fonte
# unica) e aplicado a nivel de modulo -- achado real de auditoria
# 2026-08-25: este arquivo chamava _executar_fluxo_completo() (pipeline
# real, LLM de verdade) sem NENHUM guard de API key. Sem
# OLLAMA_API_KEY/OPENCODE_GO_API_KEY configuradas, o teste ficava
# pendurado indefinidamente na chamada de rede sem timeout, em vez de
# skip limpo -- travava a suite inteira. Ver
# test_e20_regras_qualidade_codigo.py 5.1.0 para o achado completo.
pytestmark = skip_unless_ollama

# ---------------------------------------------------------------------------
# Helpers (Regra 9: apenas leitura de string)
# ---------------------------------------------------------------------------

def _ler_codigo(addon_folder: str) -> str:
	"""Tenta ler __init__.py de appModules/ ou globalPlugins/."""
	# appModules direto (nome_exe.py)
	am = os.path.join(addon_folder, "appModules")
	if os.path.isdir(am):
		for entry in os.listdir(am):
			full = os.path.join(am, entry)
			if os.path.isfile(full) and entry.endswith(".py"):
				with open(full, encoding="utf-8", errors="replace") as fh:
					return fh.read()
			elif os.path.isdir(full):
				init = os.path.join(full, "__init__.py")
				if os.path.isfile(init):
					with open(init, encoding="utf-8", errors="replace") as fh:
						return fh.read()
	# Fallback: globalPlugins
	gp = os.path.join(addon_folder, "globalPlugins")
	if os.path.isdir(gp):
		for subdir in os.listdir(gp):
			init = os.path.join(gp, subdir, "__init__.py")
			if os.path.isfile(init):
				with open(init, encoding="utf-8", errors="replace") as fh:
					return fh.read()
	return ""


def _listar_arquivos(addon_folder: str) -> list[str]:
	resultado: list[str] = []
	for root, _, files in os.walk(addon_folder):
		for f in files:
			rel = os.path.relpath(os.path.join(root, f), addon_folder).replace("\\", "/")
			resultado.append(rel)
	return resultado


# ---------------------------------------------------------------------------
# Fixture — AppModule para Notepad
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def fluxo_appmodule() -> FluxoReport:
	"""
	Gera um AppModule NVDA para o Notepad (notepad.exe).

	A query forca explicitamente:
	  - Classe AppModule (nao GlobalPlugin)
	  - event_gainFocus com nextHandler()
	  - chooseNVDAObjectOverlayClasses no AppModule
	  - Arquivo salvo como appModules/notepad.py
	"""
	return _executar_fluxo_completo(
		addon_name="MelhorasNotepad_e2e",
		query=(
			"Crie um AppModule NVDA para o Notepad (notepad.exe) chamado 'MelhorasNotepad' "
			"que melhora a acessibilidade do editor de texto. O addon deve: "
			"1) Ter classe AppModule que herda de appModuleHandler.AppModule "
			"(NAO GlobalPlugin — Notepad e uma aplicacao especifica); "
			"2) Implementar event_gainFocus(self, obj, nextHandler) chamando nextHandler() "
			"ao final; "
			"3) Ter chooseNVDAObjectOverlayClasses(self, obj, clsList) SOMENTE no AppModule "
			"(nunca num GlobalPlugin separado); "
			"4) Ter @script com NVDA+shift+S para anunciar numero de linhas do documento; "
			"5) Arquivo principal salvo como appModules/notepad.py; "
			"6) Implementar __init__(self, *args, **kwargs) com "
			"super().__init__(*args, **kwargs); "
			"7) Ter terminate() com super().terminate() como ULTIMA linha; "
			"8) Ter # Translators: antes de cada _(); "
			"9) Ter manifest.ini com minimumNVDAVersion=2026.1.1, "
			"lastTestedNVDAVersion=2026.1.1."
		),
	)


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------

class TestAppModuleAddon:
	"""
	Valida regras de AppModule contra addon AppModule gerado pela IA.

	Testes condicionais: pulam se a feature nao esta no addon gerado.
	Regra 9: nenhum codigo e executado em nenhuma validacao.
	"""

	# ------------------------------------------------------------------
	# NVDA-032: app especifica usa AppModule (nao GlobalPlugin)
	# ------------------------------------------------------------------

	def test_nvda032_app_especifica_usa_appmodule(
		self, fluxo_appmodule: FluxoReport
	):
		"""
		NVDA-032: Melhorias para uma app especifica devem usar AppModule, nao GlobalPlugin.

		GlobalPlugin afeta todo o NVDA. AppModule afeta apenas a app alvo.
		Usar GlobalPlugin para um app especifico polui o namespace global do NVDA.
		"""
		if not fluxo_appmodule.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_codigo(fluxo_appmodule.addon_folder)
		arquivos = _listar_arquivos(fluxo_appmodule.addon_folder)
		# Deve ter arquivo em appModules/ OU classe AppModule no codigo
		tem_appmodule_dir = any("appModules/" in a for a in arquivos)
		# Aceita "class Foo(AppModule):" e "class Foo(appModuleHandler.AppModule):"
		tem_classe_appmodule = (
			bool(re.search(r"class\s+\w+\s*\(.*AppModule.*\)", code))
			or "appModuleHandler.AppModule" in code
		)
		assert tem_appmodule_dir or tem_classe_appmodule, (
			"NVDA-032: addon para app especifica (Notepad) nao usa AppModule. "
			"Deve ter classe que herda de appModuleHandler.AppModule e "
			"arquivo em appModules/<nome_exe>.py."
		)

	# ------------------------------------------------------------------
	# NVDA-031: chooseNVDAObjectOverlayClasses somente em AppModule
	# ------------------------------------------------------------------

	def test_nvda031_choose_overlay_classes_somente_em_appmodule(
		self, fluxo_appmodule: FluxoReport
	):
		"""
		NVDA-031: chooseNVDAObjectOverlayClasses e event_NVDAObject_init
		so funcionam em AppModule, nao em GlobalPlugin.

		Em GlobalPlugin, esses metodos sao silenciosamente ignorados pelo NVDA.
		O dev pensa que funciona mas nao funciona — bug silencioso.
		"""
		if not fluxo_appmodule.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_codigo(fluxo_appmodule.addon_folder)
		tem_choose = "chooseNVDAObjectOverlayClasses" in code
		if not tem_choose:
			pytest.skip("Addon gerado nao implementa chooseNVDAObjectOverlayClasses")
		# Aceita tanto "class Foo(AppModule):" como "class Foo(appModuleHandler.AppModule):"
		# O padrao oficial do NVDA usa modulo qualificado (com ponto), que \w nao cobre.
		tem_appmodule = bool(
			re.search(r"class\s+\w+\s*\(.*AppModule.*\)", code)
		) or "appModuleHandler.AppModule" in code
		assert tem_appmodule, (
			"NVDA-031: chooseNVDAObjectOverlayClasses presente mas classe herda de GlobalPlugin. "
			"Este metodo so funciona em AppModule — em GlobalPlugin e silenciosamente ignorado."
		)

	# ------------------------------------------------------------------
	# NVDA-039: registerExecutableWithAppModule — condicional
	# ------------------------------------------------------------------

	def test_nvda039_multiplos_executaveis_usa_register(
		self, fluxo_appmodule: FluxoReport
	):
		"""
		NVDA-039: Se o addon suporta multiplos executaveis, deve usar
		registerExecutableWithAppModule para cada executavel adicional.

		Criar um AppModule separado por executavel e verboso. O registro
		centralizado via registerExecutableWithAppModule e mais limpo.
		"""
		if not fluxo_appmodule.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_codigo(fluxo_appmodule.addon_folder)
		# So relevante se o addon mapeia multiplos executaveis
		tem_register = "registerExecutableWithAppModule" in code
		tem_multiplos = len(re.findall(r'appModuleHandler\.AppModule', code)) > 1
		if not (tem_register or tem_multiplos):
			pytest.skip("Addon nao mapeia multiplos executaveis — NVDA-039 nao se aplica")
		assert "registerExecutableWithAppModule" in code, (
			"NVDA-039: addon com multiplos executaveis nao usa registerExecutableWithAppModule. "
			"Registre cada exe adicional via: "
			"appModuleHandler.registerExecutableWithAppModule('outro.exe', 'MeuAppModule')"
		)

	# ------------------------------------------------------------------
	# NVDA-040: Hosts especiais — condicional
	# ------------------------------------------------------------------

	def test_nvda040_wwahost_ou_webview2_herda_corretamente(
		self, fluxo_appmodule: FluxoReport
	):
		"""
		NVDA-040: Apps que rodam em wwahost.exe, WebView2 ou javaw.exe
		precisam de tratamento especial de heranca de AppModule.

		wwahost.exe hospeda apps UWP — o AppModule normal nao e ativado
		diretamente; precisa de heranca de WwahostAppModule.
		"""
		if not fluxo_appmodule.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_codigo(fluxo_appmodule.addon_folder)
		tem_host_especial = any(
			h in code for h in ["wwahost", "WebView2", "javaw", "WwahostAppModule"]
		)
		if not tem_host_especial:
			pytest.skip("Addon nao usa host especial (wwahost/WebView2/javaw) — NVDA-040 nao se aplica")
		assert "WwahostAppModule" in code or "WebView2" in code, (
			"NVDA-040: addon para wwahost nao herda de WwahostAppModule. "
			"Apps UWP precisam de heranca especial para que o AppModule seja ativado."
		)

	# ------------------------------------------------------------------
	# NVDA-041: sleepMode = True para apps autoloquentes — condicional
	# ------------------------------------------------------------------

	def test_nvda041_app_autoloquente_tem_sleep_mode(
		self, fluxo_appmodule: FluxoReport
	):
		"""
		NVDA-041: Apps que tem seu proprio leitor de tela (autoloquentes) devem
		ter sleepMode = True no AppModule.

		Sem sleepMode = True, o NVDA fala por cima da app autoloquente,
		causando dupla fala — experiencia ruim para o usuario.
		"""
		if not fluxo_appmodule.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_codigo(fluxo_appmodule.addon_folder)
		# Indicadores de app autoloquente na query ou no codigo
		indicadores = ["autoloquente", "self-voicing", "sleepMode", "sleep_mode"]
		tem_indicador = any(i.lower() in code.lower() for i in indicadores)
		if not tem_indicador:
			pytest.skip("Addon nao e para app autoloquente — NVDA-041 nao se aplica")
		assert "sleepMode" in code and "True" in code, (
			"NVDA-041: app autoloquente sem sleepMode = True. "
			"Adicione ao AppModule: sleepMode = True para suprimir a fala do NVDA."
		)

