"""
Addon complexo MINIMO: integracao externa de verdade, plano que cabe.

Motivo (2026-09-02): oito rodadas do golden set complexo nao entregaram um
addon. Aqueles pedidos tem 4 funcionalidades + configuracoes + testes, e viram
planos de 25 a 27 steps -- com 47% de aprovacao por step de codigo, a chance de
TODOS passarem e de 0,25%. O pipeline morre por orcamento antes do assembly, que
nunca chegou a rodar em nenhuma das oito.

Este caso mantem o que torna o pedido COMPLEXO de verdade -- API externa, chave
de API, tela de configuracoes, multiplos arquivos, tratamento de erro falado --
e corta o que so aumenta o comprimento da cadeia. Serve para responder a
pergunta que o golden set nao consegue responder: a cadeia inteira funciona, do
plano ao .nvda-addon?

Se este entregar e o grande nao, o problema esta no COMPRIMENTO do plano, nao na
capacidade. Se este tambem nao entregar, o problema esta antes, e aparece aqui
por um quinto do custo e do tempo.
"""

from .test_criacao_completa import _E2E_OUTPUT_DIR, _rodar_pipeline_e2e
from .test_e36_golden_eval_set_complexo import (
    _responde_clarificacao_com_defaults_sensatos,
    skip_unless_ollama,
)

_PEDIDO_MINIMO = (
    "Crie um addon NVDA chamado ResumoGemini que usa a API do Google Gemini "
    "para resumir o texto selecionado. Funcionalidades: (1) um atalho "
    "NVDA+shift+r que pega o texto selecionado e fala o resumo; (2) uma tela "
    "de configuracoes com a chave da API do Gemini. Trate erro de rede e de "
    "chave invalida com mensagem clara falada pelo NVDA."
)


@skip_unless_ollama
class TestComplexoMinimoEntrega:
    def test_entrega_addon_carregavel(self):
        report = _rodar_pipeline_e2e(
            "ResumoGemini", _PEDIDO_MINIMO, _E2E_OUTPUT_DIR,
            on_clarify=_responde_clarificacao_com_defaults_sensatos,
        )

        nomes = [n.replace("\\", "/") for n in (report.zip_names or [])]
        entrada = [
            n for n in nomes
            if n.startswith("globalPlugins/")
            and n.endswith("/__init__.py")
            and n.count("/") == 2
        ]

        assert report.success, (
            f"pipeline nao concluiu: {report.error[:400]}"
        )
        assert entrada, (
            "addon sem ponto de entrada raiz -- o NVDA nao carregaria. "
            f"Arquivos: {nomes}"
        )
        assert any(n.endswith("manifest.ini") for n in nomes), (
            f"addon sem manifest.ini. Arquivos: {nomes}"
        )
