from nvdastudio_mcp.nvda_context import NVDA_DETECTION_RULES, NVDA_GUIDE

_RULES_BY_ID = {rid: (severity, desc) for rid, severity, desc in NVDA_DETECTION_RULES}


class TestCincoRegrasNovas:
	def test_nvda_055_pip_bundlado_nao_e_api_estavel(self):
		assert "NVDA-055" in _RULES_BY_ID
		_, desc = _RULES_BY_ID["NVDA-055"]
		assert "api estavel" in desc.lower() or "nao sao api" in desc.lower()

	def test_nvda_056_messagedialog_thread_safety(self):
		assert "NVDA-056" in _RULES_BY_ID
		severity, desc = _RULES_BY_ID["NVDA-056"]
		assert severity == "Critico"
		assert "thread" in desc.lower() and "crash" in desc.lower()

	def test_nvda_057_scrcat_e_flags_do_script(self):
		assert "NVDA-057" in _RULES_BY_ID
		_, desc = _RULES_BY_ID["NVDA-057"]
		assert "SCRCAT_" in desc

	def test_nvda_058_installtasks_imports_minimos(self):
		assert "NVDA-058" in _RULES_BY_ID
		_, desc = _RULES_BY_ID["NVDA-058"]
		assert "installTasks" in desc or "uninstallTasks" in desc

	def test_nvda_059_addonid_regex_restrito(self):
		assert "NVDA-059" in _RULES_BY_ID
		_, desc = _RULES_BY_ID["NVDA-059"]
		assert "addonId" in desc or "letras, numeros" in desc.lower()

	def test_todas_tem_severidade_valida(self):
		validas = {"Critico", "Serio", "Moderado", "Menor"}
		for rid in ("NVDA-055", "NVDA-056", "NVDA-057", "NVDA-058", "NVDA-059"):
			severity, _ = _RULES_BY_ID[rid]
			assert severity in validas, f"{rid} tem severidade invalida: {severity}"


class TestReforcosDeRegrasExistentes:
	def test_nvda_010_menciona_as_3_formas_de_voltar_pra_gui_thread(self):
		_, desc = _RULES_BY_ID["NVDA-010"]
		assert "wx.CallAfter" in desc
		assert "wx.CallLater" in desc
		assert "wxCallOnMain" in desc

	def test_nvda_005_menciona_validacao_contra_versoes_reais(self):
		_, desc = _RULES_BY_ID["NVDA-005"]
		assert "nvdaAPIVersions" in desc


class TestOrdemDePropagacaoDeEvento:
	"""Prosa adicionada explicando os 4 estagios (GlobalPlugin -> AppModule ->
	TreeInterceptor -> NVDAObject) e a diferenca de assinatura por nivel."""

	def test_prompt_explica_os_4_estagios(self):
		assert "GlobalPlugin" in NVDA_GUIDE
		assert "TreeInterceptor" in NVDA_GUIDE
		assert "NVDAObject" in NVDA_GUIDE

	def test_prompt_explica_diferenca_de_assinatura(self):
		assert "nextHandler" in NVDA_GUIDE




