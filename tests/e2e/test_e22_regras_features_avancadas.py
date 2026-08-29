import os
import re

import pytest

# ---------------------------------------------------------------------------
# Importa fixtures e helpers do modulo de referencia
# ---------------------------------------------------------------------------

from tests.e2e.test_fluxo_completo_nvda import (
	FluxoReport,
	_executar_fluxo_completo,
	_ler_init_py,
	_ler_manifest,
	skip_unless_ollama,
	)

# ---------------------------------------------------------------------------
# Fixture compartilhado — mesmo padrao do arquivo de referencia
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def fluxo_report():
	"""
	Executa o fluxo completo UMA VEZ para toda a classe de testes.
	Todos os testes compartilham o mesmo FluxoReport.
	Economiza tokens e tempo de API.

	A query cobre um escopo amplo para que varios testes condicionais
	possam encontrar features avancadas no codigo gerado.
	"""
	report = _executar_fluxo_completo(
		addon_name="FeaturesAvancadas_e2e",
		query=(
			"Crie um GlobalPlugin NVDA chamado 'FeaturesAvancadas' que demonstra "
			"recursos avancados. O plugin deve: "
			"1) Ter classe GlobalPlugin com @script decorator; "
			"2) Chamar addonHandler.initTranslation() no topo; "
			"3) Implementar terminate() que chama super().terminate(); "
			"4) Usar ngettext() para mensagens com contagem de itens; "
			"5) Ter manifest.ini com version=1.0.0, minimumNVDAVersion=2026.1.1, "
			"lastTestedNVDAVersion=2026.1.1, docFileName=userGuide.html."
		),
	)
	return report


# ---------------------------------------------------------------------------
# Helpers de leitura de arquivos do addon (Regra 9: apenas string)
# ---------------------------------------------------------------------------

def _ler_arquivo(addon_folder: str, caminho_relativo: str) -> str:
	"""Retorna conteudo de arquivo dentro do addon_folder (apenas leitura, Regra 9)."""
	path = os.path.join(addon_folder, caminho_relativo)
	if os.path.isfile(path):
		with open(path, encoding="utf-8", errors="replace") as fh:
			return fh.read()
	return ""


def _listar_arquivos(addon_folder: str) -> list[str]:
	"""Lista todos os arquivos dentro do addon_folder com caminho relativo."""
	resultado: list[str] = []
	for root, _, files in os.walk(addon_folder):
		for f in files:
			abs_path = os.path.join(root, f)
			rel_path = os.path.relpath(abs_path, addon_folder).replace("\\", "/")
			resultado.append(rel_path)
	return resultado


def _ler_codigo_principal(addon_folder: str) -> str:
	"""
	Retorna o conteudo do codigo Python principal do addon.
	Tenta globalPlugins/__init__.py primeiro, depois appModules/__init__.py.
	"""
	code = _ler_init_py(addon_folder)
	if code:
		return code
	# Tenta appModules
	am = os.path.join(addon_folder, "appModules")
	if os.path.isdir(am):
		for subdir in os.listdir(am):
			init = os.path.join(am, subdir, "__init__.py")
			if os.path.isfile(init):
				with open(init, encoding="utf-8", errors="replace") as fh:
					return fh.read()
			# Tenta diretamente
			direct = os.path.join(am, subdir + ".py")
			if os.path.isfile(direct):
				with open(direct, encoding="utf-8", errors="replace") as fh:
					return fh.read()
	return ""


# ---------------------------------------------------------------------------
# Classe de testes: features avancadas
# ---------------------------------------------------------------------------

@skip_unless_ollama
class TestRegrasFeaturessAvancadas:
	"""
	5.1.0: este arquivo nao definia skip_unless_ollama -- fluxo_report
	(fixture de modulo) rodava o pipeline completo (LLM real)
	incondicionalmente e ficava pendurado sem as chaves configuradas, em
	vez de skip limpo. Ver test_e20_regras_qualidade_codigo.py 5.1.0 para o
	achado completo. Guard importado de test_fluxo_completo_nvda (fonte
	unica) em vez de redefinido, ja que este arquivo ja importa dele.

	Valida 14 regras de features avancadas contra o addon gerado pelo pipeline.

	Todos os testes sao condicionais: fazem pytest.skip() quando a feature
	nao esta presente no addon gerado — evitando falsos negativos para addons
	que nao precisam da feature em questao.

	Regra 9: nenhum codigo e executado em nenhuma validacao.
	"""

	# ------------------------------------------------------------------
	# NVDA-011: check() classmethod para SynthDriver/BrailleDisplayDriver
	# ------------------------------------------------------------------

	def test_nvda011_synth_driver_tem_check_classmethod(self, fluxo_report: FluxoReport):
		"""
		NVDA-011: SynthDriver e BrailleDisplayDriver devem ter @classmethod check().

		O NVDA chama check() antes de tentar instanciar o driver para verificar
		se o hardware/software necessario esta disponivel. Sem check(), o NVDA
		pode travar ou gerar erro ao tentar carregar o driver em hardware incompativel.

		Ref: nvda_developer_guide_2025.html — secao SynthDriver.
		"""
		if not fluxo_report.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_codigo_principal(fluxo_report.addon_folder)
		tem_synth = bool(re.search(r"class\s+\w+\s*\(\s*\w*SynthDriver\w*\s*\)", code))
		tem_braille = bool(re.search(r"class\s+\w+\s*\(\s*\w*BrailleDisplayDriver\w*\s*\)", code))
		if not (tem_synth or tem_braille):
			pytest.skip("Addon gerado nao e um SynthDriver nem BrailleDisplayDriver")
		assert "@classmethod" in code, (
			"NVDA-011: SynthDriver/BrailleDisplayDriver sem @classmethod. "
			"check() classmethod e obrigatorio para validar disponibilidade do hardware."
		)
		assert "def check(" in code, (
			"NVDA-011: @classmethod check() ausente no driver. "
			"O NVDA chama check() antes de instanciar o driver — obrigatorio."
		)

	# ------------------------------------------------------------------
	# NVDA-017: Sem DLL 32-bit / ctypes inseguro
	# ------------------------------------------------------------------

	def test_nvda017_ctypes_loading_tem_verificacao_arquitetura(self, fluxo_report: FluxoReport):
		"""
		NVDA-017: Se o codigo carrega DLLs via ctypes, deve verificar a arquitetura.

		Carregar uma DLL 32-bit em um processo 64-bit (NVDA moderno) causa falha
		imediata. A verificacao pode ser feita via struct.unpack lendo o cabecalho PE
		ou via platform.machine() antes de chamar LoadLibrary.

		Ref: nvda_developer_guide_2025.html — secao sobre extensoes nativas.
		"""
		if not fluxo_report.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_codigo_principal(fluxo_report.addon_folder)
		tem_load_library = (
			"ctypes.windll.LoadLibrary(" in code
			or "ctypes.cdll.LoadLibrary(" in code
			or "LoadLibrary(" in code
		)
		if not tem_load_library:
			pytest.skip("Addon gerado nao usa ctypes LoadLibrary")
		tem_verificacao = (
			"struct.unpack" in code
			or "platform.machine" in code
			or "platform.architecture" in code
			or "sys.maxsize" in code
		)
		assert tem_verificacao, (
			"NVDA-017: codigo usa LoadLibrary() sem verificacao de arquitetura. "
			"DLLs 32-bit causam falha em NVDA 64-bit. "
			"Use struct.unpack para ler cabecalho PE ou platform.machine() antes de carregar."
		)

	# ------------------------------------------------------------------
	# NVDA-033: installTasks.py para acoes de instalacao
	# ------------------------------------------------------------------

	def test_nvda033_install_tasks_para_logica_de_setup(self, fluxo_report: FluxoReport):
		"""
		NVDA-033: Acoes de instalacao/configuracao devem estar em installTasks.py.

		Logica de setup que roda apenas na instalacao (copiar arquivos, registrar
		servicos, criar chaves de registro) NAO deve estar no __init__.py do plugin.
		Deve ser isolada em installTasks.py com as funcoes onInstall() e/ou onUninstall().

		Ref: nvda_developer_guide_2025.html — secao installTasks.
		"""
		if not fluxo_report.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_codigo_principal(fluxo_report.addon_folder)
		# Indicadores de logica de instalacao no codigo principal
		padroes_setup = [
			"winreg.", "win32api.", "shutil.copy", "os.makedirs",
			"subprocess.run", "subprocess.call", "RegisterServer",
		]
		tem_logica_setup = any(p in code for p in padroes_setup)
		if not tem_logica_setup:
			pytest.skip("Addon gerado nao tem logica de instalacao detectavel")
		arquivos = _listar_arquivos(fluxo_report.addon_folder)
		tem_install_tasks = any("installtasks.py" == a.lower().split("/")[-1] for a in arquivos)
		assert tem_install_tasks, (
			"NVDA-033: addon tem logica de instalacao no __init__.py mas sem installTasks.py. "
			"Acoes de setup devem ser isoladas em installTasks.py com onInstall()/onUninstall(). "
			"Ref: nvda_developer_guide_2025.html — secao installTasks."
		)
		install_tasks_content = _ler_arquivo(fluxo_report.addon_folder, "installTasks.py")
		assert "onInstall" in install_tasks_content or "onUninstall" in install_tasks_content, (
			"NVDA-033: installTasks.py encontrado mas sem onInstall() nem onUninstall(). "
			"Pelo menos uma das duas funcoes deve estar presente."
		)

	# ------------------------------------------------------------------
	# NVDA-035: SynthDriver com supportedCommands + supportedNotifications
	# ------------------------------------------------------------------

	def test_nvda035_synth_driver_tem_campos_obrigatorios(self, fluxo_report: FluxoReport):
		"""
		NVDA-035: SynthDriver deve declarar supportedCommands e supportedNotifications.

		supportedCommands: frozenset de classes de comando de fala que o driver suporta.
		supportedNotifications: frozenset de sinais de notificacao (synthIndexReached,
		synthDoneSpeaking) necessarios para sincronizacao de fala.

		Sem esses campos, o NVDA nao consegue coordenar a fala corretamente.

		Ref: nvda_developer_guide_2025.html — secao SynthDriver interface.
		"""
		if not fluxo_report.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_codigo_principal(fluxo_report.addon_folder)
		if not re.search(r"class\s+\w+\s*\(\s*\w*SynthDriver\w*\s*\)", code):
			pytest.skip("Addon gerado nao e um SynthDriver")
		assert "supportedCommands" in code, (
			"NVDA-035: SynthDriver sem supportedCommands. "
			"Declare supportedCommands como frozenset das classes de comando suportadas."
		)
		assert "supportedNotifications" in code, (
			"NVDA-035: SynthDriver sem supportedNotifications. "
			"Declare supportedNotifications incluindo synthIndexReached e synthDoneSpeaking."
		)
		assert "synthIndexReached" in code, (
			"NVDA-035: supportedNotifications sem synthIndexReached. "
			"Necessario para sincronizacao de indice de fala."
		)
		assert "synthDoneSpeaking" in code, (
			"NVDA-035: supportedNotifications sem synthDoneSpeaking. "
			"Necessario para saber quando a fala terminou."
		)

	# ------------------------------------------------------------------
	# NVDA-037: BrailleDisplayDriver com numCols, display(), isThreadSafe
	# ------------------------------------------------------------------

	def test_nvda037_braille_display_driver_campos_obrigatorios(self, fluxo_report: FluxoReport):
		"""
		NVDA-037: BrailleDisplayDriver deve ter numCols, display() e isThreadSafe.

		numCols: numero de celulas braille do display (int).
		display(): metodo que recebe a lista de bytes e envia ao hardware.
		isThreadSafe: bool indicando se o driver pode ser chamado de outra thread.

		Sem esses membros, o NVDA nao consegue usar o display braille corretamente.

		Ref: nvda_developer_guide_2025.html — secao BrailleDisplayDriver.
		"""
		if not fluxo_report.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_codigo_principal(fluxo_report.addon_folder)
		if not re.search(r"class\s+\w+\s*\(\s*\w*BrailleDisplayDriver\w*\s*\)", code):
			pytest.skip("Addon gerado nao e um BrailleDisplayDriver")
		assert "numCols" in code, (
			"NVDA-037: BrailleDisplayDriver sem numCols. "
			"Declare numCols com o numero de celulas do display."
		)
		assert "def display(" in code, (
			"NVDA-037: BrailleDisplayDriver sem metodo display(). "
			"display() e o metodo principal que recebe bytes e envia ao hardware."
		)
		assert "isThreadSafe" in code, (
			"NVDA-037: BrailleDisplayDriver sem isThreadSafe. "
			"Declare isThreadSafe = True/False conforme capacidade do driver."
		)

	# ------------------------------------------------------------------
	# NVDA-038: Speech Dictionaries em speechDicts/ com formato correto
	# ------------------------------------------------------------------

	def test_nvda038_speech_dicts_formato_correto(self, fluxo_report: FluxoReport):
		"""
		NVDA-038: Arquivos .dic em speechDicts/ devem ter 4 campos separados por TAB.

		Formato correto por linha: pattern<TAB>replacement<TAB>caseSensitive<TAB>type
		Onde caseSensitive e 0 ou 1, e type e 0 (anywhere) ou 1 (word).

		Formato errado causa falha silenciosa ao carregar o dicionario de fala.

		Ref: nvda_developer_guide_2025.html — secao Speech Dictionaries.
		"""
		if not fluxo_report.success:
			pytest.skip("Pipeline nao concluiu")
		arquivos = _listar_arquivos(fluxo_report.addon_folder)
		dic_files = [a for a in arquivos if "speechdicts" in a.lower() and a.endswith(".dic")]
		if not dic_files:
			pytest.skip("Addon gerado nao tem speechDicts/")
		violacoes: list[str] = []
		for rel_path in dic_files:
			content = _ler_arquivo(fluxo_report.addon_folder, rel_path)
			for i, linha in enumerate(content.splitlines(), 1):
				linha = linha.strip()
				if not linha or linha.startswith("#"):
					continue
				campos = linha.split("\t")
				if len(campos) != 4:
					violacoes.append(
						f"{rel_path} linha {i}: esperado 4 campos TAB-separados, "
						f"encontrado {len(campos)}: {linha[:60]!r}"
					)
		assert not violacoes, (
			"NVDA-038: arquivos .dic em speechDicts/ com formato invalido:\n"
			+ "\n".join(violacoes)
			+ "\nFormato correto: pattern<TAB>replacement<TAB>caseSensitive<TAB>type"
		)

	# ------------------------------------------------------------------
	# NVDA-039: registerExecutableWithAppModule para multiplos executaveis
	# ------------------------------------------------------------------

	def test_nvda039_multiplos_executaveis_usa_register(self, fluxo_report: FluxoReport):
		"""
		NVDA-039: AppModule que cobre multiplos executaveis deve usar
		registerExecutableWithAppModule().

		Mapear manualmente nomes de arquivo para AppModules e fragil e nao escalavel.
		A API registerExecutableWithAppModule() e o mecanismo oficial para associar
		um AppModule a executaveis adicionais alem do arquivo .py principal.

		Ref: nvda_developer_guide_2025.html — secao AppModules multiplos executaveis.
		"""
		if not fluxo_report.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_codigo_principal(fluxo_report.addon_folder)
		# Detecta padrão de múltiplos executáveis: lista/tupla com .exe ou vários appModules
		padroes_multi_exec = re.findall(
			r'["\'][\w\-]+\.exe["\']',
			code,
			re.IGNORECASE,
		)
		if len(padroes_multi_exec) < 2:
			pytest.skip("Addon gerado nao tem multiplos executaveis detectados")
		assert "registerExecutableWithAppModule" in code, (
			"NVDA-039: addon com multiplos executaveis sem registerExecutableWithAppModule(). "
			"Use appModuleHandler.registerExecutableWithAppModule(exe, AppModule) "
			"para cada executavel adicional."
		)

	# ------------------------------------------------------------------
	# NVDA-040: Hosts especiais (wwahost, WebView2, javaw)
	# ------------------------------------------------------------------

	def test_nvda040_wwahost_herda_corretamente(self, fluxo_report: FluxoReport):
		"""
		NVDA-040: AppModule para wwahost deve herdar de nvdaBuiltin.appModules.wwahost.AppModule.

		wwahost e o processo host de apps Windows Runtime (UWP). Herdar do AppModule
		builtin garante que o NVDA trate corretamente o IAccessible2 dessas apps.

		Ref: nvda_developer_guide_2025.html — secao hosts especiais.
		"""
		if not fluxo_report.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_codigo_principal(fluxo_report.addon_folder)
		if "wwahost" not in code.lower():
			pytest.skip("Addon gerado nao menciona wwahost")
		herda_wwahost = (
			"nvdaBuiltin.appModules.wwahost" in code
			or "appModules.wwahost" in code
		)
		assert herda_wwahost, (
			"NVDA-040: addon menciona wwahost mas nao herda de "
			"nvdaBuiltin.appModules.wwahost.AppModule. "
			"Herdar do builtin e obrigatorio para apps UWP."
		)

	def test_nvda040_webview2_tem_disable_browse_mode(self, fluxo_report: FluxoReport):
		"""
		NVDA-040: AppModule para WebView2 deve ter disableBrowseModeByDefault = True.

		WebView2 usa Chromium embedded. Sem disableBrowseModeByDefault, o NVDA
		ativa o browse mode automaticamente, causando conflito com controles web
		customizados que gerenciam seu proprio foco.

		Ref: nvda_developer_guide_2025.html — secao WebView2.
		"""
		if not fluxo_report.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_codigo_principal(fluxo_report.addon_folder)
		if "webview2" not in code.lower() and "WebView2" not in code:
			pytest.skip("Addon gerado nao menciona WebView2")
		assert "disableBrowseModeByDefault" in code, (
			"NVDA-040: addon menciona WebView2 mas sem disableBrowseModeByDefault = True. "
			"Necessario para evitar conflito do browse mode com controles WebView2."
		)

	# ------------------------------------------------------------------
	# NVDA-041: sleepMode = True para apps autoloquentes
	# ------------------------------------------------------------------

	def test_nvda041_app_autoloquente_tem_sleep_mode(self, fluxo_report: FluxoReport):
		"""
		NVDA-041: AppModule para apps autoloquentes deve ter sleepMode = True.

		Apps autoloquentes (JAWS, VoiceOver, Narrator, outro NVDA) tem seu proprio
		sintetizador de voz. Sem sleepMode = True, o NVDA e o app se sobrepoe,
		causando dupla leitura e conflito de voz.

		Ref: nvda_developer_guide_2025.html — secao sleepMode.
		"""
		if not fluxo_report.success:
			pytest.skip("Pipeline nao concluiu")
		# Verifica no codigo e na query original do report
		code = _ler_codigo_principal(fluxo_report.addon_folder)
		_APP_AUTOLOQUENTES = ["jaws", "voiceover", "narrator", "orca", "supernova", "zoomtext"]
		query_lower = fluxo_report.query.lower()
		codigo_lower = code.lower()
		menciona_autoloquente = any(
			app in query_lower or app in codigo_lower
			for app in _APP_AUTOLOQUENTES
		)
		if not menciona_autoloquente:
			pytest.skip("Addon gerado nao e para app autoloquente")
		assert "sleepMode" in code, (
			"NVDA-041: AppModule para app autoloquente sem sleepMode = True. "
			"Apps com seu proprio sintetizador requerem sleepMode para evitar "
			"dupla leitura e conflito de voz."
		)
		assert "= True" in code or "=True" in code, (
			"NVDA-041: sleepMode encontrado mas valor nao e True. "
			"Declare sleepMode = True na classe AppModule."
		)

	# ------------------------------------------------------------------
	# NVDA-042: ngettext() para plurais, pgettext() para contexto
	# ------------------------------------------------------------------

	def test_nvda042_plural_usa_ngettext(self, fluxo_report: FluxoReport):
		"""
		NVDA-042: Strings com plural devem usar ngettext(), nao _() com interpolacao manual.

		_(f'1 item') ou _(f'{n} itens') nao permite ao tradutor definir formas de plural
		para idiomas com mais de duas formas (russo, arabe, etc.).
		ngettext(singular, plural, n) e a API correta para internacionalizacao de plurais.

		Ref: Python gettext docs + nvda_developer_guide_2025.html — secao i18n.
		"""
		if not fluxo_report.success or not fluxo_report.has_init_py:
			pytest.skip("__init__.py nao disponivel")
		code = _ler_codigo_principal(fluxo_report.addon_folder)
		# Detecta padrão de string plural: "1 item" / "N items" hardcoded dentro de _()
		padroes_plural = re.findall(
			r'_\s*\(\s*["\'].*\b(?:items?|itens?|files?|arquivos?|results?|resultados?)\b',
			code,
			re.IGNORECASE,
		)
		# Detecta interpolacao de numero dentro de _()
		interpolacao_numero = re.findall(
			r'_\s*\(\s*["\'][^"\']*%[ds][^"\']*["\']|_\s*\(\s*f["\'][^"\']*\{[^}]*\}[^"\']*["\']',
			code,
		)
		if not padroes_plural and not interpolacao_numero:
			pytest.skip("Addon gerado nao tem strings com plural detectaveis")
		assert "ngettext(" in code or "ngettext (" in code, (
			"NVDA-042: codigo tem strings com plural mas usa _() em vez de ngettext(). "
			"ngettext(singular, plural, n) e obrigatorio para idiomas com multiplas formas de plural. "
			"Ref: nvda_developer_guide_2025.html — secao i18n."
		)

	# ------------------------------------------------------------------
	# NVDA-043: Braille Tables em brailleTables/ com manifest
	# ------------------------------------------------------------------

	def test_nvda043_braille_tables_manifest_tem_secao(self, fluxo_report: FluxoReport):
		"""
		NVDA-043: Se o addon tem pasta brailleTables/, o manifest.ini deve ter
		a secao [brailleTables] declarando as tabelas disponibilizadas.

		Sem a secao no manifest, o NVDA nao registra as tabelas e elas ficam
		inacessiveis para o usuario na caixa de dialogo de configuracao braille.

		Ref: nvda_developer_guide_2025.html — secao Braille Tables.
		"""
		if not fluxo_report.success:
			pytest.skip("Pipeline nao concluiu")
		arquivos = _listar_arquivos(fluxo_report.addon_folder)
		tem_braille_tables = any("brailletables" in a.lower() for a in arquivos)
		if not tem_braille_tables:
			pytest.skip("Addon gerado nao tem pasta brailleTables/")
		manifest_content = _ler_manifest(fluxo_report.addon_folder)
		assert "[brailleTables]" in manifest_content or "[brailletables]" in manifest_content.lower(), (
			"NVDA-043: addon tem pasta brailleTables/ mas manifest.ini sem secao [brailleTables]. "
			"Adicione a secao [brailleTables] no manifest.ini para registrar as tabelas."
		)

	# ------------------------------------------------------------------
	# NVDA-044: Symbol Dictionaries em locale/<lang>/symbols-N.dic
	# ------------------------------------------------------------------

	def test_nvda044_symbol_dicts_estrutura_correta(self, fluxo_report: FluxoReport):
		"""
		NVDA-044: Symbol dictionaries em locale/<lang>/symbols-*.dic devem ter formato correto.

		Cada entrada deve ter 4 campos: identifier, replacement, level, preserve
		separados por TAB. O manifest.ini deve ter a secao [symbolDictionaries].

		Formato errado causa falha silenciosa ao carregar os simbolos customizados.

		Ref: nvda_developer_guide_2025.html — secao Symbol Dictionaries.
		"""
		if not fluxo_report.success:
			pytest.skip("Pipeline nao concluiu")
		arquivos = _listar_arquivos(fluxo_report.addon_folder)
		symbol_dic_files = [
			a for a in arquivos
			if re.match(r"locale/[^/]+/symbols", a, re.IGNORECASE) and a.endswith(".dic")
		]
		if not symbol_dic_files:
			pytest.skip("Addon gerado nao tem locale/<lang>/symbols-*.dic")
		violacoes: list[str] = []
		for rel_path in symbol_dic_files:
			content = _ler_arquivo(fluxo_report.addon_folder, rel_path)
			for i, linha in enumerate(content.splitlines(), 1):
				linha = linha.strip()
				if not linha or linha.startswith("#"):
					continue
				campos = linha.split("\t")
				if len(campos) < 3:
					violacoes.append(
						f"{rel_path} linha {i}: esperado pelo menos 3 campos TAB-separados "
						f"(identifier, replacement, level), encontrado {len(campos)}: {linha[:60]!r}"
					)
		assert not violacoes, (
			"NVDA-044: symbol dictionaries com formato invalido:\n"
			+ "\n".join(violacoes)
			+ "\nFormato correto: identifier<TAB>replacement<TAB>level<TAB>preserve"
		)
		manifest_content = _ler_manifest(fluxo_report.addon_folder)
		assert (
			"[symbolDictionaries]" in manifest_content
			or "[symboldictionaries]" in manifest_content.lower()
		), (
			"NVDA-044: addon tem symbol dictionaries mas manifest.ini sem secao [symbolDictionaries]. "
			"Adicione a secao [symbolDictionaries] no manifest.ini."
		)

	# ------------------------------------------------------------------
	# NVDA-045: Locale Gesture Remapping via locale/<lang>/gestures.ini
	# ------------------------------------------------------------------

	def test_nvda045_gestures_ini_formato_correto(self, fluxo_report: FluxoReport):
		"""
		NVDA-045: locale/<lang>/gestures.ini deve ter formato correto.

		Formato: secoes [module.ClassName] com entradas script = gesture.
		Exemplo:
		  [globalPlugins.meuAddon.GlobalPlugin]
		  script_anunciarStatus = kb:NVDA+shift+B

		Formato errado causa falha silenciosa — os gestos localizados nao sao carregados.

		Ref: nvda_developer_guide_2025.html — secao Locale Gesture Remapping.
		"""
		if not fluxo_report.success:
			pytest.skip("Pipeline nao concluiu")
		arquivos = _listar_arquivos(fluxo_report.addon_folder)
		gestures_files = [
			a for a in arquivos
			if re.match(r"locale/[^/]+/gestures\.ini", a, re.IGNORECASE)
		]
		if not gestures_files:
			pytest.skip("Addon gerado nao tem locale/<lang>/gestures.ini")
		violacoes: list[str] = []
		for rel_path in gestures_files:
			content = _ler_arquivo(fluxo_report.addon_folder, rel_path)
			# Verifica que tem pelo menos uma secao [module.ClassName]
			secoes = re.findall(r"^\[([^\]]+)\]", content, re.MULTILINE)
			if not secoes:
				violacoes.append(f"{rel_path}: sem secoes [module.ClassName]")
				continue
			# Verifica que entradas seguem o padrao script = gesture
			entradas = re.findall(r"^\s*(\w+)\s*=\s*(.+)$", content, re.MULTILINE)
			if not entradas:
				violacoes.append(f"{rel_path}: sem entradas script = gesture nas secoes")
		assert not violacoes, (
			"NVDA-045: gestures.ini com formato invalido:\n"
			+ "\n".join(violacoes)
			+ "\nFormato correto: secoes [module.ClassName] com script = gesture"
		)

	# ------------------------------------------------------------------
	# NVDA-046: CLI Arguments via addonHandler.isCLIParamKnown
	# ------------------------------------------------------------------

	def test_nvda046_cli_args_usa_is_cli_param_known(self, fluxo_report: FluxoReport):
		"""
		NVDA-046: Codigo que processa argumentos CLI deve usar
		addonHandler.isCLIParamKnown.register() em vez de acessar sys.argv diretamente.

		Acessar sys.argv diretamente em addons causa conflito com o parser de linha
		de comando do NVDA e pode provocar erros ao iniciar o NVDA com parametros
		desconhecidos pelo addon.

		Ref: nvda_developer_guide_2025.html — secao CLI Arguments.
		"""
		if not fluxo_report.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_codigo_principal(fluxo_report.addon_folder)
		tem_sys_argv = "sys.argv" in code
		if not tem_sys_argv:
			pytest.skip("Addon gerado nao acessa sys.argv")
		assert "isCLIParamKnown" in code, (
			"NVDA-046: codigo acessa sys.argv sem usar addonHandler.isCLIParamKnown.register(). "
			"Registre seus parametros CLI com isCLIParamKnown para integracao correta "
			"com o parser de linha de comando do NVDA."
		)
