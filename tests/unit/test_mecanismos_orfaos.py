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
	"_base.clear_prompt_response_cache": "idem clear_model_resolution_cache",
	"llm_factory.get_available_backends": "introspeccao usada so por diagnostico",
	"clarifier.get_clarifier_model": "resolvido inline em analyze_query; getter mantido para teste",
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
