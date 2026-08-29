from nvdastudio.builder.nvda_context import NVDA_DETECTION_RULES, NVDA_SYSTEM_PROMPT

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
		assert "GlobalPlugin" in NVDA_SYSTEM_PROMPT
		assert "TreeInterceptor" in NVDA_SYSTEM_PROMPT
		assert "NVDAObject" in NVDA_SYSTEM_PROMPT

	def test_prompt_explica_diferenca_de_assinatura(self):
		assert "nextHandler" in NVDA_SYSTEM_PROMPT


class TestTotalDeRegrasAtualizado:
	def test_total_61_regras_nvda(self):
		"""61 apos NVDA-062 (secure mode, achado de auditoria 2026-08-04)."""
		assert len(NVDA_DETECTION_RULES) == 61

	def test_rule_registry_reflete_as_61(self):
		from nvdastudio.rule_registry import RULE_REGISTRY
		nvda_ids = [rid for rid in RULE_REGISTRY if rid.startswith("NVDA-") and not rid.startswith("NVDA-UX")]
		# Exclui aliases depreciados (ex: NVDA-041) da contagem de regras ativas
		ativos = [rid for rid in nvda_ids if RULE_REGISTRY[rid].status == "active"]
		assert len(ativos) == 61

	def test_novas_regras_aparecem_no_prompt_injetado(self):
		from nvdastudio.rule_registry import RULE_REGISTRY_PROMPT_TEXT
		for rid in ("NVDA-055", "NVDA-056", "NVDA-057", "NVDA-058", "NVDA-059"):
			assert rid in RULE_REGISTRY_PROMPT_TEXT


class TestNVDA062SecureMode:
	"""Achado de auditoria full-stack 2026-08-04: o catalogo de 61 regras nao
	tinha NENHUMA cobertura de secure mode (tela de login/UAC/tela segura) --
	uma exigencia real e atual de revisao da Add-on Store. Confirmado via
	pesquisa web (comunidade de addons + codigo-fonte nvaccess/nvda)."""

	def test_nvda_062_existe(self):
		assert "NVDA-062" in _RULES_BY_ID

	def test_nvda_062_menciona_o_flag_correto(self):
		_severity, desc = _RULES_BY_ID["NVDA-062"]
		assert "globalVars.appArgs.secure" in desc

	def test_nvda_062_alerta_sobre_scripts_de_classe(self):
		"""Pegadinha real documentada pela comunidade: checar o flag so no
		__init__ nao desativa scripts, definidos a nivel de classe."""
		_severity, desc = _RULES_BY_ID["NVDA-062"]
		assert "script" in desc.lower()

	def test_nvda_062_e_critico(self):
		severity, _desc = _RULES_BY_ID["NVDA-062"]
		assert severity == "Critico"

	def test_nvda_062_aparece_no_prompt_injetado(self):
		from nvdastudio.rule_registry import RULE_REGISTRY_PROMPT_TEXT
		assert "NVDA-062" in RULE_REGISTRY_PROMPT_TEXT

	def test_nvda_062_aparece_no_range_final_do_system_prompt(self):
		assert "NVDA-042..NVDA-062" in NVDA_SYSTEM_PROMPT
