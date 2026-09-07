"""
Fitness function: mecanismo que existe precisa ter quem o consuma.

O PADRAO QUE ESTE TESTE EXISTE PARA PEGAR

Ao longo da sessao de 2026-08-29/30 o mesmo defeito apareceu SEIS vezes, sempre
com a mesma forma -- a peca certa existia e estava desligada de quem decide:

  1. ESTRUTURA-008 detectava addon sem ponto de entrada... e o veredito do
     pipeline nunca consultava. 9 addons quebrados entregues como sucesso.
  2. Os hooks do pre-commit estavam configurados... e nao instalados. 2 deles
     eram incapazes de passar.
  3. Os 3 documentos de metodologia eram obrigatorios pelo CLAUDE.md... e nao
     apareciam em prompt nenhum.
  4. `_SYNTHESIS_TEMPLATE` era codigo morto ha 3 meses... e 4 testes verdes o
     faziam parecer vivo.
  5. `iteration_budget.can_continue()` era consultado a cada tentativa... contra
     um medidor que so era alimentado no fim. 4,6 milhoes de tokens contra um
     teto de 500 mil.
  6. `target_files` era OBRIGATORIO no schema... e o planner nunca preencheu, o
     que fez o guarda de decomposicao contar zero e nunca disparar.

Nenhum foi falta de conhecimento. Todos foram desconexao. Este teste torna a
proxima ocorrencia visivel no momento em que ela nasce, em vez de meses depois
numa auditoria manual.

COMO ELE FALHA DE FORMA UTIL

Nao proibe funcao sem consumidor -- utilitario testado e nao conectado e uma
decisao legitima, e o projeto ja registrou isso antes (ver
`addon_builder.validate_manifest` no changelog 97.21.0). O que ele exige e que
a decisao seja EXPLICITA: cada orfao conhecido entra em `_ORFAOS_ACEITOS` com o
motivo. Um orfao novo, nao declarado, quebra o teste.
"""

import ast
import collections
import pathlib

_RAIZ = pathlib.Path(__file__).resolve().parents[2] / "addon" / "globalPlugins" / "nvdastudio"
_IGNORAR_DIRS = {"lib", "nvda_docs_cache", "__pycache__"}

# Orfaos conhecidos e ACEITOS, cada um com o motivo. Tirar algo daqui exige
# conectar a funcao ou remove-la (Regra 3 do README, anti-legado).
_ORFAOS_ACEITOS: dict[str, str] = {
	# --- API publica de modulos que ainda nao tem superficie de UI ---
	"skills_hub.list_skills": "catalogo de skills sem tela propria; get_skill() e o caminho real",
	"skills_hub.search_skills": "idem list_skills",
	"skills_hub.enable_skill": "idem list_skills",
	"skills_hub.disable_skill": "idem list_skills",
	"skills_hub.get_skill_registry": "idem list_skills",
	"skills_hub.get_skill_definitions": "idem list_skills",
	"cost_tracker.format_cost": "custo e computado mas nunca exibido -- achado ja registrado no changelog 97.34.0",
	"cost_tracker.get_model_cost_per_token": "idem format_cost",
	"cost_tracker.is_discounted": "idem format_cost",
	"pricing.estimate_cost_brl": "conversao BRL sem consumidor; a exibicao usa USD",
	# --- getters de timeout com politica divergente da usada em producao ---
	# ACHADO 2026-08-30, NAO corrigido de proposito: `get_api_timeout()` aplica
	# politica por modelo (kimi 240s, deepseek 120s, default 180s) enquanto
	# provider_client._TIMEOUT e ollama_client._OLLAMA_CLOUD_TIMEOUT usam 300s
	# fixo. Conectar os clientes ao getter ENCURTARIA o timeout do modelo padrao
	# de producao de 300s para 240s -- com steps de 400 mil tokens observados ao
	# vivo, isso arrisca criar timeout onde hoje nao ha. Exige decisao de
	# produto com medicao, nao um refactor cego.
	"timeouts.get_api_timeout": "politica divergente da usada nos clientes; ver comentario acima",
	"timeouts.get_api_stale_timeout": "idem get_api_timeout",
	"timeouts.get_ttfb_timeout": "idem get_api_timeout",
	"timeouts.get_sandbox_timeout": "code_sandbox usa constante propria; mesma classe de divergencia",
	"timeouts.get_pipeline_grace_period": "periodo de graca nunca aplicado ao pipeline",
	# --- utilitarios testados e deliberadamente nao conectados ---
	"addon_builder.export_addon_zip": "exportacao alternativa; o fluxo real usa .nvda-addon",
	"addon_builder.generate_quality_report": "relatorio sem superficie de UI",
	"addon_builder.get_blocking_structural_issues": "filtro auxiliar; validate_addon_structure e o caminho real",
	"addon_builder.validate_python_structure": "testado e nao conectado -- precedente registrado no changelog 97.21.0",
	"project_policy.is_below_project_baseline": "helper de politica; a comparacao real usa parse_version_tuple",
	"model_pricing.estimate_call_cost": "precificacao por chamada sem consumidor; o agregado usa ai/pricing.py",
	"model_pricing.get_pricing_gap_reason": "idem estimate_call_cost",
	"model_registry.clear_model_resolution_cache": "gancho de teste para invalidar cache entre casos",
	"llm_factory.get_available_backends": "introspeccao usada so por diagnostico",
	"clarifier.get_clarifier_model": "resolvido inline em analyze_query; getter mantido para teste",
	# Caminho 3: agentic_driver.run_agentic_build SAIU da lista no Slice 3 --
	# o orchestrator (_run_pipeline_agentic) passou a consumi-lo de verdade,
	# atras da flag NVDASTUDIO_AGENTIC_MODE. A fitness function pegou a
	# transicao de orfao->consumido sozinha, exatamente o proposito dela.
	"addon_builder.substituir_codigo_dos_blocos": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
	"addon_builder.validate_python_syntax": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
	"addon_versioning.changelog_is_uninformative": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
	"addon_versioning.enforce_version_bump": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
	"addon_versioning.extract_previous_version": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
	"anthropic_memory_tool.handle_memory_command": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
	"cost_tracker.estimate_pipeline_cost": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
	"external_search.format_results_for_prompt": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
	"external_search.search_external": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
	"injection_guard.sanitize_untrusted_block": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
	"nvda_context.get_docs_accessibility_audit": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
	"nvda_context.get_docs_agent_runner": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
	"nvda_context.get_docs_agent_template": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
	"nvda_context.get_docs_assembler": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
	"nvda_context.get_docs_design_review": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
	"nvda_context.get_docs_doc_generator": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
	"nvda_context.get_docs_test_generator": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
	"nvda_context.nvda_topics_marker": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
}


def _modulos() -> list[pathlib.Path]:
	return [
		f for f in _RAIZ.rglob("*.py")
		if not any(part in _IGNORAR_DIRS for part in f.parts)
	]


def _corpo_producao() -> str:
	return "\n".join(f.read_text(encoding="utf-8", errors="ignore") for f in _modulos())


def _funcoes_publicas_de_topo() -> list[tuple[str, str]]:
	"""(modulo, nome) de cada def publica no nivel de modulo."""
	achadas: list[tuple[str, str]] = []
	for f in _modulos():
		try:
			tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
		except SyntaxError:
			continue
		for node in tree.body:
			if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
				continue
			if node.name.startswith("__") or node.name in ("main", "run"):
				continue
			achadas.append((f.stem, node.name))
	return achadas


_CONSTANTES_ACEITAS: dict[str, str] = {
	# Reexport de compatibilidade: nomes publicos que consumidores externos e
	# testes usam; a producao le a estrutura original.
	# Conhecimento curado que HOJE nao entra em nenhum prompt. Nao e defeito:
	# e material disponivel e ainda nao ligado. Justificado aqui para que a
	# escolha seja explicita -- ou se liga, ou se apaga, nunca fica esquecido.
	"nvda_context.NVDA_QUICK_TIPS": (
		"16 fatos curtos de API do NVDA; a fonte completa do NVDA ja e injetada "
		"nos prompts de codigo, entao ligar isto so faria sentido se medisse "
		"melhora -- ainda nao medido"
	),
	"nvda_context.NVDA_VERSION_TABLE": (
		"tabela de versoes; a politica de baseline aplicada de fato vive em "
		"utils/project_policy.py (PROJECT_MIN_NVDA), que a producao le"
	),
	"controller_client_context.CTRL_CLIENT_RULE_IDS": (
		"lista de IDs derivada de CTRL_CLIENT_RULES para consulta e teste; as "
		"regras aplicadas vem do texto completo em CTRL_CLIENT_RULES"
	),
	"rule_registry.COMMUNITY_ACCESS_SOURCES": (
		"procedencia das regras, para auditoria humana e citacao; nao entra em "
		"decisao de execucao"
	),
	"opencode_go_client._KNOWN_MODELS": (
		"catalogo de referencia do provedor; a validacao real acontece na "
		"resposta HTTP, nao numa lista local que envelhece"
	),
	"settings_panel._DEFAULT_MODELS": (
		"defaults por provedor consultados pela GUI via resolucao dinamica; "
		"mantido como referencia do catalogo esperado"
	),
	"engineering_principles.SOURCE_DOCS": "procedencia dos 3 documentos de metodologia",
	"engineering_principles.UPDATED_AT": "data da ultima revisao do conteudo destilado",
	"rule_registry.UPDATED_AT": "data da ultima revisao do catalogo de regras",
	"project_policy.ABSOLUTE_MIN_NVDA_TUPLE": "forma em tupla, para comparacao futura",
	"project_policy.PROJECT_LAST_TESTED_NVDA_TUPLE": "forma em tupla, para comparacao futura",
	"addon_versioning.ADDON_LIFECYCLE_PROMPT_TEXT": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
	"controller_client_context.CTRL_CLIENT_CRITIC_ADDENDUM": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
	"controller_client_context.CTRL_CLIENT_SYSTEM_PROMPT": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
	"engineering_principles.ENGINEERING_CRITIC_PROMPT_TEXT": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
	"engineering_principles.ENGINEERING_PLANNING_PROMPT_TEXT": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
	"engineering_principles.ENGINEERING_REVIEW_PROMPT_TEXT": "orfao apos a remocao do pipeline staged (2026-09-06); consumidor era staged -- candidato a limpeza dedicada",
}


def _constantes_de_topo() -> list[tuple[str, str]]:
	"""(modulo, NOME) de cada constante declarada no nivel de modulo."""
	achadas: list[tuple[str, str]] = []
	for f in _modulos():
		try:
			tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
		except SyntaxError:
			continue
		for node in tree.body:
			alvos = []
			if isinstance(node, ast.Assign):
				alvos = [t for t in node.targets if isinstance(t, ast.Name)]
			elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
				alvos = [node.target]
			for t in alvos:
				nome = t.id
				if nome.lstrip("_").isupper() and len(nome.lstrip("_")) > 3:
					achadas.append((f.stem, nome))
	return achadas


def _nomes_lidos() -> collections.Counter:
	"""Quantas vezes cada nome e LIDO em producao (Name em Load + atributo)."""
	usos: collections.Counter = collections.Counter()
	for f in _modulos():
		try:
			tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
		except SyntaxError:
			continue
		for node in ast.walk(tree):
			if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
				usos[node.id] += 1
			elif isinstance(node, ast.Attribute):
				usos[node.attr] += 1
			elif isinstance(node, ast.ImportFrom):
				for a in node.names:
					usos[a.name] += 1
	return usos


class TestConstantesOrfas:
	"""
	Mesma regra das funcoes, aplicada a constantes de modulo.

	Foi essa a forma de defeitos reais desta sessao: um limite declarado,
	documentado e testado -- e nunca consultado. `_MAX_TOTAL_SIZE_MB`,
	`VALID_STATUSES`, `_MAX_TOOL_TIMEOUT`, `_PROGRESS_MIN_APPROVED_DELTA`,
	`_STEP_TIMEOUT_SECONDS`.

	Os piores nao eram inertes, eram MENTIROSOS: `CLARIFIER_MODEL = "kimi-k2.6"`
	com o Clarifier rodando gpt-5.6-luna, e um teste afirmando o contrario;
	`_STEP_TIMEOUT_SECONDS = 180` com um teste exigindo `<= 600` enquanto o
	valor aplicado era 1200. Testes verdes protegendo um comportamento que nao
	existia.
	"""

	def test_toda_constante_de_topo_e_lida_ou_justificada(self):
		usos = _nomes_lidos()
		orfas = []
		for modulo, nome in _constantes_de_topo():
			if usos[nome] > 0:
				continue
			if f"{modulo}.{nome}" in _CONSTANTES_ACEITAS:
				continue
			orfas.append(f"{modulo}.{nome}")
		assert not orfas, (
			"Constantes de modulo nunca lidas em producao:\n  "
			+ ("\n  ").join(sorted(orfas))
			+ "\n\nLigue a constante a quem decide, apague-a, ou declare-a em "
			"_CONSTANTES_ACEITAS COM O MOTIVO. Um limite que ninguem consulta e "
			"pior que nenhum limite: da a impressao de que existe."
		)

	def test_allowlist_de_constantes_nao_tem_entrada_obsoleta(self):
		"""Constante que voltou a ser lida (ou sumiu) nao pode ficar na lista --
		senao a lista vira deposito e para de significar alguma coisa."""
		usos = _nomes_lidos()
		existentes = {f"{m}.{n}" for m, n in _constantes_de_topo()}
		obsoletas = [
			chave for chave in _CONSTANTES_ACEITAS
			if chave not in existentes or usos[chave.split(".", 1)[1]] > 0
		]
		assert not obsoletas, (
			"Entradas obsoletas em _CONSTANTES_ACEITAS:\n  "
			+ ("\n  ").join(sorted(obsoletas))
		)

	def test_toda_constante_aceita_tem_motivo_de_verdade(self):
		vagas = [c for c, motivo in _CONSTANTES_ACEITAS.items() if len(motivo.strip()) < 25]
		assert not vagas, f"Motivo vago demais: {vagas}"


class TestMecanismosOrfaos:
	def test_toda_funcao_de_topo_tem_consumidor_ou_motivo(self):
		"""
		Uma funcao sem consumidor em producao e sem entrada em _ORFAOS_ACEITOS
		e um mecanismo que nasceu desligado -- exatamente o defeito que custou
		9 addons quebrados e 4,6 milhoes de tokens nesta sessao.
		"""
		producao = _corpo_producao()
		novos: list[str] = []
		for modulo, nome in _funcoes_publicas_de_topo():
			chave = f"{modulo}.{nome}"
			if chave in _ORFAOS_ACEITOS:
				continue
			# -1 descarta a propria definicao.
			if producao.count(nome) - 1 <= 0:
				novos.append(chave)
		assert not novos, (
			"Funcao(oes) sem nenhum consumidor em producao:\n  "
			+ "\n  ".join(sorted(novos))
			+ "\n\nConecte a funcao, remova-a (Regra 3, anti-legado), ou "
			"declare-a em _ORFAOS_ACEITOS COM O MOTIVO. Mecanismo que existe e "
			"ninguem usa foi o defeito mais caro desta sessao."
		)

	def test_allowlist_nao_tem_entrada_obsoleta(self):
		"""
		Orfao que voltou a ser usado (ou foi removido) precisa sair da lista --
		senao ela vira um deposito e para de significar alguma coisa.
		"""
		producao = _corpo_producao()
		existentes = {f"{m}.{n}" for m, n in _funcoes_publicas_de_topo()}
		obsoletas: list[str] = []
		for chave in _ORFAOS_ACEITOS:
			nome = chave.split(".", 1)[1]
			if chave not in existentes:
				obsoletas.append(f"{chave} (funcao nao existe mais)")
			elif producao.count(nome) - 1 > 0:
				obsoletas.append(f"{chave} (voltou a ter consumidor)")
		assert not obsoletas, (
			"Entradas obsoletas em _ORFAOS_ACEITOS:\n  " + "\n  ".join(sorted(obsoletas))
		)

	def test_todo_orfao_aceito_tem_motivo_de_verdade(self):
		"""Motivo vazio ou generico nao e decisao explicita -- e carimbo."""
		fracos = [
			chave for chave, motivo in _ORFAOS_ACEITOS.items()
			if len(motivo.strip()) < 15
		]
		assert not fracos, f"Motivo insuficiente em: {sorted(fracos)}"
