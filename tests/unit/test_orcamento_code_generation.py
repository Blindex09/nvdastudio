"""Regressao: o orcamento subestimava o step mais caro do pipeline.

Medido em 404 execucoes reais de code_generation nos relatorios E2E:

    mediana 112.952 | media 157.105 | p75 259.403 | p90 402.133

A tabela dizia 35.000 x 2,5 tentativas = 87.500 por step -- 1,8x abaixo da
media e 3x abaixo do p75. Como addon complexo tem 4 a 6 destes steps, o teto
ficava sistematicamente baixo justamente para os addons que mais precisam.

Medido na rodada de 2026-09-02 20:38: teto de 704.550 com TRES code_generation
aprovados (252.185 e 261.138 entre eles). Morreu por orcamento com o addon
quase pronto -- a quarta vez no dia que isso acontece por estimativa errada.
"""
from nvdastudio.utils.iteration_budget import (
    _CUSTO_MEDIDO_POR_STEP, _TENTATIVAS_ESPERADAS,
)

_MEDIA_MEDIDA = 157_105
_MEDIANA_MEDIDA = 112_952


def _estimativa(tipo: str) -> float:
    return _CUSTO_MEDIDO_POR_STEP[tipo] * _TENTATIVAS_ESPERADAS.get(tipo, 1.0)


class TestCodeGenerationEstimadoPeloMedido:
    def test_nao_subestima_a_media_medida(self):
        """Subestimar mata entrega pronta -- medido tres vezes em 2026-09-02."""
        assert _estimativa("code_generation") >= _MEDIANA_MEDIDA

    def test_fica_proximo_da_media_e_nao_do_p90(self):
        """Superestimar demais transforma o disjuntor em decoracao."""
        est = _estimativa("code_generation")
        assert _MEDIANA_MEDIDA <= est <= _MEDIA_MEDIDA * 1.35, est

    def test_e_o_step_mais_caro_da_tabela(self):
        """Ele e o unico que escreve o addon; se outro tipo passa-lo, e sinal
        de que a tabela desandou.

        Este teste ja pegou um erro real: na 1.7.0 eu havia posto
        accessibility_audit em 88.000 x 2 = 176.000, acima do code_generation,
        com base em UMA rodada. Com 125 execucoes a media e 45.734.
        """
        est = _estimativa("code_generation")
        for tipo in _CUSTO_MEDIDO_POR_STEP:
            if tipo == "code_generation":
                continue
            assert _estimativa(tipo) <= est, f"{tipo} estimado acima de code_generation"

    def test_tabela_inteira_recalibrada_pelo_medido(self):
        """Media medida por tipo, dos relatorios E2E. Tolerancia de 15% para
        arredondamento; fora disso alguem chutou de novo."""
        medias = {
            "design_review": 136_685, "agent_template": 64_272,
            "test_generation": 46_621, "assembly": 42_129,
            "manifest_builder": 35_568, "agent_runner": 78_977,
            "documentation": 31_451, "accessibility_audit": 45_734,
            "web_research": 7_895,
        }
        for tipo, medido in medias.items():
            est = _estimativa(tipo)
            assert abs(est - medido) <= medido * 0.15, (
                f"{tipo}: estimado {est:,.0f} contra {medido:,} medidos"
            )


class TestTetoDeStepsNaoVoltou:
    def test_planner_nao_tem_teto_de_steps(self):
        """A 2.44.0 introduziu _TETO_DE_STEPS=8 e a 2.45.0 removeu: a medicao
        que o justificava estava CONFUNDIDA. Planos de 6-8 steps tinham media
        de 1,5 code_generation contra 6,4 dos planos de 12+ -- eram addons
        SIMPLES, e o numero de steps era termometro da dificuldade, nao causa
        da falha. Com o teto ativo, o custo por code_generation subiu de
        ~100-135 mil para 252.185, e o teto do orcamento (que deriva do plano)
        encolheu junto: mesmo trabalho, caixa menor.
        """
        import nvdastudio.core.planner as mod

        assert not hasattr(mod, "_TETO_DE_STEPS")
        assert not hasattr(mod, "_aplicar_teto_de_steps")

    def test_a_licao_ficou_registrada_no_codigo(self):
        """Remover sem explicar convida a reintroducao."""
        import inspect
        import nvdastudio.core.planner as mod

        fonte = inspect.getsource(mod)
        assert "NAO REINTRODUZIR" in fonte
        assert "CONFUNDIDA" in fonte
