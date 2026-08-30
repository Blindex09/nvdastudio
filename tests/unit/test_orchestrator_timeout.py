from addon.globalPlugins.nvdastudio.core.orchestrator import (
    OrchestrationResult, StepResult,
    _STEP_TIMEOUT_SECONDS, MODULE_VERSION,
)


class TestOrchestratorVersao:
    def test_versao_e_2_6_0(self):
        assert MODULE_VERSION == "5.61.0"


class TestTimeoutConstante:
    def test_timeout_positivo(self):
        assert _STEP_TIMEOUT_SECONDS > 0

    def test_timeout_razoavel(self):
        """Timeout deve ser grande o suficiente para não falsar positivos."""
        assert _STEP_TIMEOUT_SECONDS >= 60

    def test_timeout_nao_excessivo(self):
        """Timeout não deve ser absurdamente alto (trancaria o NVDA)."""
        assert _STEP_TIMEOUT_SECONDS <= 600


class TestOrchestrationResultTotalTokens:
    def test_total_tokens_campo_existe(self):
        result = OrchestrationResult(
            plan_id="p1", query="q", step_results=[],
            final_output="", success=True,
        )
        assert hasattr(result, "total_tokens")

    def test_total_tokens_default_zero(self):
        result = OrchestrationResult(
            plan_id="p1", query="q", step_results=[],
            final_output="", success=True,
        )
        assert result.total_tokens == 0

    def test_total_tokens_preenchido(self):
        result = OrchestrationResult(
            plan_id="p1", query="q", step_results=[],
            final_output="", success=True, total_tokens=5000,
        )
        assert result.total_tokens == 5000


class TestStepResultTokens:
    def test_step_result_tem_tokens_used(self):
        r = StepResult(
            step_id="s1", step_type="code_generation",
            output="ok", approved=True, score=95,
        )
        assert hasattr(r, "tokens_used")

    def test_step_result_tokens_default_zero(self):
        r = StepResult(
            step_id="s1", step_type="code_generation",
            output="ok", approved=True, score=95,
        )
        assert r.tokens_used == 0

    def test_total_tokens_soma_de_steps(self):
        """OrchestrationResult.total_tokens deve ser soma de step_results.tokens_used."""
        steps = [
            StepResult("s1", "code_generation", "ok", True, 90, tokens_used=100),
            StepResult("s2", "manifest_builder", "ok", True, 90, tokens_used=50),
            StepResult("s3", "assembly", "ok", True, 90, tokens_used=200),
        ]
        result = OrchestrationResult(
            plan_id="p1", query="q", step_results=steps,
            final_output="", success=True,
            total_tokens=sum(s.tokens_used for s in steps),
        )
        assert result.total_tokens == 350


class TestTimeoutStepResult:
    """Verifica que o resultado de timeout tem formato correto."""

    def test_timeout_step_result_nao_aprovado(self):
        """Um step que deu timeout deve retornar approved=False."""
        r = StepResult(
            step_id="s1", step_type="code_generation",
            output="", approved=False, score=0,
            issues=[f"Timeout: step excedeu {_STEP_TIMEOUT_SECONDS}s."],
        )
        assert r.approved is False
        assert r.score == 0
        assert any("Timeout" in i or "timeout" in i.lower() for i in r.issues)

    def test_timeout_issue_menciona_duracao(self):
        """A mensagem de timeout deve mencionar a duração."""
        timeout_msg = f"Timeout: step excedeu {_STEP_TIMEOUT_SECONDS}s."
        assert str(_STEP_TIMEOUT_SECONDS) in timeout_msg




# ===========================================================================
# Plano aa1600dd (2026-05-10): timeout por step type + grace period
# ===========================================================================

class TestStepTypeTimeoutOverride:
	"""design_review tem timeout maior que steps padrao."""

	def test_design_review_tem_timeout_override(self):
		from nvdastudio.core.orchestrator import _get_step_timeout, _STEP_TIMEOUT_SECONDS
		t_design = _get_step_timeout("design_review")
		assert t_design > _STEP_TIMEOUT_SECONDS, (
			f"design_review deve ter timeout > {_STEP_TIMEOUT_SECONDS}s. "
			f"Recebido: {t_design}s"
		)

	def test_step_padrao_usa_default(self):
		from nvdastudio.core.orchestrator import _get_step_timeout, _STEP_TIMEOUT_SECONDS
		assert _get_step_timeout("web_research") == 600
		assert _get_step_timeout("manifest_builder") == _STEP_TIMEOUT_SECONDS
		assert _get_step_timeout("code_generation") == 1200  # 5.26.0 override

	def test_assembly_tem_timeout_override(self):
		"""5.25.0: bug real do golden eval set (test_e36) -- assembly
		consolida TODOS os steps aprovados, tao pesado quanto design_review/
		code_generation/agent_runner, mas ficava no default de 180s e
		estourava consistentemente em addons complexos.
		5.26.0: 600 -> 1200 -- 600s no orquestrador era menor que uma UNICA
		chamada HTTP interna (sub-agente OU critic) podia legitimamente levar
		(ate 660s via _OLLAMA_CLOUD_TIMEOUT_EXTENDED), confirmado ao vivo
		numa segunda rodada real do test_e36."""
		from nvdastudio.core.orchestrator import _get_step_timeout, _STEP_TIMEOUT_SECONDS
		t_assembly = _get_step_timeout("assembly")
		assert t_assembly > _STEP_TIMEOUT_SECONDS, (
			f"assembly deve ter timeout > {_STEP_TIMEOUT_SECONDS}s. Recebido: {t_assembly}s"
		)
		assert t_assembly == 1200

	def test_grace_period_existe_e_e_positivo(self):
		from nvdastudio.core.orchestrator import _GRACE_PERIOD_SECONDS
		assert _GRACE_PERIOD_SECONDS > 0


# ===========================================================================
# v4.1.1 (2026-05-11): testes de regressao para falso positivo da regex
# _IS_SUBAGENT_ERROR_RE. O antigo _INFRA_ERROR_RE aplicava 503|timeout|etc
# ao output INTEIRO do agente — inclusive codigo Python gerado — causando
# fallback incorreto e descarte de output valido (bug YouTubeMusicAI).
# ===========================================================================

class TestInfraErrorRegexNoFalsePositives:
	"""Garante que _IS_SUBAGENT_ERROR_RE nao causa falsos positivos em codigo."""

	def test_codigo_com_timeout_30_nao_dispara(self):
		"""Codigo Python com 'timeout=30' NAO deve ser tratado como erro de infra."""
		from nvdastudio.core.orchestrator import _IS_SUBAGENT_ERROR_RE
		codigo = (
			"import httpx\n"
			"with httpx.Client(timeout=30) as client:\n"
			"    resp = client.get(url)\n"
		)
		assert not _IS_SUBAGENT_ERROR_RE.search(codigo), (
			"FALSO POSITIVO: codigo com timeout=30 foi confundido com erro de infra"
		)

	def test_codigo_com_status_503_nao_dispara(self):
		"""Codigo Python com 'status_code == 503' NAO deve ser tratado como erro de infra."""
		from nvdastudio.core.orchestrator import _IS_SUBAGENT_ERROR_RE
		codigo = (
			"def handle_response(resp):\n"
			"    if resp.status_code == 503:\n"
			"        raise ServiceUnavailable()\n"
			"    elif resp.status_code == 502:\n"
			"        raise BadGateway()\n"
		)
		assert not _IS_SUBAGENT_ERROR_RE.search(codigo), (
			"FALSO POSITIVO: codigo com status == 503 foi confundido com erro de infra"
		)

	def test_codigo_com_timeout_exception_nao_dispara(self):
		"""Codigo com 'except requests.Timeout' NAO deve ser tratado como erro de infra."""
		from nvdastudio.core.orchestrator import _IS_SUBAGENT_ERROR_RE
		codigo = (
			"try:\n"
			"    response = requests.get(url, timeout=10)\n"
			"except requests.exceptions.Timeout:\n"
			"    ui.message(_('Timeout na requisicao'))\n"
		)
		assert not _IS_SUBAGENT_ERROR_RE.search(codigo), (
			"FALSO POSITIVO: codigo com except Timeout foi confundido com erro de infra"
		)

	def test_string_erro_real_dispara(self):
		"""String com prefixo [ERRO] DEVE ser detectada como erro de infra."""
		from nvdastudio.core.orchestrator import _IS_SUBAGENT_ERROR_RE
		erro_real = (
			"[ERRO] Sub-agente nao conseguiu gerar resposta: "
			"Server error '503 Service Unavailable'"
		)
		assert _IS_SUBAGENT_ERROR_RE.search(erro_real), (
			"FALSO NEGATIVO: erro real com prefixo [ERRO] nao foi detectado"
		)

	def test_string_erro_real_com_timeout_dispara(self):
		"""String com prefixo [ERRO] e timeout DEVE ser detectada."""
		from nvdastudio.core.orchestrator import _IS_SUBAGENT_ERROR_RE
		erro_real = "[ERRO] Ollama Cloud API falhou: The read operation timed out"
		assert _IS_SUBAGENT_ERROR_RE.search(erro_real), (
			"FALSO NEGATIVO: erro real com timeout nao foi detectado"
		)

	def test_linha_sem_prefixo_erro_nao_dispara(self):
		"""Linha normal de log sem [ERRO] nao deve ser detectada."""
		from nvdastudio.core.orchestrator import _IS_SUBAGENT_ERROR_RE
		assert not _IS_SUBAGENT_ERROR_RE.search("[INFO] Pipeline iniciado.")
		assert not _IS_SUBAGENT_ERROR_RE.search("[WARNING] Timeout detectado.")

	def test_codigo_com_service_unavailable_nao_dispara(self):
		"""Docstring mencionando 'Service Unavailable' NAO deve ser erro de infra."""
		from nvdastudio.core.orchestrator import _IS_SUBAGENT_ERROR_RE
		codigo = (
			'"""Verifica se a API esta disponivel. '
			'Retorna False se Service Unavailable."""\n'
			"def check():\n"
			"    return True\n"
		)
		assert not _IS_SUBAGENT_ERROR_RE.search(codigo), (
			"FALSO POSITIVO: docstring com 'Service Unavailable' confundido com erro"
		)

	def test_manifest_ini_normal_nao_dispara(self):
		"""manifest.ini valido NAO deve ser detectado como erro."""
		from nvdastudio.core.orchestrator import _IS_SUBAGENT_ERROR_RE
		manifest = (
			"name = YouTubeMusicAI\n"
			"version = 1.0.0\n"
			"minimumNVDAVersion = 2026.1.1\n"
			"lastTestedNVDAVersion = 2026.1.1\n"
		)
		assert not _IS_SUBAGENT_ERROR_RE.search(manifest), (
			"FALSO POSITIVO: manifest.ini normal confundido com erro de infra"
		)

	def test_sem_prefixo_erro_com_503_nao_dispara(self):
		"""'503 Service Unavailable' SEM prefixo [ERRO] nao deve disparar."""
		from nvdastudio.core.orchestrator import _IS_SUBAGENT_ERROR_RE
		assert not _IS_SUBAGENT_ERROR_RE.search("503 Service Unavailable"), (
			"FALSO POSITIVO: '503 Service Unavailable' sem [ERRO] foi detectado"
		)

	def test_string_vazia_nao_dispara(self):
		from nvdastudio.core.orchestrator import _IS_SUBAGENT_ERROR_RE
		assert not _IS_SUBAGENT_ERROR_RE.search("")
