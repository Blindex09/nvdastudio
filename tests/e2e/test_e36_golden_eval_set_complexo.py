import os

import pytest

from .test_criacao_completa import _rodar_pipeline_e2e, _E2E_OUTPUT_DIR

HAS_OLLAMA = os.environ.get("OLLAMA_API_KEY", "").strip()
# 2026-08-17: critic.py 3.19.0 -- o Critic agora SEMPRE usa OpenCode Go
# (prompt caching), independente do provider ativo. Sem essa chave, TODA
# avaliacao de step falha com "Chave API para opencode_go nao configurada"
# -- achado real ao vivo (madrugada 2026-08-17/18, rodada 1 do loop): os
# 2 casos deste arquivo rodaram e "passaram" no pytest (test_e36 nao exige
# success=True) mas o pipeline inteiro falhou em segundos, 0 tokens gastos,
# nenhum sinal real coletado -- so desperdicou tempo/custo do Ollama sem
# testar nada. Adicionado ao skip guard pra nao rodar (e enganar) sem as
# 2 chaves.
HAS_OPENCODE_GO = os.environ.get("OPENCODE_GO_API_KEY", "").strip()
skip_unless_ollama = pytest.mark.skipif(
	not HAS_OLLAMA or not HAS_OPENCODE_GO,
	reason=("Ollama Cloud token nao disponivel" if not HAS_OLLAMA else "OpenCode Go token nao disponivel (necessario pro Critic, ver critic.py 3.19.0)")
)


def _responde_clarificacao_com_defaults_sensatos(perguntas: list[str]) -> list[str]:
	"""on_clarify pra rodar sem humano real -- decisoes razoaveis e
	explicitas, nunca inventadas por acaso (mesma logica usada na sessao
	manual de 2026-08-07, agora persistida como parte do caso de teste)."""
	respostas = []
	for q in perguntas:
		ql = q.lower()
		if "chave" in ql or "api key" in ql or "credencial" in ql:
			respostas.append(
				"A chave de API deve ser configurada pelo usuario na tela de "
				"Configuracoes do proprio addon, salva via config.conf com "
				"config.conf.spec declarado -- nunca hardcoded."
			)
		elif "gesto" in ql or "atalho" in ql or "tecla" in ql:
			respostas.append(
				"Use um atalho NVDA+Shift+<letra> para a acao principal, e um "
				"item no menu Ferramentas do NVDA para acoes secundarias."
			)
		elif "formato" in ql or "saida" in ql or "resultado" in ql:
			respostas.append(
				"O resultado deve ser falado pelo NVDA (ui.message) e tambem "
				"disponibilizado numa janela de texto navegavel para releitura."
			)
		else:
			respostas.append(
				"Siga a pratica mais simples e segura para addons NVDA: sem "
				"coleta de dados do usuario, sempre com feedback sonoro, "
				"sempre com tratamento de erro visivel."
			)
	return respostas


_GOLDEN_PROMPTS_COMPLEXOS = [
	pytest.param(
		"AssistenteLeituraGemini",
		(
			"Crie um addon NVDA complexo chamado AssistenteLeituraGemini: um "
			"assistente de leitura com IA que usa a API do Google Gemini "
			"internamente. Funcionalidades: (1) resumir o texto selecionado no "
			"foco atual usando o Gemini; (2) responder perguntas livres do "
			"usuario sobre o texto selecionado, via dialogo dedicado; (3) "
			"pesquisar na web (via Gemini com busca nativa, quando disponivel) "
			"para complementar a resposta quando o texto selecionado nao tiver "
			"informacao suficiente; (4) salvar um historico local das "
			"perguntas e respostas para consulta posterior, navegavel numa "
			"janela propria. O addon precisa de uma tela de configuracoes "
			"propria (chave da API do Gemini, idioma da resposta, se deve "
			"ativar a busca web do Gemini). Trate erros de rede e de chave "
			"invalida com mensagens claras faladas pelo NVDA. Gere tambem "
			"testes automatizados cobrindo a logica de integracao com o "
			"Gemini (com mocks, sem chamada de rede real nos testes)."
		),
		id="assistente_leitura_gemini",
	),
	pytest.param(
		"GeminiMultimodal",
		(
			"Crie um addon NVDA complexo chamado GeminiMultimodal: um "
			"assistente multimodal que usa a API do Google Gemini "
			"internamente para acessibilidade de midia. Funcionalidades: "
			"(1) descrever em texto uma imagem selecionada/copiada pelo "
			"usuario (arquivo local ou area de transferencia), falando a "
			"descricao pelo NVDA; (2) transcrever para texto um arquivo de "
			"audio escolhido pelo usuario via dialogo de selecao de arquivo; "
			"(3) transcrever para texto a faixa de audio de um arquivo de "
			"video escolhido da mesma forma; (4) exibir o resultado (imagem, "
			"audio ou video) numa janela de texto navegavel, com opcao de "
			"salvar em .txt. O addon precisa de uma tela de configuracoes "
			"propria (chave da API do Gemini, idioma de saida da descricao/"
			"transcricao). Chamadas de rede (upload de arquivo pro Gemini) "
			"devem rodar em thread separada para nao travar o NVDA, com "
			"feedback sonoro de progresso. Trate erros de rede, arquivo "
			"invalido/corrompido e chave invalida com mensagens claras "
			"faladas pelo NVDA. Gere tambem testes automatizados cobrindo a "
			"logica de integracao com o Gemini (com mocks, sem chamada de "
			"rede real nos testes)."
		),
		id="gemini_multimodal_midia",
	),
]


@skip_unless_ollama
class TestGoldenEvalSetComplexoNaoReproduzBugsConhecidos:
	"""Pedidos complexos reais que ja quebraram o pipeline em producao (teste
	manual de 2026-08-07) -- cada assercao aqui e a regressao de UM bug ja
	corrigido, nao uma expectativa de sucesso total do pipeline."""

	@pytest.mark.parametrize("addon_name,pedido", _GOLDEN_PROMPTS_COMPLEXOS)
	def test_pedido_complexo_nao_reproduz_bugs_conhecidos(self, addon_name, pedido, request):
		caso_id = request.node.callspec.id
		report = _rodar_pipeline_e2e(
			addon_name, pedido, _E2E_OUTPUT_DIR,
			on_clarify=_responde_clarificacao_com_defaults_sensatos,
		)

		issues_por_step = {
			s.step_type: " ".join(s.issues).lower() for s in report.steps
		}

		# Bug 1 (api_key_validator.py 1.1.0): falso-positivo de "chave
		# hardcoded" num caminho de arquivo/identificador comum.
		code_gen_issues = issues_por_step.get("code_generation", "")
		if "api key hardcoded" in code_gen_issues:
			# Uma chave REAL hardcoded ainda deve ser pega -- so falha o
			# teste se o padrao bater em algo que claramente NAO e uma
			# chave real (heuristica: nenhum digito no trecho citado).
			pytest.fail(
				f"[{caso_id}] code_generation ainda reporta 'API key hardcoded' -- "
				f"verificar se e uma chave real ou o falso-positivo do bug 1 voltou. "
				f"Issues: {code_gen_issues[:300]}"
			)

		# Bug 2 (critic.py 3.9.0): critic sem teto de tokens estendido
		# causando JSON cortado/vazio ao avaliar output grande.
		for step_type, issues_text in issues_por_step.items():
			assert "critic retornou vazio ou sem json reconhecivel" not in issues_text, (
				f"[{caso_id}] step={step_type}: critic devolveu vazio/sem JSON -- "
				f"regressao do bug 2 (teto de tokens padrao em vez de estendido)."
			)

		# Bug 3 (planner.py 2.21.0): manifest_builder ausente do plano.
		step_types_executados = {s.step_type for s in report.steps}
		assert "manifest_builder" in step_types_executados, (
			f"[{caso_id}] manifest_builder NAO apareceu nos steps executados -- "
			f"regressao do bug 3 (_inject_manifest ausente/quebrado). "
			f"Steps executados: {sorted(step_types_executados)}"
		)

		# Bugs 4 e 5 (web_researcher.py 4.5.0 + critic.py 3.10.0):
		# web_research devolvendo bloco de codigo Python em vez de pesquisa.
		# Checa o output cru (output_preview), nao o texto do issue -- mais
		# robusto que casar frase exata do veredito do critic, e testa o
		# sintoma real (o marcador de fence que causou o bug) diretamente.
		web_research_step = next(
			(s for s in report.steps if s.step_type == "web_research"), None
		)
		if web_research_step is not None:
			assert "```python:" not in web_research_step.output_preview, (
				f"[{caso_id}] web_research devolveu um bloco ```python:arquivo.py``` -- "
				f"regressao dos bugs 4/5 (guardrail de prompt + guard deterministico). "
				f"Preview: {web_research_step.output_preview[:300]!r}"
			)

		# Sinal de saude geral (nao um requisito de sucesso): reporta no log
		# do teste quantos steps passaram, pra visibilidade humana sem
		# travar o teste numa expectativa de 100% que ainda nao e realista.
		aprovados = sum(1 for s in report.steps if s.approved)
		print(
			f"\n[{caso_id}] {aprovados}/{len(report.steps)} steps aprovados, "
			f"success={report.success}, total_tokens={report.total_tokens}"
		)
