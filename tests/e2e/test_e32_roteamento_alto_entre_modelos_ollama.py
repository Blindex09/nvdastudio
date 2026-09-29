"""E2E real e pago (Ollama Cloud) do roteamento "Alto" ENTRE OS PROPRIOS
MODELOS de um provedor fixo (fora do modo Studio).

Pergunta concreta do usuario que motivou este teste: configurando o provedor
manualmente como Ollama com o modelo "Alto", o Studio realmente compara os
modelos do proprio Ollama pra escolher o mais adequado a tarefa (nao so um
id fixo), e mostra o motivo real da decisao? Confirmado ao vivo duas vezes
nesta sessao com o harness de interface (kimi-k2.7-code numa rodada,
minimax-m2.7 na outra, mesma tarefa) -- mas so contra o codigo real, sem
mock, prova que nao e coincidencia de cache/estado local.

Requer OLLAMA_API_KEY (skip sem ela, nunca falha por falta de credencial).
"""
import os

import pytest

try:
	from dotenv import load_dotenv
	_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
	load_dotenv(dotenv_path=os.path.join(_REPO_ROOT, ".env"), override=False)
except ImportError:
	pass

HAS_OLLAMA = os.environ.get("OLLAMA_API_KEY", "").strip()
skip_unless_ollama = pytest.mark.skipif(not HAS_OLLAMA, reason="OLLAMA_API_KEY nao configurada")

from nvdastudio.ai import route_advisor  # noqa: E402

# tests/conftest.py desliga _ask_model (autouse, protege TODA a suite de rede
# real acidental) -- capturado aqui, na importacao do modulo, antes daquela
# fixture rodar por teste. Cada teste deste arquivo restaura explicitamente
# esta referencia real: e o unico jeito de fazer um E2E genuino do consultor
# de rota sem desligar a protecao pra suite inteira.
_ASK_MODEL_REAL = route_advisor._ask_model


@skip_unless_ollama
def test_alto_no_ollama_fixo_compara_modelos_reais_e_explica_o_motivo(monkeypatch):
	monkeypatch.setattr(route_advisor, "_ask_model", _ASK_MODEL_REAL)
	from nvdastudio.ai.model_router import RoutingHints, select_routes

	routes = select_routes(
		"ollama", "code_generation", "alto",
		request=(
			"Corrija comentarios de traducao faltando e um erro de digitacao "
			"num addon NVDA ja existente."
		),
		hints=RoutingHints.declared("medium", "balanced"),
		required_capabilities=frozenset({"tool_use"}),
	)

	print(f"\n[E2E ollama alto] routes={[(r.provider, r.model_id) for r in routes]}")
	print(f"[E2E ollama alto] reason={routes[0].reason!r}")

	assert len(routes) == 1, "provedor fixo nunca produz mais de uma rota"
	assert routes[0].provider == "ollama"
	assert routes[0].model_id, "precisa ter escolhido algum modelo real do Ollama"
	# "manualmente" e o marcador que orchestrator.py usa pra decidir a
	# narracao ("Studio selecionou..." vs "Usando..."); precisa sobreviver.
	assert "manualmente" in routes[0].reason
	# As duas frases fixas de contingencia (sem comparação real da IA) --
	# se NENHUMA delas aparecer, a rota só pode ter vindo do ranking real.
	assert "unico modelo elegivel" not in routes[0].reason
	assert "modelo especifico escolhido pelo usuario" not in routes[0].reason
	# Sem estas duas: so aparecem quando _ask_model falhou de verdade e caiu
	# no fallback por confiabilidade (ver route_advisor._fallback) -- a
	# ausencia prova que a resposta veio da IA, nao da contingencia.
	assert "consultor de IA indisponivel" not in routes[0].reason
	assert "confiabilidade observada" not in routes[0].reason
	# Reason > so a frase fixa velha ("Provedor ollama escolhido manualmente; ")
	# prova que sobrou texto real da IA depois do ponto-e-virgula.
	assert len(routes[0].reason) > len("Provedor ollama escolhido manualmente; .")


@skip_unless_ollama
def test_duas_chamadas_reais_podem_escolher_modelos_diferentes_pela_tarefa(monkeypatch):
	"""Nao afirma QUAL modelo sai vencedor (isso e julgamento da IA a cada
	chamada, nunca um fato fixo do harness) -- só que uma tarefa TRIVIAL e
	uma tarefa de ALTO RISCO/complexidade, roteadas separadamente, produzem
	uma decisão real da IA (não a mesma resposta de contingência ambas)."""
	monkeypatch.setattr(route_advisor, "_ask_model", _ASK_MODEL_REAL)
	from nvdastudio.ai.model_router import RoutingHints, select_routes

	rota_simples = select_routes(
		"ollama", "code_generation", "alto",
		request="Adicione um comentario de uma linha num arquivo.",
		hints=RoutingHints.declared("low", "cost"),
		required_capabilities=frozenset({"tool_use"}),
	)
	rota_complexa = select_routes(
		"ollama", "code_generation", "alto",
		request=(
			"Implemente um driver de sintetizador de voz completo, com "
			"deteccao automatica de dispositivo, suporte a multiplas vozes "
			"e testes de integracao."
		),
		hints=RoutingHints.declared("high", "quality"),
		required_capabilities=frozenset({"tool_use"}),
	)

	print(f"\n[E2E ollama alto] simples={rota_simples[0].model_id} reason={rota_simples[0].reason!r}")
	print(f"[E2E ollama alto] complexa={rota_complexa[0].model_id} reason={rota_complexa[0].reason!r}")

	for rota in (rota_simples, rota_complexa):
		assert len(rota) == 1
		assert "manualmente" in rota[0].reason
		assert "unico modelo elegivel" not in rota[0].reason
		assert "consultor de IA indisponivel" not in rota[0].reason
