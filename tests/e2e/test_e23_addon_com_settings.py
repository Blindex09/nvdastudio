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
# Helpers de leitura (Regra 9: apenas string, nunca exec)
# ---------------------------------------------------------------------------

def _ler_init_py(addon_folder: str) -> str:
	gp = os.path.join(addon_folder, "globalPlugins")
	if not os.path.isdir(gp):
		return ""
	for subdir in os.listdir(gp):
		init = os.path.join(gp, subdir, "__init__.py")
		if os.path.isfile(init):
			with open(init, encoding="utf-8", errors="replace") as fh:
				return fh.read()
	return ""


def _ler_arquivo(addon_folder: str, caminho: str) -> str:
	path = os.path.join(addon_folder, caminho)
	if os.path.isfile(path):
		with open(path, encoding="utf-8", errors="replace") as fh:
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
# Fixture — addon com SettingsPanel
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def fluxo_settings(tmp_path_factory: pytest.TempPathFactory) -> FluxoReport:
	"""
	Gera um addon que usa SettingsPanel para configurar chave de API.
	A query forca explicitamente o uso de:
	  - config.conf.spec (NVDA-015)
	  - NVDAState.shouldWriteToDisk() (NVDA-016)
	  - SettingsPanel registrado/removido com guard (NVDA-026)
	  - config.conf['secao']['chave'] direto, nunca .get() (NVDA-027)
	"""
	return _executar_fluxo_completo(
		addon_name="ConfiguracaoAPIKey_e2e",
		query=(
			"Crie um GlobalPlugin NVDA chamado 'ConfiguracaoAPIKey' que permite ao "
			"usuario configurar uma chave de API de traducao via painel de configuracoes "
			"do NVDA (SettingsPanel). O addon deve: "
			"1) Registrar um SettingsPanel em NVDASettingsDialog.categoryClasses com "
			"guard 'if Panel not in NVDASettingsDialog.categoryClasses' no __init__; "
			"2) Remover o panel no terminate() com guard 'if Panel in ...'; "
			"3) Ter makeSettings() com wx.TextCtrl para a chave de API — NUNCA usar "
			"config.conf['secao'].get() — usar config.conf['secao']['chave'] direto; "
			"4) Ter configSpec registrado em config.conf.spec com "
			"{'apiKey': 'string(default=\"\")'} antes de acessar a config; "
			"5) Verificar NVDAState.shouldWriteToDisk() antes de salvar qualquer arquivo; "
			"6) Implementar __init__(self, *args, **kwargs) com "
			"super().__init__(*args, **kwargs); "
			"7) Ter # Translators: antes de cada _(); "
			"8) Ter manifest.ini com minimumNVDAVersion=2026.1.1, "
			"lastTestedNVDAVersion=2026.1.1; "
			"9) dependencies=[] deve conter apenas nomes PyPI validos (sem os, sys, "
			"webbrowser, ui, api, globalPlugins ou qualquer modulo NVDA interno)."
		),
	)


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------

class TestAddonComSettings:
	"""
	Valida 5 regras de configuracao contra addon com SettingsPanel gerado pela IA.

	Todos os testes sao condicionais — pulam se a feature nao esta no addon gerado,
	evitando falsos negativos.
	Regra 9: nenhum codigo e executado em nenhuma validacao.
	"""

	# ------------------------------------------------------------------
	# NVDA-026: SettingsPanel registrado E removido com guard
	# ------------------------------------------------------------------

	def test_nvda026_settings_panel_registrado_e_removido(
		self, fluxo_settings: FluxoReport
	):
		"""
		NVDA-026: SettingsPanel deve ser adicionado com guard no __init__
		e removido com guard no terminate().

		Sem o guard de adicao: panico ao carregar o addon duas vezes.
		Sem o guard de remocao: TypeError no terminate se o panel ja foi removido.
		"""
		if not fluxo_settings.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_init_py(fluxo_settings.addon_folder)
		tem_settings_panel = (
			"SettingsPanel" in code
			or "NVDASettingsDialog" in code
			or "categoryClasses" in code
		)
		if not tem_settings_panel:
			pytest.skip("Addon gerado nao tem SettingsPanel")
		assert "categoryClasses" in code, (
			"NVDA-026: NVDASettingsDialog.categoryClasses nao referenciado. "
			"SettingsPanel deve ser registrado via categoryClasses.append() "
			"e removido via categoryClasses.remove()."
		)
		assert "append" in code or "insert" in code, (
			"NVDA-026: SettingsPanel nao adicionado a categoryClasses. "
			"Use: NVDASettingsDialog.categoryClasses.append(MeuPanel)"
		)
		assert "remove" in code, (
			"NVDA-026: SettingsPanel nao removido em terminate(). "
			"Use: NVDASettingsDialog.categoryClasses.remove(MeuPanel) com guard."
		)

	# ------------------------------------------------------------------
	# NVDA-027: makeSettings NUNCA usa .get()
	# ------------------------------------------------------------------

	def test_nvda027_make_settings_sem_config_get(
		self, fluxo_settings: FluxoReport
	):
		"""
		NVDA-027: config.conf['secao'].get() bypassa configspec.

		Retorna string bruta em vez do tipo definido no spec. Causa TypeError
		em SpinCtrl, CheckBox e faz Tab escapar para outro addon.
		Correto: config.conf['secao']['chave'] direto.
		"""
		if not fluxo_settings.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_init_py(fluxo_settings.addon_folder)
		tem_settings_panel = "makeSettings" in code or "SettingsPanel" in code
		if not tem_settings_panel:
			pytest.skip("Addon gerado nao tem SettingsPanel/makeSettings")
		# Procura config.conf["..."].get( ou config.conf['...'].get(
		padrao_get = re.compile(r'config\.conf\[.+?\]\.get\(')
		violacoes = padrao_get.findall(code)
		assert not violacoes, (
			f"NVDA-027: config.conf[...].get() encontrado {len(violacoes)} vez(es). "
			"Use config.conf['secao']['chave'] direto — .get() bypassa configspec."
		)

	# ------------------------------------------------------------------
	# NVDA-015: config.conf.spec obrigatorio para persistencia
	# ------------------------------------------------------------------

	def test_nvda015_config_conf_usa_spec(
		self, fluxo_settings: FluxoReport
	):
		"""
		NVDA-015: Configuracoes persistentes exigem config.conf.spec registrado.

		Sem spec: config.conf['secao'] lanca KeyError, painel fica vazio,
		Tab pode escapar para outro addon.
		"""
		if not fluxo_settings.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_init_py(fluxo_settings.addon_folder)
		tem_config = "config.conf" in code
		if not tem_config:
			pytest.skip("Addon gerado nao usa config.conf")
		assert "config.conf.spec" in code or "confspec" in code.lower(), (
			"NVDA-015: config.conf.spec nao registrado. "
			"Use config.conf.spec['secao'] = {'chave': 'tipo(default=val)'} "
			"antes de acessar config.conf['secao']['chave']."
		)

	# ------------------------------------------------------------------
	# NVDA-016: NVDAState.shouldWriteToDisk() antes de I/O
	# ------------------------------------------------------------------

	def test_nvda016_should_write_to_disk_antes_de_escrita(
		self, fluxo_settings: FluxoReport
	):
		"""
		NVDA-016: Em secure mode (tela de bloqueio, UAC), gravar em disco e proibido.

		Addons que escrevem arquivos sem verificar NVDAState.shouldWriteToDisk()
		podem expor dados em contextos de seguranca elevada.
		"""
		if not fluxo_settings.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_init_py(fluxo_settings.addon_folder)
		# So verifica se houver operacao de escrita em disco
		tem_escrita = (
			"open(" in code and ("'w'" in code or '"w"' in code or "'a'" in code or '"a"' in code)
		)
		if not tem_escrita:
			pytest.skip("Addon gerado nao escreve arquivos em disco")
		assert "shouldWriteToDisk" in code, (
			"NVDA-016: escrita em disco sem verificar NVDAState.shouldWriteToDisk(). "
			"Em secure mode esse flag e False — gravar sem verificar e erro de seguranca."
		)

	# ------------------------------------------------------------------
	# NVDA-024: dependencies[] so aceita nomes PyPI
	# ------------------------------------------------------------------

	def test_nvda024_dependencies_sao_nomes_pypi_validos(
		self, fluxo_settings: FluxoReport
	):
		"""
		NVDA-024: dependencies[] no manifest deve conter apenas nomes PyPI validos.

		Nomes de import (googleapiclient.discovery), stdlib (os, sys, webbrowser)
		e modulos NVDA (ui, api, globalPlugins) sao proibidos.
		"""
		if not fluxo_settings.success:
			pytest.skip("Pipeline nao concluiu")
		manifest = _ler_arquivo(fluxo_settings.addon_folder, "manifest.ini")
		m = re.search(r"dependencies\s*=\s*(.+)", manifest)
		if not m:
			pytest.skip("manifest.ini nao tem campo dependencies")
		deps_str = m.group(1).strip()
		if not deps_str or deps_str == "[]":
			pytest.skip("dependencies esta vazio — nenhuma dependencia para validar")
		# Nomes NVDA internos e stdlib que nao devem aparecer
		proibidos = [
			"os", "sys", "re", "webbrowser", "datetime", "pathlib",
			"ui", "api", "speech", "config", "nvda", "nvdaHelper",
			"globalPlugins", "appModules", "synthDrivers", "brailleDisplayDrivers",
			"globalPluginHandler", "addonHandler", "scriptHandler",
		]
		deps_lower = deps_str.lower()
		violacoes = [p for p in proibidos if p.lower() in deps_lower]
		# Nomes com ponto (import paths) sao sempre errados
		tem_ponto = "." in deps_str and re.search(r"\w+\.\w+", deps_str)
		assert not violacoes, (
			f"NVDA-024: dependencies[] contem modulos proibidos: {violacoes}. "
			"Use apenas nomes PyPI (ex: 'requests', 'google-auth'). "
			"Stdlib e modulos NVDA nao devem estar em dependencies[]."
		)
		assert not tem_ponto, (
			"NVDA-024: dependencies[] contem nome de import com ponto (ex: 'google.auth'). "
			"Use o nome PyPI correspondente (ex: 'google-auth')."
		)

