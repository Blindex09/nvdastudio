import ast
import json
import re
from dataclasses import dataclass
from enum import Enum

from .llm_client import LLMClientError
from .llm_factory import create_llm_client
from ..utils.logger import get_logger, log_llm_call, log_llm_response, log_decision
from ..builder.api_key_validator import api_key_validator
from ..rule_registry import RULE_REGISTRY_PROMPT_TEXT
from ..utils.engineering_principles import ENGINEERING_CRITIC_PROMPT_TEXT
from ..builder.controller_client_context import is_controller_client_context, CTRL_CLIENT_CRITIC_ADDENDUM
# Constantes de step_type: fonte unica de verdade (evita acoplamento por string literal)
from ..core.planner import (
	STEP_CODE_GENERATION, STEP_MANIFEST as STEP_MANIFEST_BUILDER, STEP_WEB_RESEARCH,
)

MODULE_VERSION = "3.23.0"
_logger = get_logger("critic")

# 3.19.0: Critic roteado pra OpenCode Go, independente do provider ativo do
# usuario (Ollama continua sendo usado por TODOS os outros sub-agentes --
# code_generation, web_research, etc.). Pedido explicito do Felipe
# (2026-08-17), com dado real medido nesta sessao: o Critic e o componente
# de MAIOR volume de conteudo repetido do pipeline inteiro --
# _CRITIC_SPEC_SYSTEM + _CRITIC_QUALITY_SYSTEM = ~42.400 chars FIXOS
# reenviados em TODA avaliacao (chamado apos CADA tentativa de CADA step,
# tipicamente 20-30x por pipeline). Ollama Cloud nao tem prompt caching de
# API (confirmado via docs oficiais + GitHub issues, 2026-08-17).
#
# 3.20.0: gpt-5.6-luna/grok-4.5 (modelos originais desta forcacao) achados
# FORA DO AR ao vivo em auditoria 2026-08-26 (500/503 na API do OpenCode Go,
# com chave real -- nao e bug local). Trocado pra
# model_registry.py::get_structured_output_model() -- fonte UNICA pra "qual
# modelo do OpenCode Go usar quando preciso de JSON garantido", agora
# compartilhada com todo ponto do projeto que exige response_format
# json_schema (clarifier, planner, agentic_loop, studio_dialog,
# memory_manager -- ver changelog de cada um). kimi-k2.6/glm-5.1
# confirmados ao vivo com prompt caching E schema estrito funcionando de
# verdade (ao contrario do par anterior, que so tinha o caching validado).
def get_critic_model() -> str:
	"""Modelo do Critic -- sempre OpenCode Go, nunca segue o provider ativo
	do usuario. Ver model_registry.py::get_structured_output_model()."""
	from .model_registry import get_structured_output_model
	return get_structured_output_model(0)

def get_critic_fallback_model() -> str:
	"""Fallback do Critic -- proximo da mesma cadeia verificada (modelo
	genuinamente diferente do primario), preservando a escalacao real de
	critic.py 3.15.0 (resposta vazia/cortada escala pro fallback)."""
	from .model_registry import get_structured_output_model
	return get_structured_output_model(1)

# Imports proibidos em addons NVDA: nao existem no ambiente Python do NVDA.
# Regra 5: verificacao deterministica — o LLM nao e confiavel para rejeitar
# esses imports (confirmado por E2E 2026-03-30: win32clipboard passou sem bloqueio).
FORBIDDEN_IMPORTS: frozenset[str] = frozenset({
	"win32clipboard", "win32con", "win32gui", "win32api",
	"win32com", "pywintypes", "win32process", "win32security",
})

class Verdict(Enum):
	APPROVED = "APROVADO"
	NEEDS_FIX = "CORRIGIR"
	REJECTED  = "REJEITAR"

@dataclass
class CriticResult:
	verdict: Verdict
	score: int
	issues: list[str]
	fix_instructions: str
	reasoning: str | None = None
	stage: str = "single"  # "spec" | "quality" | "single" | "two_stage"
	confidence: float = 1.0  # 0.0-1.0: calibrado pela proximidade ao limite de veredicto
	dimension_scores: dict = None  # type: ignore[assignment]  # {completeness, format, nvda_compliance}

	def __post_init__(self) -> None:
		if self.dimension_scores is None:
			self.dimension_scores = {}


# ------------------------------------------------------------------
# Estagio 1: Spec Compliance
# Pergunta: o output corresponde ao que foi pedido no step?
# ------------------------------------------------------------------

_CRITIC_SPEC_SYSTEM = """Voce e o SpecCritic do NVDAStudio — Estagio 1: Conformidade com o Spec.

Avalie SE o output entregou o que foi pedido, nem mais nem menos.
Retorne APENAS JSON valido sem texto fora:
{"verdict": "APROVADO|CORRIGIR|REJEITAR", "score": 0-100, "issues": ["..."], "fix_instructions": "..."}

Criterios objetivos por tipo de step:

code_generation:
  APROVADO se: contem codigo Python, tem classe GlobalPlugin ou AppModule ou driver, tem imports.
  EXCECAO ARCH-010 (decomposicao em subpacotes) — leia o campo "Objetivo deste step"
  no contexto: se ele pede EXPLICITAMENTE o subpacote de UMA feature (ex: "gere o
  subpacote video/", "gere os modulos do dominio audio") e NAO pede o __init__.py raiz
  do addon, NAO exija classe GlobalPlugin/AppModule/driver neste step — exija so codigo
  Python funcional, com imports corretos, que cumpra o que a description pediu. So exija
  a classe quando o objetivo do step for gerar o __init__.py raiz que integra/orquestra
  os subpacotes ja prontos (o step final da decomposicao, tipicamente depende de todos
  os outros code_generation). Julgamento semantico pelo texto do objetivo, nunca por
  keyword fixa de nome de step.
  EXCECAO OBRIGATORIA — artefatos nao-Python quando pedidos na tarefa:
    Se a tarefa original menciona speechDicts/pronuncia/dicionario de fala:
      CORRIGIR se nao houver bloco ```text:speechDicts/*.dic``` com dados reais.
      O arquivo .dic e OBRIGATORIO junto com o Python — nao aprovado sem ele.
  CORRIGIR se: codigo incompleto ou faltam imports basicos.
  REJEITAR se: sem codigo Python algum.

manifest_builder:
  FONTE: addonHandler/__init__.py (NVDA source) — AddonManifest usa ConfigObj SEM secao.
  FORMATO CORRETO: chave=valor direto na raiz. SEM linha [add-on] ou qualquer secao no inicio.
  APROVADO se: tem name, version, minimumNVDAVersion, lastTestedNVDAVersion, summary — tudo como chave=valor sem secao [add-on].
			  E respeita a politica atual do projeto: minimumNVDAVersion >= 2026.1.1
			  e lastTestedNVDAVersion >= 2026.1.1.
  CORRIGIR se: falta algum campo obrigatorio OU tem secao [add-on] (que NVDA rejeita).
			   OU se usa versoes abaixo do baseline oficial 2026.1.1.
  REJEITAR se: output vazio ou sem nenhum campo reconhecivel.
  NOTA: SHA256 (NVDA-014) e campo opcional no desenvolvimento — nao bloquear por ausencia.
  CRITICO url: o campo "url" DEVE ser nao-vazio e comecar com "https://".
              "url = " vazio ou "url = <algo>" sem "https://" sao ERROS — CORRIGIR
              usando placeholder valido como https://github.com/NVDAAddons/<nome>.
  NOTA: author com placeholders como "Seu Nome" sao aceitaveis — nao bloquear por isso.

accessibility_audit:
  APROVADO se: o output identifica pelo menos 1 regra NVDA-001..018 ou WX-A11Y-001..014 com seu ID.
			  OU conclui explicitamente que o codigo auditado nao tem violacoes encontradas.
  CORRIGIR se: menciona problemas mas sem identificar as regras pelos IDs.
  REJEITAR se: output vazio ou sem referencia alguma a boas praticas de acessibilidade NVDA.

test_generation:
  APROVADO se: contem funcoes de teste (def test_ ou class Test), usa pytest ou unittest.
  CORRIGIR se: tem estrutura de teste mas incompleta.
  REJEITAR se: sem funcoes de teste.

web_research:
  APROVADO se: contem informacao factual e relevante sobre NVDA, addons ou o topico pedido.
  Formato livre — markdown permitido. Nao exigir IDs de regras aqui.

agent_template:
  APROVADO se: contem as 8 secoes Community Access obrigatorias.
  CORRIGIR se: faltam secoes.

agent_runner:
  APROVADO se: contem AgentRunner, tem run(), tem reset_session().
  CORRIGIR se: falta reset_session() ou run().

assembly:
  APROVADO se: contem manifest.ini e codigo Python juntos no output.
  CORRIGIR se: falta um dos dois.
  LIMITES DO ASSEMBLY -- nao cobre nada disto, mesmo que o objetivo do step peca:
    * o arquivo .nvda-addon (zip) e produzido por CODIGO DETERMINISTICO depois
      deste step. Um step de IA nao emite binario. Nunca reduza o score por
      "nao produziu o pacote instalavel" nem por falta de buildVars.py/script de build.
    * pacotes pip em lib/ nao sao responsabilidade deste step. O addon gerado
      resolve dependencia externa em tempo de execucao.
  Medido em 2026-09-02: o Critic reprovou o assembly por 'nao foi produzido o
  pacote instalavel (.nvda-addon)' no MESMO SEGUNDO em que o builder registrava
  'Addon empacotado'. Foram 3 tentativas do step, todas cobrando o impossivel.

design_review:
  APROVADO se: contem as tres secoes obrigatorias (Challenger, Guardian, User Advocate)
	com pelo menos um risco ou restricao identificado por secao.
  CORRIGIR se: falta uma das tres secoes ou alguma secao sem conteudo substantivo.
  REJEITAR se: output vazio ou sem nenhuma secao de revisao de design.

documentation:
  APROVADO se: contem estrutura HTML (html, head, body) com ao menos uma secao
	de uso e descricao do addon em pt_BR ou en.
  CORRIGIR se: estrutura HTML presente mas sem conteudo de uso ou descricao.
  REJEITAR se: output vazio ou sem nenhuma estrutura de documentacao HTML.

Score: 90-100=APROVADO, 60-89=CORRIGIR, abaixo 60=REJEITAR
"""

# ------------------------------------------------------------------
# Estagio 2: Code Quality
# Pergunta: o output esta bem escrito, segue boas praticas, e acessivel?
# ------------------------------------------------------------------

_CRITIC_QUALITY_SYSTEM = """Voce e o QualityCritic do NVDAStudio — Estagio 2: Qualidade de Codigo.

REGRA FUNDAMENTAL DE ESCOPO ISOLADO:
Cada step e avaliado EXCLUSIVAMENTE pelo que ele entrega. Nao penalize um step
por ausencia de artefatos de OUTROS steps:
- manifest_builder: avalie apenas o manifest.ini. Nao exija codigo Python aqui.
- code_generation: avalie apenas o codigo Python. Nao exija manifest aqui.
- web_research: avalie apenas a qualidade da pesquisa. E texto informativo.
- Aplique as regras NVDA/WX-A11Y APENAS se o output contiver codigo Python relevante.

O output ja passou pela conformidade com o spec. Avalie agora a QUALIDADE.
Retorne APENAS JSON valido sem texto fora:
{"verdict": "APROVADO|CORRIGIR|REJEITAR", "score": 0-100, "issues": ["..."], "fix_instructions": "..."}

Regras de qualidade para codigo Python (aplique SOMENTE se houver codigo Python no output):

NVDA-001 Critico: Falta nextHandler() em event handler (ex: event_gainFocus).
  ATENCAO: Scripts normais (def script_X) NAO precisam de nextHandler(). So event handlers precisam.
NVDA-002 Critico: Bloqueio da thread principal (sleep, I/O sincrono, requests.get() sem thread).
NVDA-003 Serio: Modulo usa gettext (_(), ngettext(), pgettext() ou npgettext())
  sem inicializar as traducoes com addonHandler.initTranslation().
  No modulo principal do plugin, a inicializacao e esperada quando ha texto traduzivel.
  Modulos auxiliares que nao chamam gettext NAO precisam de initTranslation(); nao os penalize.
NVDA-004 Serio: Falta terminate() para cleanup de recursos persistentes.
NVDA-006 Moderado: Monkey-patching de modulos do core NVDA.
  ERRADO: _original_speak = speech.speak; speech.speak = _patched_speak
  CORRETO: usar extension points ou event handlers.
  EXCECAO CRITICA — NAO e monkey-patching e NAO deve ser penalizado:
    _lib_path = os.path.join(os.path.dirname(__file__), "lib")
    if os.path.isdir(_lib_path) and _lib_path not in sys.path:
        sys.path.insert(0, _lib_path)
  Este bloco e o PADRAO OFICIAL do NVDA para dependencias bundladas em lib/.
  Se o codigo tiver este bloco com _lib_path, ignore-o completamente — nao reduza o score.
  NAO gere issue sobre sys.path ou manipulacao de path para lib/ bundlada.
NVDA-007 Moderado: Script sem decorator @script.
  ERRADO: __gestures = {"kb:NVDA+t": "script_tempo"}
  CORRETO: @script(gesture="kb:NVDA+t", description=_("Anuncia hora"))
NVDA-008 Moderado: Script com decorator @script mas sem description= preenchido.
  ERRADO: @script(gesture="kb:NVDA+t") sem description
  CORRETO: @script(gesture="kb:NVDA+t", description=_("Anuncia hora atual"), category="MeuAddon")
NVDA-009 Moderado: Atalho hardcoded que conflita com NVDA core (ex: NVDA+f, NVDA+t, NVDA+q).
  Atalhos seguros: NVDA+shift+letra, NVDA+ctrl+letra.
NVDA-010 Serio: GUI de thread background sem wx.CallAfter().
NVDA-011 Moderado: SynthDriver ou BrailleDisplayDriver sem classmethod check().
  check() e obrigatorio para o NVDA detectar se o driver esta disponivel.
  ESCOPO ESTRITO: aplique SOMENTE se o codigo tem uma classe que herda de SynthDriver
  ou BrailleDisplayDriver. NUNCA aplique a GlobalPlugin, AppModule ou outras classes.
NVDA-012 Menor: except: sem especificar excecao E sem logar o erro.
  ERRADO: except: pass
  CORRETO: except Exception as exc: log.exception("Erro: %s", exc)
NVDA-013 Serio: lastTestedNVDAVersion < BACK_COMPAT_TO do NVDA alvo.
  FONTE: addonAPIVersion.py — compare com o BACK_COMPAT_TO da versao-alvo.
  REGRA CORRETA: lastTestedNVDAVersion >= minimumNVDAVersion do proprio addon.

  POLITICA DO PROJETO: addons novos do NVDAStudio usam baseline minimo
  2026.1.1+ (fonte unica de verdade: utils/project_policy.py, PROJECT_MIN_NVDA/
  PROJECT_LAST_TESTED_NVDA -- NAO trate os numeros acima como um valor fixo
  a exigir; sao um PISO minimo, o valor real evolui conforme releases novas
  do NVDA sao confirmadas compativeis).
  SO penalize se lastTestedNVDAVersion for claramente abaixo de 2025.1.
NVDA-014 OPCIONAL: SHA256 ausente — NAO bloquear em desenvolvimento. E necessario apenas
  para submissao ao Add-on Store. Nunca use NVDA-014 como motivo para CORRIGIR ou REJEITAR.
NVDA-015 Moderado: Configuracoes salvas sem config.conf.spec.
  ERRADO: open(config_path, "w").write(data)
  CORRETO: config.conf.spec["meuAddon"] = {"opcao": "boolean(default=True)"}
		   e acessar via config.conf["meuAddon"]["opcao"]
NVDA-016 Serio: Acesso a arquivo ou rede sem verificar NVDAState.shouldWriteToDisk().
  Em secure mode (tela de bloqueio, UAC), gravar em disco e ler senhas e proibido.
  CORRETO: if NVDAState.shouldWriteToDisk(): ... antes de abrir arquivos para escrita.
NVDA-018 Serio: minimumNVDAVersion abaixo de 2019.3.0 (antes era Python 2).
  POLITICA DO PROJETO: para addons novos do NVDAStudio, minimumNVDAVersion tambem
  nao deve ficar abaixo de 2026.1.1.

REGRAS ARQUITETURAIS (ARCH-001..009) — aplique APENAS em code_generation com codigo Python:

ASSINATURAS REAIS DO NVDA -- nao contradiga estas.
Verificadas na fonte que o projeto mantem em nvda_docs_cache/nvda/source/.
Se voce acha que uma chamada abaixo esta errada, VOCE esta errado:

  api.copyToClip(text: str, notify: Optional[bool] = False) -> bool
    `notify` E parametro publico e nomeado. NUNCA gere issue dizendo que
    copyToClip(..., notify=False) levanta TypeError ou que notify nao
    existe na API publica. Fonte: nvda_docs_cache/nvda/source/api.py:399,
    e o proprio core usa assim em textInfos/__init__.py::copyToClipboard().

REGRA GERAL: alegar que uma API do NVDA nao aceita um parametro e uma
afirmacao FACTUAL, nao estetica. Se voce nao tem certeza da assinatura, nao
levante o achado -- descreva a duvida sem reprovar. Um falso positivo aqui
custa 3 tentativas de geracao inteiras.

Medido em 2026-09-02 (AssistenteEscrita, step s5): o Critic reprovou 3x
alegando que "api.copyToClip nao aceita o parametro keyword notify=False na
API publica do NVDA; a chamada levantara TypeError". A assinatura acima
desmente isso e estava em disco no mesmo repositorio. 324.380 tokens
queimados para reprovar codigo correto.

LIMITES DESTA ETAPA:
- Empacotar dependencias NAO e trabalho de nenhum step de IA -- nem deste, nem do
  assembly. Nao rejeite nenhum step porque um pacote externo nao aparece em lib/.
- manifest.ini e avaliado por manifest_builder. Ignore nome, URL e outros campos de
  manifesto que tenham aparecido acidentalmente neste output.
- `scriptCategory` na classe GlobalPlugin e API valida documentada pelo NVDA.
- TAB e LF sao o estilo oficial. Divergencia de formatacao isolada pede CORRIGIR,
  nunca REJEITAR codigo Python sintaticamente valido.

ARCH-001 Serio: Addon que usa API externa COM chave nao tem SettingsPanel para configurar a chave.
  GATILHO: codigo importa google.generativeai, requests para endpoint externo,
           elevenlabs, deepl, azure.cognitiveservices, ou qualquer cliente de API cloud.
  ESPERADO: deve existir codigo que registra um SettingsPanel em NVDASettingsDialog.categoryClasses
            OU adiciona item no menu Ferramentas para acessar configuracoes.
  SEM ISSO: o usuario nao tem como configurar a chave de API.

ARCH-002 Serio: I/O pesado (HTTP, arquivo, audio, OCR) na thread principal sem threading.
  GATILHO: codigo chama requests.get/post, subprocess.run bloqueante, wave.open() em loop,
           whisper.load_model() ou similar diretamente em um script_ ou event_.
  ESPERADO: operacao pesada deve estar em threading.Thread(target=...).start()
            com wx.CallAfter() para atualizar a UI.

ARCH-004 Serio: Logica de API misturada diretamente no __init__.py GlobalPlugin.
  GATILHO: __init__.py tem mais de 120 linhas E contem tanto codigo de UI (wx.)
           quanto chamadas de API (requests., etc.) no mesmo arquivo.
  ESPERADO: logica de servico/API em arquivo separado (<nome_servico>.py) dentro do globalPlugins.
  EXCECAO: addons simples (< 80 linhas) podem ter tudo em __init__.py.

ARCH-005 Serio: Configuracao persistente salva fora do config.conf.
  GATILHO: codigo usa open() para gravar config, shelve, pickle, ou variaveis globais
           como unico mecanismo de persistencia de preferencias do usuario.
  ESPERADO: usar config.conf.spec + config.conf["secao"]["chave"] (padrao NVDA-015).

Score para ARCH: falha em ARCH-001 ou ARCH-002 penaliza -15 pontos no score.
                 falha em ARCH-004 ou ARCH-005 penaliza -10 pontos no score.

ARCH-003 Serio: AppModule vs GlobalPlugin — orientacao incorreta para o tipo de addon.
  Se o addon e especifico para UMA aplicacao, DEVE usar AppModule (appModules/<exe>.py).
  GlobalPlugin afeta TODAS as aplicacoes — use apenas para funcionalidades globais.
  Verifique se o tipo de plugin usado corresponde a especificacao do Clarifier.
ARCH-006 Serio: Extension points sem padrao register/unregister completo.
  Alem de ter register() em __init__ e unregister() em terminate() (NVDA-032),
  verifique que o handler usa a assinatura correta do extension point:
  Action=callable(), Filter=retorna dado, Decider=retorna bool, Chain=yield.
ARCH-007 Moderado: 3+ features/servicos substanciais em arquivos soltos genericos.
  GATILHO: addon tem 3 ou mais dominios distintos (ex: spotify_client.py, transcricao.py,
           playlists.py todos soltos na raiz do pacote) em vez de cada um no seu proprio
           subpacote nomeado pela funcionalidade (spotify/, transcricao/, playlists/).
  ESPERADO: cada feature substancial organizada em subpacote proprio dentro de
            globalPlugins/<addon_name>/, nomeado pela funcionalidade -- nao arquivos
            genericos (helper.py, utils.py, misc.py) nem tudo direto na raiz do pacote.
  EXCECAO: 1-2 features (caso comum, coberto por ARCH-004) continuam bastando arquivo(s) soltos.
  ERRADO: speech.filter_speechSequence.register(self._filtro) — mas _filtro retorna None
ARCH-008 Moderado: multiplas funcionalidades sem ponto de entrada principal definido.
  GATILHO: addon com 2 ou mais funcoes distintas para o usuario (ex: transcrever audio +
           configurar idioma + ver historico) SEM item de menu Ferramentas, SEM SettingsPanel,
           E sem nenhum outro ponto de entrada claro (script/gesture documentado conta).
  ESPERADO: pelo menos UM ponto de entrada principal -- item no menu Ferramentas OU
            SettingsPanel OU ambos, conforme o que o pedido original indicar. CONTEXTUAL:
            se o pedido nao deixa preferencia clara, nao penalize por escolher UMA das
            opcoes razoaveis -- so penalize se NENHUMA existir e o addon realmente precisar
            de um ponto de entrada (ex: 2+ funcoes que nao sao so scripts/gestures).
  Quando usa menu: bind/unbind do wx.EVT_MENU deve ocorrer no mesmo owner do menu resolvido.
ARCH-009 Moderado: dialog/frame principal sem ponto de entrada coerente com o pedido.
  GATILHO: addon abre wx.Dialog ou wx.Frame como interface principal.
  ESPERADO: CONTEXTUAL -- se o pedido pede menu explicitamente, deve ter item no menu
            Ferramentas com fallback de API (toolsMenu/systray toolsMenu); se pede so
            configuracoes, SettingsPanel basta; se ambiguo, nao penalize a escolha razoavel
            que o codigo fez. So penalize se o dialog/frame nao tiver NENHUM jeito documentado
            de ser aberto pelo usuario (nem menu, nem settings, nem script/gesture).
  Quando usa menu: bind/unbind sempre no owner correspondente ao menu efetivamente usado.

NVDA-UX-001 Serio: Feedback de resultado visivel sem equivalente sonoro via ui.message().
  Addons que atualizam GUI (SetLabel, SetValue, titulo de janela, barra de progresso)
  sem chamar ui.message() ou ui.browseableMessage() deixam o usuario cego sem feedback.
  O NVDA nao anuncia mudancas visuais silenciosas — o usuario nao sabe o que aconteceu.
  ERRADO: self.lbl_status.SetLabel("Transcricao concluida")  <- silencioso para cego
  CORRETO: self.lbl_status.SetLabel("Transcricao concluida"); ui.message("Transcricao concluida")
  EXCECOES: atualizacoes de progresso em loop (cada %) — ok anunciar apenas inicio e fim.
  Verifica apenas quando o codigo tem componentes de GUI (wx.Dialog, wx.Frame, wx.Panel).
NVDA-UX-002 Serio: Script ou botao sem feedback auditivo para o usuario.
  Toda acao acionavel pelo usuario (script, botao, item de menu) DEVE dar retorno em voz.
  skill: screen-reader-testing — "automated tools find only 30-50% of accessibility issues"
  ERRADO: def script_transcrever(self, gesture): self._processar()  # silencio
  CORRETO: ui.message(_("Iniciando transcricao...")); self._processar()
  EXCECAO: scripts que abrem dialogs (o dialog em si ja anuncia o contexto).
NVDA-UX-003 Moderado: Fluxo de uso nao completavel apenas com teclado e voz.
  Verifique se o usuario cego consegue completar o fluxo principal sem pistas visuais.
  Checklist (skill: screen-reader-testing — testing-strategy):
    - Todos os campos tem label anunciado ANTES do tipo de campo?
    - Erros sao anunciados por voz (nao apenas por cor ou icone)?
    - O resultado final da acao e anunciado explicitamente?
    - Nenhuma instrucao pressupoe que o usuario VE a tela?
  ERRADO: "Veja o icone verde para confirmar." (usuario cego nao ve icone)
  CORRETO: ui.message(_("Configuracao salva com sucesso."))
  Penaliza -5 pontos por criterio falho no score de acessibilidade.

WX-A11Y-004 Serio: wx.Dialog sem StdDialogButtonSizer nem handler de tecla Escape.
  Dialogos sem StdDialogButtonSizer e sem handler para WXK_ESCAPE ou wx.ID_CANCEL
  deixam usuarios de teclado presos — sem forma de fechar sem mouse.
  ERRADO: dlg = wx.Dialog(parent, title="Config"); dlg.ShowModal()
  CORRETO: dlg.SetEscapeId(wx.ID_CANCEL) ou crie StdDialogButtonSizer.
WX-A11Y-007 Serio: Uso de cor como unico indicador de estado sem anuncio textual.
  Mudancas visuais como cor de fundo (verde=OK, vermelho=erro) sem ui.message()
  sao completamente invisiveis para usuarios cegos.
  ERRADO: self.btn.SetBackgroundColour("green")  # usuario cego nao percebe
  CORRETO: self.btn.SetBackgroundColour("green"); ui.message(_("OK"))
WX-A11Y-008 Serio: Timer ou status periodico sem feedback auditivo.
  Atualizacoes periodicas (relogio, status) sem anuncio sonoro sao perdidas.
  Use wx.CallLater com ui.message() ou tones.beep() no callback.
WX-A11Y-010 Serio: Ordem de tabulacao nao segue ordem logica.
  Garanta que Tab navega em ordem logica (esquerda->direita, cima->baixo).
  A ordem de criacao define a tab order padrao no wx.
WX-A11Y-001 Critico: wx.StaticText ausente imediatamente antes de controle de entrada/selecao, ou label= ausente em wx.Button (fix primario). SetName() e complemento, nao substituto.
WX-A11Y-003 Critico: EVT_LEFT_DOWN/EVT_LEFT_DCLICK sem evento de teclado equivalente.
WX-A11Y-005 Serio: wx.Dialog.ShowModal() sem SetFocus() em controle significativo.
WX-A11Y-006 Serio: wx.StaticBitmap ou wx.BitmapButton sem SetToolTip() ou subclasse wx.Accessible.
  Imagens sem nome acessivel sao invisíveis para leitores de tela. SetName() nao conta (nao afeta
  leitores de tela, so FindWindowByName()).
WX-A11Y-009 Moderado: wx.Panel customizado com EVT_PAINT sem subclasse wx.Accessible.
  Controles desenhados manualmente sao invisíveis para UIA/MSAA.
WX-A11Y-011 Serio: wx.ListCtrl ou wx.TreeCtrl em modo virtual sem override GetItemText.
  Modo virtual sem GetItemText faz o leitor de tela anunciar itens em branco.
WX-A11Y-012 Moderado: Item de menu sem tecla aceleradora (sufixo \tCtrl+X ausente).
WX-A11Y-013 Critico: EVT_KEY_DOWN/EVT_CHAR em ListBox/ListCtrl/TreeCtrl com NVDA/JAWS ativo — usar EVT_CHAR_HOOK.
WX-A11Y-014 Serio: wx.ListCtrl com EVT_KEY_DOWN para Enter em vez de EVT_LIST_ITEM_ACTIVATED.

DTK-A11Y (camada de API de plataforma UIA/MSAA, complementar a WX-A11Y — nao duplica):
DTK-A11Y-001 Critico: Controle interativo sem Name exposto via UIA/MSAA — leitor de tela nao anuncia nada.
DTK-A11Y-002 Critico: Role/ControlType nao bate com o comportamento real do controle.
DTK-A11Y-003 Serio: Mudanca de estado (checked/expanded/disabled/selected) nao refletida na API de acessibilidade.
DTK-A11Y-004 Serio: Controle com valor (slider/progress/spinner/campo) nao expoe valor atual via ValuePattern/accValue.
DTK-A11Y-005 Critico: Elemento interativo nao alcancavel via teclado (sem tab stop).
DTK-A11Y-006 Serio: Foco perdido apos mudanca de UI (deletar item, fechar dialogo) — cai fora do destino logico.
DTK-A11Y-007 Moderado: Foco de teclado sem indicador visual em tema padrao E alto contraste.
DTK-A11Y-008 Moderado: Cores hardcoded em vez de wx.SystemSettings.GetColour() — quebra em Alto Contraste.
DTK-A11Y-009 Serio: Atualizacao de conteudo silenciosa, sem evento UIA/notificacao de acessibilidade.
DTK-A11Y-010 Serio: Dialogo modal nao prende o foco — Tab alcanca a janela pai.
DTK-A11Y-011 Menor: Atalho de teclado customizado sem documentacao descobrivel pelo usuario.
DTK-A11Y-012 Moderado: API de plataforma depreciada (ex: so MSAA em vez de UIA no Windows moderno).

Regras para agent_runner (aplique se step_type=agent_runner):
  reset_session() presente; _fallback_chain e lista de modelos;
  cliente LLM importado condicionalmente (try/except ImportError);
  historico sem role=system (contrato llm_client.py: historico nunca contem mensagens do sistema);
  logging sem emojis.

Regras para agent_template (aplique se step_type=agent_template):
  Todas as 8 secoes Community Access presentes
  (Descricao, Responsabilidades, Regras de Comportamento, Entradas, Saidas, Invariantes, Referencias, Versao).

Regras para tipos sem codigo Python (nao aplique regras NVDA/WX-A11Y):
- manifest_builder: APROVADO se manifest.ini correto e campos preenchidos.
  CRITICO: manifest.ini NUNCA deve ter secao [add-on]. A presenca de [add-on] e um ERRO grave.
  O formato correto e chave=valor direto na raiz, sem nenhuma linha de secao.
  O baseline oficial do projeto e 2026.1.1+ para minimumNVDAVersion e lastTestedNVDAVersion.
  CRITICO url: campo "url" DEVE ser nao-vazio e comecar com "https://". Url vazio = ERRO grave.
  SHA256 e OPCIONAL — nunca penalize sua ausencia (so necessario para o Add-on Store).
- web_research: APROVADO se conteudo informativo e relevante.
- accessibility_audit: APROVADO se identificou regras com IDs ou concluiu sem violacoes.
- assembly: APROVADO se output coerente, manifest.ini sem [add-on], e codigo Python presentes.

Score: 90-100=APROVADO, 60-89=CORRIGIR, abaixo 60=REJEITAR

SCORING MULTIDIMENSIONAL — inclua sempre no JSON de Quality (skill: llm-evaluation):
"dimension_scores": {
  "completeness": 0-100,  // entregou tudo que foi pedido no step?
  "format": 0-100,         // formato correto (Python puro, INI sem [add-on], sem HTML)?
  "nvda_compliance": 0-100 // regras NVDA-xxx e WX-A11Y-xxx respeitadas?
}
Se o step nao e codigo Python (web_research, design_review), use nvda_compliance=100.
Retorne APENAS JSON valido:
{"verdict": "...", "score": 0-100, "issues": [...], "fix_instructions": "...",
 "dimension_scores": {"completeness": X, "format": X, "nvda_compliance": X}}
"""

# 2026-08-29: alem do catalogo de regras, o QualityCritic passa a julgar
# ENGENHARIA -- os defeitos que nenhum ID de regra descreve (erro engolido,
# operacao externa sem timeout, recurso sem fim de vida, complexidade que o
# addon nao precisa, logica impossivel de testar sem o NVDA real). Fonte unica
# de verdade em utils/engineering_principles.py, compartilhada com planner,
# code_generator e engineering_reviewer -- nunca duplicar o texto aqui
# (README Regra 5).
_CRITIC_QUALITY_SYSTEM += "\n\n" + RULE_REGISTRY_PROMPT_TEXT
_CRITIC_QUALITY_SYSTEM += "\n\n" + ENGINEERING_CRITIC_PROMPT_TEXT

# _CRITIC_SYSTEM: compatibilidade com testes e modulos externos que importam este simbolo.
# Contem os criterios completos (spec + quality) para que asserts de conteudo funcionem.
_CRITIC_SYSTEM = _CRITIC_SPEC_SYSTEM + "\n\n" + _CRITIC_QUALITY_SYSTEM


class Critic:
	"""
	Avalia outputs de sub-agentes em dois estagios.

	Estagio 1 (SpecCritic): o output corresponde ao spec do step?
	Estagio 2 (QualityCritic): o codigo segue boas praticas e e acessivel?

	evaluate_two_stage(): metodo principal — dois estagios.
	evaluate(): retrocompatibilidade — estagio unico combinado.
	"""

	def __init__(self):
		pass

	# ------------------------------------------------------------------
	# API Publica
	# ------------------------------------------------------------------

	def evaluate_two_stage(
		self, step_type: str, output: str, context: str = ""
	) -> CriticResult:
		"""
		Avaliacao em dois estagios (padrao subagent-driven-development).
		Estagio 1: spec compliance. So avanca se passar.
		Estagio 2: code quality.
		Retorna o resultado do estagio mais restritivo.
		"""
		# Guard deterministico (Regra 5)
		if not output or not output.strip():
			return self._empty_output_result(step_type)

		# Guard deterministico: imports proibidos em code_generation.
		# Nao depende de LLM — scan de texto puro antes de qualquer chamada.
		# 3.13.0: pulado pra project_type=="controller_client" -- e um
		# programa EXTERNO, nao roda dentro do sandbox de imports do NVDA
		# (o guard existe pra pegar import que quebra addonHandler.load(),
		# irrelevante pra um processo Windows independente).
		if step_type == STEP_CODE_GENERATION and not is_controller_client_context(context):
			forbidden_found = self._check_forbidden_imports(output)
			if forbidden_found:
				issues = [
					f"Import nao-padrao NVDA detectado: '{imp}' "
					f"nao existe no ambiente Python do NVDA e causara ImportError em runtime."
					for imp in forbidden_found
				]
				fix = (
					"Remova os imports proibidos e substitua pela API nativa do NVDA. "
					"Use apenas modulos da stdlib Python, nvwave, speech, braille, "
					"gui, config, addonHandler, winUser, NVDAObjects e similares."
				)
				log_decision(_logger, f"veredicto_{Verdict.NEEDS_FIX.value}",
							 f"step={step_type} forbidden_imports={forbidden_found}")
				return CriticResult(
					verdict=Verdict.NEEDS_FIX,
					score=55,
					issues=issues,
					fix_instructions=fix,
					stage="spec",
				)

			# G2 (2026-05-15): Guard deterministico de API keys hardcoded.
			# Detecta chaves de API no codigo gerado ANTES de chamar o LLM.
			# Penalidade: -20 pontos por violacao.
			api_audit = api_key_validator.audit_code(output)
			if not api_audit.is_clean:
				fix = api_key_validator.get_fix_instructions(api_audit.violations)
				issues = [
					f"API key hardcoded detectada (linha {v.line_number}): {v.provider}. "
					f"Use config.conf ou variavel de ambiente."
					for v in api_audit.violations
				]
				log_decision(_logger, f"veredicto_{Verdict.NEEDS_FIX.value}",
							 f"step={step_type} api_key_violations={len(api_audit.violations)}")
				return CriticResult(
					verdict=Verdict.NEEDS_FIX,
					score=max(0, 80 - api_audit.score_penalty),
					issues=issues,
					fix_instructions=fix,
					stage="spec",
				)

		# Guard deterministico: web_research devolveu bloco de codigo Python
		# em vez de texto de pesquisa. Achado real reproduzido 3x em 3
		# rodadas do teste E2E complexo real (2026-08-07, addon
		# AssistenteLeituraGemini, deepseek-v4-flash): o step web_research
		# devolvia um ```python:__init__.py``` de addon NVDA generico
		# (as vezes literalmente "Hello World") em vez do formato markdown
		# esperado. O fix de prompt (_SYSTEM de web_researcher.py 4.5.0) ja
		# instrui o modelo a nao fazer isso, mas depender so de instrucao
		# de prompt significa esperar uma chamada LLM inteira (o Critic) so
		# pra descobrir que o formato esta errado -- esse guard detecta
		# antes de gastar essa chamada, com diagnostico mais preciso.
		if step_type == STEP_WEB_RESEARCH and re.search(r"```python:", output):
			log_decision(_logger, f"veredicto_{Verdict.NEEDS_FIX.value}",
						 f"step={step_type} bloco_python_detectado=True")
			return CriticResult(
				verdict=Verdict.NEEDS_FIX,
				score=50,
				issues=[
					"Output e um bloco de codigo Python (```python:arquivo.py```), "
					"nao texto de pesquisa. web_research nunca escreve o addon -- "
					"isso e responsabilidade do step code_generation, separado.",
				],
				fix_instructions=(
					"Reescreva a resposta como texto markdown seguindo o 'Formato de "
					"Resposta Obrigatorio' (Pacote/Versao estavel/Instalacao/API "
					"principal/Exemplo minimo/Compatibilidade/Confianca). NAO use "
					"```python:arquivo.py``` -- esse formato e exclusivo do step "
					"code_generation, nunca de web_research."
				),
				stage="spec",
			)

		# Guard deterministico: url vazio ou sem HTTPS em manifest_builder.
		# Detecta o defeito antes de gastar chamadas de LLM. O Add-on Store
		# do NVDA rejeita manifests sem url HTTPS valida.
		if step_type == STEP_MANIFEST_BUILDER:
			url_issue = self._check_manifest_url_invalid(output)
			if url_issue:
				log_decision(_logger, f"veredicto_{Verdict.NEEDS_FIX.value}",
							 f"step={step_type} {url_issue['key']}")
				return CriticResult(
					verdict=Verdict.NEEDS_FIX,
					score=55,
					issues=[url_issue["msg"]],
					fix_instructions=(
						"Defina o campo 'url' com um endereco HTTPS valido. "
						"Quando nao houver URL oficial do projeto, use o placeholder "
						"https://github.com/NVDAAddons/<nome-do-addon>."
					),
					stage="spec",
				)

		# Estagio 1: Spec
		spec_result = self._evaluate_with_system(
			_CRITIC_SPEC_SYSTEM, step_type, output, context, stage="spec"
		)
		log_decision(_logger, f"spec_veredicto_{spec_result.verdict.value}",
					 f"step={step_type} score={spec_result.score}")

		if spec_result.verdict == Verdict.REJECTED:
			spec_result.stage = "spec"
			return self._calibrate_confidence(spec_result)

		if spec_result.verdict == Verdict.NEEDS_FIX:
			spec_result.stage = "spec"
			return self._calibrate_confidence(spec_result)

		# Estagio 2: Quality (so se spec passou)
		quality_result = self._evaluate_with_system(
			_CRITIC_QUALITY_SYSTEM, step_type, output, context, stage="quality"
		)
		log_decision(_logger, f"quality_veredicto_{quality_result.verdict.value}",
					 f"step={step_type} score={quality_result.score}")
		quality_result.stage = "quality"

		# Combina: score final e o menor dos dois
		if spec_result.score < quality_result.score:
			quality_result.score = spec_result.score
			quality_result.issues = spec_result.issues + quality_result.issues

		# dimension_scores vem do QualityCritic (Estagio 2).
		# Se Estagio 1 (spec) falhou antes do Quality, nao ha dimension_scores — ok.
		quality_result.stage = "two_stage"
		calibrated = self._calibrate_confidence(quality_result)

		# skill: agent-evaluation ("Statistical Test Evaluation — run multiple times").
		# Quando confidence=0.65 (score no limite APROVADO/CORRIGIR ou CORRIGIR/REJEITAR),
		# executa segundo julgamento e toma o resultado mais conservador (menor score).
		# Evita que um score de 88 ou 62 tome o veredicto errado por variabilidade do LLM.
		if calibrated.confidence < 1.0:
			_logger.info(
				"[CRITIC] Baixa confianca (score=%d). Executando segundo julgamento.",
				calibrated.score
			)
			second = self._evaluate_with_system(
				_CRITIC_QUALITY_SYSTEM, step_type, output, context, stage="quality_recheck"
			)
			if second.score < calibrated.score:
				_logger.info(
					"[CRITIC] Segundo julgamento mais conservador: %d < %d. Adotando.",
					second.score, calibrated.score
				)
				second.stage = "two_stage_recheck"
				second.dimension_scores = second.dimension_scores or calibrated.dimension_scores
				calibrated = second
			calibrated.confidence = 0.8  # melhorado apos segundo julgamento
			log_decision(_logger, "recheck_aplicado",
						 f"step={step_type} score_final={calibrated.score}")

		# skill: agent-evaluation + pesquisa dedicada 2026-08-04 (Multi-Review /
		# Self-Agg: rodar a mesma avaliacao N vezes e votar reduz falso-positivo
		# sem custar uma segunda geracao completa -- Gemini-2.5-Flash Self-Agg
		# n=10 teve +43.67% F1 e +118.83% recall vs. passada unica em revisao de
		# codigo). REJEITAR e o veredicto mais caro (dispara replan inteiro,
		# nao so um retry) e ficava FORA da zona de recheck acima (essa so cobre
		# score 60-89 -- um REJEITAR com score<60 nunca era reconferido). Fix:
		# todo REJEITAR do Estagio 2 (quality) passa por um segundo julgamento
		# independente antes de virar final. NAO cobre REJEITAR do Estagio 1
		# (spec) -- esse retorna cedo por design (linha ~578) e ja tem
		# regressao pinada (test_dois_estagios_spec_rejected_quality_nao_roda,
		# chat.call_count==1): rejeicoes de spec tendem a ser mais objetivas
		# (ex: output vazio, ja capturado por guard deterministico acima) do
		# que rejeicoes de quality, que sao julgamento mais subjetivo -- por
		# isso a confirmacao extra se justifica mais aqui. Ao contrario do
		# recheck de fronteira (que toma o score
		# mais conservador), aqui a logica e "concordancia" -- so mantem
		# REJEITAR se as DUAS passadas concordarem que o output esta quebrado;
		# se a segunda discordar, isso e evidencia de variabilidade do LLM
		# (nao um REJEITAR real), entao rebaixa pra CORRIGIR em vez de deixar
		# a rejeicao (potencialmente falsa) disparar um replan caro.
		if calibrated.verdict == Verdict.REJECTED and calibrated.confidence >= 1.0:
			_logger.info(
				"[CRITIC] REJEITAR (score=%d). Confirmando com segundo julgamento independente.",
				calibrated.score
			)
			confirm = self._evaluate_with_system(
				_CRITIC_QUALITY_SYSTEM, step_type, output, context, stage="reject_confirm"
			)
			if confirm.verdict != Verdict.REJECTED:
				_logger.info(
					"[CRITIC] Segundo julgamento discordou do REJEITAR (verdict=%s, score=%d). "
					"Rebaixando para CORRIGIR em vez de confirmar rejeicao potencialmente falsa.",
					confirm.verdict.value, confirm.score
				)
				calibrated.verdict = Verdict.NEEDS_FIX
				calibrated.score = max(calibrated.score, min(confirm.score, 69))
				calibrated.issues = calibrated.issues + [
					"Veredicto REJEITAR nao confirmado por segundo julgamento independente "
					"(rebaixado para CORRIGIR — skill agent-evaluation, evita false-reject)."
				]
				calibrated.stage = "two_stage_reject_downgraded"
			else:
				_logger.info(
					"[CRITIC] Segundo julgamento confirmou REJEITAR (score=%d).", confirm.score
				)
				calibrated.stage = "two_stage_reject_confirmed"
			calibrated.confidence = 0.9
			log_decision(_logger, "reject_confirmacao_aplicada",
						 f"step={step_type} confirmado={confirm.verdict == Verdict.REJECTED} "
						 f"score_final={calibrated.score}")

		return calibrated

	def evaluate(
		self, step_type: str, output: str, context: str = ""
	) -> CriticResult:
		"""Avaliacao de estagio unico (retrocompatibilidade)."""
		if not output or not output.strip():
			return self._empty_output_result(step_type)

		prompt = self._build_prompt(step_type, output, context)
		log_llm_call(_logger, f"critic_v{MODULE_VERSION}", prompt)
		raw = self._call_critic_with_system(_CRITIC_SPEC_SYSTEM, prompt, step_type=step_type)
		log_llm_response(_logger, f"critic_v{MODULE_VERSION}", raw)

		result = self._parse_result(raw)
		result.stage = "single"
		log_decision(_logger, f"veredicto_{result.verdict.value}",
					 f"step={step_type} score={result.score} issues={len(result.issues)}")
		return result

	# ------------------------------------------------------------------
	# Internos
	# ------------------------------------------------------------------

	@staticmethod
	def _calibrate_confidence(result: CriticResult) -> CriticResult:
		"""
		Calibra o campo confidence baseado na proximidade ao limite de veredicto.

		Limites de veredicto:
		  score >= 90  -> APROVADO
		  score 60-89  -> CORRIGIR
		  score < 60   -> REJEITAR

		Zonas de baixa confianca (skill: advanced-evaluation):
		  score 80-89: proximo ao limite APROVADO/CORRIGIR  -> confidence=0.65
		  score 60-69: proximo ao limite CORRIGIR/REJEITAR  -> confidence=0.65
		  demais faixas: score claramente dentro da zona    -> confidence=1.0

		Nao altera verdict nem score — apenas registra a incerteza para o Orchestrator.
		"""
		score = result.score
		if 80 <= score <= 89 or 60 <= score <= 69:
			result.confidence = 0.65
			result.issues = list(result.issues) + [
				f"Confianca reduzida: score {score} esta proximo ao limite de veredicto "
				f"(boundary ±10 pts). Revisar manualmente se possivel."
			]
		else:
			result.confidence = 1.0
		return result

	def _evaluate_with_system(
		self, system: str, step_type: str, output: str, context: str, stage: str
	) -> CriticResult:
		# 3.13.0: roteamento deterministico (Regra 5/9) -- quando o contexto
		# vem marcado como controller_client, anexa a rubrica dedicada
		# (testIfRunning, retorno checado, DLL por arquitetura) em vez de
		# avaliar so pela rubrica de addon NVDA, que exigiria coisas que nao
		# se aplicam aqui (GlobalPlugin, manifest.ini).
		if is_controller_client_context(context):
			system = system + CTRL_CLIENT_CRITIC_ADDENDUM
		prompt = self._build_prompt(step_type, output, context)
		log_llm_call(_logger, f"critic_{stage}_v{MODULE_VERSION}", prompt)
		raw = self._call_critic_with_system(system, prompt, step_type=step_type)
		log_llm_response(_logger, f"critic_{stage}_v{MODULE_VERSION}", raw)
		result = self._parse_result(raw)
		result.stage = stage
		return result

	def _build_prompt(self, step_type: str, output: str, context: str) -> str:
		if context:
			return (
				f"Tipo de step: {step_type}\n\n"
				f"Output do agente a avaliar:\n{output}\n\n"
				f"Contexto adicional:\n{context}"
			)
		return f"Tipo de step: {step_type}\n\nOutput do agente a avaliar:\n{output}"

	def _call_critic_with_system(self, system: str, prompt: str, step_type: str = "") -> str:
		"""
		step_type: repassado ate client.chat() (mesmo mecanismo de
		_run_sub_agent, ver sub_agents/_base.py 1.17.0/1.18.0) -- achado real
		no teste E2E complexo real (2026-08-07, addon AssistenteLeituraGemini):
		o critic avaliava um code_generation de 166k tokens com o teto de
		saida PADRAO (24k, ai/ollama_client.py _MAX_TOKENS_DEFAULT), nunca o
		estendido (48k, _MAX_TOKENS_EXTENDED) que o proprio code_generation ja
		ganha -- 3 tentativas seguidas retornaram "Critic retornou vazio ou
		sem JSON reconhecivel", condizente com o veredito JSON sendo cortado
		antes de fechar. Passar step_type aqui ativa o mesmo teto estendido
		pro critic quando o step avaliado e code_generation/agent_runner
		(ai/ollama_client.py _EXTENDED_TOKENS_STEP_TYPES).
		"""
		full_prompt = system + "\n\n" + prompt
		primary_exc: LLMClientError | None = None
		resp = None
		try:
			client = create_llm_client(model_id=get_critic_model())
			resp = client.chat(
				full_prompt,
				response_format={"type": "json_object"},
				step_type=step_type,
			)
		except LLMClientError as exc:
			_logger.warning("[AVISO] Critic: modelo principal falhou. Usando fallback.")
			primary_exc = exc
		# 3.15.0: achado real ao vivo (test_e36, GeminiMultimodal, s5 code_generation) --
		# "Critic retornou vazio ou sem JSON reconhecivel" 3x seguidas, sempre no
		# modelo LEVE (get_critic_model()). O fallback pro modelo pesado so disparava
		# em LLMClientError (excecao de rede/HTTP) -- uma chamada que TERMINA com
		# sucesso mas devolve content vazio/cortado (comum em modelo leve avaliando
		# um code_generation grande sob o teto estendido de tokens, ver
		# _EXTENDED_TOKENS_STEP_TYPES) nunca escalava, so caia direto no fallback
		# textual generico -- 3 tentativas identicas, nenhuma progride. Agora
		# resp vazio/truncado (sem excecao) tambem escala pro fallback, mesmo
		# mecanismo ja usado pra LLMClientError. Excecao no fallback continua
		# propagando (comportamento antigo preservado) -- so o caminho "sucesso
		# mas vazio" ganhou uma segunda chance.
		primary_empty_or_truncated = resp is not None and (
			not (resp.content or "").strip() or getattr(resp, "truncated", False) is True
		)
		if primary_exc is not None or primary_empty_or_truncated:
			if primary_empty_or_truncated:
				_logger.warning(
					"[AVISO] Critic: modelo principal devolveu conteudo vazio/cortado "
					"(step_type=%s). Escalando pro modelo fallback.", step_type,
				)
			fallback_client = create_llm_client(model_id=get_critic_fallback_model())
			fallback_resp = fallback_client.chat(
				full_prompt,
				response_format={"type": "json_object"},
				step_type=step_type,
			)
			# So substitui a resposta original se o fallback realmente trouxe
			# conteudo -- um fallback tambem vazio nao deve apagar um resp
			# truncado (mas nao-vazio) que ainda pode ser parseavel.
			if (fallback_resp.content or "").strip() or resp is None:
				resp = fallback_resp
		if resp is not None and getattr(resp, "truncated", False) is True:
			_logger.warning(
				"[AVISO] Critic: resposta cortada pelo teto de tokens (step_type=%s). "
				"O veredicto JSON pode estar incompleto/nao-parseavel.", step_type,
			)
		return (resp.content or "") if resp is not None else ""

	# Alias interno para retrocompatibilidade (usado por evaluate())
	def _call_critic(self, prompt: str) -> str:
		return self._call_critic_with_system(_CRITIC_SPEC_SYSTEM, prompt)

	@staticmethod
	def _check_forbidden_imports(output: str) -> list[str]:
		"""Retorna lista de imports proibidos encontrados no output (deterministico)."""
		found = []
		for imp in FORBIDDEN_IMPORTS:
			# Detecta: import win32xxx  OU  from win32xxx import ...
			if re.search(r'\b(?:import|from)\s+' + re.escape(imp) + r'\b', output):
				found.append(imp)
		return found

	@staticmethod
	def _check_manifest_url_invalid(output: str):
		"""Detecta url vazio ou sem HTTPS em manifest.ini (deterministico).

		Retorna dict {'key': str, 'msg': str} se o campo url for invalido,
		ou None se estiver ok ou ausente (outros guards tratam ausencia).
		Aceita variantes de espacamento e aspas. Ignora linhas em comentarios.
		"""
		# Procura a primeira linha "url = ..." fora de blocos markdown
		# (manifest.ini real nao tem markdown, mas LLM as vezes envolve em ```ini).
		for raw_line in output.splitlines():
			line = raw_line.strip()
			if not line or line.startswith("#") or line.startswith(";"):
				continue
			match = re.match(r"^url\s*=\s*(.*)$", line, re.IGNORECASE)
			if not match:
				continue
			value = match.group(1).strip()
			# Remove aspas opcionais ao redor do valor
			if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
				value = value[1:-1].strip()
			if not value:
				return {
					"key": "url_vazio",
					"msg": (
						"Campo 'url' esta vazio no manifest.ini. "
						"O Add-on Store do NVDA rejeita manifests sem URL HTTPS valida."
					),
				}
			if not value.lower().startswith("https://"):
				return {
					"key": "url_sem_https",
					"msg": (
						f"Campo 'url' nao comeca com 'https://' (valor recebido: '{value}'). "
						"O Add-on Store do NVDA exige URLs HTTPS."
					),
				}
			# Achou um url valido — para por aqui (primeira ocorrencia vence)
			return None
		# Sem linha "url =" no output: nao e responsabilidade deste guard
		return None

	@staticmethod
	def _empty_output_result(step_type: str) -> CriticResult:
		log_decision(_logger, f"veredicto_{Verdict.REJECTED.value}",
					 f"step={step_type} score=0 output_vazio=True")
		return CriticResult(
			verdict=Verdict.REJECTED,
			score=0,
			issues=["Output vazio — o agente nao gerou nenhum conteudo."],
			fix_instructions="Execute novamente o step. O agente deve gerar conteudo nao vazio.",
			stage="single",
		)

	def _parse_result(self, raw: str) -> CriticResult:
		clean = self._extract_result_candidate(raw)
		if not clean:
			return CriticResult(
				verdict=Verdict.NEEDS_FIX,
				score=50,
				issues=["Critic retornou vazio ou sem JSON reconhecivel."],
				fix_instructions="Revise e corrija o output com base nos criterios do spec.",
			)

		parsed = self._try_parse_payload(clean)
		try:
			if parsed is not None:
				return self._result_from_payload(parsed)
		except (ValueError, KeyError, TypeError) as exc:
			_logger.warning("[AVISO] Critic: payload parseado invalido: %s", exc)

		fallback_payload = self._extract_fields_fallback(clean)
		if fallback_payload is not None:
			return self._result_from_payload(fallback_payload)

		_logger.warning("[AVISO] Critic: falha ao parsear JSON. Trecho: %s", clean[:200])
		return CriticResult(
			verdict=Verdict.NEEDS_FIX,
			score=50,
			issues=["Nao foi possivel avaliar o output corretamente."],
			fix_instructions="Revise e corrija o output com base nos criterios do spec.",
		)

	@staticmethod
	def _extract_result_candidate(raw: str) -> str:
		"""Extrai o bloco mais provavel de JSON/Python-dict do output bruto."""
		clean = (raw or "").strip()
		clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
		clean = re.sub(r"\s*```$", "", clean)

		verdict_pos = clean.lower().find("verdict")
		if verdict_pos != -1:
			start = clean.rfind("{", 0, verdict_pos + 1)
			end = clean.rfind("}")
			if start != -1 and end != -1 and end > start:
				return clean[start:end + 1].strip()

		start = clean.find("{")
		end = clean.rfind("}")
		if start != -1 and end != -1 and end > start:
			return clean[start:end + 1].strip()
		return clean

	@staticmethod
	def _sanitize_json_candidate(candidate: str) -> str:
		"""Repara desvios comuns de quase-JSON produzidos por LLM."""
		sanitized = candidate.replace("\r", " ").replace("\n", " ").replace("\t", " ")
		sanitized = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", sanitized)
		sanitized = re.sub(r",\s*([}\]])", r"\1", sanitized)
		return sanitized.strip()

	@staticmethod
	def _to_python_literal(candidate: str) -> str:
		"""Converte true/false/null em literais Python para ast.literal_eval."""
		literal = candidate
		literal = re.sub(r"\btrue\b", "True", literal, flags=re.IGNORECASE)
		literal = re.sub(r"\bfalse\b", "False", literal, flags=re.IGNORECASE)
		literal = re.sub(r"\bnull\b", "None", literal, flags=re.IGNORECASE)
		return literal

	def _try_parse_payload(self, candidate: str) -> dict | None:
		"""Tenta parsear o payload em varios formatos seguros."""
		variants = [
			candidate,
			self._sanitize_json_candidate(candidate),
		]
		for item in variants:
			try:
				data = json.loads(item)
				if isinstance(data, dict):
					return data
			except json.JSONDecodeError:
				pass

		for item in variants:
			try:
				data = ast.literal_eval(self._to_python_literal(item))
				if isinstance(data, dict):
					return data
			except (ValueError, SyntaxError):
				pass
		return None

	@staticmethod
	def _extract_fields_fallback(candidate: str) -> dict | None:
		"""
		Fallback final para saidas muito proximas do contrato, mas ainda quebradas.
		Extrai apenas campos essenciais sem executar nada.
		"""
		verdict_match = re.search(
			r'["\']?verdict["\']?\s*[:=]\s*["\']?(APROVADO|CORRIGIR|REJEITAR)',
			candidate,
			re.IGNORECASE,
		)
		if not verdict_match:
			return None

		score_match = re.search(r'["\']?score["\']?\s*[:=]\s*(\d+)', candidate, re.IGNORECASE)
		issues_match = re.search(r'["\']?issues["\']?\s*[:=]\s*\[(.*?)\]', candidate, re.IGNORECASE | re.DOTALL)
		fix_match = re.search(
			r'["\']?fix_instructions["\']?\s*[:=]\s*["\'](.*?)["\']\s*(?:,|})',
			candidate,
			re.IGNORECASE | re.DOTALL,
		)

		issues: list[str] = []
		if issues_match:
			issues = re.findall(r'["\']([^"\']+)["\']', issues_match.group(1))

		return {
			"verdict": verdict_match.group(1).upper(),
			"score": int(score_match.group(1)) if score_match else 50,
			"issues": issues,
			"fix_instructions": fix_match.group(1).strip() if fix_match else "",
		}

	@staticmethod
	def _result_from_payload(data: dict) -> CriticResult:
		verdict_str = str(data.get("verdict", "CORRIGIR")).upper()
		verdict = (
			Verdict(verdict_str)
			if verdict_str in {v.value for v in Verdict}
			else Verdict.NEEDS_FIX
		)

		raw_issues = data.get("issues", [])
		if isinstance(raw_issues, (str, bytes)):
			raw_issues = [raw_issues]
		elif not isinstance(raw_issues, list):
			raw_issues = [raw_issues]

		issues: list[str] = [
			i if isinstance(i, str) else json.dumps(i, ensure_ascii=False)
			for i in raw_issues
		]

		# Extrai dimension_scores se presentes na resposta do QualityCritic (skill: llm-evaluation)
		dimension_scores: dict[str, int] = {}
		raw_dims = data.get("dimension_scores")
		if isinstance(raw_dims, dict):
			for k in ("completeness", "format", "nvda_compliance"):
				if k in raw_dims:
					try:
						dimension_scores[k] = max(0, min(100, int(raw_dims[k])))
					except (ValueError, TypeError):
						pass

		return CriticResult(
			verdict=verdict,
			score=int(data.get("score", 50)),
			issues=issues,
			fix_instructions=str(data.get("fix_instructions", "")),
			dimension_scores=dimension_scores,
		)
