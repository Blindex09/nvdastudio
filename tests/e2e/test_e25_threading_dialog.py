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
# Helpers (Regra 9: apenas leitura)
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
# Fixture — addon com threading, dialog e ngettext
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def fluxo_threading() -> FluxoReport:
	"""
	Gera um addon que faz busca em arquivos em thread separada e exibe resultado
	em dialog, usando ngettext para plurais.

	A query forca explicitamente:
	  - threading.Thread + wx.CallAfter (NVDA-010)
	  - gui.message.MessageDialog nao wx.MessageDialog (NVDA-023)
	  - ngettext() para contar resultados (NVDA-042)
	  - imports do modulo original sem re-exports (NVDA-020)
	  - installTasks.py (NVDA-033 — condicional)
	"""
	return _executar_fluxo_completo(
		addon_name="BuscaArquivos_e2e",
		query=(
			"Crie um GlobalPlugin NVDA chamado 'BuscaArquivos' que busca texto em "
			"arquivos do computador ao pressionar NVDA+shift+F, processa em thread "
			"separada para nao travar o NVDA, e exibe os resultados em dialog. "
			"O addon deve: "
			"1) Usar threading.Thread(target=...).start() para a busca pesada "
			"(nunca buscar na thread principal — bloquearia o NVDA); "
			"2) Usar wx.CallAfter(callback) para atualizar a UI apos o thread concluir "
			"(obrigatorio para acesso a wx de thread worker); "
			"3) Usar gui.message.MessageDialog (importado de gui.message) para mostrar "
			"resultados — NUNCA wx.MessageDialog diretamente; "
			"4) Usar ngettext() para anunciar '1 arquivo encontrado' vs "
			"'{n} arquivos encontrados' — nunca _() para strings com plural; "
			"5) Importar modulos do modulo ORIGINAL: 'from gui.message import MessageDialog' "
			"nao de re-exports transitivos; "
			"6) Ter installTasks.py com funcoes onInstall() e onUninstall() para "
			"configurar/limpar recursos na instalacao; "
			"7) Ter # Translators: antes de cada _() e ngettext(); "
			"8) Implementar __init__(self, *args, **kwargs) com "
			"super().__init__(*args, **kwargs); "
			"9) Ter manifest.ini com minimumNVDAVersion=2026.1.1, "
			"lastTestedNVDAVersion=2026.1.1."
		),
	)


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------

class TestThreadingDialog:
	"""
	Valida regras de threading, dialog e ngettext contra addon gerado pela IA.

	Testes condicionais: pulam se a feature nao esta no addon gerado.
	Regra 9: nenhum codigo e executado em nenhuma validacao.
	"""

	# ------------------------------------------------------------------
	# NVDA-010: wx.CallAfter para UI de thread worker
	# ------------------------------------------------------------------

	def test_nvda010_wxcallafter_se_tem_thread(
		self, fluxo_threading: FluxoReport
	):
		"""
		NVDA-010: UI do wx so pode ser atualizada da thread principal.

		threading.Thread() workers que atualizam a UI sem wx.CallAfter()
		causam crashes intermitentes em Windows — problema classico com wxPython.
		"""
		if not fluxo_threading.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_init_py(fluxo_threading.addon_folder)
		tem_thread = "threading.Thread" in code or "Thread(" in code
		if not tem_thread:
			pytest.skip("Addon gerado nao usa threading — NVDA-010 nao se aplica")
		assert "wx.CallAfter" in code or "CallAfter" in code, (
			"NVDA-010: addon usa threading.Thread mas nao tem wx.CallAfter(). "
			"Atualizacoes de UI a partir de thread worker DEVEM usar wx.CallAfter(callback). "
			"Sem isso: crashes intermitentes em Windows com wxPython."
		)

	# ------------------------------------------------------------------
	# NVDA-023: gui.message.MessageDialog (nao wx.MessageDialog)
	# ------------------------------------------------------------------

	def test_nvda023_message_dialog_de_gui_message(
		self, fluxo_threading: FluxoReport
	):
		"""
		NVDA-023: gui.message.MessageDialog e a API moderna do NVDA para dialogs.

		wx.MessageDialog e a API bruta do wxPython — nao integrada com o sistema
		de acessibilidade do NVDA. Dialogs via gui.message sao anunciados
		automaticamente para o usuario cego.
		"""
		if not fluxo_threading.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_init_py(fluxo_threading.addon_folder)
		tem_dialog = (
			"MessageDialog" in code
			or "wx.MessageDialog" in code
			or "messageBox" in code
			or "gui.message" in code
		)
		if not tem_dialog:
			pytest.skip("Addon gerado nao usa dialog — NVDA-023 nao se aplica")
		assert "wx.MessageDialog" not in code, (
			"NVDA-023: wx.MessageDialog usado diretamente. "
			"Use gui.message.MessageDialog — e a API acessivel integrada ao NVDA. "
			"wx.MessageDialog nao anuncia titulo/conteudo para o usuario cego."
		)
		assert "gui.message" in code or "MessageDialog" in code, (
			"NVDA-023: dialog presente mas sem gui.message.MessageDialog. "
			"Importe via: from gui.message import MessageDialog"
		)

	# ------------------------------------------------------------------
	# NVDA-042: ngettext() para plurais
	# ------------------------------------------------------------------

	def test_nvda042_plural_usa_ngettext(
		self, fluxo_threading: FluxoReport
	):
		"""
		NVDA-042: strings que variam no singular/plural devem usar ngettext().

		_('1 arquivo encontrado') e _('%d arquivos encontrados') nao adaptam
		o numero gramaticalmente. ngettext() faz isso corretamente.
		"""
		if not fluxo_threading.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_init_py(fluxo_threading.addon_folder)
		# Detecta strings com contagem numerica que deveriam usar ngettext
		tem_contagem = bool(re.search(r'_\(["\'].*\{.*(n|count|total|num).*\}.*["\']', code))
		tem_ngettext = "ngettext" in code
		if not tem_contagem and not tem_ngettext:
			pytest.skip("Addon gerado nao tem strings com contagem — NVDA-042 nao se aplica")
		# Se tem string de contagem, deve usar ngettext
		if tem_contagem and not tem_ngettext:
			# Verificar mais especificamente se parece ser uma string plural
			plural_pattern = re.compile(
				r'_\(["\'].*\d.*["\']|_\(["\'].*arquivo[s]?.*["\']|_\(["\'].*result.*["\']',
				re.IGNORECASE,
			)
			if plural_pattern.search(code):
				assert tem_ngettext, (
					"NVDA-042: codigo tem strings com contagem mas usa _() em vez de ngettext(). "
					"Use ngettext('1 item', '{n} itens', n).format(n=n) para plural correto."
				)
		if tem_ngettext:
			# ngettext deve ter 3 argumentos
			ngettext_calls = re.findall(r"ngettext\(([^)]+)\)", code)
			for call in ngettext_calls:
				partes = [p.strip() for p in call.split(",")]
				assert len(partes) >= 3, (
					f"NVDA-042: ngettext() com menos de 3 argumentos: ngettext({call}). "
					"Assinatura: ngettext(singular, plural, n)"
				)

	# ------------------------------------------------------------------
	# NVDA-020: imports do modulo ORIGINAL
	# ------------------------------------------------------------------

	def test_nvda020_imports_de_modulo_original(
		self, fluxo_threading: FluxoReport
	):
		"""
		NVDA-020: imports devem vir do modulo onde o simbolo e DEFINIDO,
		nao de re-exports transitivos.

		Re-exports quebram quando o NVDA reestruturas seus modulos internos.
		Ex: 'from gui import MessageDialog' em vez de 'from gui.message import MessageDialog'.
		"""
		if not fluxo_threading.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_init_py(fluxo_threading.addon_folder)
		# Re-exports conhecidos proibidos
		reexports_proibidos = [
			(r"from gui import MessageDialog", "MessageDialog deve vir de gui.message"),
			(r"from gui import browseableMessage", "browseableMessage deve vir de gui.message"),
			(r"from nvda import \*", "nunca usar import * de modulos NVDA"),
		]
		violacoes: list[str] = []
		for padrao, motivo in reexports_proibidos:
			if re.search(padrao, code):
				violacoes.append(motivo)
		assert not violacoes, (
			"NVDA-020: imports de re-exports transitivos encontrados:\n"
			+ "\n".join(f"  - {v}" for v in violacoes)
		)

	# ------------------------------------------------------------------
	# NVDA-033: installTasks.py — condicional
	# ------------------------------------------------------------------

	def test_nvda033_install_tasks_para_logica_de_setup(
		self, fluxo_threading: FluxoReport
	):
		"""
		NVDA-033: logica de instalacao/desinstalacao vai em installTasks.py,
		nao no __init__.py do GlobalPlugin.

		Configuracoes one-time (criar diretorios, instalar componentes) devem
		ser feitas no momento da instalacao, nao ao carregar o addon.
		"""
		if not fluxo_threading.success:
			pytest.skip("Pipeline nao concluiu")
		arquivos = _listar_arquivos(fluxo_threading.addon_folder)
		tem_install_tasks = any("installTasks" in a for a in arquivos)
		if not tem_install_tasks:
			pytest.skip("Addon gerado nao tem installTasks.py — NVDA-033 nao se aplica")
		# O AI pode colocar installTasks.py na raiz OU em subdiretorio — buscar o caminho real.
		install_tasks_rel = next(
			(a for a in arquivos if a.endswith("installTasks.py")), None
		)
		install_tasks_code = (
			_ler_arquivo(fluxo_threading.addon_folder, install_tasks_rel)
			if install_tasks_rel else ""
		)
		assert "def onInstall" in install_tasks_code or "onInstall" in install_tasks_code, (
			"NVDA-033: installTasks.py presente mas sem funcao onInstall(). "
			"installTasks.py deve ter onInstall() e onUninstall() definidos."
		)
		assert "def onUninstall" in install_tasks_code or "onUninstall" in install_tasks_code, (
			"NVDA-033: installTasks.py presente mas sem funcao onUninstall(). "
			"Cleanup de recursos instalados vai em onUninstall()."
		)

