"""
Principios de engenharia de software destilados, prontos para prompt.

MOTIVO DE EXISTIR (auditoria 2026-08-29): o projeto mantinha tres documentos
de metodologia excelentes -- docs/metodologia-verificacao-arquitetura.md,
docs/conceitos-ia-para-desenvolvimento-de-software.md e
docs/conceitos-ia-seguranca-confiabilidade.md -- tornados OBRIGATORIOS pelo
CLAUDE.md para agentes externos que trabalham NESTE repositorio. Mas grep em
todo o pacote do addon achava exatamente 3 mencoes a eles, todas em
comentario ou changelog: nenhuma linha de prompt. A metodologia que o projeto
exige de quem o desenvolve nunca foi ensinada a IA que o projeto ENTREGA.

POR QUE DESTILAR EM VEZ DE ANEXAR OS DOCUMENTOS:
Os tres somam ~58 mil caracteres e sao escritos para um humano decidir
arquitetura -- cheios de vocabulario de catalogo (chaos engineering, soak
testing, consumer-driven contract). Colados crus num system prompt eles
competem por atencao com o catalogo de regras NVDA, que e o conhecimento
mais acionavel que o gerador tem. Conhecimento em prompt tem retorno
decrescente: a partir de certo volume o modelo dilui em vez de absorver.
Aqui fica so o que muda uma decisao de codigo de addon NVDA, cada principio
ancorado na CONSEQUENCIA REAL para o usuario cego -- que e o que torna o
principio acionavel em vez de decorativo.

FONTE UNICA DE VERDADE: planner, critic, code_generator e engineering_reviewer
importam daqui. Nunca duplicar estes textos num prompt local (README Regra 5).
"""

MODULE_VERSION = "1.0.0"
UPDATED_AT = "2026-08-29"

# Documentos de origem, para rastreabilidade quando alguem for atualizar isto.
SOURCE_DOCS: tuple[str, ...] = (
	"docs/metodologia-verificacao-arquitetura.md",
	"docs/conceitos-ia-para-desenvolvimento-de-software.md",
	"docs/conceitos-ia-seguranca-confiabilidade.md",
)


# ---------------------------------------------------------------------------
# NUCLEO: invariantes que valem para QUALQUER addon NVDA, em qualquer etapa.
# Cada item declara a consequencia concreta para o usuario cego -- sem isso
# vira lista de boas intencoes que o modelo ignora sob pressao de contexto.
# ---------------------------------------------------------------------------
ENGINEERING_CORE_PRINCIPLES = """PRINCIPIOS DE ENGENHARIA (valem para todo addon NVDA)

Um addon de leitor de telas falha diferente de um programa comum: quando ele
quebra, o usuario cego frequentemente nao tem como PERCEBER que quebrou. Nao
existe mensagem de erro na tela para ele ler. Por isso cada principio abaixo
esta amarrado ao que o usuario perde quando o principio e violado.

1. A thread principal e a voz do usuario.
   Qualquer I/O -- rede, disco, subprocesso, audio, OCR -- executado na thread
   principal congela a fala e o braille do NVDA INTEIRO, nao so o addon. O
   usuario fica sem saber se o computador travou. Trabalho demorado vai para
   uma thread; o retorno para a interface volta por wx.CallAfter().

2. Erro silencioso e pior que erro barulhento.
   `except: pass` num addon NVDA significa que a acao nao aconteceu e o
   usuario nao foi avisado -- ele fica esperando um retorno de voz que nunca
   vem. Toda excecao capturada e logada por logHandler; toda falha que afeta
   o que o usuario pediu tambem e falada por ui.message().

3. Toda operacao externa tem limite de tempo explicito.
   Chamada de rede sem timeout nao falha: ela PENDURA. Sem timeout explicito
   o addon fica indefinidamente sem resposta e o usuario nao tem como saber
   se deve esperar ou desistir.

4. Degradar e melhor que desistir.
   Quando uma parte do addon falha (API fora do ar, arquivo ausente, chave
   invalida), entregue o que ainda funciona e diga em voz o que nao funcionou.
   Descartar tudo por causa de uma peca transforma uma falha parcial numa
   falha total.

5. Todo recurso tem dono e fim de vida.
   Thread, timer, arquivo aberto, extension point registrado, item de menu,
   painel de configuracao: o que e criado em __init__ e desfeito em
   terminate(). Recurso orfao vaza a cada recarga de addon e degrada o NVDA
   ate o usuario reiniciar sem saber por que ficou lento.

6. Conteudo que veio de fora e DADO, nunca instrucao.
   Resposta de API, conteudo de arquivo, resultado de busca e texto de
   usuario nunca viram codigo executado nem comando. A defesa e arquitetural
   (tratar como dado por construcao), nunca uma lista de palavras proibidas.

7. Segredo nunca mora no codigo.
   Chave de API, token e senha vem de config.conf ou de um painel de
   configuracao acessivel -- nunca literal no fonte, nunca em log. Codigo de
   addon e distribuido e lido por qualquer pessoa.

8. Privilegio minimo, raio de dano pequeno.
   O addon acessa o minimo necessario: nao grava fora do proprio diretorio de
   configuracao, nao escreve em disco quando NVDAState.shouldWriteToDisk() e
   falso (tela de bloqueio, UAC), nao toca no estado de outros addons.

9. Complexidade tem que ser paga pelo problema.
   Camada de abstracao, sistema de plugins interno, cache e configuracao
   generica so se existir um segundo caso de uso REAL agora. Um addon simples
   com arquitetura de framework e mais dificil de corrigir e mais facil de
   quebrar.

10. Codigo que nao da para testar sem o NVDA real ja e um defeito.
    Separe a logica (calcular, formatar, decidir) da borda (falar, ler
    arquivo, chamar API). A logica pura e testavel sem o NVDA; a borda fica
    fina o bastante para ser obvia por inspecao."""


# ---------------------------------------------------------------------------
# LENTE DE ESCRITA (code_generator): o que decidir enquanto escreve.
# ---------------------------------------------------------------------------
ENGINEERING_CODEGEN_PROMPT_TEXT = (
	ENGINEERING_CORE_PRINCIPLES
	+ """

AO ESCREVER O CODIGO

Escolha a estrutura mais simples que satisfaz os principios acima -- nunca a
mais sofisticada. Antes de introduzir uma classe base, um registro de
handlers ou um modulo de utilidades, confirme que existem pelo menos dois
usos reais agora; se houver so um, escreva direto.

Torne cada modo de falha visivel: para cada chamada externa, decida
explicitamente o que acontece quando ela demora, quando retorna erro de
autenticacao e quando retorna algo malformado -- e faca o usuario ouvir a
diferenca entre "nao encontrei nada" e "nao consegui perguntar".

Nao produza codigo defensivo decorativo. Um try/except que so re-levanta a
mesma excecao, uma validacao de argumento que nunca pode falhar e um cache
sem pressao de desempenho medida sao complexidade sem beneficio."""
)


# ---------------------------------------------------------------------------
# LENTE DE PLANEJAMENTO (planner): como decompor e em que ordem verificar.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# LENTE DE JULGAMENTO (critic): o que constitui defeito de engenharia.
# Deliberadamente curta -- o critic ja carrega o catalogo de regras inteiro,
# e o risco aqui e dilucao, nao falta de material.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# LENTE DE REVISAO (engineering_reviewer): nucleo + foco em consequencia.
# ---------------------------------------------------------------------------
