import os
import re

import pytest

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

_RULE_ID_RE = re.compile(r"\b(?:NVDA|WX-A11Y|ARCH|NVDA-UX)-\d+\b")

_PROMPT = (
	"Addon NVDA que integra com a API multimodal do Google Gemini: permite "
	"enviar imagens, audios e videos para analise via IA, com painel de "
	"configuracoes para a chave de API e opcoes de modelo, e leitura em voz "
	"das respostas via NVDA."
)


@pytest.fixture(scope="module")
def design_review_result():
	"""1 chamada real (3 sub-chamadas internas: Challenger/Guardian/Advocate),
	compartilhada pelos 2 testes abaixo -- evita pagar a chamada 2x."""
	from nvdastudio.sub_agents.design_review_agent import run

	result = run(_PROMPT, "gpt-oss:20b", {})
	try:
		print(f"\n--- design_review resultado ({len(result)} chars) ---\n{result}\n")
	except UnicodeEncodeError:
		# console Windows (cp1252) as vezes nao encoda caracteres unicode
		# raros do output do modelo (ex: hifen nao-quebravel ‑) -- nao
		# deve derrubar o fixture, so a impressao no terminal.
		print(result.encode("ascii", errors="replace").decode("ascii"))
	return result


@skip_unless_ollama
class TestDesignReviewDedupeModeloFraco:
	def test_guardian_sem_rule_id_repetido_com_modelo_fraco(self, design_review_result):
		counts: dict[str, int] = {}
		for rid in _RULE_ID_RE.findall(design_review_result):
			counts[rid] = counts.get(rid, 0) + 1
		dupes = {rid: n for rid, n in counts.items() if n > 1}
		assert not dupes, (
			f"Regressao do bug real (test_e36): rule IDs repetidos no resultado "
			f"final mesmo com dedupe mecanico (design_review_agent.py 2.12.0): "
			f"{dupes}"
		)

	def test_advocate_sem_rule_ids_com_modelo_fraco(self, design_review_result):
		assert "User Advocate" in design_review_result, (
			"Estrutura da sintese mudou -- secao 'User Advocate' nao encontrada."
		)
		advocate_section = design_review_result.split("User Advocate")[-1]
		ids_no_advocate = _RULE_ID_RE.findall(advocate_section)
		assert not ids_no_advocate, (
			f"Regressao do bug real (test_e36): Advocate citou rule ID(s) mesmo "
			f"com o strip mecanico (design_review_agent.py 2.12.0): {ids_no_advocate}"
		)
