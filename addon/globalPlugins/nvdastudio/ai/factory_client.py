"""Cliente do Factory Droid como provedor de LLM (terceiro provedor).

POR QUE EXISTE
--------------
Ate 2026-09-03 o projeto tinha dois provedores: Ollama Cloud e OpenCode Go.
Na mesma sessao os dois falharam -- OpenCode Go com 401 (sem saldo) e Ollama
com 429 (rate limit) -- e a `STRUCTURED_OUTPUT_MODEL_CHAIN`, que parece uma
cadeia de cinco modelos, e na verdade cinco modelos do MESMO provedor: quando
o OpenCode Go cai, a cadeia inteira cai junto e o Planner passa a rodar sem
json_schema.

A Factory entra como terceira perna REAL, por assinatura ja paga, e serve os
MESMOS ids de modelo que o projeto ja roteia (gpt-5.6-luna, kimi-k2.7-code,
kimi-k2.6, glm-5.2, deepseek-v4-flash-0731).

Nao ha "tier barato" para onde fugir: medido em 2026-09-03, o
kimi-k2.7-code (que o projeto ja usa como heavy) e o MAIS BARATO do
catalogo da Factory -- claude-haiku custa 7,4x mais e ainda errou o JSON,
gemini-3.7-flash custa 20,6x. Os multiplicadores da Factory nao seguem o
preco por token dos provedores de origem.

O QUE ELE NAO E
---------------
A Factory nao expoe API de inferencia. A API HTTP deles (api.factory.ai) e de
analytics/sessions. O unico caminho programatico e o `droid exec`, headless,
que e um AGENTE, nao um endpoint de completions. Este cliente o adapta ao
contrato LLMClientProtocol -- com as consequencias documentadas abaixo.

Sem `response_format` nativo: o schema vai no PROMPT. Medido em 2026-09-03
com o `_PLAN_SCHEMA` real (o maior do projeto): 2 de 3 amostras devolveram
JSON valido, com todos os campos, enums corretos, caixa do nome coerente e
`dependencies` limpo. A terceira falhou com is_error. Nao e garantia como o
json_schema do OpenCode Go -- mas o caminho degradado de hoje nao tem garantia
NENHUMA e ainda usa um modelo mais fraco.

ECONOMIA (medida, nao suposta)
------------------------------
Cada decisao aqui saiu de medicao no dia 2026-09-03:

1. SESSAO NOVA A CADA CHAMADA. Reusar sessao (`-s`) acumula historico que e
   reenviado e pago em toda chamada seguinte -- e o orchestrator JA reenvia o
   contexto completo por tentativa, entao o historico seria contexto em
   dobro. E desnecessario: medido, sessoes NOVAS ja leem o harness do cache
   (`cache_read_input_tokens` 94.644 e 41.696 em duas sessoes novas). O
   caching da Factory e entre sessoes, nao so dentro de uma.

2. `--disable-builtin-skills`. Medido: harness de 15.349 -> 13.475 tokens
   (-12%). O NVDAStudio traz o proprio contexto; as skills da Factory sao
   peso morto aqui.

3. CWD NUM DIRETORIO VAZIO. O `droid exec` e um agente de codigo: apontado
   para um repositorio, ele explora arquivos e cobra por isso. Um diretorio
   temporario vazio elimina esse gasto -- e de quebra reduz o blast radius,
   porque o agente nao enxerga o projeto do usuario.

4. MODELO EXPLICITO SEMPRE. O padrao do droid e `claude-opus-5`, o mais caro
   do catalogo: os 135 mil creditos por plano medidos no spike eram Opus. O
   padrao daqui e o mesmo heavy que o projeto ja usa.
"""

import json
import os
import shutil
import subprocess
import tempfile
from typing import Any, Callable

from ..utils.hidden_process import CREATE_NO_WINDOW
from ..utils.logger import get_logger
from .llm_client import LLMClientError, LLMResponse

MODULE_VERSION = "1.3.0"
_logger = get_logger("factory_client")

# Mesmo heavy que o projeto ja usa no Ollama -- trocar de provedor nao pode
# trocar de modelo por acidente. Nunca claude-opus-5 (padrao do droid, o mais
# caro do catalogo).
_DEFAULT_MODEL = "kimi-k2.7-code"

# Timeout por chamada. O spike com o _PLAN_SCHEMA real levou 108-165s; 600s
# da folga para step de codigo grande sem deixar o pipeline pendurado.
_TIMEOUT_PADRAO = 600

_NOMES_DO_BINARIO = ("droid", "droid.cmd", "droid.exe")

# O `droid` e um AGENTE, nao um endpoint de completions. Sem esta instrucao no
# TOPO do prompt ele intermitentemente decide AGIR -- escreve arquivos, roda
# comandos, ate empacota o .nvda-addon -- e devolve so um RESUMO em vez do
# codigo, o que a extracao nao aproveita. Medido em 2026-09-04, 5 rodadas de um
# prompt estilo montagem/retentativa: SEM esta instrucao 2/5 viraram agenticas
# (uma custou 36.002 creditos, 18x uma resposta normal); COM ela, 5/5 devolveram
# o codigo como TEXTO, com a correcao aplicada, a ~2.000 creditos. Nao e so
# correcao de bug: corta o custo das chamadas que o droid resolvia "trabalhar".
# Read-only NAO basta (o agente as vezes escreve mesmo assim) -- a instrucao e
# que segura. Prefixada, nunca embutida no meio, para maxima primazia de atencao.
_INSTRUCAO_SO_TEXTO = (
	"MODO DE SAIDA: TEXTO PURO. Voce NAO tem permissao para agir. NAO crie, "
	"escreva, mova ou modifique nenhum arquivo. NAO rode comandos. NAO use "
	"nenhuma ferramenta. Sua UNICA saida e o TEXTO da resposta, contendo os "
	"blocos de codigo. Se voce tentar criar arquivos ou empacotar qualquer "
	"coisa, a tarefa FALHA. Apenas ESCREVA o conteudo completo, como blocos de "
	"codigo anotados, nada mais."
)


class FactoryClientError(LLMClientError):
	"""Erro da integracao com o Factory Droid."""
	pass


def _achar_droid() -> str:
	"""Localiza o binario do droid. PATH primeiro, depois os locais padrao."""
	for nome in _NOMES_DO_BINARIO:
		caminho = shutil.which(nome)
		if caminho:
			return caminho
	candidatos = [
		os.path.expanduser(os.path.join("~", "bin", "droid")),
		os.path.expanduser(os.path.join("~", ".factory", "bin", "droid")),
	]
	for base in candidatos:
		for sufixo in ("", ".cmd", ".exe"):
			if os.path.isfile(base + sufixo):
				return base + sufixo
	raise FactoryClientError(
		"Factory Droid nao encontrado. Instale o droid CLI e faca login "
		"(https://docs.factory.ai) ou escolha outro provedor em "
		"NVDA > Preferencias > Configuracoes > NVDAStudio."
	)


def _instrucao_de_schema(response_format: dict | None) -> str:
	"""Traduz um response_format json_schema em instrucao de prompt.

	O `droid exec` nao tem response_format; o `-o json` dele descreve o
	ENVELOPE da execucao, nao o conteudo. Entao o schema vai no texto. As
	`description` de cada campo vao junto DE PROPOSITO: medido em 2026-09-03,
	com o schema compacto (sem descricoes) o modelo devolveu `dependencies`
	com stdlib e caixa divergente no nome do addon; com o schema completo,
	nenhum dos dois defeitos apareceu.
	"""
	if not response_format:
		return ""
	esquema = (response_format.get("json_schema") or {}).get("schema")
	if not esquema:
		return ""
	return (
		"\n\nDevolva APENAS um objeto JSON valido, sem markdown, sem cercas de "
		"codigo, sem texto antes ou depois. O JSON deve obedecer a ESTE schema, "
		"incluindo TODAS as instrucoes escritas nos campos 'description' -- elas "
		"nao sao comentarios, sao requisitos:\n\n"
		+ json.dumps(esquema, ensure_ascii=False, indent=1)
	)


class FactoryClient:
	"""Adapta `droid exec` ao contrato LLMClientProtocol."""

	def __init__(self, api_key: str = "", model_id: str = _DEFAULT_MODEL):
		# api_key opcional: o droid tambem autentica pelo login do proprio CLI
		# (~/.factory/auth.v2.keyring). Quando ha chave configurada, ela vence
		# -- permite usar uma conta diferente da que esta logada na maquina.
		self._api_key = (api_key or "").strip()
		self._model_id = model_id or _DEFAULT_MODEL
		self._droid = _achar_droid()

	def chat(
		self,
		user_message: str,
		on_chunk: Callable[[str], None] | None = None,
		system_override: str | None = None,
		tools: list | None = None,
		tool_choice: object | None = None,
		tool_results: list | None = None,
		response_format: dict | None = None,
		reasoning_effort: str | None = None,
		step_type: str = "",
		**kwargs: Any,
	) -> LLMResponse:
		# SEM tool use: falha ALTO em vez de gerar lixo caro.
		#
		# `droid exec` e um agente com as ferramentas DELE; nao aceita
		# definicao de funcao do chamador como um endpoint de completions
		# aceita. Ate a 1.0.0 este cliente recebia `tools` e ignorava em
		# silencio -- e o silencio custou caro.
		#
		# Medido na rodada de 2026-09-03 17:26: web_researcher e
		# design_review_agent entregam o resultado por tool call OBRIGATORIA
		# (`entregar_sintese`, `entregar_critica_challenger` -- padrao "final
		# answer as tool"). Sem o canal, os dois deram voltas e reprovaram:
		#
		#   "a ferramenta entregar_sintese solicitada nao esta disponivel"
		#   "A ferramenta entregar_critica_challenger nao esta disponivel"
		#
		#   research_openai  692.032 tokens, reprovado 3x
		#   dr0              132.875 tokens, reprovado
		#
		# 824.907 tokens gastos tentando chamar o que nao existe. Levantar aqui
		# faz o orchestrator tratar como falha de infraestrutura (guarda da
		# 5.79.0) e rotear para um provedor com tool use -- correto, e barato.
		if tools:
			nomes = [
				(t.get("function", {}) or {}).get("name") or t.get("name") or "?"
				for t in tools if isinstance(t, dict)
			]
			raise FactoryClientError(
				"Factory Droid nao aceita ferramentas definidas pelo chamador "
				f"(pedidas: {', '.join(str(n) for n in nomes)}). Este step precisa "
				"de um provedor com tool use nativo."
			)

		prompt = _INSTRUCAO_SO_TEXTO + "\n\n" + "\n\n".join(
			p for p in (system_override, user_message) if p
		) + _instrucao_de_schema(response_format)

		# Diretorio vazio E descartavel: serve de cwd (para o agente nao
		# explorar o projeto) e de casa do arquivo de prompt.
		trabalho = tempfile.mkdtemp(prefix="nvdastudio_factory_")
		arquivo_prompt = os.path.join(trabalho, "prompt.txt")
		try:
			with open(arquivo_prompt, "w", encoding="utf-8") as fh:
				fh.write(prompt)

			cmd = [
				self._droid, "exec",
				"-o", "json",
				"-m", self._model_id,
				"--disable-builtin-skills",
				"--cwd", trabalho,
				"-f", arquivo_prompt,
			]
			if reasoning_effort:
				cmd += ["-r", reasoning_effort]

			env = dict(os.environ)
			if self._api_key:
				env["FACTORY_API_KEY"] = self._api_key

			try:
				proc = subprocess.run(
					cmd, capture_output=True, text=True, encoding="utf-8",
					errors="replace", timeout=_TIMEOUT_PADRAO, env=env, cwd=trabalho,
					# Sem isto o `droid` abre uma janela de console no Windows que
					# rouba o foco do NVDA (0 fora do Windows -- portavel).
					creationflags=CREATE_NO_WINDOW,
				)
			except subprocess.TimeoutExpired:
				raise FactoryClientError(
					f"Factory Droid excedeu {_TIMEOUT_PADRAO}s no modelo {self._model_id}."
				) from None
			except OSError as exc:
				raise FactoryClientError(f"Nao foi possivel executar o droid: {exc}") from exc

			return self._ler_envelope(proc.stdout, proc.stderr, proc.returncode)
		finally:
			shutil.rmtree(trabalho, ignore_errors=True)

	def _ler_envelope(self, stdout: str, stderr: str, returncode: int) -> LLMResponse:
		"""Converte o envelope do `droid exec -o json` em LLMResponse."""
		bruto = (stdout or "").strip()
		if not bruto:
			raise FactoryClientError(
				f"Factory Droid nao devolveu saida (exit={returncode}): "
				f"{(stderr or '')[:300]}"
			)
		# O droid pode imprimir avisos antes do JSON; o envelope e a ULTIMA
		# linha que parseia como objeto.
		envelope = None
		for linha in reversed(bruto.split("\n")):
			linha = linha.strip()
			if not linha.startswith("{"):
				continue
			try:
				envelope = json.loads(linha)
				break
			except json.JSONDecodeError:
				continue
		if envelope is None:
			raise FactoryClientError(
				f"Saida do Factory Droid nao e JSON reconhecivel: {bruto[:300]}"
			)

		if envelope.get("is_error"):
			raise FactoryClientError(
				"Factory Droid reportou erro na execucao: "
				f"{str(envelope.get('result') or envelope.get('subtype'))[:300]}"
			)

		uso = envelope.get("usage") or {}
		conteudo = envelope.get("result") or ""

		# tokens_used alimenta o medidor de orcamento, que e uma regua de
		# CUSTO. Conta o que e cobrado como token novo (entrada, saida e
		# criacao de cache) e NAO conta `cache_read_input_tokens`, que e
		# fracao do preco: somar leitura de cache a peso cheio penalizaria
		# justamente o mecanismo que barateia a rodada, e faria o medidor
		# recusar trabalho que custa pouco. O numero completo, incluindo
		# cache_read e os creditos que a propria Factory reporta, vai em
		# usage_breakdown -- nada fica escondido.
		tokens = (
			int(uso.get("input_tokens") or 0)
			+ int(uso.get("output_tokens") or 0)
			+ int(uso.get("cache_creation_input_tokens") or 0)
		)
		detalhe = dict(uso)
		detalhe["total_tokens"] = tokens
		detalhe["session_id"] = envelope.get("session_id", "")

		_logger.info(
			"[FACTORY] model=%s tokens_novos=%d cache_read=%s creditos=%s dur_ms=%s",
			self._model_id, tokens, uso.get("cache_read_input_tokens"),
			uso.get("factory_credits"), envelope.get("duration_ms"),
		)
		return LLMResponse(
			content=conteudo,
			model_used=self._model_id,
			tokens_used=tokens,
			usage_breakdown=detalhe,
		)
