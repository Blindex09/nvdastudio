import re
from ._base import _run_sub_agent, narrate
from ..utils.logger import get_logger, log_decision
from ..builder.nvda_context import get_docs_agent_runner

MODULE_VERSION = "1.5.0"

_logger = get_logger("agent_runner_agent")

_SYSTEM = """Voce e o AgentRunnerAgent do NVDAStudio.
Gere um arquivo agent_runner.py COMPLETO para um addon NVDA que possui agentes de IA internos.

TEXTO PURO — sem markdown, sem asteriscos, sem sustenidos fora dos blocos de codigo.

O AgentRunner gerado DEVE conter TODOS os itens abaixo. Sem excecoes:

1. IMPORTACAO LAZY DO CLIENTE LLM — CRITICO para addons NVDA:
   O NVDA carrega addons em ordem alfabetica. O addon gerado pode carregar ANTES do
   NVDAStudio (que adiciona lib/ ao sys.path). Por isso o cliente LLM NUNCA deve ser
   importado no topo do arquivo. Sempre use importacao lazy DENTRO do metodo run():

   def run(self, query, on_chunk=None):
	   try:
		   import httpx  # lazy: so importa quando usuario aciona o addon
	   except ImportError:
		   return "httpx nao disponivel. Certifique-se que o NVDAStudio esta instalado."
	   # ... resto da implementacao usando httpx para chamar a API LLM

2. Classe AgentRunner com:
   __init__(self, api_key: str, model_id: str) — inicializa atributos (SEM importar httpx aqui)
   run(self, query: str, on_chunk=None) -> str — executa o agente (importa httpx aqui)
   reset_session(self) — metodo PUBLICO que limpa self._history = []
   _fallback_chain: list — ATRIBUTO de instancia com ao menos 2 model IDs

3. Historico:
   self._history nunca recebe {"role": "system", ...}

4. try/except em toda chamada externa dentro de run()

5. Logging sem emojis, compativel com cp1252

6. Imports de stdlib (os, logging, etc.) no topo; httpx sempre lazy em run()

Formate o codigo como bloco anotado, substituindo NOME_DO_ADDON pelo nome real
do addon extraido do pedido do usuario (sem espacos, sem acentos, em CamelCase):
```python:globalPlugins/NOME_DO_ADDON/agent_runner.py
[codigo completo aqui]
```"""

# Padroes deterministicos obrigatorios no codigo gerado (Regra 5)
# Cada item: (descricao, pattern_regex)
_REQUIRED_PATTERNS: list[tuple[str, str]] = [
	("reset_session() publico",           r"def\s+reset_session\s*\("),
	("_fallback_chain definido",          r"_fallback_chain\s*[=:]"),
	("cliente LLM importado lazy em run()", r"try\s*:\s*\n\s*(import httpx|from httpx)"),
	("try/except em chamada externa",     r"try\s*:"),
	("historico nunca recebe system",     r"_history"),
]


def _validate_structure(code: str) -> list[str]:
	"""
	Verifica presenca dos padroes obrigatorios no codigo gerado.
	Retorna lista de avisos para itens ausentes.
	Regra 5: esta verificacao e deterministica, nao semantica.
	Regra 9: verifica texto — nunca executa.
	"""
	warnings = []
	for descricao, pattern in _REQUIRED_PATTERNS:
		if not re.search(pattern, code, re.MULTILINE | re.IGNORECASE):
			warnings.append(f"[AVISO-ESTRUTURA] Ausente: {descricao}")
	return warnings


def run(prompt: str, model_id: str, reasoning_params: dict, cache_key: str | None = None) -> str:
	# Narracao "antes" removida (v1.4.0) -- duplicava o que o proprio modelo
	# ja narra ao vivo no content (LiveNarrator, ligado via live_narrate=True
	# abaixo), instruido por _TOOL_PREAMBLE_INSTRUCTION -- texto solto fora dos
	# fences ```python:... e descartado na extracao (extract_code_blocks), entao
	# narrar ali nao "vaza" pro artefato final. narrate() aqui era uma segunda
	# chamada de IA cara e sem memoria repetindo a mesma intencao.
	output = _run_sub_agent(
		_SYSTEM, prompt, model_id, reasoning_params,
		extra_docs=get_docs_agent_runner(), cache_key=cache_key, live_narrate=True,
		step_type="agent_runner",
	)

	# Validacao estrutural deterministica — Regra 5
	warnings = _validate_structure(output)
	if warnings:
		narrate(f"o executor do agente ficou faltando {len(warnings)} item(ns) obrigatorio(s)")
		aviso_bloco = (
			"# AVISO DE ESTRUTURA — itens obrigatorios ausentes detectados:\n"
			+ "\n".join(f"# {w}" for w in warnings)
			+ "\n# O Critic ira avaliar e solicitar correcao.\n\n"
		)
		log_decision(_logger, "agent_runner_estrutura_incompleta",
					 f"ausentes={len(warnings)}: {'; '.join(warnings)}")
		return aviso_bloco + output

	narrate("o executor do agente ficou completo, com todos os itens obrigatorios")
	log_decision(_logger, "agent_runner_estrutura_ok", "todos os padroes presentes")
	return output
