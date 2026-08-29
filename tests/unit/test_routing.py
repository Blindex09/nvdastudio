from nvdastudio.core.planner import (
    ExecutionStep,
    apply_model_budget,
    resolve_step_model,
    STEP_CODE_GENERATION,
    STEP_SYNTAX_VALIDATION,
    STEP_DESIGN_REVIEW,
    STEP_DOCUMENTATION,
)
from nvdastudio.ai.model_registry import (
    clear_model_resolution_cache,
    get_provider_step_models,
    resolve_provider_tier_model,
)

def test_resolve_step_model_heavy_and_light():
    # OpenAI provider routing
    openai_models = get_provider_step_models("openai")
    assert resolve_step_model(STEP_CODE_GENERATION, "openai") == openai_models["heavy"]
    assert resolve_step_model(STEP_DESIGN_REVIEW, "openai") == openai_models["light"]
    assert resolve_step_model(STEP_SYNTAX_VALIDATION, "openai") == openai_models["light"]
    assert resolve_step_model(STEP_DOCUMENTATION, "openai") == openai_models["light"]

    # Anthropic provider routing
    anthropic_models = get_provider_step_models("anthropic")
    assert resolve_step_model(STEP_CODE_GENERATION, "anthropic") == anthropic_models["heavy"]
    assert resolve_step_model(STEP_SYNTAX_VALIDATION, "anthropic") == anthropic_models["light"]

    # Google Gemini provider routing
    google_models = get_provider_step_models("google")
    assert resolve_step_model(STEP_CODE_GENERATION, "google") == google_models["heavy"]
    assert resolve_step_model(STEP_SYNTAX_VALIDATION, "google") == google_models["light"]

    # xAI provider routing
    xai_models = get_provider_step_models("xai")
    assert resolve_step_model(STEP_CODE_GENERATION, "xai") == xai_models["heavy"]
    assert resolve_step_model(STEP_SYNTAX_VALIDATION, "xai") == xai_models["light"]

    # Ollama provider routing
    ollama_models = get_provider_step_models("ollama")
    assert resolve_step_model(STEP_CODE_GENERATION, "ollama") == ollama_models["heavy"]
    assert resolve_step_model(STEP_SYNTAX_VALIDATION, "ollama") == ollama_models["light"]


def test_configured_model_overrides_heavy_and_light():
    assert resolve_step_model(STEP_CODE_GENERATION, "openai", "gpt-custom") == "gpt-custom"
    assert resolve_step_model(STEP_SYNTAX_VALIDATION, "openai", "gpt-custom") == "gpt-custom"


def test_env_override_for_tier(monkeypatch):
    monkeypatch.setenv("NVDASTUDIO_OPENAI_HEAVY_MODEL", "gpt-heavy-local")
    assert resolve_provider_tier_model("openai", "heavy", "alto") == "gpt-heavy-local"
    assert resolve_step_model(STEP_CODE_GENERATION, "openai") == "gpt-heavy-local"


def test_alto_usa_registry_auditado_do_provider():
    clear_model_resolution_cache()
    assert resolve_provider_tier_model("openai", "heavy", "alto") == "gpt-5.6-sol"
    assert resolve_provider_tier_model("xai", "light", "alto") == "grok-4.3"


def test_xai_heavy_tier_e_grok_build():
    """v1.6.0: grok-build-0.1 (modelo xAI dedicado a coding agentico) vira
    o tier heavy do xAI -- mesmo raciocinio de kimi-k2.7-code no Ollama,
    ja que _HEAVY_STEPS so cobre code_generation."""
    clear_model_resolution_cache()
    assert resolve_provider_tier_model("xai", "heavy", "alto") == "grok-build-0.1"
    assert resolve_step_model(STEP_CODE_GENERATION, "xai") == "grok-build-0.1"


def test_xai_fallback_chain_inclui_grok_build_primeiro():
    from nvdastudio.ai.model_registry import registry
    chain = registry.get_fallback_chain("grok-build-0.1")
    assert chain[0] == "grok-build-0.1"
    assert "grok-4.5" in chain


def test_alto_mantem_oitenta_por_cento_das_etapas_no_modelo_leve():
    """planner.py 2.23.0: apply_model_budget() pontua (ai/model_router.py)
    em vez de escolher sempre o mesmo model_id fixo por tier -- a
    IDENTIDADE do modelo elevado pode variar (o melhor pontuado pra
    complexity="medium", nao necessariamente sempre "gpt-5.6-sol"), mas o
    PERCENTUAL (2 de 10 elevados) continua igual.

    model_router.py 1.3.0 (custo real $/token): contar por STRING (quantos
    steps tem model_id == elevated_model) ficou fragil -- com custo real,
    o modelo "leve" (complexity="low") de um step FORA do orcamento pode
    coincidentemente resolver pro MESMO modelo do slot elevado (nao e uma
    violacao do orcamento, so as 2 escolhas pontuarem igual). O invariante
    real e sobre QUAIS steps foram deliberadamente sobrescritos pelo
    orcamento -- exatamente os primeiros heavy_budget candidates de
    code_generation (candidates[:heavy_budget] em apply_model_budget)."""
    from nvdastudio.ai.model_router import select_model
    steps = [
        ExecutionStep(f"s{i}", "code_generation" if i < 3 else "documentation", "tarefa", "alto")
        for i in range(10)
    ]
    apply_model_budget(steps, "openai", "alto")
    elevated_model = select_model("openai", STEP_CODE_GENERATION, "alto", complexity="medium")
    heavy_budget = 2  # floor(10 * 0.20), complexity default "medium"
    code_gen_steps = [s for s in steps if s.step_type == "code_generation"]
    assert all(step.model_id == elevated_model for step in code_gen_steps[:heavy_budget]), (
        "os primeiros heavy_budget candidates de code_generation devem ser "
        "deliberadamente sobrescritos pro modelo elevado."
    )


class TestCostScoreComPrecoRealDoToken:
    """
    model_router.py 1.3.0: _cost_score() ganha custo real $/token
    (model_pricing.py), motivado por comparacao direta com C:\\agentic e
    pedido do Felipe ("traz custo real em $/token igual o agentic"). Faixa
    CHEIA [0,1] (nao reescalada) -- achado real ao vivo: uma primeira versao
    reescalada pra [0.45, 0.85] comprimia demais a diferenca real entre
    modelo caro/barato, quebrando o orcamento de apply_model_budget()
    (ver test_alto_mantem_oitenta_por_cento_das_etapas_no_modelo_leve acima).
    """

    def test_modelo_mais_barato_pontua_mais_que_mais_caro(self):
        from nvdastudio.ai.model_router import _cost_score
        # gpt-5.6-luna ($1/$6) e bem mais barato que gpt-5.6-sol ($5/$30).
        barato = _cost_score("openai", "gpt-5.6-luna")
        caro = _cost_score("openai", "gpt-5.6-sol")
        assert barato > caro

    def test_cost_score_fica_na_faixa_zero_um(self):
        from nvdastudio.ai.model_router import _cost_score
        for provider, model_id in [
            ("openai", "gpt-5.6-sol"), ("openai", "gpt-5.6-luna"),
            ("anthropic", "claude-opus-5"), ("anthropic", "claude-haiku-4-5"),
        ]:
            score = _cost_score(provider, model_id)
            assert 0.0 <= score <= 1.0, f"{provider}/{model_id}: score={score} fora de [0,1]"

    def test_ollama_sem_preco_real_usa_cost_tier_antigo(self):
        """Sem preco catalogado (Ollama e assinatura), _cost_score() deve
        cair pro cost_tier curado -- mesmo valor de antes da 1.3.0, nao a
        formula de custo real (que trataria $0 uniforme e apagaria a
        diferenciacao entre modelos Ollama)."""
        from nvdastudio.ai.model_router import _cost_score, _COST_TIER_SCORE
        from nvdastudio.ai.model_registry import registry
        info = registry.get_model_info("qwen3.5:397b")
        assert info is not None
        expected = _COST_TIER_SCORE.get(info.cost_tier, 0.6)
        assert _cost_score("ollama", "qwen3.5:397b") == expected

    def test_modelo_openai_nao_catalogado_usa_cost_tier_antigo(self):
        """Provider pago mas modelo sem preco pesquisado (ex: gpt-5.4-mini,
        nao pesquisado nesta rodada) tambem cai pro fallback -- nunca $0
        nem quebra."""
        from nvdastudio.ai.model_router import _cost_score, _COST_TIER_SCORE
        from nvdastudio.ai.model_registry import registry
        info = registry.get_model_info("gpt-5.4-mini")
        tier = info.cost_tier if info else "medium"
        assert _cost_score("openai", "gpt-5.4-mini") == _COST_TIER_SCORE.get(tier, 0.6)
