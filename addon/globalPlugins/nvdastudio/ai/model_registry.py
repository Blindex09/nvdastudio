from dataclasses import dataclass, field
from enum import Enum
import os
from typing import Optional

from ..utils.logger import get_logger

MODULE_VERSION = "1.19.0"
_logger = get_logger("model_registry")

ALTO_MODEL = "alto"
_ALTO_SENTINELS = {"", ALTO_MODEL}

# Fabricantes cujos modelos sao servidos via Ollama Cloud (mesmo endpoint/
# chave que kimi/deepseek), nao via API propria do fabricante. Usado tanto
# pro fold de fallback chain quanto pra montar a lista de modelos do
# provedor "ollama" na UI -- fonte unica (Regra 5 do README), antes cada
# consumidor tinha sua propria lista hardcoded que desalinhava sozinha.
_OLLAMA_SERVED_MAKERS: frozenset = frozenset({
	"moonshot", "deepseek", "zhipu", "minimax", "openai_oss",
	# 1.15.0: catalogo real da conta (GET https://ollama.com/api/tags,
	# 2026-08-08) tinha 8 fabricantes nunca registrados aqui.
	"alibaba", "nvidia", "mistral", "google_oss",
})

# 2026-08-16: catalogo real da conta reverificado (GET https://ollama.com/
# api/tags) -- os 16 modelos acima ja cobrem TODOS os fabricantes/familias
# ativos, incluindo os mais recentes (deepseek-v4-flash:0731, deepseek-v4-
# pro:0813). Um modelo novo real apareceu no catalogo, "kimi-k3" (sucessor
# de kimi-k2.x, ganhou capability "vision"), mas foi DELIBERADAMENTE
# deixado de fora por pedido explicito do Felipe: consome creditos de uso
# que a assinatura atual dele nao cobre. Nao adicionar sem confirmar
# antes que o plano mudou.

# Mapeia o codigo de provedor usado na UI (settings_panel.py) pros valores
# reais de ModelInfo.provider que devem aparecer sob aquele provedor.
# "gemini" e alias de "google" (mesmo provedor, 2 nomes historicos na UI).
_UI_PROVIDER_TO_REGISTRY_PROVIDERS: dict[str, tuple[str, ...]] = {
    "ollama": tuple(_OLLAMA_SERVED_MAKERS),
    "anthropic": ("anthropic",),
    "openai": ("openai",),
    "google": ("google",),
    "gemini": ("google",),
    "xai": ("xai",),
    "opencode_go": ("opencode_go",),
}


class ModelStatus(Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"
    PREVIEW = "preview"


@dataclass
class ModelInfo:
    """Informacao sobre um modelo LLM."""
    model_id: str
    provider: str
    status: ModelStatus
    description: str
    capabilities: list[str] = field(default_factory=list)
    deprecated_since: str = ""
    migration_target: str = ""
    cost_tier: str = "medium"  # low, medium, high
    context_window: int = 0  # tokens de INPUT; 0 = nao confirmado por pesquisa dedicada


# ---------------------------------------------------------------------------
# Registro de modelos — atualizado em Maio 2026
# Fontes: docs.anthropic.com, platform.openai.com, ai.google.dev
# ---------------------------------------------------------------------------

_MODEL_REGISTRY: dict[str, ModelInfo] = {
    # --- Claude / Anthropic ---
    "claude-opus-5": ModelInfo(
        model_id="claude-opus-5",
        provider="anthropic",
        status=ModelStatus.ACTIVE,
        description="Modelo near-frontier default -- coding agentico complexo e trabalho empresarial, metade do custo de claude-fable-5",
        capabilities=["adaptive_thinking", "tool_use", "vision", "1M_context", "128k_output"],
        cost_tier="high",
        context_window=1_000_000,
    ),
    "claude-opus-4-8": ModelInfo(
        model_id="claude-opus-4-8",
        provider="anthropic",
        status=ModelStatus.DEPRECATED,
        description="Substituido por claude-opus-5",
        capabilities=["adaptive_thinking", "tool_use", "vision", "1M_context", "128k_output"],
        deprecated_since="2026-08",
        migration_target="claude-opus-5",
        cost_tier="high",
        context_window=1_000_000,
    ),
    "claude-sonnet-5": ModelInfo(
        model_id="claude-sonnet-5",
        provider="anthropic",
        status=ModelStatus.ACTIVE,
        description="Equilibrio atual entre velocidade e inteligencia",
        capabilities=["adaptive_thinking", "tool_use", "vision", "1M_context", "128k_output"],
        cost_tier="medium",
        context_window=1_000_000,
    ),
    "claude-opus-4-7": ModelInfo(
        model_id="claude-opus-4-7",
        provider="anthropic",
        status=ModelStatus.DEPRECATED,
        description="Substituido por claude-opus-4-8, por sua vez substituido por claude-opus-5",
        capabilities=["thinking", "tool_use", "vision", "1M_context", "128k_output"],
        deprecated_since="2026-07",
        migration_target="claude-opus-5",
        cost_tier="high",
    ),
    "claude-sonnet-4-6": ModelInfo(
        model_id="claude-sonnet-4-6",
        provider="anthropic",
        status=ModelStatus.DEPRECATED,
        description="Substituido por claude-sonnet-5",
        capabilities=["thinking", "tool_use", "vision", "1M_context", "64k_output"],
        deprecated_since="2026-07",
        migration_target="claude-sonnet-5",
        cost_tier="medium",
    ),
    "claude-haiku-4-5": ModelInfo(
        model_id="claude-haiku-4-5",
        provider="anthropic",
        status=ModelStatus.ACTIVE,
        description="Modelo mais rapido com inteligencia near-frontier",
        capabilities=["thinking", "tool_use", "vision", "200k_context", "64k_output"],
        cost_tier="low",
        context_window=200_000,
    ),
    "claude-opus-4": ModelInfo(
        model_id="claude-opus-4",
        provider="anthropic",
        status=ModelStatus.DEPRECATED,
        description="Substituido por claude-opus-4-7",
        deprecated_since="2026-03",
        migration_target="claude-opus-4-7",
        cost_tier="high",
    ),
    "claude-sonnet-4": ModelInfo(
        model_id="claude-sonnet-4",
        provider="anthropic",
        status=ModelStatus.DEPRECATED,
        description="Substituido por claude-sonnet-4-6",
        deprecated_since="2026-03",
        migration_target="claude-sonnet-4-6",
        cost_tier="medium",
    ),

    # --- OpenAI / GPT ---
    "gpt-5.6-sol": ModelInfo(
        model_id="gpt-5.6-sol", provider="openai", status=ModelStatus.ACTIVE,
        description="Flagship para raciocinio complexo e coding",
        capabilities=["reasoning", "tools", "vision", "1M_context", "128k_output"], cost_tier="high",
        context_window=1_050_000,
    ),
    "gpt-5.6-terra": ModelInfo(
        model_id="gpt-5.6-terra", provider="openai", status=ModelStatus.ACTIVE,
        description="Equilibrio entre inteligencia e custo",
        capabilities=["reasoning", "tools", "vision", "1M_context", "128k_output"], cost_tier="medium",
        context_window=1_050_000,
    ),
    "gpt-5.6-luna": ModelInfo(
        model_id="gpt-5.6-luna", provider="openai", status=ModelStatus.ACTIVE,
        description="Modelo atual para alto volume sensivel a custo",
        capabilities=["reasoning", "tools", "vision", "1M_context", "128k_output"], cost_tier="low",
        context_window=1_050_000,
    ),
    "gpt-5.5": ModelInfo(
        model_id="gpt-5.5",
        provider="openai",
        status=ModelStatus.DEPRECATED,
        description="Substituido por gpt-5.6-sol",
        capabilities=["reasoning", "tools", "web_search", "file_search", "computer_use", "1M_context", "128k_output"],
        deprecated_since="2026-07",
        migration_target="gpt-5.6-sol",
        cost_tier="high",
    ),
    "gpt-5.4": ModelInfo(
        model_id="gpt-5.4",
        provider="openai",
        status=ModelStatus.DEPRECATED,
        description="Substituido por gpt-5.6-terra",
        capabilities=["reasoning", "tools", "web_search", "file_search", "computer_use", "1M_context", "128k_output"],
        deprecated_since="2026-07",
        migration_target="gpt-5.6-terra",
        cost_tier="medium",
    ),
    "gpt-5.4-mini": ModelInfo(
        model_id="gpt-5.4-mini",
        provider="openai",
        status=ModelStatus.DEPRECATED,
        description="Substituido por gpt-5.6-luna",
        capabilities=["reasoning", "tools", "web_search", "file_search", "computer_use", "400k_context", "128k_output"],
        deprecated_since="2026-07",
        migration_target="gpt-5.6-luna",
        cost_tier="low",
    ),

    # --- Google / Gemini ---
    "gemini-3.1-pro-preview": ModelInfo(
        model_id="gemini-3.1-pro-preview",
        provider="google",
        status=ModelStatus.PREVIEW,
        # Achado de teste E2E real ao vivo (2026-08-04): este model_id
        # retorna HTTP 404 "Model not found" na API real (confirmado via
        # GET /v1/models com chave real -- listagem completa nao inclui
        # NENHUM tier "pro" da linha 3.x, so flash/flash-lite; o unico "pro"
        # realmente disponivel e gemini-2.5-pro). Nao e erro de permissao
        # (403 seria o codigo pra isso) -- o model_id genuinamente nao
        # existe no catalogo publico ainda, apesar de anunciado. Estava
        # sendo usado como default do tier "heavy" (_PROVIDER_TIER_MODELS),
        # entao TODA chamada heavy do Gemini falhava 404 em producao.
        # Roteamento corrigido pra gemini-2.5-pro (real, confirmado ao vivo)
        # ate este model_id realmente existir na API.
        description="Inteligencia avancada, habilidades complexas e coding agentivo -- ANUNCIADO mas retorna 404 na API real (2026-08-04); nao usar como default ate confirmacao",
        capabilities=["thinking", "tool_use", "vision", "audio", "video", "1M_context"],
        cost_tier="high",
        context_window=1_000_000,
    ),
    "gemini-3.6-flash": ModelInfo(
        model_id="gemini-3.6-flash",
        provider="google",
        status=ModelStatus.ACTIVE,
        description="Estavel (GA), equilibra velocidade e inteligencia em tarefas agenticas/multimodais; sucessor pratico de gemini-3.5-flash como tier leve padrao",
        capabilities=["thinking", "tool_use", "vision", "audio", "1M_context"],
        cost_tier="low",
        context_window=1_048_576,
    ),
    "gemini-3.5-flash": ModelInfo(
        model_id="gemini-3.5-flash",
        provider="google",
        status=ModelStatus.ACTIVE,
        description="Estavel, mais inteligente da linha 3.5 para coding/tarefas agenticas sustentadas -- nao deprecated, so deixou de ser o tier leve padrao (ver gemini-3.6-flash)",
        capabilities=["thinking", "tool_use", "vision", "audio", "1M_context"],
        cost_tier="low",
        context_window=1_048_576,  # mesma familia/geracao do 3.6-flash; janela exata do 3.5-flash nao teve fonte dedicada
    ),
    "gemini-3.5-flash-lite": ModelInfo(
        model_id="gemini-3.5-flash-lite",
        provider="google",
        status=ModelStatus.ACTIVE,
        description="Mais rapido e barato da linha 3.5 -- sucessor pratico de gemini-3.1-flash-lite",
        capabilities=["thinking", "tool_use", "vision", "audio", "1M_context"],
        cost_tier="low",
        context_window=1_048_576,  # idem
    ),
    "gemini-3.1-flash-lite": ModelInfo(
        model_id="gemini-3.1-flash-lite",
        provider="google",
        status=ModelStatus.ACTIVE,
        description="Modelo leve de baixa latencia para tarefas simples -- ver gemini-3.5-flash-lite (mais recente, mesma faixa de custo)",
        capabilities=["thinking", "tool_use", "vision", "audio", "1M_context"],
        cost_tier="low",
        context_window=1_000_000,
    ),
    "gemini-3-flash-preview": ModelInfo(
        model_id="gemini-3-flash-preview",
        provider="google",
        status=ModelStatus.DEPRECATED,
        description="Substituido por gemini-3.5-flash (GA)",
        capabilities=["thinking", "tool_use", "vision", "audio", "1M_context"],
        deprecated_since="2026-07",
        migration_target="gemini-3.5-flash",
        cost_tier="low",
    ),
    "gemini-2.5-pro": ModelInfo(
        model_id="gemini-2.5-pro",
        provider="google",
        # Re-promovido a ACTIVE (achado de teste E2E real ao vivo, 2026-08-04):
        # estava marcado DEPRECATED com migration_target=gemini-3.1-pro-preview,
        # mas esse model_id retorna 404 na API real -- confirmado via GET
        # /v1/models que gemini-2.5-pro e o UNICO tier "pro" genuinamente
        # disponivel hoje. Volta a ser o default do tier "heavy" ate
        # gemini-3.1-pro-preview realmente existir na API.
        status=ModelStatus.ACTIVE,
        description="Unico tier 'pro' confirmado disponivel na API real (2026-08-04) -- gemini-3.1-pro-preview esta anunciado mas retorna 404",
        capabilities=["thinking", "tool_use", "vision", "audio", "1M_context"],
        cost_tier="high",
    ),
    "gemini-2.5-flash": ModelInfo(
        model_id="gemini-2.5-flash",
        provider="google",
        status=ModelStatus.DEPRECATED,
        description="Substituido por gemini-3.5-flash",
        capabilities=["thinking", "tool_use", "vision", "audio", "1M_context"],
        deprecated_since="2026-07",
        migration_target="gemini-3.5-flash",
        cost_tier="low",
    ),
    "gemini-3-pro-preview": ModelInfo(
        model_id="gemini-3-pro-preview",
        provider="google",
        status=ModelStatus.RETIRED,
        # migration_target atualizado 2026-08-04: apontava pra
        # gemini-3.1-pro-preview, que retorna 404 na API real (ver nota em
        # gemini-2.5-pro/gemini-3.1-pro-preview acima).
        description="DESLIGADO em 9 Marco 2026. Migre para gemini-2.5-pro",
        deprecated_since="2026-03-09",
        migration_target="gemini-2.5-pro",
        cost_tier="high",
    ),
    "gemini-2.0-flash": ModelInfo(
        model_id="gemini-2.0-flash",
        provider="google",
        status=ModelStatus.DEPRECATED,
        description="Substituido por gemini-2.5-flash",
        deprecated_since="2026-03",
        migration_target="gemini-2.5-flash",
        cost_tier="low",
    ),

    # --- Ollama Cloud ---
    "kimi-k2.7-code": ModelInfo(
        model_id="kimi-k2.7-code",
        provider="moonshot",
        status=ModelStatus.ACTIVE,
        description="Modelo principal do NVDAStudio (tier heavy) — sucessor de kimi-k2.6 focado em coding agentico",
        # json_schema removido da lista (2026-08-26): servido via Ollama Cloud,
        # onde json_schema estrito NAO e honrado de verdade (auditoria ao vivo,
        # ver STRUCTURED_OUTPUT_MODEL_CHAIN abaixo) -- so via OpenCode Go.
        capabilities=["thinking", "tool_use"],
        # cost_tier corrigido de "medium" pra "high" (pesquisa dedicada
        # 2026-08-17, ollama.com/library/kimi-k2.7-code): pagina oficial
        # mostra "Usage: high", 1.04T parametros -- estava subestimado.
        cost_tier="high",
        context_window=256_000,
    ),
    "kimi-k2.6": ModelInfo(
        model_id="kimi-k2.6",
        provider="moonshot",
        status=ModelStatus.ACTIVE,
        description="Antigo padrao do tier heavy — substituido por kimi-k2.7-code, ainda ativo (fallback)",
        # json_schema removido da lista (2026-08-26): mesmo motivo do kimi-k2.7-code acima.
        capabilities=["thinking", "tool_use"],
        # cost_tier corrigido de "medium" pra "high" (pesquisa dedicada
        # 2026-08-17, ollama.com/library/kimi-k2.6): "Usage: high", 1.04T
        # parametros -- mesma correcao do kimi-k2.7-code.
        cost_tier="high",
        context_window=256_000,
    ),
    "deepseek-v4-flash": ModelInfo(
        model_id="deepseek-v4-flash",
        provider="deepseek",
        status=ModelStatus.ACTIVE,
        description="Modelo rapido para criticas, revisoes e fallback",
        capabilities=["json_object"],
        # cost_tier corrigido de "low" pra "medium" (pesquisa dedicada
        # 2026-08-17, ollama.com/library/deepseek-v4-flash): pagina oficial
        # mostra "Usage: medium", 304B parametros -- "low" estava otimista
        # demais (nao e o modelo mais leve do catalogo, gpt-oss:20b/
        # nemotron-3-nano:30b/gemma4:31b sao os reais "low").
        cost_tier="medium",
        # 1M confirmado por pesquisa dedicada (2026-08-03) -- context_compressor.py
        # tinha 64000 hardcoded pra este modelo (achado real desta auditoria, ver
        # changelog do context_compressor.py 3.0.0).
        context_window=1_000_000,
    ),
    "glm-5.2": ModelInfo(
        model_id="glm-5.2",
        provider="zhipu",
        status=ModelStatus.ACTIVE,
        description="Zhipu/Z.ai -- construido especificamente para engenharia de longo horizonte ('requirements to multi-platform deployment'), lider em benchmarks de coding de longo horizonte entre modelos open-source (pesquisa dedicada 2026-08-04); candidato forte a tier heavy do Ollama, ainda nao promovido a default -- ver changelog 1.10.0",
        capabilities=["thinking", "tool_use", "coding_agentic", "1M_context"],
        cost_tier="high",
        context_window=1_000_000,  # ~976k conforme ollama.com/library/glm-5.2, arredondado
    ),
    "minimax-m3": ModelInfo(
        model_id="minimax-m3",
        provider="minimax",
        status=ModelStatus.ACTIVE,
        description="MiniMax -- decomposicao autonoma de tarefas + invocacao de tools + contexto de ate 1M via sparse attention; 'top-tier em benchmarks de coding e agentic' (pesquisa dedicada 2026-08-04)",
        capabilities=["thinking", "tool_use", "coding_agentic", "vision", "1M_context"],
        # cost_tier corrigido de "medium" pra "high" (pesquisa dedicada
        # 2026-08-17, ollama.com/library/minimax-m3): pagina oficial mostra
        # "Usage: high" -- estava subestimado.
        cost_tier="high",
        context_window=1_000_000,  # varia conforme configuracao (min 512k) -- 1M e o teto documentado
    ),
    # 1.15.0: 8 modelos confirmados AO VIVO no catalogo real da conta
    # (GET https://ollama.com/api/tags, 2026-08-08) mas nunca registrados
    # aqui -- gap real encontrado a pedido do Felipe apos ele perguntar
    # por que "Alto" nunca usava GLM/MiniMax/GPT-OSS (que ja estavam
    # cadastrados mas fora do roteamento) nem os que faltavam de todo.
    # Descricoes conservadoras -- specs completas nao auditadas em
    # profundidade ainda, adicionados por completude de catalogo (Regra 5:
    # fonte unica) e para viabilizar o tier "frontier" novo (ver
    # _PROVIDER_TIER_MODELS["ollama"] abaixo).
    "minimax-m2.7": ModelInfo(
        model_id="minimax-m2.7", provider="minimax", status=ModelStatus.ACTIVE,
        description="MiniMax, geracao anterior ao M3 -- presente na conta real, specs nao auditadas em profundidade.",
        capabilities=["tool_use", "coding_agentic"], cost_tier="medium",
        context_window=1_000_000,
    ),
    # kimi-k3 NAO adicionado: aparece no catalogo /api/tags mas retorna
    # HTTP 402 (extra usage only, saldo vazio) -- mesmo padrao ja excluido
    # antes pra kimi3/claude-fable-5 (ver test_model_registry_ollama_2026_08.py
    # ::test_kimi_k3_nao_foi_adicionado, teste PRE-EXISTENTE que travava
    # isso -- quase reintroduzi o mesmo problema adicionando por completude
    # de catalogo sem checar essa exclusao deliberada anterior).
    "deepseek-v4-pro": ModelInfo(
        model_id="deepseek-v4-pro", provider="deepseek", status=ModelStatus.ACTIVE,
        description="DeepSeek, tier 'pro' acima do v4-flash (ja tier light do Ollama) -- presente na conta real, specs nao auditadas em profundidade.",
        # cost_tier corrigido de "medium" pra "high" (pesquisa dedicada
        # 2026-08-17, ollama.com/library/deepseek-v4-pro): pagina oficial
        # mostra "Usage: extra high" (o nivel mais pesado documentado, 1.65T
        # parametros totais) -- mapeado pro balde "high" (o mais severo dos
        # 3 existentes; _COST_TIER_SCORE nao tem um 4o balde) -- estava
        # classificado como "medium", bem abaixo da realidade.
        capabilities=["thinking", "tool_use"], cost_tier="high",
        context_window=128_000,
    ),
    "glm-5.1": ModelInfo(
        model_id="glm-5.1", provider="zhipu", status=ModelStatus.ACTIVE,
        description="Zhipu/Z.ai, geracao anterior ao GLM 5.2 (ja registrado) -- presente na conta real.",
        capabilities=["thinking", "tool_use", "coding_agentic"], cost_tier="high",
        context_window=1_000_000,
    ),
    "gpt-oss:120b": ModelInfo(
        model_id="gpt-oss:120b", provider="openai_oss", status=ModelStatus.ACTIVE,
        description="OpenAI (peso aberto, Apache 2.0), variante maior do gpt-oss:20b (ja registrado, tier light) -- servido via Ollama Cloud, NAO e a API OpenAI paga. Candidato a tier heavy/frontier quando validado.",
        # json_schema removido (2026-08-26): servido via Ollama Cloud, onde
        # json_schema estrito nao e honrado de verdade (auditoria ao vivo).
        capabilities=["thinking", "tool_use"], cost_tier="medium",
        context_window=128_000,
    ),
    "qwen3.5:397b": ModelInfo(
        model_id="qwen3.5:397b", provider="alibaba", status=ModelStatus.ACTIVE,
        description="Alibaba, o maior modelo confirmado na conta real (397B parametros) -- specs de benchmark nao auditadas em profundidade ainda, mas escala sugere candidato natural a tier 'frontier' pra tarefas de alta complexidade.",
        # cost_tier corrigido de "high" pra "medium" (pesquisa dedicada
        # 2026-08-17, ollama.com/library/qwen3.5): pagina oficial mostra
        # "Usage: medium" apesar dos 397B parametros -- MoE eficiente,
        # nao e o mais pesado do catalogo (deepseek-v4-pro/kimi/glm/minimax-m3
        # sao "high"). Continua vencendo em complexity="high" via qualidade
        # documentada (_DOCUMENTED_STRENGTHS em model_router.py), so o custo
        # real e menor do que a classificacao antiga sugeria.
        capabilities=["thinking", "tool_use", "coding_agentic"], cost_tier="medium",
        context_window=256_000,
    ),
    "nemotron-3-ultra": ModelInfo(
        model_id="nemotron-3-ultra", provider="nvidia", status=ModelStatus.ACTIVE,
        description="NVIDIA, tier 'ultra' da familia Nemotron 3 -- presente na conta real, specs nao auditadas em profundidade.",
        capabilities=["thinking", "tool_use"], cost_tier="high",
        context_window=128_000,
    ),
    "nemotron-3-super": ModelInfo(
        model_id="nemotron-3-super", provider="nvidia", status=ModelStatus.ACTIVE,
        description="NVIDIA, tier 'super' da familia Nemotron 3 -- presente na conta real, specs nao auditadas em profundidade.",
        capabilities=["thinking", "tool_use"], cost_tier="medium",
        context_window=128_000,
    ),
    "nemotron-3-nano:30b": ModelInfo(
        model_id="nemotron-3-nano:30b", provider="nvidia", status=ModelStatus.ACTIVE,
        description="NVIDIA, tier 'nano' (30B) da familia Nemotron 3 -- rapido/barato, candidato a tier light quando validado.",
        capabilities=["tool_use"], cost_tier="low",
        context_window=64_000,
    ),
    "mistral-large-3:675b": ModelInfo(
        model_id="mistral-large-3:675b", provider="mistral", status=ModelStatus.ACTIVE,
        description="Mistral AI, 675B parametros -- presente na conta real, specs nao auditadas em profundidade.",
        # cost_tier corrigido de "high" pra "medium" (pesquisa dedicada
        # 2026-08-17, ollama.com/library/mistral-large-3): pagina oficial
        # mostra "Usage: medium" apesar dos 675B parametros (MoE eficiente).
        capabilities=["thinking", "tool_use"], cost_tier="medium",
        context_window=128_000,
    ),
    "gemma4:31b": ModelInfo(
        model_id="gemma4:31b", provider="google_oss", status=ModelStatus.ACTIVE,
        description="Google (peso aberto), servido via Ollama Cloud -- NAO e a API Gemini paga (provider='google'). Presente na conta real, specs nao auditadas em profundidade.",
        capabilities=["tool_use"], cost_tier="low",
        context_window=128_000,
    ),
    "gpt-oss:20b": ModelInfo(
        model_id="gpt-oss:20b",
        provider="openai_oss",
        status=ModelStatus.ACTIVE,
        description="OpenAI (peso aberto, Apache 2.0), servido via Ollama Cloud -- NAO e a API OpenAI paga (gpt-5.6-*, provider='openai'). Tool-calling agentico bem documentado, rapido/barato -- candidato a tier light do Ollama (pesquisa dedicada 2026-08-04)",
        # json_schema removido (2026-08-26): servido via Ollama Cloud, onde
        # json_schema estrito nao e honrado de verdade (auditoria ao vivo).
        capabilities=["thinking", "tool_use"],
        cost_tier="low",
        context_window=128_000,
    ),
	"grok-build-0.1": ModelInfo(
		model_id="grok-build-0.1", provider="xai", status=ModelStatus.ACTIVE,
		description="Modelo xAI dedicado a coding agentico (web dev, debug, MCP) -- novo tier heavy para code_generation, mesmo raciocinio usado pra kimi-k2.7-code no Ollama",
		capabilities=["reasoning", "tool_use", "coding_agentic"], cost_tier="medium",
		context_window=256_000,
	),
	"grok-4.5": ModelInfo(
        model_id="grok-4.5", provider="xai", status=ModelStatus.ACTIVE,
        description="Modelo xAI atual para coding, agentes e trabalho de conhecimento -- fallback do tier heavy",
        capabilities=["reasoning", "tool_use", "web_search", "code_execution"], cost_tier="medium",
        context_window=500_000,
	),
	"grok-4.3": ModelInfo(
		model_id="grok-4.3", provider="xai", status=ModelStatus.ACTIVE,
		description="Modelo xAI de menor custo para alto volume",
		capabilities=["reasoning", "tool_use"], cost_tier="low",
		context_window=1_000_000,
	),
	# 3 modelos confirmados na tabela de precos oficial (docs.x.ai/developers/
	# models, pesquisa dedicada 2026-08-04) mas SEM nenhuma linha de descricao
	# alem do proprio nome -- a pagina oficial nao documenta pra que cada um
	# e otimizado. Adicionados por completude do catalogo (Regra 5: fonte
	# unica), mas NAO promovidos a nenhum tier/fallback ate ter clareza real
	# do caso de uso -- evita poluir o roteamento com "modelo generico que
	# talvez sirva". Mesmo preco/contexto de grok-4.3 (1M ctx, $1.25/$2.50
	# por 1M tokens abaixo de 200k prompt).
	"grok-4.20-0309-reasoning": ModelInfo(
		model_id="grok-4.20-0309-reasoning", provider="xai", status=ModelStatus.ACTIVE,
		description="xAI, presente na tabela de precos oficial sem descricao dedicada -- nome sugere modo de raciocinio explicito. Nao usado em nenhum tier/fallback ate confirmacao do caso de uso real.",
		capabilities=["reasoning"], cost_tier="low",
		context_window=1_000_000,
	),
	"grok-4.20-0309-non-reasoning": ModelInfo(
		model_id="grok-4.20-0309-non-reasoning", provider="xai", status=ModelStatus.ACTIVE,
		description="xAI, presente na tabela de precos oficial sem descricao dedicada -- nome sugere variante sem raciocinio explicito (menor latencia). Nao usado em nenhum tier/fallback ate confirmacao do caso de uso real.",
		capabilities=[], cost_tier="low",
		context_window=1_000_000,
	),
	"grok-4.20-multi-agent-0309": ModelInfo(
		model_id="grok-4.20-multi-agent-0309", provider="xai", status=ModelStatus.ACTIVE,
		description="xAI, presente na tabela de precos oficial sem descricao dedicada -- nome sugere otimizacao para orquestracao multi-agente. Nao usado em nenhum tier/fallback ate confirmacao do caso de uso real.",
		capabilities=["tool_use"], cost_tier="low",
		context_window=1_000_000,
	),
	# 1.11.0: OpenCode Go (opencode.ai) -- provider novo pra resgate
	# cross-provider do web_research. Chave de registry namespaced
	# ("opencode-go/<id>") porque o catalogo real do OpenCode Go
	# (confirmado ao vivo via GET /v1/models, 2026-08-08) reusa os
	# MESMOS model_id de outros provedores ja registrados aqui
	# (kimi-k2.7-code, deepseek-v4-flash, glm-5.2, gpt-5.6-luna...) -- uma
	# chave de dict compartilhada colidiria e sobrescreveria a entrada
	# existente. ModelInfo.model_id fica com o id NU real (confirmado ao
	# vivo: a API rejeita o prefixo "opencode-go/" no corpo da requisicao,
	# so aceita no nome de config). So gpt-5.6-luna registrado por ora --
	# e o unico confirmado ao vivo (testado real, 2026-08-08, seguiu a
	# instrucao de formato onde kimi/deepseek via Ollama falhavam) pro
	# caso de uso concreto que motivou este provider; o resto do catalogo
	# do plano Go (20+ modelos) pode ser adicionado depois, sob demanda
	# real, em vez de registrar especulativamente sem validacao.
	"opencode-go/gpt-5.6-luna": ModelInfo(
		model_id="gpt-5.6-luna", provider="opencode_go", status=ModelStatus.ACTIVE,
		description="GPT-5.6 Luna via OpenCode Go (plano de assinatura fixa, opencode.ai) -- unico modelo GPT do plano Go. Usado como resgate cross-provider quando web_research falha o guard deterministico apos escalonamento normal no provedor ativo: sem o vies de especializacao em codigo que os modelos do catalogo Ollama tem (testado ao vivo, seguiu a instrucao de formato corretamente).",
		capabilities=["tool_use"], cost_tier="low",
		context_window=128_000,
	),
}

# ---------------------------------------------------------------------------
# Fallback chains por provider
# ---------------------------------------------------------------------------

_FALLBACK_CHAINS: dict[str, list[str]] = {
    "ollama": ["kimi-k2.7-code", "glm-5.2", "minimax-m3", "kimi-k2.6", "gpt-oss:20b", "deepseek-v4-flash"],
    "anthropic": ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"],
    "openai": ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"],
    "google": ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-2.5-pro"],
	"xai": ["grok-build-0.1", "grok-4.5", "grok-4.3"],
	"opencode_go": ["gpt-5.6-luna"],
}

# ---------------------------------------------------------------------------
# Modelos por tier/provedor
# ---------------------------------------------------------------------------

_PROVIDER_TIER_MODELS: dict[str, dict[str, str]] = {
    "ollama": {
        "heavy": "kimi-k2.7-code",
        "light": "deepseek-v4-flash",
        # 1.15.0: tier novo pra roteamento por complexidade (apply_model_budget()
        # em planner.py 2.22.0) -- so pedidos "high" complexity usam este tier
        # pra code_generation. qwen3.5:397b escolhido por escala (397B params,
        # maior modelo confirmado na conta real) -- specs de benchmark reais
        # ainda nao auditadas em profundidade, revisar quando houver evidencia.
        "frontier": "qwen3.5:397b",
    },
    "anthropic": {
        "heavy": "claude-opus-5",
        "light": "claude-haiku-4-5",
    },
    "openai": {
        "heavy": "gpt-5.6-sol",
        "light": "gpt-5.6-luna",
    },
    "google": {
        "heavy": "gemini-2.5-pro",
        "light": "gemini-3.6-flash",
    },
    "gemini": {
        "heavy": "gemini-2.5-pro",
        "light": "gemini-3.6-flash",
    },
	"xai": {
		"heavy": "grok-build-0.1",
		"light": "grok-4.3",
	},
	# So 1 modelo registrado (ver ModelInfo acima) -- heavy/light apontam
	# pro mesmo, unica opcao validada ao vivo ate hoje.
	"opencode_go": {
		"heavy": "gpt-5.6-luna",
		"light": "gpt-5.6-luna",
	},
}

def get_provider_step_models(provider: str) -> dict[str, str]:
    """Retorna os modelos heavy/light do provedor, com fallback para ollama."""
    return dict(_PROVIDER_TIER_MODELS.get(provider, _PROVIDER_TIER_MODELS["ollama"]))


# 2026-08-26: achado real de auditoria com chaves reais (Ollama Cloud e
# OpenCode Go do Felipe) -- Ollama Cloud NAO tem prompt caching (confirmado
# via docs oficiais + issues do GitHub, ja documentado em critic.py 3.19.0)
# NEM structured output real: testados os 17 modelos da conta real contra
# https://ollama.com/api/chat com format=<schema estrito>, NENHUM seguiu o
# schema -- nem kimi-k2.6 (json_schema_native=True corrigido pra False em
# ollama_client.py 2.25.0 por causa deste mesmo achado). Teste de controle
# decisivo: format="json" e SEM format nenhum deram resultado identico pro
# Kimi -- o parametro nao tem efeito observavel via essa API hoje.
#
# Testados os 31 modelos do OpenCode Go com a mesma chave: destes 4 via
# Chat Completions (/v1/chat/completions), TODOS confirmados COM as duas
# capacidades ao vivo (json_schema estrito seguido corretamente + 2a
# chamada com mesmo prefixo longo reaproveitando >=80% dos tokens de
# prompt).
#
# gpt-5.6-luna foi originalmente forcado no Critic (3.19.0) mas parecia
# "fora do ar" (500 via /chat/completions) ate auditoria adicional
# 2026-08-26 comparando com C:\agentic (mesmo gateway, provider ja
# implementado la corretamente): gpt-5.6-luna e o unico modelo OpenAI-family
# do catalogo do OpenCode Go e exige a Responses API (/v1/responses), nunca
# Chat Completions -- nao estava fora do ar, era o endpoint errado pro
# modelo. Corrigido em ai/opencode_go_client.py 1.2.0 (_RESPONSES_API_MODELS).
# Confirmado ao vivo via /responses: json_schema estrito perfeito E prompt
# caching real (cache hit reenviando o mesmo prefixo longo,
# cached_tokens=2212/2215). Primeiro da cadeia -- e o modelo original que
# motivou a decisao de forcar OpenCode Go no Critic (3.19.0), e o padrao de
# chamada do Critic (mesmo prompt de sistema de ~42k chars repetido em toda
# avaliacao) e exatamente o caso onde a cache de prefixo da Responses API
# reaproveita sem precisar de previous_response_id (conversas encadeadas).
STRUCTURED_OUTPUT_MODEL_CHAIN: tuple[str, ...] = (
    "gpt-5.6-luna", "kimi-k2.6", "glm-5.1", "deepseek-v4-flash", "qwen3.8-max",
)


# Disjuntor de sessao para o provedor de saida estruturada.
#
# get_structured_output_model() forca OpenCode Go porque so ele honra
# json_schema estrito e prompt caching (auditoria ao vivo 2026-08-26). Mas
# forcar UM provedor cria ponto unico de falha: se a conta fica sem saldo,
# TUDO que precisa de JSON garantido cai junto -- Clarifier, Critic e o
# caminho estrito do Planner.
#
# Confirmado ao vivo em 2026-09-02: a chave estava VALIDA (GET /models = 200)
# e /chat/completions devolvia 401 CreditsError "Insufficient balance" em
# todos os 33 modelos da conta. Nao adianta trocar de modelo dentro da cadeia:
# ela tem 5 modelos e todos no mesmo provedor.
#
# Marcado o provedor como indisponivel, as chamadas seguintes caem no provedor
# ATIVO do usuario. Perde-se a garantia de JSON estrito -- o Ollama Cloud nao
# a oferece em nenhum modelo -- e isso e uma degradacao REAL, nao equivalencia:
# os consumidores ja toleram JSON imperfeito (o Critic tem caminho para
# "sem JSON reconhecivel", o Planner tem _parse_plan), mas a taxa de acerto
# cai. E melhor que a alternativa, que e o pipeline inteiro parar.
_estruturado_indisponivel = False


def marcar_saida_estruturada_indisponivel(motivo: str = "") -> None:
	"""Registra que o provedor de saida estruturada nao esta atendendo."""
	global _estruturado_indisponivel
	if not _estruturado_indisponivel:
		_logger.warning(
			"[ESTRUTURADO] Provedor de saida estruturada indisponivel (%s). "
			"As proximas chamadas usam o provedor ativo, SEM garantia de "
			"json_schema estrito -- a qualidade do JSON cai.", motivo or "sem detalhe",
		)
	_estruturado_indisponivel = True


def resetar_saida_estruturada() -> None:
	"""Volta ao provedor preferido. Chamado no inicio de cada execucao: o
	limite de uso do OpenCode Go e por JANELA DE TEMPO (5 horas / semana /
	mes), entao a indisponibilidade e temporaria e nao pode virar permanente."""
	global _estruturado_indisponivel
	_estruturado_indisponivel = False


def get_structured_output_model(fallback_index: int = 0) -> str:
    """Modelo do OpenCode Go com json_schema estrito + prompt caching
    confirmados ao vivo (ver STRUCTURED_OUTPUT_MODEL_CHAIN acima).

    Qualquer chamada que precise de JSON garantido (response_format
    type=json_schema) deve usar este helper em vez de resolver o modelo
    pelo provider ativo do usuario -- Ollama Cloud nao oferece nenhuma das
    duas garantias, em nenhum modelo da conta. Retorna no formato
    "<provider>::<model>" (convencao de ai/llm_factory.py::create_llm_client(),
    forca o provider ignorando o provider ativo do usuario -- mesmo
    mecanismo ja usado por critic.py desde 3.19.0).

    fallback_index: indice na cadeia (0 = preferido). Fora do intervalo
    satura no ultimo item -- nunca levanta excecao nem retorna vazio.
    """
    if _estruturado_indisponivel:
        # Degradacao anunciada: sem o provedor preferido, o provedor ATIVO
        # do usuario continua respondendo -- so que sem json_schema estrito.
        try:
            from ..gui.settings_panel import get_llm_model, get_llm_provider

            return resolve_provider_tier_model(
                get_llm_provider(), "heavy", get_llm_model(),
            )
        except Exception:  # pragma: no cover - defesa
            pass
    chain = STRUCTURED_OUTPUT_MODEL_CHAIN
    idx = min(max(fallback_index, 0), len(chain) - 1)
    return f"opencode_go::{chain[idx]}"


def is_alto_model(model: str | None) -> bool:
    """True quando o modelo selecionado deve ser resolvido automaticamente."""
    return (model or "").strip().lower() in _ALTO_SENTINELS


def resolve_provider_tier_model(
    provider: str,
    tier: str,
    configured_model: str = ALTO_MODEL,
) -> str:
    """
    Resolve o modelo para um tier.

    Ordem:
    1. Modelo escolhido pelo usuario, quando diferente de alto.
    2. Override de ambiente NVDASTUDIO_<PROVIDER>_<TIER>_MODEL.
    3. Modelo oficial auditado no registry para provider/tier.

    1.15.0: tier "frontier" novo (roteamento por complexidade, ver
    planner.py apply_model_budget() 2.22.0) -- nem todo provider tem essa
    entrada (so ollama por ora); cai pra "heavy" quando ausente, em vez de
    KeyError ou virar "light" silenciosamente (bug que existiria se
    "frontier" caisse no else->"light" do normalized_tier antigo).
    """
    if not is_alto_model(configured_model):
        return configured_model

    normalized_provider = provider if provider in _PROVIDER_TIER_MODELS else "ollama"
    normalized_tier = tier if tier in ("heavy", "light", "frontier") else "light"
    env_name = f"NVDASTUDIO_{normalized_provider.upper()}_{normalized_tier.upper()}_MODEL"
    env_model = os.getenv(env_name, "").strip()
    if env_model:
        return env_model

    tier_models = _PROVIDER_TIER_MODELS[normalized_provider]
    if normalized_tier not in tier_models:
        normalized_tier = "heavy"
    return tier_models[normalized_tier]


def resolve_alto_model(provider: str, configured_model: str = ALTO_MODEL) -> str:
    """Resolve o modelo Alto do provider selecionado."""
    return resolve_provider_tier_model(provider, "heavy", configured_model)


def clear_model_resolution_cache() -> None:
	"""Mantido para compatibilidade; a resolucao atual nao usa cache externo."""
	return None

# ---------------------------------------------------------------------------
# Aliases — resolvem para o modelo mais recente
# ---------------------------------------------------------------------------

_ALIASES: dict[str, str] = {
    "claude-latest": "claude-opus-5",
    "claude-fast": "claude-haiku-4-5",
    "gpt-latest": "gpt-5.6-sol",
    "gpt-fast": "gpt-5.6-luna",
    "gemini-latest": "gemini-2.5-pro",
    "gemini-fast": "gemini-3.6-flash",
}


class ModelRegistry:
    """Registro dinamico de modelos LLM com deteccao de deprecated."""

    def __init__(self):
        self._warnings_issued: set[str] = set()

    def get_model_info(self, model_id: str) -> Optional[ModelInfo]:
        """Retorna informacao sobre um modelo, resolvendo aliases."""
        resolved = _ALIASES.get(model_id, model_id)
        return _MODEL_REGISTRY.get(resolved)

    def is_deprecated(self, model_id: str) -> bool:
        """Verifica se um modelo esta deprecated ou retired."""
        info = self.get_model_info(model_id)
        if info is None:
            return False
        return info.status in (ModelStatus.DEPRECATED, ModelStatus.RETIRED)

    def is_active(self, model_id: str) -> bool:
        """Verifica se um modelo esta ativo (active ou preview)."""
        info = self.get_model_info(model_id)
        if info is None:
            return True  # desconhecido = assume ativo (fail-open)
        return info.status in (ModelStatus.ACTIVE, ModelStatus.PREVIEW)

    def get_migration_target(self, model_id: str) -> Optional[str]:
        """Retorna o modelo de migracao recomendado, se disponivel."""
        info = self.get_model_info(model_id)
        if info is None:
            return None
        return info.migration_target or None

    def validate_model(self, model_id: str) -> tuple[bool, str]:
        """
        Valida um modelo e retorna (ok, mensagem).

        Se o modelo esta deprecated/retired, retorna False com mensagem de aviso.
        Se o modelo tem migracao sugerida, inclui na mensagem.
        """
        if model_id in self._warnings_issued:
            return True, ""

        info = self.get_model_info(model_id)
        if info is None:
            return True, ""  # modelo desconhecido — assume ok

        if info.status == ModelStatus.RETIRED:
            msg = (
                f"[ALERTA] Modelo '{model_id}' foi DESLIGADO em {info.deprecated_since}. "
                f"NAO funcionara mais."
            )
            if info.migration_target:
                msg += f" Migre para '{info.migration_target}'."
            self._warnings_issued.add(model_id)
            _logger.warning(msg)
            return False, msg

        if info.status == ModelStatus.DEPRECATED:
            msg = (
                f"[AVISO] Modelo '{model_id}' esta DEPRECATED desde {info.deprecated_since}. "
                f"Pode parar de funcionar a qualquer momento."
            )
            if info.migration_target:
                msg += f" Recomendado migrar para '{info.migration_target}'."
            self._warnings_issued.add(model_id)
            _logger.warning(msg)
            return True, msg  # deprecated ainda funciona, mas avisa

        return True, ""

    def get_fallback_chain(self, model_id: str) -> list[str]:
        """Retorna a cadeia de fallback para um modelo."""
        info = self.get_model_info(model_id)
        if info is None:
            return [model_id]

        provider = info.provider
        if provider in _OLLAMA_SERVED_MAKERS:
            provider = "ollama"

        chain = _FALLBACK_CHAINS.get(provider, [])
        # Remove o proprio modelo da cadeia
        chain = [m for m in chain if m != model_id]
        return [model_id] + chain

    def get_active_models(self, provider: Optional[str] = None) -> list[ModelInfo]:
        """Retorna todos os modelos ativos, opcionalmente filtrados por provider."""
        active = [
            info for info in _MODEL_REGISTRY.values()
            if info.status in (ModelStatus.ACTIVE, ModelStatus.PREVIEW)
        ]
        if provider:
            active = [info for info in active if info.provider == provider]
        return active

    def get_active_models_for_ui_provider(self, ui_provider: str) -> list[ModelInfo]:
        """
        Retorna os modelos ativos/preview visiveis sob um codigo de provedor
        da UI (settings_panel.py: ollama/openai/google/gemini/anthropic/xai).

        Fonte unica de verdade pro dropdown de modelo da UI -- antes,
        settings_panel.py mantinha uma lista `_MODELS_BY_PROVIDER` propria,
        hand-maintained, que desalinhou do registry real (achado de
        auditoria 2026-08-04: UI faltava kimi-k2.7-code, gemini-3.6-flash,
        claude-opus-5 e grok-build-0.1 -- os proprios defaults atuais --
        ainda oferecia claude-fable-5 (removido) e um modelo fantasma
        "glm-z1" que nunca existiu em nenhum catalogo real).
        """
        registry_providers = _UI_PROVIDER_TO_REGISTRY_PROVIDERS.get(ui_provider, ())
        return [
            info for info in self.get_active_models()
            if info.provider in registry_providers
        ]

    def check_startup_models(self, models_in_use: list[str]) -> list[str]:
        """
        Verifica todos os modelos em uso na inicializacao.
        Retorna lista de warnings para exibir ao usuario.
        """
        warnings: list[str] = []
        for model_id in models_in_use:
            ok, msg = self.validate_model(model_id)
            if msg and not ok:
                warnings.append(msg)
            elif msg:
                warnings.append(msg)
        return warnings


# Instancia global
registry = ModelRegistry()
