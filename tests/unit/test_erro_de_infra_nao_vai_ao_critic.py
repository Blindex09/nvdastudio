"""Regressao: falha de infraestrutura era pontuada como se fosse conteudo.

Quando a chamada de LLM falha, `_base.py::_run_sub_agent` devolve
"[ERRO] Sub-agente nao conseguiu gerar resposta: ..." COMO SE fosse a resposta.
O orchestrator ja tinha `_IS_SUBAGENT_ERROR_RE` -- construida exatamente para
reconhecer isso, com correcao documentada de falso positivo (v4.1.1) -- mas so
a consultava no ramo de fallback de modelo. Quando o fallback tambem falhava,
o codigo registrava "fallback tambem falhou" e SEGUIA, sem nenhuma guarda ate
a chamada do Critic ~330 linhas adiante.

Medido em 2026-09-02 (rodada AssistenteEscrita): web_research escalou para
opencode_go, que esta sem saldo, e o Critic reprovou com score=0 escrevendo
"o output e apenas uma mensagem de erro de API (401 Unauthorized), sem nenhuma
informacao factual pesquisada". A BUSCA tinha funcionado (paralelo: 1/3 fontes,
exa); morreu a sintese, no provedor derrubado. O veredito culpava a pesquisa
por uma falha de conta.
"""
import inspect
import re

from nvdastudio.core import orchestrator as orch
from nvdastudio.core.orchestrator import Orchestrator, _IS_SUBAGENT_ERROR_RE
from nvdastudio.core.planner import ExecutionStep


def _step(step_id="s1", step_type="web_research"):
    return ExecutionStep(
        step_id=step_id, step_type=step_type, description="d", model_id="kimi-k2.6",
    )


def _fonte_do_metodo(nome: str) -> str:
    src = inspect.getsource(orch)
    i = src.index(f"def {nome}(")
    resto = src[i + 10:]
    fim = i + 10 + resto.index("\n\tdef ") if "\n\tdef " in resto else len(src)
    return src[i:fim]


class TestDeteccaoDoErro:
    def test_reconhece_a_string_que_base_devolve(self):
        real = "[ERRO] Sub-agente nao conseguiu gerar resposta: OpenCode Go Responses API falhou: 401 Unauthorized"
        assert _IS_SUBAGENT_ERROR_RE.search(real)

    def test_nao_confunde_codigo_gerado_com_erro(self):
        """Guarda ja existente (v4.1.1): a regex antiga batia em codigo que
        continha 'status == 503' e descartava output valido."""
        codigo = "def f():\n\tif resp.status_code == 503:\n\t\traise TimeoutError('timeout=30')\n"
        assert not _IS_SUBAGENT_ERROR_RE.search(codigo)

    def test_nao_bate_em_erro_no_meio_do_texto(self):
        """So o PREFIXO conta -- prosa citando '[ERRO]' nao e falha de infra."""
        assert not _IS_SUBAGENT_ERROR_RE.search("O guia explica o que fazer quando aparece [ERRO] na tela.")


class TestResultadoDeInfra:
    def _result(self, saida="[ERRO] Sub-agente nao conseguiu gerar resposta: 401 Unauthorized"):
        orch_obj = Orchestrator.__new__(Orchestrator)
        return orch_obj._infra_failure_result(_step(), saida, 1234, 2)

    def test_nao_aprovado(self):
        assert self._result().approved is False

    def test_nao_entrega_a_mensagem_de_erro_como_conteudo(self):
        """O output tem que ficar VAZIO: a string de erro nao pode virar
        contexto do proximo step nem texto do addon."""
        assert self._result().output == ""

    def test_registra_a_causa_real(self):
        issues = self._result().issues
        assert issues and "infraestrutura" in issues[0].lower()
        assert "401" in issues[0], "a causa concreta tem que sobreviver ao resumo"

    def test_preserva_tokens_e_retentativas(self):
        """O consumo aconteceu de verdade -- some do medidor se nao for contado."""
        r = self._result()
        assert r.tokens_used == 1234
        assert r.retries_used == 2

    def test_saida_vazia_ainda_produz_causa_legivel(self):
        issues = self._result("").issues
        assert issues and issues[0].strip()


class TestGuardaNoFluxo:
    def test_guarda_existe_antes_do_critic(self):
        fonte = inspect.getsource(orch)
        i_guarda = fonte.index("output e falha de infraestrutura, nao conteudo")
        i_critic = fonte.index("crit = self._critic.evaluate_two_stage", i_guarda - 20000)
        assert i_guarda < i_critic, "a guarda tem que vir ANTES da chamada do Critic"

    def test_consome_retentativa_em_vez_de_abortar(self):
        """Risco introduzido ao escrever este fix: um `return` direto abortaria
        as retentativas restantes e deixaria o pipeline MENOS resiliente do que
        era antes. O objetivo e nao pagar o Critic por uma mensagem de erro --
        nao desistir mais cedo."""
        fonte = inspect.getsource(orch)
        i = fonte.index("output e falha de infraestrutura, nao conteudo")
        trecho = fonte[i:i + 1500]
        assert "retries += 1" in trecho
        assert "continue" in trecho
        assert trecho.index("retries += 1") < trecho.index("_infra_failure_result")

    def test_so_desiste_na_ultima_tentativa(self):
        fonte = inspect.getsource(orch)
        i = fonte.index("output e falha de infraestrutura, nao conteudo")
        assert re.search(r"attempt < step\.max_retries - 1", fonte[i:i + 1500])


class TestRegexJaExistiaSemConsumidorNoFluxo:
    def test_regex_agora_e_consultada_fora_do_fallback(self):
        """O defeito era de LIGACAO, nao de deteccao: a peca certa existia e so
        era usada no ramo de fallback."""
        fonte = inspect.getsource(orch)
        assert fonte.count("_IS_SUBAGENT_ERROR_RE.search") >= 4
