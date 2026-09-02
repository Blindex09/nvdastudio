"""Orquestracao adaptativa: o plano tem teto, medido em 415 relatorios.

Entre as rodadas que chegaram a gerar codigo aprovado (excluindo abortos
precoces -- 123 dos 132 casos de 1-5 steps eram execucao truncada disfarcada
de plano curto, o que quase me fez concluir o oposto):

    6-8  steps: 110/117 entregaram   94%
    9-11 steps:   3/11               27%
   12-14 steps:   3/9                33%

O penhasco e em 9. As duas rodadas complexas que falharam em 2026-09-02 tinham
12 e 14 steps.

Ate aqui o projeto so tinha pressao numa direcao: oversized_code_generation_
steps() DECOMPOE o plano e nada o encurtava.
"""
from nvdastudio.core.planner import (
    ExecutionStep, _aplicar_teto_de_steps, _TETO_DE_STEPS, _PRIORIDADE_DE_PODA,
    STEP_CODE_GENERATION, STEP_ASSEMBLY, STEP_DOCUMENTATION,
    STEP_MANIFEST, STEP_ENGINEERING_REVIEW, STEP_DESIGN_REVIEW,
    STEP_ACCESSIBILITY_AUDIT, STEP_WEB_RESEARCH,
)


def _step(sid, stype, deps=()):
    return ExecutionStep(
        step_id=sid, step_type=stype, description="d", model_id="m",
        depends_on=list(deps), context_from_steps=list(deps),
    )


def _plano(*tipos):
    return [_step(f"s{i}", t) for i, t in enumerate(tipos)]


class TestTetoNaoMexeNoQueJaCabe:
    def test_plano_pequeno_intacto(self):
        p = _plano(STEP_CODE_GENERATION, STEP_ASSEMBLY)
        assert _aplicar_teto_de_steps(p) == p

    def test_plano_exatamente_no_teto_intacto(self):
        p = _plano(*([STEP_CODE_GENERATION] * (_TETO_DE_STEPS - 1)), STEP_ASSEMBLY)
        assert len(_aplicar_teto_de_steps(p)) == _TETO_DE_STEPS


class TestPodaPorValorMedido:
    def test_poda_o_consultivo_de_conversao_zero_primeiro(self):
        p = _plano(
            *([STEP_CODE_GENERATION] * 7),
            STEP_ENGINEERING_REVIEW, STEP_ACCESSIBILITY_AUDIT, STEP_ASSEMBLY,
        )
        tipos = [s.step_type for s in _aplicar_teto_de_steps(p)]
        assert STEP_ENGINEERING_REVIEW not in tipos, "0% de conversao sai primeiro"
        assert tipos.count(STEP_CODE_GENERATION) == 7

    def test_nunca_poda_quem_produz_arquivo(self):
        """Encurtar jogando fora o produto trocaria 'entrega improvavel' por
        'entrega vazia'."""
        p = _plano(
            *([STEP_CODE_GENERATION] * 9),
            STEP_MANIFEST, STEP_DOCUMENTATION, STEP_ASSEMBLY,
        )
        r = _aplicar_teto_de_steps(p)
        tipos = [s.step_type for s in r]
        assert tipos.count(STEP_CODE_GENERATION) == 9
        assert STEP_ASSEMBLY in tipos and STEP_DOCUMENTATION in tipos
        assert len(r) > _TETO_DE_STEPS, "aceita exceder em vez de mutilar a entrega"

    def test_para_de_podar_ao_atingir_o_teto(self):
        """Nao poda alem do necessario -- o consultivo tem valor quando cabe."""
        p = _plano(
            *([STEP_CODE_GENERATION] * 6),
            STEP_ENGINEERING_REVIEW, STEP_DESIGN_REVIEW, STEP_WEB_RESEARCH,
            STEP_ASSEMBLY,
        )
        r = _aplicar_teto_de_steps(p)
        assert len(r) == _TETO_DE_STEPS
        tipos = [s.step_type for s in r]
        assert STEP_WEB_RESEARCH in tipos, "o terceiro da fila nao devia ser podado"

    def test_ordem_da_fila_segue_a_conversao_medida(self):
        assert _PRIORIDADE_DE_PODA[0] == STEP_ENGINEERING_REVIEW  # 0%
        assert _PRIORIDADE_DE_PODA[1] == STEP_DESIGN_REVIEW       # 0%
        assert _PRIORIDADE_DE_PODA.index(STEP_WEB_RESEARCH) < \
            _PRIORIDADE_DE_PODA.index(STEP_ACCESSIBILITY_AUDIT)


class TestDependenciasFicamCoerentes:
    def test_limpa_referencia_a_step_podado(self):
        """Sem isso o orchestrator esperaria por um step que nunca vem --
        exatamente o travamento que a rodada de 13:46 sofreu por outra causa."""
        p = _plano(*([STEP_CODE_GENERATION] * 7))
        p.append(_step("er", STEP_ENGINEERING_REVIEW))
        p.append(_step("asm", STEP_ASSEMBLY, ["s0", "er"]))
        r = _aplicar_teto_de_steps(p)
        asm = [s for s in r if s.step_type == STEP_ASSEMBLY][0]
        assert "er" not in asm.depends_on
        assert "er" not in asm.context_from_steps
        assert "s0" in asm.depends_on, "dependencia valida nao pode ser perdida"

    def test_nenhuma_dependencia_orfa_sobra(self):
        p = _plano(*([STEP_CODE_GENERATION] * 6))
        p.append(_step("er", STEP_ENGINEERING_REVIEW))
        p.append(_step("dr", STEP_DESIGN_REVIEW))
        p.append(_step("wr", STEP_WEB_RESEARCH))
        p.append(_step("asm", STEP_ASSEMBLY, ["er", "dr", "wr", "s0"]))
        r = _aplicar_teto_de_steps(p)
        ids = {s.step_id for s in r}
        for s in r:
            assert not (set(s.depends_on) - ids), f"{s.step_id} depende de step podado"


class TestDecisaoEDeterministica:
    def test_poda_e_reprodutivel(self):
        """Regra 7: roteamento e deterministico. Duas chamadas iguais, mesmo
        resultado -- sem consultar LLM."""
        def novo():
            return _plano(
                *([STEP_CODE_GENERATION] * 7),
                STEP_ENGINEERING_REVIEW, STEP_DESIGN_REVIEW, STEP_ASSEMBLY,
            )
        a = [s.step_id for s in _aplicar_teto_de_steps(novo())]
        b = [s.step_id for s in _aplicar_teto_de_steps(novo())]
        assert a == b

    def test_teto_bate_com_a_faixa_medida(self):
        """94% de entrega em 6-8 steps; 27-33% acima disso."""
        assert _TETO_DE_STEPS == 8
