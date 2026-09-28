"""Regressões da auditoria de economia: esforço calibrado pela complexidade
já declarada pela IA, teto agregado de tokens por build, corte do histórico
de ferramentas antigo e visibilidade de custo em dólar."""
import types
from unittest.mock import MagicMock, patch

import pytest

from nvdastudio.ai.model_pricing import estimate_cost_usd
from nvdastudio.builder import agentic_driver as ad
from nvdastudio.builder.agent_checkpoint import AgentCheckpointStore, trim_tool_history
from nvdastudio.builder.agentic_driver import run_provider_agentic_build


# ----------------------------------------------------------------- reasoning_effort

def test_reasoning_effort_chega_ao_cliente_sem_heuristica_no_meio():
	"""route.complexity (decisão da IA) chega intacta ao client.chat -- o
	driver não reinterpreta nem adivinha, só repassa."""
	client = MagicMock()
	client.chat.return_value = types.SimpleNamespace(content="ok", tokens_used=1, tool_calls=[])
	with patch("nvdastudio.ai.llm_factory.create_llm_client", return_value=client):
		run_provider_agentic_build(
			"pedido", provider="openai", model_id="m", reasoning_effort="high",
			use_nvda_context=False,
		)
	assert client.chat.call_args.kwargs["reasoning_effort"] == "high"


def test_default_reasoning_effort_da_cadeia_barata_e_low(monkeypatch):
	from nvdastudio.ai import llm_factory

	capturado = {}

	class Client:
		def chat(self, *a, **kw):
			capturado.update(kw)
			return types.SimpleNamespace(content="{}", tokens_used=1)

	monkeypatch.setattr(llm_factory, "create_llm_client", lambda **kw: Client())
	llm_factory.call_with_structured_output("oi", {"type": "json_object"})
	assert capturado["reasoning_effort"] == "low"


# ----------------------------------------------------------------- corte de histórico

def test_trim_preserva_janela_recente_e_encolhe_o_resto_openai():
	grande = "x" * 2000
	history = [
		{"role": "tool_result", "tool_call_id": "1", "content": grande},
		{"role": "assistant", "content": "a", "tool_calls": [{"id": "1"}]},
		{"role": "tool_result", "tool_call_id": "2", "content": grande},
		{"role": "assistant", "content": "b", "tool_calls": [{"id": "2"}]},
	]
	out = trim_tool_history(history, keep_recent=1, max_chars=100)
	assert len(out) == len(history)  # nenhuma entrada removida
	assert out[0]["content"] != grande and len(out[0]["content"]) < len(grande)
	assert out[0]["tool_call_id"] == "1"  # id preservado -- pairing intacto
	assert out[2]["content"] == grande  # dentro da janela recente


def test_trim_encolhe_bloco_aninhado_da_anthropic_sem_tocar_o_resto():
	grande = "y" * 2000
	history = [
		{"role": "user", "content": [
			{"type": "tool_result", "tool_use_id": "1", "content": grande},
			{"type": "tool_result", "tool_use_id": "2", "content": "curto"},
		]},
		{"role": "assistant", "content": [{"type": "tool_use", "id": "1"}]},
	]
	out = trim_tool_history(history, keep_recent=0, max_chars=100)
	assert len(out[0]["content"][0]["content"]) < len(grande)
	assert out[0]["content"][1]["content"] == "curto"  # já era curto, não muda


def test_trim_e_idempotente():
	grande = "z" * 2000
	history = [{"role": "tool", "content": grande}]
	once = trim_tool_history(history, keep_recent=0, max_chars=100)
	twice = trim_tool_history(once, keep_recent=0, max_chars=100)
	assert once == twice


def test_trim_nunca_remove_nem_reordena_entradas():
	history = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
	assert trim_tool_history(history, keep_recent=0, max_chars=10) == history


# ----------------------------------------------------------------- custo em dólar

def test_custo_calculado_com_breakdown_real():
	custo = estimate_cost_usd(
		"openai", "gpt-5.6-luna",
		{"input_tokens": 1_000_000, "output_tokens": 1_000_000}, 2_000_000,
	)
	assert custo == pytest.approx(0.20 + 1.20)


def test_custo_sem_breakdown_usa_estimativa_meio_a_meio():
	custo = estimate_cost_usd("openai", "gpt-5.6-luna", None, 1_000_000)
	assert custo == pytest.approx((0.20 + 1.20) / 2)


def test_custo_none_sem_preco_catalogado_nunca_numero_fabricado():
	assert estimate_cost_usd("ollama", "kimi-k2.7-code", {"input_tokens": 1, "output_tokens": 1}, 2) is None


# ----------------------------------------------------------------- teto de tokens

def test_orcamento_excedido_para_preserva_arquivos_e_marca_o_resultado(tmp_path, monkeypatch):
	monkeypatch.setenv("NVDASTUDIO_MAX_TOKENS_PER_BUILD", "5")
	(tmp_path / "manifest.ini").write_text("name = X\n", encoding="utf-8")

	class Client:
		def chat(self, *a, **kw):
			return types.SimpleNamespace(content="trabalhando", tokens_used=10, tool_calls=[
				{"id": "1", "function": {"name": "list_workspace", "arguments": {}}},
			])

	avisos = []
	with patch("nvdastudio.ai.llm_factory.create_llm_client", return_value=Client()):
		result = run_provider_agentic_build(
			"pedido", provider="openai", model_id="m", workdir=str(tmp_path),
			use_nvda_context=False, progress_callback=avisos.append,
			state_store=AgentCheckpointStore(str(tmp_path / "s")),
		)
	assert result.budget_exceeded is True
	assert result.success is False
	assert (tmp_path / "manifest.ini").exists()  # nada foi apagado
	assert any("orçamento" in a for a in avisos)


def test_orcamento_padrao_generoso_nao_interfere_em_build_normal(tmp_path):
	"""Sem override de env, o teto e alto o bastante pra nunca disparar numa
	build de poucos turnos -- regressao contra um teto acidentalmente baixo."""
	(tmp_path / "manifest.ini").write_text("name = X\n", encoding="utf-8")
	p = tmp_path / "globalPlugins" / "X"
	p.mkdir(parents=True)
	(p / "__init__.py").write_text(
		"import globalPluginHandler\nclass GlobalPlugin(globalPluginHandler.GlobalPlugin):\n\tpass\n",
		encoding="utf-8",
	)

	class Client:
		def chat(self, *a, **kw):
			return types.SimpleNamespace(content="pronto", tokens_used=1000, tool_calls=[])

	with (
		patch("nvdastudio.ai.llm_factory.create_llm_client", return_value=Client()),
		patch.object(ad, "_run_gates", return_value=(True, "")),
	):
		result = run_provider_agentic_build(
			"pedido", provider="openai", model_id="m", workdir=str(tmp_path),
			use_nvda_context=False, state_store=AgentCheckpointStore(str(tmp_path / "s")),
		)
	assert result.budget_exceeded is False


def test_custo_da_build_acumula_e_aparece_no_resultado(tmp_path):
	(tmp_path / "manifest.ini").write_text("name = X\n", encoding="utf-8")
	p = tmp_path / "globalPlugins" / "X"
	p.mkdir(parents=True)
	(p / "__init__.py").write_text(
		"import globalPluginHandler\nclass GlobalPlugin(globalPluginHandler.GlobalPlugin):\n\tpass\n",
		encoding="utf-8",
	)

	class Client:
		def chat(self, *a, **kw):
			return types.SimpleNamespace(
				content="pronto", tokens_used=2_000_000, tool_calls=[],
				usage_breakdown={"input_tokens": 1_000_000, "output_tokens": 1_000_000},
			)

	with (
		patch("nvdastudio.ai.llm_factory.create_llm_client", return_value=Client()),
		patch.object(ad, "_run_gates", return_value=(True, "")),
	):
		result = run_provider_agentic_build(
			"pedido", provider="openai", model_id="gpt-5.6-luna", workdir=str(tmp_path),
			use_nvda_context=False, state_store=AgentCheckpointStore(str(tmp_path / "s")),
		)
	assert result.cost_usd == pytest.approx(0.20 + 1.20)


# ----------------------------------------------------------------- orquestrador

def test_orchestrator_repassa_complexidade_da_rota_como_esforco():
	with patch("nvdastudio.builder.agentic_driver.run_provider_agentic_build") as native:
		native.return_value = types.SimpleNamespace(
			success=True, execution_ok=True, files=["manifest.ini"], workdir=".",
			tokens=1, cost_usd=0.0, error="", gate_report="", rounds=1, cancelled=False,
		)
		from nvdastudio.core.orchestrator import Orchestrator
		o = Orchestrator()
		o._on_complete = lambda _r: None
		o._suppress_complete_callback = False
		with patch(
			"nvdastudio.core.orchestrator._get_agentic_routes",
			lambda _r="", _h=None: [
				types.SimpleNamespace(
					provider="openai", model_id="m", reason="teste", complexity="high",
					to_dict=lambda: {},
				),
			],
		):
			o._run_agent("crie um addon")
	assert native.call_args.kwargs["reasoning_effort"] == "high"


# ----------------------------------------------------------------- nomes de ferramenta

def test_write_workspace_sem_sufixo_e_reconhecido():
	"""Achado do E2E real via Ollama Cloud (gpt-oss:20b): o modelo chamou
	"write_workspace" (sem "_file") de forma consistente e nunca escreveu
	nada até o detector de loop interromper -- ~350k tokens gastos em
	tentativas que nunca poderiam funcionar."""
	from nvdastudio.builder.agent_tools import canonical_permission_name

	assert canonical_permission_name("write_workspace") == "write_workspace_file"
	assert canonical_permission_name("read_workspace") == "read_workspace_file"
	assert canonical_permission_name("delete_workspace") == "delete_workspace_file"
