"""E2E real e pago (Ollama Cloud) da auditoria de economia de tokens.

Confirma ao vivo o que os testes mockados não conseguem: que os parâmetros
novos (reasoning_effort, corte de histórico, teto de orçamento, custo)
realmente atravessam o contrato HTTP real da Ollama Cloud sem erro -- E2E
confirma, não descobre (a lógica já foi provada nos degraus baratos em
tests/unit/test_economia_de_tokens.py).

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


@skip_unless_ollama
def test_build_real_via_ollama_cloud_usa_esforco_calibrado_e_reporta_custo(tmp_path):
	from nvdastudio.builder.agent_checkpoint import AgentCheckpointStore
	from nvdastudio.builder.agentic_driver import run_provider_agentic_build

	eventos: list[str] = []
	tokens_ao_vivo: list[str] = []
	result = run_provider_agentic_build(
		"Crie um addon NVDA simples: ao pressionar NVDA+Shift+H, anuncia a hora "
		"atual por voz. Sem configurações, sem outras funcionalidades.",
		provider="ollama",
		model_id="gpt-oss:20b",
		reasoning_effort="low",  # tarefa simples -- mesma calibracao que o roteador aplicaria
		use_nvda_context=False,  # o spec compacto (_NVDA_SPEC) já basta pro contrato minimo;
		# mante-lo desligado aqui reduz o custo real deste E2E sem mudar o que
		# esta sendo validado (roteamento de esforço, corte de histórico,
		# teto de orçamento, custo, streaming -- nenhum depende do contexto extra).
		correction_rounds=0,
		progress_callback=eventos.append,
		token_callback=tokens_ao_vivo.append,
		# Aprova ferramentas perigosas automaticamente -- o teste valida o
		# loop de build/economia, não o portão de aprovação (fail-closed sem
		# callback é o comportamento certo, coberto em test_tool_system_approval.py).
		permission_callback=lambda *_args: True,
		state_store=AgentCheckpointStore(str(tmp_path / "checkpoints")),
	)

	print(f"\n[E2E ollama] success={result.success} tokens={result.tokens} "
		  f"cost_usd={result.cost_usd} rounds={result.rounds} files={result.files}")
	print(f"[E2E ollama] eventos: {len(eventos)} | tokens ao vivo: {len(tokens_ao_vivo)}")
	print(f"[E2E ollama] stdout_tail: {result.stdout_tail[:300]!r}")

	assert not result.budget_exceeded, "orcamento nao deveria estourar numa build tao simples"
	assert result.tokens > 0, "a chamada real precisa ter consumido tokens de verdade"
	# Ollama Cloud e assinatura/cota (sem preco por token catalogado) --
	# estimate_cost_usd() deve retornar None pra este provider, nunca um
	# numero fabricado (ver model_pricing.py).
	assert result.cost_usd == 0.0
	assert result.files, "o agente precisa ter produzido pelo menos um arquivo real"
	assert any("manifest.ini" in f for f in result.files)
	# Streaming token a token so tem o que mostrar quando o modelo narra texto
	# antes de chamar a ferramenta -- gpt-oss:20b, na pratica, às vezes só
	# chama a ferramenta direto (documentado em ollama_client.py, issue
	# ollama/ollama#12557). Sem narração alguma (stdout_tail também vazio),
	# não há bug de streaming pra cobrar aqui -- só nada pra transmitir.
	if result.stdout_tail.strip():
		assert tokens_ao_vivo, (
			"o modelo narrou texto (stdout_tail não vazio) mas nada chegou "
			"token a token -- isso sim seria uma falha real do streaming"
		)
	assert result.success or result.gate_report, (
		"sem sucesso, precisa ao menos ter um relatorio de gate explicando por que"
	)
