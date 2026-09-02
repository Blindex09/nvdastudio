"""Regressao: o Critic reprovava o que o projeto conserta sozinho, e inventava API.

Dois defeitos medidos na rodada AssistenteEscrita de 2026-09-02, ambos do mesmo
padrao -- a peca certa existe e nao esta onde decide:

1. cg3 gastou 3 tentativas e caiu para score 78 com um unico achado:
   "NVDA-003: usa _('...') sem addonHandler.initTranslation()". O projeto TEM
   garantir_init_translation() deterministica desde a 4.17.0 -- mas ela so
   rodava no addon_builder, na extracao dos blocos, DEPOIS do julgamento.

2. s5 foi reprovado 3x (324.380 tokens) porque o Critic alegou que
   "api.copyToClip nao aceita o parametro keyword notify=False na API publica
   do NVDA; a chamada levantara TypeError". A fonte do NVDA que o proprio
   projeto mantem em cache diz o contrario:

       nvda_docs_cache/nvda/source/api.py:399
       def copyToClip(text: str, notify: Optional[bool] = False) -> bool

   O codigo estava certo. O Critic inventou a restricao, com a verdade em disco
   no mesmo repositorio.
"""
import inspect
import pathlib
import re

from nvdastudio.ai import critic as critic_mod
from nvdastudio.core import orchestrator as orch_mod
from nvdastudio.builder.addon_builder import garantir_init_translation


class TestCorrecaoMecanicaAntesDoCritic:
    def test_orchestrator_aplica_init_translation_antes_de_julgar(self):
        fonte = inspect.getsource(orch_mod)
        i_fix = fonte.index("garantir_init_translation(codigo)")
        i_critic = fonte.index("crit = self._critic.evaluate_two_stage", i_fix)
        assert i_fix < i_critic, (
            "a correcao mecanica tem que rodar ANTES do julgamento -- senao o "
            "Critic reprova por um defeito que o projeto conserta depois"
        )

    def test_roda_junto_do_lint_autofix(self):
        """Mesmo racional, mesmo lugar: correcao mecanica nao se paga a preco
        de modelo."""
        fonte = inspect.getsource(orch_mod)
        i_init = fonte.index("garantir_init_translation(codigo)")
        i_lint = fonte.index("lint_autofix(", i_init)
        assert i_lint - i_init < 600, "os dois corretores mecanicos ficaram distantes"

    def test_a_funcao_resolve_o_caso_medido(self):
        """Atributo de CLASSE com gettext -- o caso exato do cg3."""
        codigo = (
            "import addonHandler\n"
            "import wx\n\n\n"
            "class Painel(wx.Panel):\n"
            "\ttitle = _('Assistente de Escrita')\n"
        )
        corrigido = garantir_init_translation(codigo)
        assert "addonHandler.initTranslation()" in corrigido

    def test_nao_mexe_em_modulo_que_nao_usa_gettext(self):
        codigo = "import os\n\n\ndef f():\n\treturn os.sep\n"
        assert garantir_init_translation(codigo) == codigo


class TestAncoraFactualNoCritic:
    def _prompt(self) -> str:
        return pathlib.Path(critic_mod.__file__).read_text(encoding="utf-8")

    def test_tem_secao_de_assinaturas_reais(self):
        assert "ASSINATURAS REAIS DO NVDA" in self._prompt()

    def test_copytoclip_esta_ancorado(self):
        p = self._prompt()
        assert "copyToClip" in p
        assert "notify" in p
        assert "nvda_docs_cache" in p, "a ancora precisa citar a fonte verificavel"

    def test_manda_nao_reprovar_por_duvida_de_assinatura(self):
        """Um falso positivo aqui custa 3 tentativas de geracao inteiras."""
        # normaliza espaco: a frase quebra de linha no arquivo
        p = " ".join(self._prompt().split())
        assert "nao levante o achado" in p

    def test_versao_subiu_porque_o_prompt_mudou(self):
        """O log carimba a versao (critic_spec_v3.22.0). Mudar o texto sem
        subir a versao torna relatorios antigos indistinguiveis dos novos."""
        assert critic_mod.MODULE_VERSION == "3.23.0"


class TestAncoraBateComAFonteReal:
    def test_assinatura_ancorada_confere_com_o_cache_do_projeto(self):
        """Fitness function: se o NVDA mudar a assinatura, a ancora vira
        mentira -- e mentira ancorada e pior que ausencia de ancora."""
        fonte = pathlib.Path(critic_mod.__file__).parent.parent / (
            "nvda_docs_cache/nvda/source/api.py"
        )
        if not fonte.is_file():
            import pytest
            pytest.skip("nvda_docs_cache/api.py ausente neste checkout")
        texto = fonte.read_text(encoding="utf-8", errors="replace")
        assert re.search(r"def copyToClip\(\s*text[^)]*notify", texto), (
            "a assinatura real de copyToClip mudou -- atualize a ancora em "
            "critic.py antes que ela reprove codigo correto pelo motivo oposto"
        )
