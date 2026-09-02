"""Regressao: o pipeline cobrava do assembly o que codigo deterministico faz.

Medido em 2026-09-02, entrega ResumoGemini (primeiro addon complexo entregue):
o Critic reprovou o step de assembly por "Nao foi produzido o pacote instalavel
(.nvda-addon) nem script de build" no MESMO SEGUNDO em que o addon_builder
registrava "[OK] Addon empacotado". Tres tentativas do step, todas cobrando
algo que um step de IA nao tem como entregar.

A causa estava na COSTURA, nos dois lados:
 - planner: o prompt dizia que assembly "monta e EMPACOTA", entao o modelo
   escrevia "produzir o pacote instalavel" no objetivo do step;
 - critic: julga o output contra o objetivo do step, entao cobrava.
Corrigir so um lado deixaria o outro reintroduzindo o problema.
"""
import re
from nvdastudio.core import planner as planner_mod
from nvdastudio.ai import critic as critic_mod


def _prompt_planner() -> str:
	fonte = __import__("pathlib").Path(planner_mod.__file__).read_text(encoding="utf-8")
	return fonte


def _prompt_critic() -> str:
	return __import__("pathlib").Path(critic_mod.__file__).read_text(encoding="utf-8")


class TestPlannerNaoPedeEmpacotamento:
	def test_nao_diz_que_assembly_empacota(self):
		"""A frase 'monta e empacota' era o que o modelo copiava pro objetivo."""
		assert "monta e empacota todos os artefatos" not in _prompt_planner()

	def test_proibe_explicitamente_pedir_nvda_addon(self):
		p = _prompt_planner()
		assert "NAO peca ao assembly" in p
		assert ".nvda-addon" in p

	def test_proibe_pedir_vendoring_de_pip(self):
		assert "vendorizar" in _prompt_planner()


class TestCriticNaoCobraEmpacotamento:
	def test_tem_limites_explicitos_do_assembly(self):
		assert "LIMITES DO ASSEMBLY" in _prompt_critic()

	def test_manda_ignorar_o_objetivo_quando_pede_o_impossivel(self):
		"""O ponto sutil: o Critic julga contra o OBJETIVO do step. Se o
		objetivo pedir o impossivel, o limite tem que vencer o objetivo."""
		assert "mesmo que o objetivo do step peca" in _prompt_critic()

	def test_nao_culpa_mais_o_assembly_pelo_bundling(self):
		"""A regra antiga redirecionava a culpa pro 'builder/assembly' -- que
		inclui um step de IA que tambem nao empacota."""
		assert "pertence ao builder/assembly" not in _prompt_critic()
		assert "NAO e trabalho de nenhum step de IA" in _prompt_critic()


class TestVersoesAcompanham:
	def test_prompts_mudaram_entao_versoes_subiram(self):
		"""O log carimba a versao no prompt (critic_spec_v3.21.0). Mudar o
		texto sem subir a versao torna os relatorios antigos indistinguiveis
		dos novos."""
		# Faixa, nao valor exato: a intencao e "a versao acompanhou a mudanca
		# de prompt", e travar o numero exato quebra a cada mudanca legitima
		# seguinte (aconteceu na 3.23.0, ancora de assinaturas reais).
		assert re.match(r"3\.(2[2-9]|[3-9]\d)", critic_mod.MODULE_VERSION), critic_mod.MODULE_VERSION
		assert re.match(r"2\.4[3-9]|2\.[5-9]", planner_mod.MODULE_VERSION), planner_mod.MODULE_VERSION
