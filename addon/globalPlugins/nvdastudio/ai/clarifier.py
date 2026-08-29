import json
import re
from dataclasses import dataclass, field

from .llm_client import LLMClientError
from .llm_factory import call_with_structured_output
from ..utils.logger import get_logger, log_llm_call, log_llm_response, log_decision

MODULE_VERSION = "1.6.0"
_logger = get_logger("clarifier")

CLARIFIER_MODEL = "kimi-k2.6"

# 1.6.0: analyze_query() exige JSON estrito (_CLARIFIER_SCHEMA, additionalProperties=
# False) mas seguia o tier "light" do provider ATIVO do usuario -- no Ollama (default),
# isso e deepseek-v4-flash, sem json_schema real (achado de auditoria 2026-08-26, ver
# model_registry.py::get_structured_output_model()). Toda chamada real caia no
# fallback de "sem clarificacao" quando o JSON vinha malformado, silenciosamente.
def get_clarifier_model() -> str:
	"""Retorna o modelo do clarifier -- sempre OpenCode Go com json_schema
	estrito garantido, nunca o tier light do provider ativo do usuario. Ver
	model_registry.py::get_structured_output_model()."""
	from .model_registry import get_structured_output_model
	return get_structured_output_model(0)

# Valores validos para addon_architecture
_VALID_ARCHITECTURES = frozenset({"external", "driver", "deep_integration", "ambiguous"})

_CLARIFIER_SYSTEM = (
	'Voce e o Clarifier do NVDAStudio. Analisa pedidos do usuario sobre addons NVDA.\n'
	'\n'
	'Seu trabalho:\n'
	'1. Classificar o TIPO do pedido (ver TIPOS abaixo).\n'
	'2. Detectar o nivel tecnico do usuario pela sua escrita.\n'
	'3. Diagnosticar a ARQUITETURA do addon necessaria (ver ARQUITETURA abaixo).\n'
	'4. Decidir SE o pedido tem informacoes suficientes.\n'
	'5. Se precisar perguntar, formular perguntas no nivel do usuario.\n'
	'6. Identificar se o pedido viola regras de seguranca.\n'
	'7. Identificar se a implementacao exigiria funcionalidades nao solicitadas.\n'
	'\n'
	'Retorne APENAS JSON valido:\n'
	'{\n'
	'  "intent": "create|iterate|surgical_edit|chat|forbidden",\n'
	'  "addon_architecture": "external|driver|deep_integration|ambiguous",\n'
	'  "surgical_description": "",\n'
	'  "needs_clarification": true|false,\n'
	'  "user_level": "iniciante|intermediario|avancado",\n'
	'  "questions": ["pergunta 1"],\n'
	'  "forbidden": false,\n'
	'  "refusal_reason": "",\n'
	'  "extra_features_planned": []\n'
	'}\n'
	'\n'
	'TIPOS DE INTENT:\n'
	'- create: usuario quer criar um addon novo do zero.\n'
	'- iterate: usuario quer melhorar, corrigir ou adicionar funcionalidade a um addon existente.\n'
	'- surgical_edit: usuario pede uma mudanca PEQUENA e ESPECIFICA -- um campo, um valor, uma linha.\n'
	'  Preencha surgical_description com a instrucao exata.\n'
	'- chat: usuario esta fazendo uma pergunta, pedindo explicacao, ou conversando.\n'
	'- forbidden: pedido viola regras de seguranca.\n'
	'\n'
	'DIAGNOSTICO DE ARQUITETURA (addon_architecture) -- raciocine semanticamente, sem keywords:\n'
	'\n'
	'external: o addon ADICIONA funcionalidade nova sobre o NVDA sem substituir nada.\n'
	'  O NVDA continua funcionando igual para todo o resto.\n'
	'  Exemplos: addon que anuncia hora, que le conteudo da tela, que melhora um app especifico.\n'
	'  Implementacao: GlobalPlugin ou AppModule.\n'
	'\n'
	'driver: o addon SUBSTITUI um componente interno do NVDA.\n'
	'  O usuario escolhe esse driver e o NVDA para de usar o componente original.\n'
	'  Toda a funcionalidade passa por esse driver -- menus, botoes, notificacoes, tudo.\n'
	'  Exemplos: sintetizador de voz alternativo, driver de display braille.\n'
	'  Implementacao: SynthDriver ou BrailleDisplayDriver.\n'
	'\n'
	'deep_integration: o addon MODIFICA como o NVDA processa algo internamente.\n'
	'  Nao substitui um componente, mas intercepta o pipeline para alterar o comportamento.\n'
	'  Exemplos: filtrar todas as falas do NVDA, interceptar todas as teclas globalmente.\n'
	'  Implementacao: extension points (register/unregister no pipeline do NVDA).\n'
	'\n'
	'ambiguous: o pedido pode ser external OU driver, e a diferenca muda tudo.\n'
	'  Use quando a descricao menciona uma tecnologia de audio/voz/braille sem deixar claro\n'
	'  se o usuario quer substituir o componente todo ou apenas acionar sob demanda.\n'
	'  QUANDO ambiguous: OBRIGATORIAMENTE defina needs_clarification=true e formule\n'
	'  UMA pergunta funcional, simples, no nivel do usuario:\n'
	'    - Para iniciante: use linguagem do dia a dia, sem termos tecnicos.\n'
	'      Ex: "Voce quer que o NVDA inteiro fale com essa voz (inclusive menus e botoes),\n'
	'           ou so um botao para ouvir algo especifico com essa voz quando voce quiser?"\n'
	'    - Para intermediario: pode usar termos do NVDA.\n'
	'      Ex: "Esse addon deve substituir o sintetizador atual do NVDA por completo,\n'
	'           ou deve ser acionado por atalho quando necessario?"\n'
	'    - Para avancado: pode ser tecnico.\n'
	'      Ex: "O pedido implica SynthDriver (substitui todo o pipeline de fala)\n'
	'           ou GlobalPlugin com chamada sob demanda via atalho?"\n'
	'\n'
	'REGRA CRITICA: A pergunta arquitetural elimina ramos inteiros de trabalho.\n'
	'  A diferenca entre driver e external nao e de implementacao -- e de experiencia:\n'
	'  driver afeta TODO o NVDA; external e acionado quando o usuario decide.\n'
	'  Pergunte sempre que houver ambiguidade arquitetural real.\n'
	'\n'
	'PEDIDOS PROIBIDOS - intent=forbidden, forbidden=true, refusal_reason preenchido:\n'
	'- Coletaria dados do usuario sem seu conhecimento ou ativacao explicita.\n'
	'- Modificaria comportamento CORE do NVDA de forma perigosa.\n'
	'\n'
	'extra_features_planned - funcionalidades NAO pedidas que a IA adicionaria.\n'
	'Se houver, gere UMA pergunta de confirmacao em questions.\n'
	'\n'
	'DETECCAO DE NIVEL:\n'
	'- iniciante: linguagem simples, sem termos tecnicos\n'
	'- intermediario: conhece o NVDA, usa alguns termos\n'
	'- avancado: usa termos tecnicos, globalPlugin, appModule, SynthDriver\n'
	'\n'
	'QUANDO PERGUNTAR (needs_clarification=true):\n'
	'- addon_architecture == ambiguous (SEMPRE perguntar)\n'
	'- Pedido vago sobre O QUE deve fazer\n'
	'- Falta saber para qual aplicativo (se aplicavel)\n'
	'- Ambiguidade critica: sem essa informacao o resultado seria errado\n'
	'NUNCA PERGUNTE sobre versao do NVDA, estrutura interna de arquivos.\n'
	'\n'
	'Sem texto fora do JSON.'
)



@dataclass
class ClarificationResult:
	"""Resultado da analise do Clarifier."""
	needs_clarification: bool
	questions: list[str]
	enriched_query: str = ""
	user_level: str = "intermediario"
	forbidden: bool = False
	refusal_reason: str = ""
	extra_features_planned: list[str] = field(default_factory=list)
	intent: str = "create"           # create | iterate | surgical_edit | chat | forbidden
	surgical_description: str = ""   # instrucao deterministica para surgical_edit
	addon_architecture: str = "external"  # external | driver | deep_integration | ambiguous


def analyze_query(query: str) -> ClarificationResult:
	"""
	Analisa a query, detecta nivel e arquitetura do addon, retorna perguntas se necessario.
	Regra 5: LLM decide semantica. Este metodo decide fluxo.
	"""
	if not query or not query.strip():
		return ClarificationResult(needs_clarification=False, questions=[])

	log_llm_call(_logger, f"clarifier_v{MODULE_VERSION}", query)

	try:
		_CLARIFIER_SCHEMA = {
			"type": "json_schema",
			"json_schema": {
				"name": "clarifier_result",
				"schema": {
					"type": "object",
					"properties": {
						"intent":                   {"type": "string", "enum": ["create", "iterate", "surgical_edit", "chat", "forbidden"]},
						"addon_architecture":       {"type": "string", "enum": ["external", "driver", "deep_integration", "ambiguous"]},
						"surgical_description":     {"type": "string"},
						"needs_clarification":      {"type": "boolean"},
						"user_level":               {"type": "string", "enum": ["iniciante", "intermediario", "avancado"]},
						"questions":                {"type": "array", "items": {"type": "string"}},
						"forbidden":                {"type": "boolean"},
						"refusal_reason":           {"type": "string"},
						"extra_features_planned":   {"type": "array", "items": {"type": "string"}},
					},
					"required": ["intent", "addon_architecture", "needs_clarification", "user_level", "forbidden"],
					"additionalProperties": False,
				}
			}
		}
		resp = call_with_structured_output(
			f"Pedido do usuario: {query}",
			_CLARIFIER_SCHEMA,
			system_override=_CLARIFIER_SYSTEM,
		)
		raw = resp.content or ""
		log_llm_response(_logger, f"clarifier_v{MODULE_VERSION}", raw)

		if not raw.strip():
			_logger.warning("[AVISO] Clarifier: API retornou conteudo vazio. Prosseguindo sem perguntas.")
			return ClarificationResult(needs_clarification=False, questions=[])

		clean = raw.strip()
		clean = re.sub(r"^```(?:json)?\n?", "", clean)
		clean = re.sub(r"\n?```$", "", clean)

		if not clean.strip():
			_logger.warning("[AVISO] Clarifier: resposta apos limpeza esta vazia. Prosseguindo sem perguntas.")
			return ClarificationResult(needs_clarification=False, questions=[])

		data = json.loads(clean)
		return _parse_clarifier_json(data)

	except json.JSONDecodeError:
		_logger.info("[INFO] Clarifier: JSON invalido. Tentando extrair objeto do texto...")
		try:
			data = _extract_json_fallback(raw)
			return _parse_clarifier_json(data)
		except (json.JSONDecodeError, KeyError) as exc2:
			_logger.warning("[AVISO] Clarifier: fallback JSON falhou (%s). Prosseguindo sem perguntas.", exc2)
			return ClarificationResult(needs_clarification=False, questions=[])
	except (LLMClientError, Exception) as exc:
		exc_str = str(exc)
		if "400" in exc_str or "Bad Request" in exc_str:
			_logger.warning("[AVISO] Clarifier: conteudo bloqueado pela API (%s). Retornando forbidden.", exc)
			return ClarificationResult(
				needs_clarification=False, questions=[],
				forbidden=True, intent="forbidden",
				refusal_reason="Pedido bloqueado pela politica de conteudo da API.",
			)
		_logger.warning("[AVISO] Clarifier falhou (%s). Prosseguindo sem perguntas.", exc)
		return ClarificationResult(needs_clarification=False, questions=[])


def _extract_json_fallback(text: str) -> dict:
	"""Tenta extrair o primeiro objeto JSON completo do texto.

	v1.5.2 (2026-05-11): corrige 'Extra data' — modelo as vezes gera
	JSON valido seguido de mais texto. Agora tenta parsear do primeiro {
	ao ultimo } e, se falhar com Extra data, faz parse incremental
	(fecha no primeiro objeto JSON completo).
	"""
	text = text.strip()
	if not text:
		raise json.JSONDecodeError("texto vazio", text, 0)

	start = text.find("{")
	if start == -1:
		raise json.JSONDecodeError("sem { encontrado", text, 0)

	# Tenta do primeiro { ao ultimo } (cobre JSON unico com nesting)
	end = text.rfind("}")
	if end != -1 and start < end:
		candidate = text[start:end + 1]
	else:
		raise json.JSONDecodeError("sem } encontrado", text, 0)

	# Se falhar com Extra data (texto apos o fechamento),
	# tenta parse incremental: encontra o primeiro objeto completo
	# contando nested braces.
	try:
		return json.loads(candidate)
	except json.JSONDecodeError as e:
		if "Extra data" not in str(e):
			raise
		depth = 0
		for i, ch in enumerate(candidate):
			if ch == "{":
				depth += 1
			elif ch == "}":
				depth -= 1
				if depth == 0:
					obj = candidate[:i + 1]
					return json.loads(obj)
		raise


def _parse_clarifier_json(data: dict) -> ClarificationResult:
	"""Converte dict do JSON (principal ou fallback) em ClarificationResult.

	Extraida como funcao separada para reuso entre o fluxo principal e o fallback.
	v1.5.1: DRY — a logica de parse estava duplicada no bloco try.
	"""
	intent = str(data.get("intent", "create")).lower()
	surgical_description = str(data.get("surgical_description", "")).strip()

	addon_architecture = str(data.get("addon_architecture", "external")).lower()
	if addon_architecture not in _VALID_ARCHITECTURES:
		addon_architecture = "external"

	if intent == "forbidden" or data.get("forbidden", False):
		reason = str(data.get("refusal_reason", "Pedido nao permitido."))
		log_decision(_logger, "pedido_recusado", reason[:100])
		return ClarificationResult(
			needs_clarification=False, questions=[],
			user_level="intermediario", forbidden=True,
			refusal_reason=reason, intent="forbidden",
			addon_architecture=addon_architecture,
		)

	needs = bool(data.get("needs_clarification", False))
	questions = [str(q) for q in data.get("questions", []) if q][:5]
	user_level = str(data.get("user_level", "intermediario")).lower()
	if user_level not in ("iniciante", "intermediario", "avancado"):
		user_level = "intermediario"
	extra_features = [str(e) for e in data.get("extra_features_planned", []) if e]

	log_decision(_logger, "intent_detectado",
				 f"intent={intent} level={user_level} "
				 f"architecture={addon_architecture} "
				 f"surgical={bool(surgical_description)}")

	if intent == "surgical_edit" and surgical_description:
		log_decision(_logger, "surgical_edit", surgical_description[:100])
		return ClarificationResult(
			needs_clarification=False, questions=[],
			user_level=user_level, intent="surgical_edit",
			surgical_description=surgical_description,
			addon_architecture=addon_architecture,
		)

	if needs and questions:
		log_decision(_logger, "clarificacao_necessaria",
					 f"{len(questions)} pergunta(s): {'; '.join(questions)} "
					 f"[architecture={addon_architecture}]")
		return ClarificationResult(
			needs_clarification=True, questions=questions,
			user_level=user_level, intent=intent,
			extra_features_planned=extra_features,
			addon_architecture=addon_architecture,
		)

	log_decision(_logger, "query_clara",
				 f"intent={intent} level={user_level} architecture={addon_architecture}")
	return ClarificationResult(
		needs_clarification=False, questions=[],
		user_level=user_level, intent=intent,
		extra_features_planned=extra_features,
		addon_architecture=addon_architecture,
	)


def build_enriched_query(
	original_query: str,
	questions: list[str],
	answers: list[str],
	user_level: str = "intermediario",
	addon_architecture: str = "external",
) -> str:
	"""
	Monta query enriquecida com respostas do usuario, nivel e arquitetura detectada.
	O nivel e arquitetura sao passados ao Planner para gerar o tipo correto de addon.
	Regra 5: combinacao deterministica -- nao LLM.
	"""
	parts = [original_query]

	if questions and answers:
		parts.append("\n\nInformacoes adicionais fornecidas pelo usuario:")
		for q, a in zip(questions, answers):
			if a and a.strip():
				parts.append(f"- {q}: {a.strip()}")

	parts.append(f"\n[Nivel do usuario detectado: {user_level}]")

	# Injeta arquitetura apenas quando relevante para o Planner
	if addon_architecture and addon_architecture != "external":
		parts.append(f"[Arquitetura detectada: {addon_architecture}]")

	return "\n".join(parts)
