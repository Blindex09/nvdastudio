import inspect

_TOTAL_TOKENS_CALC = "total_tokens=sum(r.tokens_used for r in step_results)"


class TestTotalTokensNoCaminhoDeFalhaPorArtefatoAusente:
    def test_run_conversational_pipeline_inclui_total_tokens_na_falha(self):
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator.Orchestrator._run_conversational_pipeline)
        assert _TOTAL_TOKENS_CALC in src, (
            "_run_conversational_pipeline deveria somar total_tokens dos "
            "step_results tambem no caminho de falha por artefato ausente "
            "-- caso contrario o custo real gasto some do relatorio."
        )

    def test_run_pipeline_inclui_total_tokens_na_falha(self):
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator.Orchestrator._run_pipeline)
        assert _TOTAL_TOKENS_CALC in src, (
            "_run_pipeline deveria somar total_tokens dos step_results "
            "tambem no caminho de falha por artefato ausente -- caso "
            "contrario o custo real gasto some do relatorio."
        )

    def test_ambos_os_metodos_tem_a_mesma_conta_no_caminho_de_sucesso_e_falha(self):
        """Confirma que o calculo aparece 2x em cada metodo (sucesso + falha
        por artefato ausente) -- nao so 1x (o que indicaria que so um dos
        2 caminhos foi corrigido)."""
        from nvdastudio.core import orchestrator
        for method in (
            orchestrator.Orchestrator._run_conversational_pipeline,
            orchestrator.Orchestrator._run_pipeline,
        ):
            src = inspect.getsource(method)
            assert src.count(_TOTAL_TOKENS_CALC) == 2, (
                f"{method.__name__} deveria ter total_tokens calculado nos "
                f"2 desfechos (sucesso e falha por artefato ausente), "
                f"encontrado {src.count(_TOTAL_TOKENS_CALC)}x"
            )
