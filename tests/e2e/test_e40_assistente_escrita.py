"""Segundo addon complexo: confirma que a entrega de 2026-09-02 nao foi sorte.

O ResumoGemini (test_e39) foi o primeiro addon complexo entregue pelo pipeline,
depois de seis defeitos corrigidos no mesmo dia. Uma entrega nao prova um
pipeline -- prova que aquele pedido passou. Este caso existe para responder se
a capacidade e reproduzivel.

Deliberadamente DIFERENTE do e39, nao uma copia com outro nome:
  - dois comandos (@script) em vez de um -- exercita conflito de atalho e
    registro de mais de um gesto;
  - painel de configuracoes com DOIS campos (chave + modelo) em vez de um --
    exercita configSpec com mais de uma entrada;
  - resultado vai para a area de transferencia alem de ser falado -- exercita
    api.copyToClip, um caminho que o e39 nunca tocou.

E deliberadamente do MESMO TAMANHO: a licenca das oito rodadas do golden set e
que plano comprido mata (25-27 steps, 0,25% de chance de todos passarem).
Provar reproducibilidade exige variar a NATUREZA do pedido, nao o comprimento.

O addon integra o GPT (OpenAI); o pipeline que o gera continua no Ollama.
"""

import pytest

from .test_criacao_completa import _E2E_OUTPUT_DIR, _rodar_pipeline_e2e
from .test_e36_golden_eval_set_complexo import (
    _responde_clarificacao_com_defaults_sensatos,
    skip_unless_ollama,
)

_PEDIDO = (
    "Crie um addon NVDA chamado AssistenteEscrita que usa a API do ChatGPT "
    "da OpenAI para ajudar a revisar textos. Funcionalidades: (1) um atalho "
    "NVDA+shift+g que pega o texto selecionado, corrige a gramatica e a "
    "ortografia, fala o resultado e copia para a area de transferencia; "
    "(2) um atalho NVDA+shift+j que pega o texto selecionado e fala uma "
    "versao mais simples e clara dele; (3) uma tela de configuracoes com a "
    "chave da API da OpenAI e a escolha do modelo. Trate erro de rede, de "
    "chave invalida e de cota excedida com mensagem clara falada pelo NVDA."
)


@skip_unless_ollama
class TestAssistenteEscritaEntrega:
    """Uma unica rodada do pipeline serve as duas verificacoes.

    Fixture de CLASSE de proposito: cada rodada custa ~1h e chamada de API
    real. Repetir o pipeline por metodo dobraria custo e tempo sem responder
    nenhuma pergunta a mais.
    """

    @pytest.fixture(scope="class")
    def report(self):
        return _rodar_pipeline_e2e(
            "AssistenteEscrita", _PEDIDO, _E2E_OUTPUT_DIR,
            on_clarify=_responde_clarificacao_com_defaults_sensatos,
        )

    def test_entrega_addon_carregavel(self, report):
        nomes = [n.replace("\\", "/") for n in (report.zip_names or [])]
        entrada = [
            n for n in nomes
            if n.startswith("globalPlugins/")
            and n.endswith("/__init__.py")
            and n.count("/") == 2
        ]

        assert report.success, f"pipeline nao concluiu: {report.error[:400]}"
        assert entrada, (
            "addon sem ponto de entrada raiz -- o NVDA nao carregaria. "
            f"Arquivos: {nomes}"
        )
        assert any(n.endswith("manifest.ini") for n in nomes), (
            f"addon sem manifest.ini. Arquivos: {nomes}"
        )

    def test_entrega_o_que_torna_o_pedido_complexo(self, report):
        """Um .nvda-addon valido com so o __init__.py atenderia o teste acima
        e nao seria o addon pedido. Aqui verifica que as partes que fazem o
        pedido ser COMPLEXO chegaram no pacote."""
        nomes = [n.replace("\\", "/") for n in (report.zip_names or [])]
        pacote = [n for n in nomes if n.startswith("globalPlugins/") and n.endswith(".py")]

        assert len(pacote) >= 3, (
            "addon complexo com menos de 3 modulos Python -- o pedido tem "
            f"servico externo, painel e ponto de entrada. Arquivos: {pacote}"
        )
        assert any(n.endswith(".html") for n in nomes), (
            f"addon sem guia do usuario. Arquivos: {nomes}"
        )
