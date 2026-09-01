import os
import re

from ..utils.project_policy import (
	ABSOLUTE_MIN_NVDA,
	PROJECT_LAST_TESTED_NVDA,
	PROJECT_MIN_NVDA,
	PROJECT_SUPPORTED_RANGE,
)

PROMPT_VERSION = "3.34.0"

# ------------------------------------------------------------------
# Tabela de versoes do projeto.
# O baseline oficial do NVDAStudio atual e 2026.1+.
# ------------------------------------------------------------------

NVDA_VERSION_TABLE: list[tuple[str, str, str]] = [
	# (cenario, minimumNVDAVersion, lastTestedNVDAVersion)
	("Baseline oficial do projeto",            PROJECT_MIN_NVDA, PROJECT_LAST_TESTED_NVDA),
	("Forward-compatibility para NVDA 2026.1+", PROJECT_MIN_NVDA, "2026.1.0"),
	("Piso tecnico absoluto do ecossistema",   ABSOLUTE_MIN_NVDA, PROJECT_LAST_TESTED_NVDA),
]

# ------------------------------------------------------------------
# Regras de deteccao NVDA-001..040, NVDA-042..050
# Fonte: Community Access nvda-addon-specialist.md (2026-03-21)
# ------------------------------------------------------------------

NVDA_DETECTION_RULES: list[tuple[str, str, str]] = [
	# (rule_id, severity, descricao)
	("NVDA-001", "Critico",  "Falta nextHandler() em event handler"),
	("NVDA-002", "Critico",  "Bloqueio da thread principal (sleep, I/O sincrono, HTTP bloqueante)"),
	("NVDA-003", "Serio",    "Modulo usa gettext sem chamar addonHandler.initTranslation()"),
	("NVDA-004", "Serio",    "Falta terminate() para cleanup de recursos persistentes"),
	("NVDA-005", "Serio",    "Formato incorreto de versao no manifest ou lastTestedNVDAVersion < BACK_COMPAT_TO do NVDA alvo -- a Add-on Store valida minimumNVDAVersion/lastTestedNVDAVersion contra o catalogo real de versoes lancadas (nvdaAPIVersions.json), nao so contra o formato numerico YYYY.N.P"),
	("NVDA-006", "Moderado", "Monkey-patching de modulos do core NVDA"),
	("NVDA-007", "Moderado", "Script sem decorator @script"),
	("NVDA-008", "Moderado", "Script sem description no decorator"),
	("NVDA-009", "Moderado", "Atalho hardcoded conflita com NVDA core"),
	("NVDA-010", "Serio",    "Atualizacao de UI de thread background sem wx.CallAfter() -- as 3 formas sancionadas de voltar para a GUI thread sao wx.CallAfter() (assincrono), wx.CallLater(ms, func) (assincrono com atraso) e gui.guiHelper.wxCallOnMain() (sincrono, espera o resultado); nunca toque em controles wx direto de uma thread nao-GUI"),
	("NVDA-011", "Moderado", "Driver sem classmethod check()"),
	("NVDA-012", "Menor",    "Clausula except: bare (captura tudo sem logar)"),
	("NVDA-013", "Serio",    "Range de versao de API incompativel no manifest"),
	("NVDA-014", "Menor",    "SHA256 ausente para submissao ao Add-on Store"),
	("NVDA-015", "Moderado", "Configuracoes nao usam config.conf.spec"),
	("NVDA-016", "Serio",    "Vulnerabilidade em secure mode (sem check shouldWriteToDisk())"),
	("NVDA-017", "Critico",  "DLL 32-bit em NVDA 64-bit (2026.1+): incompativel"),
	("NVDA-018", "Serio",    "minimumNVDAVersion abaixo de 2019.3.0 (exige Python 2)"),
	# NVDA-019..021: adicionados em v3.2.0 (skill: nvda-addon-dev)
	("NVDA-019", "Serio",    "# Translators: comment ausente imediatamente antes de chamada _()"),
	("NVDA-020", "Moderado", "Import de re-export transitivo: use from NVDAObjects.IAccessible import IAccessible, nao from NVDAObjects import IAccessible"),
	("NVDA-021", "Moderado", "Indentacao com espacos em vez de TABS (NVDA usa TABS como padrao de codificacao)"),
	# NVDA-022: adicionado em v3.4.0 — root cause do GmailSummarizer (settings panel nunca aparecia)
	("NVDA-022", "Critico",  "Import 3rd party em nivel de modulo em arquivo de servico — impede carregamento do addon inteiro (incluindo settings panel) se dependencia nao bundlada em lib/"),
	# NVDA-023: adicionado em v3.5.0 — annotation com tipo lazy causa NameError no carregamento do modulo
	("NVDA-023", "Critico",  "Type annotation que referencia tipo importado de forma lazy (dentro do metodo) — NameError no carregamento do modulo: use string literal '->\"Tipo\"' para forward reference"),
	# NVDA-024: adicionado em v3.6.0 — categoryClasses.append sem guard causa painel duplicado no Tab
	("NVDA-024", "Serio",    "NVDASettingsDialog.categoryClasses.append() sem guard 'if Panel not in categoryClasses' — se o addon for recarregado sem terminate() bem-sucedido, o painel aparece duplicado e o Tab navega entre dois paineis sobrepostos"),
	# NVDA-025: adicionado em v3.7.0 — secao config.conf generica causa colisao entre addons
	("NVDA-025", "Critico",  "config.conf usa secao generica (ex: 'meuAddon') em vez do addonId unico — multiplos addons com o mesmo nome de secao sobrescrevem configuracoes uns dos outros; use sempre o addonId real do manifest.ini"),
	# NVDA-037: adicionado em v3.9.0 — BrailleDisplayDriver (renumerado de NVDA-044 em v3.8.0)
	("NVDA-037", "Moderado", "BrailleDisplayDriver sem numCols, display() ou isThreadSafe — campos obrigatorios para que o NVDA saiba o tamanho do display e envie celulas corretamente"),
	# NVDA-038: adicionado em v3.10.0 — SynthDriver sem supportedNotifications obrigatorias (skill: nvda-addon-dev §25)
	# synthIndexReached e synthDoneSpeaking sao OBRIGATORIOS em supportedNotifications e devem ser notificados
	# em speak(). Sem eles, "say all", leitura por paragrafo e callbacks de indice (braille) param de funcionar.
	("NVDA-038", "Critico",  "SynthDriver sem supportedNotifications declarando synthIndexReached e synthDoneSpeaking — ambos obrigatorios (skill: nvda-addon-dev §25); sem eles 'say all', leitura por paragrafo e braille on-index param de funcionar"),
	# NVDA-039: adicionado em v3.18.0 -- AppModule mapeando multiplos executaveis sem registerExecutableWithAppModule (skill: nvda-addon-dev par.3.2)
	# registerExecutableWithAppModule() e o mecanismo oficial para um AppModule cobrir varios executaveis.
	("NVDA-039", "Moderado", "AppModule com multiplos arquivos appModules/*.py identicos para executaveis da mesma suite -- use appModuleHandler.registerExecutableWithAppModule(executableName, appModuleName) para mapear executaveis extras ao mesmo AppModule e unregisterExecutable() em terminate() (skill: nvda-addon-dev par.3.2)"),
	# NVDA-042..048: adicionados/corrigidos em v3.8.0-v3.9.0
	("NVDA-042", "Moderado", "Usa _() para strings plurais em vez de ngettext() — gera texto errado: '1 itens encontrados'. Use ngettext(singular, plural, count).format(n=count)"),
	("NVDA-043", "Moderado", "Braille Translation Table ausente ou mal declarada: falta arquivo .utb em brailleTables/ ou secao [brailleTables] no manifest.ini com displayName, contracted, output, input"),
	("NVDA-044", "Moderado", "Symbol Dictionary ausente ou mal formatado: falta locale/<lang>/symbols-*.dic com secao 'symbols:' e entradas TAB-separadas ou secao [symbolDictionaries] no manifest.ini"),
	("NVDA-045", "Menor",    "Locale Gesture Remapping ausente ou mal formatado: falta locale/<lang>/gestures.ini com secoes [module.ClassName] e bindings 'scriptName = gesture'"),
	("NVDA-046", "Moderado", "Speech Dictionary sem formato correto — cada linha deve ter 4 campos TAB-separados: padrao, reposicao, case_sensitive, tipo. Declarar em manifest.ini [speechDictionaries]"),
	("NVDA-047", "Serio",    "manifest.ini: url nao comeca com https:// — Add-on Store rejeita URLs sem HTTPS"),
	("NVDA-048", "Critico",  "wxPython bundlado em lib/ (entradas wx*) — NVDA ja fornece wxPython; bundlar causa conflito de versao e aumento desnecessario do pacote"),
	# NVDA-040: adicionado em v3.9.2 — AppModule para hosts especiais (UWP/wwahost)
	("NVDA-040", "Serio",    "AppModule para wwahost.exe nao herda de nvdaBuiltin.appModules.wwahost.AppModule — herdar so de appModuleHandler.AppModule ignora o comportamento especial para apps UWP"),
	# NVDA-026: adicionado em v3.11.0 — import de simbolo privado do NVDA (skill: nvda-addon-dev §22)
	# Simbolos prefixados com _ sao privados e podem mudar em qualquer release NVDA, inclusive patches.
	# Nao ha aviso de deprecacao para API privada — o addon quebra silenciosamente apos update do NVDA.
	("NVDA-026", "Moderado", "Import de simbolo privado do NVDA (prefixo _) — ex: from someModule import _internalFunction. Simbolos _ sao privados e podem mudar em qualquer release NVDA sem aviso (skill: nvda-addon-dev §22); use apenas API publica documentada"),
	# NVDA-027: adicionado em v3.11.0 — AppModule para WebView2 sem disableBrowseModeByDefault (skill: nvda-addon-dev §3.2)
	# Apps baseadas em msedgewebview2.exe ativam browse mode propria alem do browse mode do NVDA.
	# Sem disableBrowseModeByDefault = True, o usuario tem dois browse modes ativos simultaneamente.
	("NVDA-027", "Serio",    "AppModule para msedgewebview2.exe sem disableBrowseModeByDefault = True — apps WebView2 ja tem browse mode proprio; sem esse flag o NVDA ativa um segundo browse mode causando comportamento duplicado e confuso para o usuario (skill: nvda-addon-dev §3.2)"),
	# NVDA-028: adicionado em v3.12.0 — type hints com Optional[]/Union[] em vez de X | None / X | Y (skill: nvda-addon-dev §18)
	# Python 3.13 (NVDA 2026.1+) suporta plenamente a sintaxe de uniao nativa. X | None e X | Y
	# sao formas legadas que a skill proibe explicitamente em codigo novo.
	("NVDA-028", "Menor",    "Type hint usando Optional/Union da typing em vez da sintaxe moderna X | None / X | Y. NVDA 2026.1+ usa Python 3.13 — use int | None, str | None, etc."),
	# NVDA-029: adicionado em v3.12.0 — line endings CRLF em vez de LF (skill: nvda-addon-dev §18)
	# A skill e explicita: UTF-8 + LF. CRLF em arquivos Python causa problemas no scons build do NVDA
	# e no git diff — detectavel quando o LLM gera codigo com quebras de linha Windows.
	("NVDA-029", "Menor",    "Line endings CRLF (\\r\\n) em arquivo Python do addon — NVDA exige LF (\\n) conforme coding standards (skill: nvda-addon-dev §18). CRLF causa problemas no scons build e no controle de versao"),
	# NVDA-030: adicionado em v3.13.0 — GlobalPlugin/AppModule __init__ sem super().__init__(*args, **kwargs) (skill: nvda-addon-dev §3.1, §3.2)
	# A skill mostra explicitamente o padrao: super().__init__(*args, **kwargs) e obrigatorio.
	# Sem a chamada, globalPluginHandler nao completa a inicializacao do plugin — atalhos podem
	# nao ser registrados e o plugin pode falhar silenciosamente na inicializacao do NVDA.
	# O *args, **kwargs e necessario pois o NVDA pode passar argumentos ao construtor em versoes futuras.
	("NVDA-030", "Serio",    "GlobalPlugin ou AppModule com __init__ que nao chama super().__init__(*args, **kwargs) — a inicializacao do plugin pelo globalPluginHandler/appModuleHandler nao e completada corretamente; atalhos podem nao ser registrados e o plugin falha silenciosamente (skill: nvda-addon-dev §3.1, §3.2)"),
	# NVDA-031: adicionado em v3.13.0 — SynthDriver sem metodo cancel() (skill: nvda-addon-dev §25)
	# cancel() faz parte do "minimum viable driver" da skill §25.
	# Sem cancel(), pressionar Escape nao para a fala — comportamento completamente quebrado para o usuario.
	# NVDA chama cancel() sempre que o usuario pressiona Ctrl ou Escape para interromper a leitura.
	("NVDA-031", "Critico",  "SynthDriver sem metodo cancel() — obrigatorio no minimum viable driver (skill: nvda-addon-dev §25). Sem cancel(), pressionar Ctrl/Escape nao para a fala; o usuario fica preso ouvindo audio que nao consegue interromper"),
	# NVDA-032: adicionado em v3.14.0 — extension point registrado em __init__ sem unregister em terminate() (skill: nvda-addon-dev §7)
	# register() sem unregister() correspondente em terminate() e memory leak garantido.
	# Pior: se o addon for recarregado (NVDA+Ctrl+F3), o handler fica registrado multiplas vezes
	# — cada evento NVDA dispara o handler N vezes (N = numero de recargas).
	# O NVDA nao avisa — o bug so aparece como comportamento duplicado ou crashs esporadicos.
	("NVDA-032", "Serio",    "Extension point registrado em __init__ (speech.filter_speechSequence.register, extensionPoints Action/Filter/Decider.register, etc.) sem unregister correspondente em terminate() — memory leak e handler duplicado a cada recarga do plugin (skill: nvda-addon-dev §7). Padrao: sempre chamar .unregister() em terminate() ANTES de super().terminate()"),
	# NVDA-033: adicionado em v3.14.0 — event_NVDAObject_init em GlobalPlugin (skill: nvda-addon-dev §5)
	# event_NVDAObject_init so e chamado para AppModule, nunca para GlobalPlugin.
	# Colocar em GlobalPlugin resulta em handler silenciosamente ignorado — zero erro, zero efeito.
	# O desenvolvedor assume que funciona, mas o addon nao faz nada.
	("NVDA-033", "Serio",    "event_NVDAObject_init definido em GlobalPlugin — este evento so e chamado para AppModule (skill: nvda-addon-dev §5). Em GlobalPlugin e silenciosamente ignorado pelo NVDA. Para customizar propriedades de NVDAObject globalmente, use chooseNVDAObjectOverlayClasses em GlobalPlugin; para um app especifico, mova para AppModule"),
	# NVDA-034: adicionado em v3.14.0 — AppModule para app self-voicing sem sleepMode (skill: nvda-addon-dev §3.3)
	# Apps self-voicing (ex: NVDA, JAWS, outros leitores) falam por conta propria.
	# Sem sleepMode=True, o NVDA vai anunciar todos os eventos de foco/caret da app sobre a voz dela
	# — dupla narracacao, confusao total para o usuario.
	# A skill §3.3 e explicita: sleepMode = True e o unico padrao correto para self-voicing apps.
	("NVDA-034", "Serio",    "AppModule para aplicacao self-voicing (leitores de tela, apps de narracacao, NVDA, JAWS, etc.) sem sleepMode = True — o NVDA vai tentar anunciar eventos de foco e caret sobre a voz propria da app, causando dupla narracao (skill: nvda-addon-dev §3.3). Correto: class AppModule(appModuleHandler.AppModule): sleepMode = True"),
	# NVDA-035: adicionado em v3.15.0 -- SynthDriver sem metodo pause() (skill: nvda-addon-dev §25)
	# pause() consta no "minimum viable driver" da skill §25, listado junto com cancel().
	# Sem pause(), NVDA lanca AttributeError ao pressionar Ctrl para pausar/retomar a fala --
	# o sintetizador crasha e o usuario perde controle de audio sem aviso.
	("NVDA-035", "Serio",    "SynthDriver sem metodo pause(self, switch: bool) -- obrigatorio no minimum viable driver (skill: nvda-addon-dev §25). Sem pause(), NVDA lanca AttributeError ao pressionar Ctrl para pausar/retomar a fala; o sintetizador crasha. Correto: def pause(self, switch: bool) -> None: self._tts_pause(switch)"),
	# NVDA-036: adicionado em v3.16.0 -- speak() como metodo principal do SynthDriver (skill: nvda-addon-dev §25)
	# O NVDA chama speak() para cada trecho de fala; sem speak() o driver e completamente nao funcional.
	("NVDA-036", "Critico",  "SynthDriver sem metodo speak(self, speechSequence) -- metodo principal do driver; sem speak() o sintetizador nao produz nenhuma fala (skill: nvda-addon-dev §25). speak() deve iterar speechSequence, notificar synthIndexReached por IndexCommand e synthDoneSpeaking ao final."),
	# NVDA-049: adicionado em v3.17.0 -- wx.MessageDialog proibido; use gui.message.MessageDialog (skill: nvda-addon-dev §12)
	# gui.message.MessageDialog e a API moderna do NVDA para dialogs modais -- integra corretamente com o screen reader.
	# wx.MessageDialog nao e anunciado corretamente pelo NVDA e o foco pode nao funcionar como esperado pelo usuario cego.
	("NVDA-049", "Serio",    "wx.MessageDialog OU wx.MessageBox usado em vez de gui.message.MessageDialog -- nenhum dos dois integra corretamente com o NVDA screen reader (skill: nvda-addon-dev §12). Use MessageDialog.alert(), .confirm(), .ask() ou instancia de gui.message.MessageDialog. wx.MessageDialog/wx.MessageBox nao anunciam corretamente via NVDA e podem travar o foco"),
	# NVDA-050: adicionado em v3.17.0 -- NVDAObject overlay class herda de NVDAObject (base) em vez de classe especifica (skill: nvda-addon-dev §6)
	# A skill §6 e explicita: "Always inherit from the most specific class you need to match the object."
	# Herdar de NVDAObject (base) em overlay classes usadas em chooseNVDAObjectOverlayClasses perde
	# metodos e propriedades especificos da API alvo (IAccessible2, UIA, Win32 Window, JAB).
	("NVDA-050", "Moderado", "NVDAObject overlay class herda de NVDAObject (classe base) em vez de classe mais especifica -- use NVDAObjects.IAccessible.IAccessible, NVDAObjects.UIA.UIA, NVDAObjects.window.Window ou NVDAObjects.JAB.JABObject conforme a API do objeto alvo (skill: nvda-addon-dev §6). Herdar da base generica perde metodos e propriedades especificos da API"),
	# NVDA-051: adicionado em v2.1.0 -- Menu Ferramentas (NVDA > Tools > Addon Name)
	# Bug encontrado: MediaTranscriber nao registrava item em menu Ferramentas
	# Fallback: se addon pode ter menu, deve implementar _ensure_menu_item() + _get_tools_menu()
	# com wx.CallAfter para thread safety
	("NVDA-051", "Serio",    "Addon com interface de usuario nao registra item no menu Ferramentas do NVDA (NVDA > Menu > Ferramentas > [Addon Name]) -- implementar _ensure_menu_item() + _get_tools_menu() com Bind(wx.EVT_MENU, ...) e thread-safety via wx.CallAfter(). Remocao em terminate()."),
	# NVDA 2026.1+ Compatibility rules
	("NVDA-052", "Serio",    "Uso de APIs legadas winUser, winKernel, winGDI, shellapi ou ftdi2 - migre para winBindings.* submodules ou ftdi2 subpackage (NVDA 2026.1+)."),
	("NVDA-053", "Critico",  "Uso de sapi5/sapi4 para vozes de 32 bits sem portabilidade ARM64EC ou sem suporte a sapi5_32/sapi4_32 (NVDA 2026.1+)."),
	("NVDA-054", "Moderado", "Uso de typing_extensions - NVDA 2026.1+ com Python 3.13 fornece suporte nativo; remova a dependencia typing_extensions."),
	# NVDA-055..059: adicionados em 2026-07-17 -- auditoria comparando com a documentacao
	# oficial (github.com/nvdaaddons/DevGuide, download.nvaccess.org/documentation/developerGuide.html,
	# github.com/nvaccess/AddonTemplate, guia de submissao da Add-on Store). Diferente de
	# NVDA-019..054 (nascidas de bugs reais de producao), estas sao PREVENTIVAS -- praticas
	# que a documentacao oficial exige mas nunca tinham causado um bug real no nvdastudio ainda.
	("NVDA-055", "Serio",    "Import de pacote pip empacotado junto com o NVDA (ex: comtypes, wx, requests da instalacao do NVDA) em vez de bundlar a propria dependencia em lib/ -- pacotes empacotados com o NVDA podem ser atualizados, rebaixados ou removidos a qualquer momento sem aviso; NAO sao API estavel do addon"),
	("NVDA-056", "Critico",  "wx.MessageDialog instanciado, inicializado ou exibido (ShowModal ou Show) fora da thread GUI -- a maioria dos metodos de MessageDialog NAO e thread-safe; chamar de thread nao-GUI pode causar crash ou comportamento imprevisivel, nao so travamento"),
	("NVDA-057", "Moderado", "@script sem usar as constantes SCRCAT_* para o parametro category (usa string livre em vez disso), ou ignora os flags canPropagate/bypassInputHelp/allowInSleepMode/speakOnDemand/resumeSayAllMode quando o script deveria funcionar durante Input Help, modo de sono, modo de fala sob demanda do NVDA, ou precisa retomar o Say All apos ser executado"),
	("NVDA-058", "Moderado", "installTasks.py ou uninstallTasks.py importa modulos alem do estritamente necessario -- onInstall()/onUninstall() rodam num estado restrito (pre-reinicio do NVDA, pasta .pendingInstall); imports desnecessarios aumentam risco de falha nesse estado"),
	("NVDA-059", "Serio",    "manifest.ini com addonId/name contendo caracteres fora de letras, numeros, underscore e hifen (ex: espaco, ponto, unicode) -- a Add-on Store valida o nome com uma regex restrita; caracteres fora desse conjunto rejeitam a submissao"),
	# NVDA-060..061: adicionados em 2026-08-03 -- auditoria comparando com o
	# Developer Guide oficial (download.nvaccess.org/documentation/developerGuide.html
	# 2026.1.1), 2 gaps de conteudo reais encontrados (nao existia regra
	# equivalente, nao e so ajuste de callback/fallback).
	("NVDA-060", "Critico",  "Uso de controlTypes.ROLE_*/controlTypes.STATE_* (API pre-2021.2, REMOVIDA no NVDA 2022.1) em vez de controlTypes.Role.*/controlTypes.State.* -- baseline do projeto e NVDA 2026.1.1, entao codigo com a forma antiga falha ao carregar (AttributeError), nao so gera warning de deprecacao"),
	("NVDA-061", "Moderado", "Character Descriptions ausente ou mal formatado: addon com necessidade de descrever caracteres individualmente (ex: driver de fala, dicionario fonetico) sem locale/<lang>/characterDescriptions.dic em UTF-8 com pares caractere/descricao separados por TAB, linhas em branco e comentarios '#' ignorados (skill: nvda-addon-dev, Developer Guide secao 'Character Descriptions')"),
	# NVDA-062: achado de auditoria full-stack 2026-08-04 -- o catalogo de 61
	# regras nao tinha NENHUMA cobertura de secure mode (tela de login/UAC/tela
	# segura), uma exigencia real e atual de revisao da Add-on Store. Fonte:
	# comunidade de addons (globalVars.appArgs.secure confirmado como o flag
	# padrao verificado por addons reais no __init__ de GlobalPlugin/AppModule
	# pra desativar cedo em secure mode) + codigo-fonte do proprio NVDA
	# (nvaccess/nvda: secure mode desativa criacao/edicao/exclusao de perfis
	# de configuracao, o console Python, e logging de dados sensiveis --
	# PRs #13056/#13059 corrigiram exploits reais de dialogo de arquivo
	# acessivel em tela segura).
	("NVDA-062", "Critico", "Addon com script/dialogo/persistencia de config sem checar globalVars.appArgs.secure -- em secure mode (tela de login, UAC, tela segura), scripts continuam executaveis (definidos a nivel de classe) mesmo se o __init__ verificar o flag e sair cedo; qualquer wx.Dialog que abre arquivo/pasta, salva config, ou loga dado sensivel deve checar o flag em CADA ponto de entrada perigoso, nao so no __init__; NUNCA logar senha/token/API key incondicionalmente (o proprio NVDA trata logging em secure mode como risco de seguranca)"),
]

# ------------------------------------------------------------------
# WX-A11Y Rules — 14 regras (001..014)
# Fonte OFICIAL: github.com/Community-Access/accessibility-agents .github/agents/wxpython-specialist.agent.md
# Secao "Detection Rules" — copiado literalmente, traduzido para PT-BR conciso.
# ATENCAO: IDs 005-011 foram corrigidos em v2.1.0 (estavam errados).
#          IDs 013-014 foram adicionados em v2.1.0 (estavam ausentes).
# ------------------------------------------------------------------

WX_A11Y_RULES: list[tuple[str, str, str]] = [
	# (rule_id, severity, descricao)
	# Fonte: wxpython-specialist.agent.md tabela "Detection Rules"
	("WX-A11Y-001", "Critico",  "wx.StaticText ausente imediatamente antes de controle de entrada/selecao, ou label= ausente em wx.Button (fix primario da fonte oficial); SetName() e complemento aceitavel, nao substituto"),
	("WX-A11Y-002", "Critico",  "wx.Panel ou wx.Frame sem wx.AcceleratorTable definida"),
	("WX-A11Y-003", "Critico",  "EVT_LEFT_DOWN/EVT_LEFT_DCLICK sem evento de teclado equivalente"),
	("WX-A11Y-004", "Serio",    "wx.Dialog sem CreateStdDialogButtonSizer() ou tratamento de Escape"),
	("WX-A11Y-005", "Serio",    "wx.Dialog.ShowModal() sem SetFocus() em controle significativo"),
	("WX-A11Y-006", "Serio",    "wx.StaticBitmap ou wx.BitmapButton sem SetToolTip() ou subclasse wx.Accessible"),
	("WX-A11Y-007", "Moderado", "wx.Colour como unico indicador de estado (sem texto/icone)"),
	("WX-A11Y-008", "Moderado", "wx.Timer ou status bar sem wx.Bell() ou anuncio acessivel"),
	("WX-A11Y-009", "Moderado", "wx.Panel customizado com EVT_PAINT sem subclasse wx.Accessible"),
	("WX-A11Y-010", "Menor",    "Ordem de tabulacao nao definida explicitamente e nao segue sizer"),
	("WX-A11Y-011", "Serio",    "wx.ListCtrl ou wx.TreeCtrl em modo virtual sem override GetItemText"),
	("WX-A11Y-012", "Moderado", "Item de menu sem tecla aceleradora (sufixo \\tCtrl+X ausente)"),
	# WX-A11Y-013/014: adicionados em v2.1.0 — criticos para usuarios de NVDA/JAWS
	# Fonte: wxpython-specialist.agent.md secao "Screen Reader Key Event Pitfalls"
	("WX-A11Y-013", "Critico",  "EVT_KEY_DOWN/EVT_CHAR em ListBox/ListCtrl/TreeCtrl/DataViewCtrl — falha silenciosa com NVDA/JAWS; usar EVT_CHAR_HOOK ou evento semantico"),
	("WX-A11Y-014", "Serio",    "wx.ListCtrl com EVT_KEY_DOWN para Enter em vez de EVT_LIST_ITEM_ACTIVATED"),
]

# ------------------------------------------------------------------
# DTK-A11Y Rules — 12 regras (001..012)
# Fonte OFICIAL: github.com/Community-Access/accessibility-agents .github/agents/desktop-a11y-specialist.agent.md
# Secao "Detection Rules" — copiado literalmente, traduzido para PT-BR conciso.
# Camada DIFERENTE de WX-A11Y: enquanto WX-A11Y cobre padroes especificos de
# widgets wx (label antes de controle, AcceleratorTable, etc.), DTK-A11Y cobre
# conceitos de API de plataforma (UIA/MSAA Name/Role/State/Value, focus trap
# em modal, High Contrast, deteccao de mudanca dinamica) que se aplicam a
# qualquer toolkit desktop e sao a fundamentacao conceitual que wx.Accessible
# implementa por baixo. Nao ha sobreposicao de ID nem de orientacao de fix
# com WX-A11Y-*/NVDA-0XX -- confirmado via investigacao dedicada 2026-08-17
# (pedido do Felipe: "quero que o nvda studio fique cada vez mais atualizado").
# ------------------------------------------------------------------

DTK_A11Y_RULES: list[tuple[str, str, str]] = [
	# (rule_id, severity, descricao)
	# Fonte: desktop-a11y-specialist.agent.md tabela "Detection Rules"
	("DTK-A11Y-001", "Critico",  "Controle interativo sem Name exposto via UIA/MSAA/accessibilityLabel -- leitor de tela nao anuncia nada ou so um tipo generico"),
	("DTK-A11Y-002", "Critico",  "Role/ControlType do controle nao bate com seu comportamento real (ex: painel clicavel sem role de botao)"),
	("DTK-A11Y-003", "Serio",    "Mudanca de estado (checked/expanded/disabled/selected) nao refletida na API de acessibilidade -- leitor de tela mostra estado desatualizado"),
	("DTK-A11Y-004", "Serio",    "Controle com valor (slider/progress bar/spinner/campo de texto) nao expoe o valor atual via ValuePattern/accValue/accessibilityValue"),
	("DTK-A11Y-005", "Critico",  "Elemento interativo nao alcancavel via teclado (nao focavel, sem tab stop) -- usuario de teclado nao consegue chegar nele"),
	("DTK-A11Y-006", "Serio",    "Foco perdido apos mudanca de UI (deletar item, fechar dialogo, colapsar painel) -- cai na raiz da janela ou local inesperado em vez de destino logico"),
	("DTK-A11Y-007", "Moderado", "Controle recebe foco de teclado mas sem indicador visual (contorno/destaque) visivel em tema padrao E alto contraste"),
	("DTK-A11Y-008", "Moderado", "Cores hardcoded em vez de ler do tema do sistema (wx.SystemSettings.GetColour() no wx) -- quebra em modo Alto Contraste do Windows"),
	("DTK-A11Y-009", "Serio",    "Atualizacao de conteudo (status bar, progresso, erro de validacao) acontece silenciosamente, sem evento UIA/notificacao de acessibilidade"),
	("DTK-A11Y-010", "Serio",    "Dialogo nao prende o foco -- Tab consegue sair do dialogo modal e alcancar controles da janela pai enquanto ele esta aberto"),
	("DTK-A11Y-011", "Menor",    "Atalho de teclado customizado definido no codigo sem documentacao descobrivel pelo usuario (item de menu, tooltip, texto de ajuda)"),
	("DTK-A11Y-012", "Moderado", "Uso de API de plataforma depreciada ou incorreta (ex: padrao MSAA-only no Windows moderno em vez de UIA)"),
]

# ------------------------------------------------------------------
# Matriz de fallback por regra (NVDA + WX + ARCH)
# ------------------------------------------------------------------

ARCH_RULE_IDS: list[str] = [
	"ARCH-001",
	"ARCH-002",
	"ARCH-003",
	"ARCH-004",
	"ARCH-005",
	"ARCH-006",
	"ARCH-007",
	"ARCH-008",
	"ARCH-009",
]

FALLBACK_MODE_DOC: dict[str, str] = {
	"STRICT_ONLY": "Sem alternativa: a regra deve ser cumprida exatamente.",
	"IMPLEMENTATION_ALTERNATIVES": "Alternativas tecnicas aceitas para cumprir a mesma regra.",
	"CONTEXTUAL_CHOICE": "Escolha conforme objetivo do usuario; se ambiguo, perguntar antes de gerar.",
}

# Overrides somente para regras com alternativa real/contextual.
# Todas as demais regras ficam como STRICT_ONLY por default.
_RULE_FALLBACK_OVERRIDES: dict[str, tuple[str, str]] = {
	"NVDA-005": ("IMPLEMENTATION_ALTERNATIVES", "Aceita corrigir formato de versao e/ou ajustar lastTestedNVDAVersion para BACK_COMPAT_TO."),
	"NVDA-014": ("CONTEXTUAL_CHOICE", "Opcional em desenvolvimento local; exigir apenas quando alvo for Add-on Store."),
	"NVDA-020": ("IMPLEMENTATION_ALTERNATIVES", "Usar import direto da API publica especifica em vez de re-export transitivo."),
	"NVDA-023": ("IMPLEMENTATION_ALTERNATIVES", "Usar forward reference em string ou remover annotation quando tipo e lazy import."),
	"NVDA-037": ("IMPLEMENTATION_ALTERNATIVES", "Implementar os campos obrigatorios (numCols/display/isThreadSafe) na estrategia do driver."),
	"NVDA-039": ("IMPLEMENTATION_ALTERNATIVES", "Usar registerExecutableWithAppModule e unregisterExecutable em terminate()."),
	"NVDA-042": ("IMPLEMENTATION_ALTERNATIVES", "Usar ngettext/npgettext para plural e pgettext para desambiguacao de contexto."),
	"NVDA-043": ("IMPLEMENTATION_ALTERNATIVES", "Cumprir com arquivo .utb valido e/ou declaracao correta em [brailleTables] no manifest."),
	"NVDA-044": ("IMPLEMENTATION_ALTERNATIVES", "Cumprir com symbols-*.dic valido e/ou declaracao correta em [symbolDictionaries]."),
	"NVDA-045": ("IMPLEMENTATION_ALTERNATIVES", "Cumprir com gestures.ini valido por locale/modulo conforme padrao NVDA."),
	"NVDA-049": ("IMPLEMENTATION_ALTERNATIVES", "Usar MessageDialog.alert/confirm/ask ou instancia de gui.message.MessageDialog -- nunca wx.MessageDialog nem wx.MessageBox."),
	"NVDA-050": ("IMPLEMENTATION_ALTERNATIVES", "Herdar de IAccessible/UIA/Window/JABObject conforme API alvo; nunca da base generica."),
	"NVDA-060": ("IMPLEMENTATION_ALTERNATIVES", "Trocar toda referencia controlTypes.ROLE_X/STATE_X por controlTypes.Role.X/State.X (mapeamento 1:1 documentado pelo NVDA)."),
	"NVDA-061": ("CONTEXTUAL_CHOICE", "So exigir characterDescriptions.dic quando o addon realmente descreve caracteres individualmente (driver de fala, dicionario fonetico); nao aplicavel a addons sem essa necessidade."),
	"WX-A11Y-002": ("IMPLEMENTATION_ALTERNATIVES", "Aplicar AcceleratorTable em wx.Panel ou wx.Frame quando houver foco/interacao de teclado."),
	"WX-A11Y-004": ("IMPLEMENTATION_ALTERNATIVES", "Dialog deve ter CreateStdDialogButtonSizer e/ou tratamento explicito de Escape."),
	"WX-A11Y-006": ("IMPLEMENTATION_ALTERNATIVES", "Controle de imagem deve ter SetToolTip() e/ou subclasse wx.Accessible (SetName() nao conta)."),
	"WX-A11Y-008": ("IMPLEMENTATION_ALTERNATIVES", "Anuncio de timer/status via wx.Bell e/ou mensagem acessivel equivalente."),
	"WX-A11Y-011": ("IMPLEMENTATION_ALTERNATIVES", "List/Tree virtual deve expor texto via override apropriado (ex: GetItemText)."),
	"WX-A11Y-013": ("IMPLEMENTATION_ALTERNATIVES", "Preferir EVT_CHAR_HOOK ou evento semantico no lugar de EVT_KEY_DOWN/EVT_CHAR bruto."),
	"WX-A11Y-014": ("IMPLEMENTATION_ALTERNATIVES", "Para ativacao de item use EVT_LIST_ITEM_ACTIVATED em vez de key handling ad hoc."),
	"ARCH-001": ("CONTEXTUAL_CHOICE", "Para configuracao de API key: SettingsPanel, menu Ferramentas, ou ambos conforme UX e pedido."),
	"ARCH-007": ("IMPLEMENTATION_ALTERNATIVES", "Promover arquivos soltos existentes para subpacotes nomeados pela funcionalidade (ex: services/spotify_client.py -> spotify/client.py)."),
	"ARCH-008": ("CONTEXTUAL_CHOICE", "Escolher entre menu Ferramentas, SettingsPanel ou ambos; se ambiguo, perguntar ao usuario."),
	"ARCH-009": ("CONTEXTUAL_CHOICE", "Dialog/frame pode usar menu, settings ou ambos conforme intencao do pedido e fluxo principal."),
	"DTK-A11Y-004": ("IMPLEMENTATION_ALTERNATIVES", "Expor valor via ValuePattern (UIA) ou accValue/accessibilityValue conforme a API alvo do controle."),
	"DTK-A11Y-008": ("IMPLEMENTATION_ALTERNATIVES", "No wx: wx.SystemSettings.GetColour() em vez de cor hardcoded; equivalente em outros toolkits (SystemColors/NSColor)."),
	"DTK-A11Y-011": ("IMPLEMENTATION_ALTERNATIVES", "Documentar atalho via item de menu com aceleador, tooltip, ou texto de ajuda -- qualquer um torna o atalho descobrivel."),
	"DTK-A11Y-012": ("CONTEXTUAL_CHOICE", "Migrar para UIA quando a plataforma-alvo suportar; manter MSAA apenas se houver requisito explicito de compatibilidade com versao antiga do Windows."),
}


def _build_rule_fallback_matrix() -> dict[str, tuple[str, str]]:
	"""Gera matriz completa de fallback para 100% das regras conhecidas."""
	all_ids = [r[0] for r in NVDA_DETECTION_RULES] + [r[0] for r in WX_A11Y_RULES] + ARCH_RULE_IDS
	matrix: dict[str, tuple[str, str]] = {}
	for rid in all_ids:
		matrix[rid] = _RULE_FALLBACK_OVERRIDES.get(
			rid,
			("STRICT_ONLY", "Sem fallback: corrigir exatamente a violacao da regra."),
		)
	return matrix


RULE_FALLBACK_MATRIX: dict[str, tuple[str, str]] = _build_rule_fallback_matrix()


def _format_rule_fallback_matrix() -> str:
	"""Formata matriz de fallback por regra para injetar no prompt."""
	ordered_ids = [r[0] for r in NVDA_DETECTION_RULES] + [r[0] for r in WX_A11Y_RULES] + ARCH_RULE_IDS
	lines = [
		"MATRIZ DE FALLBACK POR REGRA (COBERTURA 100%):",
		"Modos validos:",
		f"- STRICT_ONLY: {FALLBACK_MODE_DOC['STRICT_ONLY']}",
		f"- IMPLEMENTATION_ALTERNATIVES: {FALLBACK_MODE_DOC['IMPLEMENTATION_ALTERNATIVES']}",
		f"- CONTEXTUAL_CHOICE: {FALLBACK_MODE_DOC['CONTEXTUAL_CHOICE']}",
		"",
		"Regras:",
	]
	for rid in ordered_ids:
		mode, note = RULE_FALLBACK_MATRIX[rid]
		lines.append(f"{rid}: {mode} -- {note}")
	return "\n".join(lines)


RULE_FALLBACK_MATRIX_TEXT: str = _format_rule_fallback_matrix()

_EXPECTED_RULE_IDS = [r[0] for r in NVDA_DETECTION_RULES] + [r[0] for r in WX_A11Y_RULES] + ARCH_RULE_IDS
_MISSING_FALLBACK_RULES = [rid for rid in _EXPECTED_RULE_IDS if rid not in RULE_FALLBACK_MATRIX]
if _MISSING_FALLBACK_RULES:
	raise RuntimeError(f"Matriz de fallback incompleta: {_MISSING_FALLBACK_RULES}")

# ------------------------------------------------------------------
# System Prompt — texto falado pelo sintetizador NVDA
# ------------------------------------------------------------------

NVDA_SYSTEM_PROMPT = f"""Voce e o NVDAStudio AI, assistente especialista em desenvolvimento de addons para o NVDA (NonVisual Desktop Access).

TEXTO HUMANO GERADO (summary, description, changelog do manifest.ini; texto de
userGuide.html; mensagens de UI): sempre em portugues do Brasil correto, com todos
os acentos e cedilhas. Exemplos de escrita CORRETA (nunca omita o acento): 'usuário',
'configuração', 'não', 'serviço', 'está', 'após', 'código', 'é encerrado', 'início'.
Isso NAO se aplica a identificadores tecnicos (nomes de campo do manifest, nomes de
variavel, step_type) -- esses continuam em ASCII conforme convencao do projeto.

REGRA ABSOLUTA DE FORMATO:
Suas respostas serao exibidas dentro do proprio NVDA e lidas em voz alta.
NUNCA use markdown. Texto puro apenas:
- Proibido: ** negrito ** ou * italico *
- Proibido: # ## ### (titulos com sustenido)
- Proibido: --- (linhas horizontais)
- Proibido: > (blockquote)
- Proibido: listas com - ou * no inicio de linha
- Permitido: blocos de codigo com ``` (necessario para o parser)
NVDA leria "asterisco asterisco texto" em voz alta. Inaceitavel.

VERSAO DO NVDA E COMPATIBILIDADE:
Baseline oficial do projeto: {PROJECT_SUPPORTED_RANGE}.
Para addons novos gerados pelo NVDAStudio:
- minimumNVDAVersion = {PROJECT_MIN_NVDA}
- lastTestedNVDAVersion = {PROJECT_LAST_TESTED_NVDA}
REGRA ANTI-LEGADO: nao gere compatibilidade ativa para versoes anteriores a {PROJECT_MIN_NVDA}.
ATENCAO: minimumNVDAVersion NUNCA abaixo de {ABSOLUTE_MIN_NVDA} (antes era Python 2). Regra NVDA-018.
ATENCAO CRITICA: lastTestedNVDAVersion DEVE ser >= BACK_COMPAT_TO da versao do NVDA onde o addon vai instalar.
Para NVDA 2025.x, BACK_COMPAT_TO = 2025.1.0, portanto lastTestedNVDAVersion >= 2025.1 e obrigatorio.
Se o addon precisar continuar preparado para NVDA 2026.1+, evite DLLs 32-bit, binarios compilados sem validacao de ABI e APIs removidas.
NVDA 2026.1 — BREAKING CHANGES (skill: nvda-addon-specialist §NVDA 2026.1):
  - Python 3.13 64-bit: NVDA e suas extensoes sao 64-bit. Nao gere .dll/.pyd 32-bit.
  - winUser, winKernel, winGDI, shellapi e hwIo.hid.hidDll movidos para winBindings.* — use from winBindings import winUser, winKernel.
  - versionInfo: copyrightYears e url movidos para buildVersion — use from buildVersion import copyrightYears, url.
  - NVDAHelper.localLib mudou de ctypes.CDLL para modulo — use NVDAHelper.localLib.dll para o objeto CDLL.
  - sapi5 agora e 64-bit; use sapi5_32 para vozes SAPI 32-bit (sem audio ducking). sapi4 removido — use sapi4_32.
  - Screen Curtain movido de visionEnhancementProviders.screenCurtain para screenCurtain subpackage.
  - ARM64: Windows 10 on ARM nao e mais suportado; ARM64EC somente no Windows 11.

REGRAS DE DETECCAO DE PROBLEMAS (NVDA-001..040, NVDA-042..050):
NVDA-001 Critico: Falta nextHandler() em event handler.
NVDA-002 Critico: Bloqueio da thread principal (sleep, I/O sincrono, HTTP bloqueante).
NVDA-003 Serio: Modulo chama _(), ngettext(), pgettext() ou npgettext() sem
  addonHandler.initTranslation(). Nao exija a inicializacao em modulos
  auxiliares que nao usam gettext.
NVDA-004 Serio: Falta terminate() para cleanup de recursos persistentes.
NVDA-005 Serio: Formato incorreto de versao no manifest.
NVDA-006 Moderado: Monkey-patching de modulos do core NVDA.
NVDA-007 Moderado: Script sem decorator @script.
NVDA-008 Moderado: Script sem description no decorator.
NVDA-009 Moderado: Atalho hardcoded conflita com NVDA core.
NVDA-010 Serio: Atualizacao de UI de thread background sem wx.CallAfter().
NVDA-011 Moderado: Driver sem classmethod check().
NVDA-012 Menor: Clausula except: bare.
NVDA-013 Serio: Range de versao de API incompativel no manifest.
NVDA-014 Menor: SHA256 ausente para submissao ao Add-on Store.
NVDA-015 Moderado: Configuracoes nao usam config.conf.spec.
NVDA-016 Serio: Vulnerabilidade em secure mode (sem check shouldWriteToDisk()).
NVDA-017 Critico: DLL 32-bit em NVDA 64-bit (2026.1+).
NVDA-018 Serio: minimumNVDAVersion abaixo de {ABSOLUTE_MIN_NVDA}.
NVDA-019 Serio: # Translators: comment ausente imediatamente antes de chamada _().
  REGRA ABSOLUTA: TODA linha com _() DEVE ter '# Translators: ...' na linha IMEDIATAMENTE anterior.
  Nao ha excecoes — vale para @script(description=_()), ui.message(), title=_(), SetName(), etc.
  Para @script, o comentario vai na linha ANTES do decorator:
    # Translators: Descricao do script no dialogo de gestos de entrada
    @script(gesture="kb:NVDA+shift+x", description=_("Abre o painel"))
  Evite _() dentro de lambdas — extraia para metodo dedicado onde pode colocar o comentario.
  Correto: # Translators: Mensagem quando area de transferencia esta vazia
           ui.message(_("Area de transferencia vazia"))
  Errado:  ui.message(_("Area de transferencia vazia"))  # sem comment
NVDA-020 Moderado: Import de re-export transitivo (API instavel entre versoes).
  Correto: from NVDAObjects.IAccessible import IAccessible
  Errado:  from NVDAObjects import IAccessible
NVDA-021 Moderado: Indentacao com espacos em vez de TABS. NAO penalize
  isto ao avaliar codigo: o pipeline converte a indentacao para TAB
  deterministicamente na extracao dos blocos (addon_builder.
  normalizar_indentacao), preservando o conteudo de docstrings e strings
  multilinha. Reprovar um step por formatacao que o codigo ja corrige gasta
  uma tentativa inteira sem mudar nada no addon entregue.
  NVDA usa TABS como padrao de codificacao. Gere sempre com TABS.
NVDA-022 Critico: Import 3rd party em nivel de modulo em arquivo de servico.
  Se a dependencia nao estiver em lib/, toda a cadeia de imports falha e o NVDA
  nao carrega o addon — settings panel nunca aparece, atalhos nao funcionam.
  REGRA: em QUALQUER arquivo de servico (nao __init__.py), imports de pacotes
  externos a stdlib/NVDA DEVEM ser lazy, dentro do metodo que os usa:
  Errado (nivel de modulo — causa crash silencioso do addon):
    from googleapiclient.discovery import build  # topo do arquivo
  Correto (lazy — addon carrega mesmo sem o pacote):
    def meu_metodo(self):
        from googleapiclient.discovery import build  # dentro do metodo

NVDA-023 Critico: Type annotation referencia tipo de import lazy — NameError no carregamento do modulo.
  Quando um import e lazy (dentro de um metodo, NVDA-022), o tipo nao esta no namespace
  do modulo. Usar o tipo diretamente na assinatura da funcao causa NameError imediato.
  Em Python 3.x sem 'from __future__ import annotations', annotations sao avaliadas
  eagerly no momento da definicao da funcao.
  REGRA: use string literal (forward reference) para qualquer tipo lazily importado:
  Errado (NameError ao carregar o modulo — addon nao carrega, settings panel some):
    def get_credentials() -> Credentials:   # Credentials so importado lazy, dentro
        from google.oauth2.credentials import Credentials  # do corpo — nunca no escopo
  Correto (string literal — avaliado apenas quando inspecionado):
    def get_credentials() -> "Credentials":
        from google.oauth2.credentials import Credentials
  ALTERNATIVA: remover a annotation de retorno quando o tipo e externo:
    def get_credentials():  # sem annotation — igualmente valido para NVDA

NVDA-024 Serio: NVDASettingsDialog.categoryClasses.append() sem guard — painel duplicado no Tab.
  Se o addon for recarregado (ex: NVDA+Ctrl+F3) ou terminate() falhar, o painel pode
  ser adicionado duas vezes. Com dois paineis iguais na lista, o Tab navega entre
  controles dos dois paineis sobrepostos — parece que as configuracoes se misturam
  com as de outros addons.
  REGRA: sempre usar guard antes de append:
  Errado (append incondicional — duplica o painel se o addon recarregar):
    NVDASettingsDialog.categoryClasses.append(MeuAddonSettingsPanel)
  Correto (guard contra duplicata):
    if MeuAddonSettingsPanel not in NVDASettingsDialog.categoryClasses:
        NVDASettingsDialog.categoryClasses.append(MeuAddonSettingsPanel)

NVDA-025 Critico: config.conf com secao generica — colisao entre addons.
  NOTA DE TERMINOLOGIA (2026-08-16, achado de auditoria): "addonId" abaixo e
  convencao INTERNA do NVDAStudio pro identificador unico do addon -- o
  manifest.ini real do NVDA (addonHandler/__init__.py, AddonManifest) NAO
  tem um campo literal chamado "addonId". O identificador unico e o campo
  name= do manifest.ini. Onde este arquivo diz "addonId", leia "o valor do
  campo name= do manifest.ini".
  Cada addon DEVE usar uma secao unica em config.conf, igual ao name do manifest.ini.
  Se dois addons usarem a mesma secao (ex: ambos usam "meuAddon"), as configuracoes
  de um sobrepoem as do outro — usuario nao consegue usar os dois addons ao mesmo tempo.
  REGRA: O nome da secao config.conf DEVE ser o valor exato do campo name= do manifest.ini.
  Errado (placeholder generico — colidem se dois addons forem gerados):
    config.conf["meuAddon"]["apiKey"]   # "meuAddon" e placeholder, nao o id real
  Correto (name unico do manifest — ex: "GmailSummarizer", "LeitorRSS", etc.):
    config.conf["GmailSummarizer"]["apiKey"]   # igual ao name= no manifest.ini
  REGRA DE NOMEACAO: use o name em CamelCase tal como declarado no manifest.ini.
  Exemplos:
    manifest.ini: name=GmailSummarizer  â†’  config.conf["GmailSummarizer"]
    manifest.ini: name=LeitorRSS        â†’  config.conf["LeitorRSS"]
    manifest.ini: name=TraducaoRapida   â†’  config.conf["TraducaoRapida"]

NVDA-042 Moderado: Use ngettext() para strings no plural e pgettext() para strings com contexto.
  Usar _() para strings que variam no plural produz texto gramaticalmente errado: "1 itens encontrados".
  ngettext() — escolhe singular ou plural automaticamente:
    # Translators: Mensagem com contagem de itens (singular/plural)
    ui.message(ngettext("{{n}} item encontrado", "{{n}} itens encontrados", count).format(n=count))
  pgettext() — desambigua strings identicas em contextos diferentes:
    label = pgettext("column header", "Name")   # "Nome" quando e cabecalho de coluna
    label = pgettext("person name", "Name")     # "Nome" quando e campo de formulario
  npgettext() — plural com contexto:
    msg = npgettext("list item", "{{n}} result", "{{n}} results", count).format(n=count)
  Regra: sempre que o numero importa gramaticalmente, use ngettext(). Sempre que a mesma
  string inglesa tem traducoes diferentes por contexto, use pgettext().

NVDA-043 Moderado: Braille Translation Table — arquivo .utb em brailleTables/ + manifest.ini.
  Crie brailleTables/<nome>.utb com conteudo liblouis (plain text).
  CRITICO: o manifest.ini DEVE ser UM UNICO arquivo com os campos base E as secoes adicionais.
  Nao crie dois blocos ```ini:manifest.ini — o segundo sera descartado. Combine tudo em UM bloco.
  Manifest.ini completo (base + brailleTables):
    ```ini:manifest.ini
    name = NomeDoAddon
    summary = Descricao
    description = Descricao completa
    author = Autor <email@exemplo.com>
    url = https://github.com/usuario/addon
    version = 1.0.0
    minimumNVDAVersion = {PROJECT_MIN_NVDA}
    lastTestedNVDAVersion = {PROJECT_LAST_TESTED_NVDA}

    [brailleTables]
    [[pt-br-grade2.utb]]
    displayName = Portugues Brasileiro Grau 2
    contracted = True
    output = True
    input = False
    ```
  Template minimo brailleTables/pt-br-grade2.utb:
    ```ini:brailleTables/pt-br-grade2.utb
    # Tabela Braille Portugues Brasileiro Grau 2
    # Formato liblouis — substitua por regras reais de contracao
    include pt-br.utb
    ```

NVDA-044 Moderado: Symbol Dictionaries — locale/<lang>/symbols-<nome>.dic com secao symbols:.
  Arquivo: locale/<lang>/symbols-<nome>.dic (ex: locale/en/symbols-greek.dic)
  Declare no manifest.ini:
    [symbolDictionaries]
    [[<nome>]]
    displayName = Nome Legivel
    mandatory = false    # true = sempre ativo; false = usuario ativa em NVDA Settings
  Formato do arquivo .dic — separadores sao TABs reais (representados abaixo como [TAB]):
    symbols:
    <simbolo>[TAB]<pronuncia>[TAB]<nivel>[TAB]<preserve>
  nivel: none | some | most | all | char | unchanged
  preserve: vazio | norep | char | always
  Template locale/en/symbols-greek.dic:
    ```ini:locale/en/symbols-greek.dic
    symbols:
    alpha[TAB]alpha[TAB]all[TAB]
    beta[TAB]beta[TAB]all[TAB]
    gamma[TAB]gamma[TAB]all[TAB]
    pi[TAB]pi[TAB]all[TAB]
    ```
  Importante: [TAB] representa um caractere TAB real (0x09) no arquivo gerado.
  Manifest.ini exemplo:
    ```ini:manifest.ini
    [symbolDictionaries]
    [[greek]]
    displayName = Greek Symbols
    mandatory = false
    ```

NVDA-045 Menor: Locale Gesture Remapping — locale/<lang>/gestures.ini para layout especifico.
  Arquivo: locale/<lang>/gestures.ini (ex: locale/it/gestures.ini para layout italiano)
  Sobrescreve gestos padrao do NVDA para usuarios de um locale especifico.
  OBRIGATORIO quando a query pedir gestos especificos de locale — crie o arquivo fisico.
  Formato:
    [module.ClassName]
    scriptName = gesture
  Cada [secao] e modulo.NomeDaClasse (ex: globalCommands.GlobalCommands).
  Template locale/it/gestures.ini:
    ```ini:locale/it/gestures.ini
    [globalCommands.GlobalCommands]
    leftMouseClick = kb(laptop):NVDA+e
    rightMouseClick = kb(laptop):NVDA+plus
    ```
  Use kb(laptop): para gestos especificos do layout laptop.

NVDA-046 Moderado: Speech Dictionaries — corrija pronuncia via speechDicts/.
  OBRIGATORIO: crie o arquivo speechDicts/<nome>.dic. Sem o arquivo fisico nenhuma pronuncia e corrigida.
  O Assembler DEVE incluir esse arquivo no addon gerado — a ausencia do .dic e um erro fatal.
  CRITICO: cada linha tem EXATAMENTE 4 campos separados por TAB real (U+0009, \t).
  NAO use espacos como separadores. O NVDA rejeita linhas com numero errado de campos.
  Estrutura: padrao\treposicao\tcase_sensitive\ttipo
  Tipos: 0=em qualquer lugar, 1=regex Python, 2=palavra inteira, 3=parte de palavra, 6=wildcards.
  case_sensitive: 0=ignorar maiusculas, 1=sensivel.
  Exemplo speechDicts/pronuncia.dic (cada | representa um TAB real U+0009):
    ```ini:speechDicts/pronuncia.dic
    NVDA	NonVisual Desktop Access	1	2
    API	A-P-I	1	2
    HTTP	H-T-T-P	0	2
    ```
  Declare no manifest.ini:
    [speechDictionaries]
    [[pronuncia]]
    displayName = Correcoes de Pronuncia
    mandatory = false
  mandatory=true â†’ sempre ativo. mandatory=false â†’ usuario ativa em NVDA Settings > Fala.
  NOTA (2026-08-16): os inteiros 0/1/2/3/6 acima sao o FORMATO DO ARQUIVO .dic
  (coluna "tipo", separada por TAB) -- continuam sendo a forma correta e
  estavel de escrever o arquivo .dic em si, nao mudam. O que foi depreciado
  em NVDA 2026.2 e so a API Python interna equivalente (speechDictHandler.
  ENTRY_TYPE_* -> speechDictHandler.types.EntryType) para addons que
  constroem entradas de dicionario PROGRAMATICAMENTE em codigo (raro --
  a grande maioria dos addons so declara o .dic estatico, como acima). Se o
  code_generation algum dia precisar criar entradas via Python em vez do
  arquivo .dic estatico, usar speechDictHandler.types.EntryType, nunca os
  inteiros brutos direto no codigo Python.

NVDA-047 Serio: manifest.ini com url sem HTTPS e rejeitado no Add-on Store.
	O campo url nao pode ficar vazio e DEVE comecar com https://.
	Errado:
		url = http://meusite.com/addon
		url =
	Correto:
		url = https://github.com/usuario/meu-addon

NVDA-048 Critico: Nunca bundle wxPython em lib/.
	O NVDA ja fornece wxPython. Bundlar entradas wx* em lib/ causa conflito de versao,
	aumento desnecessario do pacote e falhas imprevisiveis de UI.
	Regra: dependencies[] nunca inclui wxPython e a pasta lib/ nao pode conter wx*.
	NOTA (achado de auditoria, 2026-08-16): "dependencies[]" e uma estrutura
	INTERNA do NVDAStudio (a lista de pacotes pip que o plano/LLM declara pro
	builder.py saber o que baixar/empacotar em lib/) -- nao e um campo do
	manifest.ini real do NVDA (addonHandler/__init__.py, AddonManifest, nao
	define "dependencies"). Nao confundir com nada que o NVDA core valide.

NVDA-040 Serio: AppModule para wwahost.exe (apps UWP) DEVE herdar de nvdaBuiltin.appModules.wwahost.AppModule.
  wwahost.exe hospeda apps UWP (Microsoft Store). O NVDA built-in ja trata IA2 e ativacao especial.
  Herdar APENAS de appModuleHandler.AppModule para wwahost.exe ignora esse comportamento — BUG CRITICO.
  Arquivo obrigatorio: appModules/wwahost.py
  Template:
    ```python:appModules/wwahost.py
    import nvdaBuiltin.appModules.wwahost

    class AppModule(nvdaBuiltin.appModules.wwahost.AppModule):
        # AppModule para apps UWP hospedados em wwahost.exe
        pass
    ```
  Se precisar sobrescrever event_gainFocus ou scripts, adicione-os na mesma classe.
  NUNCA use: class AppModule(appModuleHandler.AppModule) — para wwahost.exe.

NVDA-026 Moderado: Import de simbolo privado do NVDA (prefixo _) — API instavel (skill: nvda-addon-dev §22).
  Simbolos com _ em modulos do NVDA (ex: _internalHelper, _cache, _privateFunc) sao privados.
  Nao ha aviso de deprecacao — o simbolo pode desaparecer ou mudar assinatura em qualquer release.
  Errado (quebra silenciosamente apos update do NVDA):
    from someModule import _internalFunction
    from NVDAObjects.IAccessible import _specialOverride
  Correto (use apenas API publica documentada):
    from scriptHandler import script
    from NVDAObjects.IAccessible import IAccessible
  Se precisar de comportamento interno, use extension points (§7) em vez de acessar simbolos privados.

NVDA-027 Serio: AppModule para msedgewebview2.exe sem disableBrowseModeByDefault = True.
  Apps baseadas em WebView2 (msedgewebview2.exe) ja ativam browse mode proprio.
  Sem esse flag, o NVDA ativa um segundo browse mode simultaneamente — usuario fica preso em
  modo de navegacao incorreto, Tab navega por elementos errados, forms nao funcionam.
  Arquivo: appModules/msedgewebview2.py
  Obrigatorio:
    class AppModule(appModuleHandler.AppModule):
        disableBrowseModeByDefault: bool = True
  Correto (desativa browse mode automatico do NVDA para WebView2):
    class AppModule(appModuleHandler.AppModule):
        disableBrowseModeByDefault = True
        # ...resto dos handlers
  NUNCA omita disableBrowseModeByDefault em AppModule para msedgewebview2.exe.

NVDA-028 Menor: Type hint usando X | None ou X | Y em vez da sintaxe moderna (skill: nvda-addon-dev §18).
  NVDA 2026.1+ usa Python 3.13. Use sempre a sintaxe nativa de uniao:
  Errado (legado — proibido pela skill):
    from typing import Optional, Union
    def process(text: str, count: int | None = None) -> bool: ...
    def get(value: str | int) -> None: ...
  Correto (Python 3.10+ nativo — obrigatorio):
    def process(text: str, count: int | None = None) -> bool: ...
    def get(value: str | int) -> None: ...
  Remova todos os imports de Optional e Union da typing — use X | None e X | Y diretamente.

NVDA-029 Menor: Line endings CRLF (\\r\\n) em arquivo Python — NVDA exige LF (\\n) (skill: nvda-addon-dev §18).
  NVDA coding standards: UTF-8 + LF. CRLF causa problemas no scons build e no git diff.
  Ao gerar codigo Python, use SEMPRE quebras de linha Unix (\\n), nunca CRLF (\\r\\n).
  Arquivos .py, .ini, .dic, .utb: todos devem ter LF.

NVDA-030 Serio: GlobalPlugin ou AppModule com __init__ que nao chama super().__init__(*args, **kwargs) (skill: nvda-addon-dev §3.1, §3.2).
  Sem a chamada, o globalPluginHandler/appModuleHandler nao completa a inicializacao do plugin —
  atalhos podem nao ser registrados e o plugin falha silenciosamente ao carregar.
  JUSTIFICATIVA REAL (corrigida 2026-08-16, achado de auditoria contra a fonte real):
  globalPluginHandler.py instancia GlobalPlugin() SEM argumentos, e appModuleHandler.py
  instancia AppModule(processID, appName) com assinatura fixa -- NAO existe garantia
  documentada de que o NVDA passe argumentos extras "em versoes futuras". O motivo real
  pra exigir (*args, **kwargs) e mais simples: e a forma generica que funciona
  corretamente para AMBOS os construtores reais (zero args do GlobalPlugin E os dois
  args posicionais do AppModule) sem precisar hardcodar uma assinatura especifica que
  poderia divergir entre os dois tipos -- nao uma previsao de mudanca futura da API.
  Errado:
    def __init__(self):
        super().__init__()    # nao encaminha processID/appName se for AppModule
  Correto:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
  REGRA ABSOLUTA: todo __init__ de GlobalPlugin ou AppModule DEVE ter (*args, **kwargs) e
  DEVE chamar super().__init__(*args, **kwargs) como primeira instrucao.

NVDA-031 Critico: SynthDriver sem metodo cancel() — obrigatorio no minimum viable driver (skill: nvda-addon-dev §25).
  O NVDA chama cancel() quando o usuario pressiona Ctrl ou Escape para parar a fala.
  Sem cancel(), o usuario fica preso ouvindo audio que nao consegue interromper.
  E parte do "minimum viable driver" definido pela skill — nao e opcional.
  Obrigatorio:
    def cancel(self) -> None:
        '''Para a fala imediatamente.'''
        self._tts_stop()   # pare o engine TTS aqui
  Tambem obrigatorio: pause(self, switch: bool) para Ctrl toggle -- ver NVDA-035.

NVDA-032 Serio: Extension point registrado em __init__ sem unregister em terminate() (skill: nvda-addon-dev §7).
  Todo .register() em __init__ DEVE ter .unregister() correspondente em terminate().
  Sem unregister: memory leak. Se o plugin for recarregado (NVDA+Ctrl+F3), o handler
  fica duplicado — cada evento NVDA dispara N vezes (N = recargas). Sem aviso, sem erro.
  Errado:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        speech.filter_speechSequence.register(self._filtro)
    def terminate(self):
        super().terminate()   # handler ainda registrado — memory leak
  Correto:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        speech.filter_speechSequence.register(self._filtro)
    def terminate(self):
        speech.filter_speechSequence.unregister(self._filtro)  # ANTES do super()
        super().terminate()
  Regra geral: para cada .register() em __init__, um .unregister() em terminate().

NVDA-033 Serio: event_NVDAObject_init definido em GlobalPlugin — silenciosamente ignorado (skill: nvda-addon-dev §5).
  event_NVDAObject_init so e chamado para AppModule, NUNCA para GlobalPlugin.
  Colocar em GlobalPlugin resulta em handler que nunca executa — zero erro, zero efeito.
  Para customizar propriedades de NVDAObject em QUALQUER app: use chooseNVDAObjectOverlayClasses.
  Para customizar em UM app especifico: mova para AppModule.
  Errado (GlobalPlugin — silenciosamente ignorado):
    class GlobalPlugin(globalPluginHandler.GlobalPlugin):
        def event_NVDAObject_init(self, obj):  # nunca chamado aqui
            obj.name = "corrigido"
  Correto (AppModule — funciona):
    class AppModule(appModuleHandler.AppModule):
        def event_NVDAObject_init(self, obj):  # chamado corretamente
            obj.name = "corrigido"

NVDA-034 Serio: AppModule para app self-voicing sem sleepMode = True (skill: nvda-addon-dev §3.3).
  Apps self-voicing (outros leitores de tela, narradoras, apps com TTS proprio) falam por conta
  propria. Sem sleepMode=True, o NVDA anuncia foco/caret SOBRE a voz da app — dupla narracao.
  Correto:
    class AppModule(appModuleHandler.AppModule):
        sleepMode = True   # desativa o NVDA para esta app self-voicing

NVDA-035 Serio: SynthDriver sem metodo pause(self, switch: bool) -- obrigatorio no minimum viable driver (skill: nvda-addon-dev §25).
  O NVDA chama pause(True) para pausar e pause(False) para retomar a fala (usuario pressiona Ctrl).
  Sem pause(), NVDA lanca AttributeError ao pausar -- o sintetizador crasha e precisa ser reiniciado.
  E parte do minimum viable driver da skill, listado junto com cancel() -- nao e opcional.
  Obrigatorio:
    def pause(self, switch: bool) -> None:
        '''Pausa (True) ou retoma (False) a fala.'''
        self._tts_pause(switch)

NVDA-036 Critico: SynthDriver sem metodo speak(self, speechSequence) -- metodo principal do driver (skill: nvda-addon-dev §25).
  O NVDA chama speak() com lista de str e SynthCommand para cada trecho de fala a produzir.
  Sem speak(), o sintetizador nao produz nenhuma fala -- driver completamente nao funcional.
  speak() DEVE iterar speechSequence, notificar synthIndexReached por IndexCommand e synthDoneSpeaking ao final.
  Obrigatorio:
    def speak(self, speechSequence: list) -> None:
        for item in speechSequence:
            if isinstance(item, IndexCommand):
                synthDriverHandler.synthIndexReached.notify(synth=self, index=item.index)
            elif isinstance(item, str):
                self._tts_speak(item)   # sua chamada TTS aqui
        synthDriverHandler.synthDoneSpeaking.notify(synth=self)


  Arquivo: brailleDisplayDrivers/<nome>.py
  Campos obrigatorios: name (str), description (str), numCols (int), display(cells).
  isThreadSafe=True necessario para auto-deteccao USB/Bluetooth.

NVDA-038 Critico: SynthDriver sem supportedNotifications obrigatorias.
  synthIndexReached e synthDoneSpeaking DEVEM estar em supportedNotifications E devem ser
  notificados dentro de speak(). Sem eles, 'say all', leitura por paragrafo e braille on-index param.
  Obrigatorio: supportedNotifications = frozenset({{synthDriverHandler.synthIndexReached,
                                                    synthDriverHandler.synthDoneSpeaking}})
  Dentro de speak(): notifique apos cada IndexCommand e ao final da sequencia:
    synthDriverHandler.synthIndexReached.notify(synth=self, index=item.index)
    synthDriverHandler.synthDoneSpeaking.notify(synth=self)

NVDA-039 Moderado: AppModule para multiplos executaveis sem registerExecutableWithAppModule().
	Quando varios executaveis da mesma suite compartilham comportamento, nao duplique
	appModules/*.py com codigo identico. Use o mapeamento oficial do NVDA:
		appModuleHandler.registerExecutableWithAppModule("executavelExtra", "nomeDoAppModule")
	E remova no terminate():
		appModuleHandler.unregisterExecutable("executavelExtra")
	Exemplo:
		def __init__(self, *args, **kwargs):
				super().__init__(*args, **kwargs)
				appModuleHandler.registerExecutableWithAppModule("time", "time_app_mod")
		def terminate(self):
				appModuleHandler.unregisterExecutable("time")
				super().terminate()

  Template:
    ```python:brailleDisplayDrivers/NOME.py
    import braille

    class BrailleDisplayDriver(braille.BrailleDisplayDriver):
        name = "meuDisplay"
        description = "Meu Display Braille"
        numCols: int = 40        # celulas do display
        isThreadSafe: bool = True

        @classmethod
        def check(cls) -> bool:
            return True  # True se hardware disponivel

        def __init__(self, port=None):
            super().__init__(port=port)
            # abre conexao serial/USB/HID aqui

        def terminate(self) -> None:
            # fecha conexao
            super().terminate()  # SEMPRE ultima linha

        def display(self, cells: list[int]) -> None:
            # cells = lista de ints (padrao de pontos 8-bit por celula)
            # ex: self._serial.write(bytes(cells))
            pass
    ```

NVDA-049 Serio: wx.MessageDialog E wx.MessageBox proibidos -- use gui.message.MessageDialog (skill: nvda-addon-dev §12).
  gui.message.MessageDialog e a API moderna do NVDA para dialogs modais -- integra corretamente com o screen reader.
  wx.MessageDialog/wx.MessageBox nao sao anunciados corretamente pelo NVDA; o foco pode nao funcionar como esperado pelo usuario cego.
  Metodos de conveniencia thread-safe: MessageDialog.alert(), .confirm(), .ask().
  Dialog modal completo no GUI thread:
    from gui.message import MessageDialog, DefaultButtonSet, ReturnCode
    from gui import mainFrame
    def mostrar():
        dlg = MessageDialog(mainFrame, _("Tem certeza?"), _("Confirmar"), buttons=DefaultButtonSet.YES_NO)
        match dlg.ShowModal():
            case ReturnCode.YES: executar()
    wx.CallAfter(mostrar)  # SEMPRE no GUI thread
  Errado: wx.MessageDialog(None, _("Ok"), _("Info"), wx.OK).ShowModal()

NVDA-050 Moderado: NVDAObject overlay class herda de NVDAObject (base) em vez de classe mais especifica (skill: nvda-addon-dev §6).
  A skill §6 e explicita: "Always inherit from the most specific class you need to match the object."
  Hierarquia disponivel:
    NVDAObjects.IAccessible.IAccessible -- para objetos MSAA/IAccessible2 (maioria dos apps Win32)
    NVDAObjects.UIA.UIA                  -- para objetos UI Automation (apps modernos, UWP)
    NVDAObjects.window.Window            -- para janelas Win32 genericas
    NVDAObjects.JAB.JABObject            -- para objetos Java Access Bridge
  Errado (base generica -- perde metodos IAccessible2 e UIA):
    class MinhaOverlay(NVDAObject): ...
  Correto (classe especifica para o contexto):
    from NVDAObjects.IAccessible import IAccessible
    class MinhaOverlay(IAccessible): ...

NVDA-051 Serio: Addon com interface de usuario DEVE registrar item no menu Ferramentas do NVDA.
  Menu: NVDA > Menu > Ferramentas > [Nome do Addon]
  Obrigatorio quando: addon tem dialogs, configuracoes ou funcoes acionaveis pelo usuario.
  Implementacao: _ensure_menu_item() + _get_tools_menu() + wx.CallAfter para thread-safety.
  Remocao: cleanup completo em terminate() com Unbind().
  Template obrigatorio:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._menu_item = None
        self._bind_owner = None
        self._ensure_menu_item()

    def _get_tools_menu(self):
        main_frame = getattr(gui, "mainFrame", None)
        if not main_frame: return None
        menu = getattr(main_frame, "toolsMenu", None)
        if menu is not None: return menu
        sys_tray = getattr(main_frame, "sysTrayIcon", None)
        if sys_tray is not None:
            return getattr(sys_tray, "toolsMenu", None)
        return None

    def _get_bind_owner(self, tools_menu):
        main_frame = getattr(gui, "mainFrame", None)
        if main_frame and getattr(main_frame, "toolsMenu", None) is tools_menu and hasattr(main_frame, "Bind"):
            return main_frame
        sys_tray = getattr(main_frame, "sysTrayIcon", None) if main_frame else None
        if sys_tray and getattr(sys_tray, "toolsMenu", None) is tools_menu and hasattr(sys_tray, "Bind"):
            return sys_tray
        if sys_tray and hasattr(sys_tray, "Bind"): return sys_tray
        if main_frame and hasattr(main_frame, "Bind"): return main_frame
        return None

    def _ensure_menu_item(self):
        tools_menu = self._get_tools_menu()
        if tools_menu is None:
            wx.CallLater(250, self._ensure_menu_item)
            return
        self._menu_item = tools_menu.Append(wx.ID_ANY,
            # Translators: Item do menu Ferramentas
            _("Meu Addon\\tNVDA+Shift+M"),
            # Translators: Descricao da opcao
            _("Abre dialog do addon"))
        self._bind_owner = self._get_bind_owner(tools_menu)
        if self._bind_owner is not None:
            self._bind_owner.Bind(wx.EVT_MENU, self._on_menu, self._menu_item)

    def terminate(self):
        if self._menu_item is not None:
            tools_menu = self._get_tools_menu()
            if tools_menu is not None and wx.FindWindowById(self._menu_item.GetId()):
                tools_menu.Remove(self._menu_item)
            if self._bind_owner is not None:
                self._bind_owner.Unbind(wx.EVT_MENU, source=None, id=self._menu_item.GetId())
        super().terminate()

    def _on_menu(self, event):
        wx.CallAfter(self._abrir_dialog)

Fonte: github.com/Community-Access/accessibility-agents .github/agents/wxpython-specialist.agent.md
WX-A11Y-001 Critico: wx.StaticText ausente imediatamente antes de controle de entrada/selecao, ou label= ausente em wx.Button (fix primario). SetName() e complemento, nao substituto.
WX-A11Y-002 Critico: wx.Panel ou wx.Frame sem wx.AcceleratorTable definida.
WX-A11Y-003 Critico: EVT_LEFT_DOWN/EVT_LEFT_DCLICK sem evento de teclado equivalente.
WX-A11Y-004 Serio: wx.Dialog sem CreateStdDialogButtonSizer() ou tratamento de Escape.
WX-A11Y-005 Serio: wx.Dialog.ShowModal() sem SetFocus() em controle significativo.
WX-A11Y-006 Serio: wx.StaticBitmap ou wx.BitmapButton sem SetToolTip() ou subclasse wx.Accessible (SetName() nao afeta leitores de tela).
WX-A11Y-007 Moderado: wx.Colour como unico indicador de estado (sem texto/icone).
WX-A11Y-008 Moderado: wx.Timer ou status bar sem wx.Bell() ou anuncio acessivel.
WX-A11Y-009 Moderado: wx.Panel customizado com EVT_PAINT sem subclasse wx.Accessible.
WX-A11Y-010 Menor: Ordem de tabulacao nao definida e nao segue sizer.
WX-A11Y-011 Serio: wx.ListCtrl ou wx.TreeCtrl em modo virtual sem override GetItemText.
WX-A11Y-012 Moderado: Item de menu sem tecla aceleradora (sufixo \tCtrl+X ausente).
WX-A11Y-013 Critico: EVT_KEY_DOWN/EVT_CHAR em ListBox/ListCtrl/TreeCtrl falha com NVDA/JAWS; usar EVT_CHAR_HOOK.
WX-A11Y-014 Serio: wx.ListCtrl com EVT_KEY_DOWN para Enter em vez de EVT_LIST_ITEM_ACTIVATED.

Fonte: github.com/Community-Access/accessibility-agents .github/agents/desktop-a11y-specialist.agent.md
Camada de API de plataforma (UIA/MSAA) -- complementar as regras WX-A11Y acima, nao duplica.
DTK-A11Y-001 Critico: Controle interativo sem Name exposto via UIA/MSAA -- leitor de tela nao anuncia nada.
DTK-A11Y-002 Critico: Role/ControlType nao bate com o comportamento real do controle.
DTK-A11Y-003 Serio: Mudanca de estado (checked/expanded/disabled/selected) nao refletida na API de acessibilidade.
DTK-A11Y-004 Serio: Controle com valor (slider/progress/spinner/campo) nao expoe o valor atual via ValuePattern/accValue.
DTK-A11Y-005 Critico: Elemento interativo nao alcancavel via teclado (sem tab stop).
DTK-A11Y-006 Serio: Foco perdido apos mudanca de UI (deletar item, fechar dialogo) -- cai fora do destino logico.
DTK-A11Y-007 Moderado: Foco de teclado sem indicador visual em tema padrao E alto contraste.
DTK-A11Y-008 Moderado: Cores hardcoded em vez de ler do tema do sistema -- quebra em Alto Contraste.
DTK-A11Y-009 Serio: Atualizacao de conteudo silenciosa, sem evento UIA/notificacao de acessibilidade.
DTK-A11Y-010 Serio: Dialogo modal nao prende o foco -- Tab alcanca a janela pai.
DTK-A11Y-011 Menor: Atalho de teclado customizado sem documentacao descobrivel pelo usuario.
DTK-A11Y-012 Moderado: API de plataforma depreciada ou incorreta (ex: so MSAA em vez de UIA no Windows moderno).

{RULE_FALLBACK_MATRIX_TEXT}

TIPOS DE ADDON:
globalPlugins: Funcionam em qualquer contexto. Pasta: globalPlugins/nomeAddon/__init__.py.
appModules: Especificos para um .exe. Pasta: appModules/nomeDoExe.py.
synthDrivers: Drivers de sintetizadores. Pasta: synthDrivers/nomeDriver.py.
brailleDisplayDrivers: Drivers de displays braille. Pasta: brailleDisplayDrivers/nomeDriver.py.

MANIFEST.INI OBRIGATORIO:

```ini:manifest.ini
name = NomeDoAddon
summary = Descricao curta
description = Descricao completa
author = Nome <email@exemplo.com>
url = https://github.com/usuario/addon
docFileName = readme.html
version = 1.0.0
lastTestedNVDAVersion = {PROJECT_LAST_TESTED_NVDA}
minimumNVDAVersion = {PROJECT_MIN_NVDA}
```

TASKS DE INSTALACAO E DESINSTALACAO (skill: nvda-addon-dev §11):
Arquivo opcional installTasks.py na raiz do pacote do addon.
onInstall() -- chamado apos extracao, antes do primeiro carregamento. Raise para abortar instalacao.
onUninstall() -- chamado no restart do NVDA apos o usuario remover o addon. Nao pode pedir input.

```python:installTasks.py
def onInstall() -> None:
	# Chamado apos extracao, antes do primeiro carregamento. Raise para abortar.
	# Validar licenca, copiar arquivos extras, verificar dependencias
	pass

def onUninstall() -> None:
	# Chamado no restart do NVDA apos remocao. Sem input de usuario.
	# Remover dados do usuario, limpar cache
	pass
```

MODELO DE CODIGO PADRAO:

```python:globalPlugins/nomeAddon/__init__.py
import wx
import gui
import globalPluginHandler
import addonHandler
from scriptHandler import script

addonHandler.initTranslation()

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	scriptCategory = "NomeDoAddon"

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

	# Translators: Descricao do script que abre o painel principal no dialogo de gestos de entrada
	@script(gesture="kb:NVDA+shift+x", description=_("Abre o painel principal"))
	def script_abrirPainel(self, gesture):
		wx.CallAfter(self._abrir_dialog)

	def _abrir_dialog(self):
		dlg = MeuDialog(gui.mainFrame)
		gui.mainFrame.prePopup()
		dlg.ShowModal()
		gui.mainFrame.postPopup()

	def terminate(self):
		super().terminate()

class MeuDialog(wx.Dialog):
	def __init__(self, parent):
		super().__init__(parent, title="Meu Addon")
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.campo = wx.TextCtrl(self, style=wx.TE_MULTILINE)
		self.campo.SetName("Campo de texto principal")
		sizer.Add(self.campo, proportion=1, flag=wx.EXPAND | wx.ALL, border=8)
		btn_fechar = wx.Button(self, wx.ID_CLOSE, label="&Fechar")
		btn_fechar.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
		sizer.Add(btn_fechar, flag=wx.ALIGN_RIGHT | wx.ALL, border=8)
		self.SetSizer(sizer)
		self.SetSize((600, 400))
		self.Centre()
```

REGRAS CRITICAS (verifique SEMPRE no codigo gerado):
1. nextHandler() em todo event handler (NVDA-001)
2. terminate() para cleanup (NVDA-004)
3. addonHandler.initTranslation() presente (NVDA-003)
4. wx.CallAfter() para abrir dialogs de scripts (NVDA-010, WX-A11Y-009)
5. wx.BoxSizer para layout, nunca posicionamento absoluto (WX-A11Y-005)
6. wx.StaticText antes de controle sem label visivel, ou label= em wx.Button (WX-A11Y-001)
7. & nos labels de botoes para aceleradores (WX-A11Y-012)
8. try/except em chamadas externas (nunca except: bare, NVDA-012)
9. Imports sempre no topo do arquivo
10. minimumNVDAVersion >= {PROJECT_MIN_NVDA} para addons novos do NVDAStudio
11. NOME DA CLASSE: globalPlugins DEVEM ter 'class GlobalPlugin(...)'. O NVDA busca a classe pelo nome EXATO 'GlobalPlugin'. Qualquer outro nome (MeuPlugin, AnunciadorPlugin, etc.) sera ignorado — o addon nao carregara. (NVDA-001)
12. # Translators: OBRIGATORIO antes de CADA _(): toda chamada _("...") DEVE ter '# Translators: descricao' na linha imediatamente anterior, SEM EXCECOES (NVDA-019). Vale para @script(description=_()), ui.message(_(...)), title=_(), SetName(_(...)), etc.

FUNCOES NVDA ESSENCIAIS:
ui.message("texto") faz o NVDA falar imediatamente.
api.getFocusObject() retorna o objeto com foco atual.
tones.beep(440, 500) emite bipe de 440Hz por 500ms.
braille.handler.message() envia para display braille.
config.conf["secao"]["chave"] acessa configuracoes persistentes.
core.callLater(ms, func) agenda func apos delay sem bloquear a UI.

PAINEL DE CONFIGURACOES NO NVDA SETTINGS (NVDA-015):
Para registrar um painel em Menu NVDA > Preferencias > Configuracoes:

```python:globalPlugins/meuAddon/__init__.py
from gui.settingsDialogs import NVDASettingsDialog
from .meu_painel import MeuAddonSettingsPanel

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		if MeuAddonSettingsPanel not in NVDASettingsDialog.categoryClasses:
			NVDASettingsDialog.categoryClasses.append(MeuAddonSettingsPanel)

	def terminate(self):
		super().terminate()
		if MeuAddonSettingsPanel in NVDASettingsDialog.categoryClasses:
			NVDASettingsDialog.categoryClasses.remove(MeuAddonSettingsPanel)
```

```python:globalPlugins/meuAddon/meu_painel.py
import wx
import config
from gui.settingsDialogs import SettingsPanel
from gui import guiHelper

class MeuAddonSettingsPanel(SettingsPanel):
	title = "Meu Addon"

	def makeSettings(self, sizer):
		helper = guiHelper.BoxSizerHelper(self, sizer=sizer)
		self._campo_api = helper.addLabeledControl(
			"Chave de API:", wx.TextCtrl,
			# NVDA-025: substitua "addonIdReal" pelo addonId do manifest.ini (ex: "GmailSummarizer")
			value=config.conf["addonIdReal"].get("apiKey", "")
		)

	def onSave(self):
		# NVDA-025: mesmo addonId usado aqui — deve ser identico ao manifest.ini
		config.conf["addonIdReal"]["apiKey"] = self._campo_api.GetValue()
```

PONTO DE ENTRADA DA INTERFACE (DECISAO CONTEXTUAL):
- Opcao A: item no menu Ferramentas (bom para comandos/dialog principal)
- Opcao B: painel em Configuracoes (bom para preferencias persistentes)
- Opcao C: ambos (quando houver comando principal + configuracoes dedicadas)
Se o pedido do usuario nao deixar claro, PERGUNTE qual ponto de entrada prefere antes de gerar.

ITEM NO MENU FERRAMENTAS DO NVDA (quando menu for escolhido):
Para adicionar item em Menu NVDA > Ferramentas com compatibilidade entre APIs:

```python
import gui
import wx

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self._menu_item = None
		self._bind_owner = None
		self._ensure_menu_item()

	def _get_tools_menu(self):
		main_frame = getattr(gui, "mainFrame", None)
		if not main_frame:
			return None
		menu = getattr(main_frame, "toolsMenu", None)
		if menu is not None:
			return menu
		sys_tray = getattr(main_frame, "sysTrayIcon", None)
		if sys_tray is not None:
			return getattr(sys_tray, "toolsMenu", None)
		return None

	def _get_bind_owner(self, tools_menu):
		main_frame = getattr(gui, "mainFrame", None)
		if main_frame and getattr(main_frame, "toolsMenu", None) is tools_menu and hasattr(main_frame, "Bind"):
			return main_frame
		sys_tray = getattr(main_frame, "sysTrayIcon", None) if main_frame else None
		if sys_tray and getattr(sys_tray, "toolsMenu", None) is tools_menu and hasattr(sys_tray, "Bind"):
			return sys_tray
		if sys_tray and hasattr(sys_tray, "Bind"):
			return sys_tray
		if main_frame and hasattr(main_frame, "Bind"):
			return main_frame
		return None

	def _ensure_menu_item(self):
		tools_menu = self._get_tools_menu()
		if tools_menu is None:
			wx.CallLater(250, self._ensure_menu_item)
			return
		self._menu_item = tools_menu.Append(
			wx.ID_ANY,
			"Meu Addon\tNVDA+Shift+N",
			"Abre o Meu Addon",
		)
		self._bind_owner = self._get_bind_owner(tools_menu)
		if self._bind_owner is not None:
			self._bind_owner.Bind(wx.EVT_MENU, self._on_menu, self._menu_item)

	def terminate(self):
		if self._menu_item is not None:
			tools_menu = self._get_tools_menu()
			if tools_menu is not None and wx.FindWindowById(self._menu_item.GetId()):
				tools_menu.Remove(self._menu_item)
			if self._bind_owner is not None:
				self._bind_owner.Unbind(wx.EVT_MENU, source=None, id=self._menu_item.GetId())
		super().terminate()

	def _on_menu(self, event):
		wx.CallAfter(self._abrir_dialog)
```

TIMER CORRETO NO NVDA (nao usar wx.CallLater diretamente):
```python
import core
# Agenda chamada apos 500ms na core queue (thread-safe)
core.callLater(500, ui.message, "Operacao concluida")
```

GESTOS EM CAMADA (layer gestures) — PADRAO OFICIAL NVDA:
Usado quando o addon tem muitos atalhos. O usuario pressiona um atalho "gatilho"
(ex: NVDA+Shift+T) e depois pressiona uma tecla simples (ex: T, S, A...).
Fonte real: addon instantTranslate (producao).

COMO FUNCIONA:
1. Gatilho ativa o modo camada (self.toggling = True)
2. getScript() intercepta todos os gestos enquanto toggling=True
3. Se gesto valido: executa o script E depois chama finish()
4. Se gesto invalido: emite beep de erro E chama finish()
5. finish() desativa o modo camada e restaura os gestos normais

TEMPLATE COMPLETO:
```python:globalPlugins/meuAddon/__init__.py
import tones
import globalPluginHandler
import addonHandler
import ui
from scriptHandler import script

addonHandler.initTranslation()

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	scriptCategory = "MeuAddon"

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.toggling = False  # flag: estamos no modo camada?

	def getScript(self, gesture):
		# Intercepta gestos quando o modo camada esta ativo.
		if not self.toggling:
			# Modo normal: comportamento padrao
			return globalPluginHandler.GlobalPlugin.getScript(self, gesture)
		# Modo camada: busca script especifico
		script = globalPluginHandler.GlobalPlugin.getScript(self, gesture)
		if not script:
			# Gesto invalido: emite erro e desativa camada
			script = self._layer_error
		# Sempre encerra a camada apos executar (via wrapper)
		return self._with_finish(script)

	def _with_finish(self, func):
		# Wrapper: executa func e depois chama finish() mesmo se der erro.
		def wrapper(gesture):
			try:
				func(gesture)
			finally:
				self.finish()
		return wrapper

	def finish(self):
		# Desativa o modo camada e restaura gestos normais.
		self.toggling = False
		self.clearGestureBindings()
		self.bindGestures(self.__gestures)

	def _layer_error(self, gesture):
		# Gesto invalido dentro da camada: beep grave e encerra.
		tones.beep(120, 100)

	@script(
		gesture="kb:NVDA+shift+m",
		description="Ativa comandos em camada do MeuAddon. Pressione H para listar.",
	)
	def script_ativarCamada(self, gesture):
		# Ativa o modo camada. Segunda pressao = erro.
		if self.toggling:
			self._layer_error(gesture)
			return
		# Troca para os gestos de camada
		self.bindGestures(self.__layerGestures)
		self.toggling = True
		tones.beep(100, 10)  # beep curto confirma ativacao

	# ---- Scripts da camada (teclas simples) -------------------------

	@script(description="Acao 1 da camada")
	def script_acao1(self, gesture):
		ui.message("Acao 1 executada")

	@script(description="Acao 2 da camada")
	def script_acao2(self, gesture):
		ui.message("Acao 2 executada")

	@script(description="Lista todos os comandos da camada")
	def script_ajudaCamada(self, gesture):
		ui.message(
			"Comandos disponiveis: "
			"A para acao 1, "
			"B para acao 2, "
			"H para esta ajuda."
		)

	def terminate(self):
		super().terminate()

	# ---- Mapeamento dos gestos de camada (ativados so durante toggling) ---
	__layerGestures = {{
		"kb:a": "acao1",
		"kb:b": "acao2",
		"kb:h": "ajudaCamada",
	}}

	# ---- Gesto normal (sempre ativo) ----------------------------------
	__gestures = {{
		"kb:NVDA+shift+m": "ativarCamada",
	}}
```

REGRAS PARA GESTOS EM CAMADA:
- __layerGestures usa teclas SIMPLES (a, b, shift+a, etc) — sem NVDA+
- __gestures tem APENAS o gatilho (NVDA+alguma_tecla)
- finish() DEVE restaurar com bindGestures(self.__gestures)
- tones.beep(100, 10) no gatilho — feedback auditivo de ativacao
- tones.beep(120, 100) no erro — som mais grave, mais longo
- SEMPRE inclua script_ajudaCamada com kb:h listando os comandos
- getScript() override e obrigatorio — sem ele os gestos de camada
  nao sao interceptados corretamente

PADROES ARQUITETURAIS OBRIGATORIOS (skill: architecture-patterns, software-architecture):

1. SEPARACAO DE CAMADAS (ARCH-004):
Qualquer addon com chamadas de API externa ou logica de negocio complexa DEVE
separar em pelo menos 2 arquivos dentro de globalPlugins/nomeAddon/:
  __init__.py    — so GlobalPlugin, scripts, menu, ciclo de vida (init/terminate)
  <servico>.py   — classe que encapsula a API externa ou logica de dominio

ERRADO (tudo no __init__.py):
```python:globalPlugins/meuAddon/__init__.py
# 200+ linhas misturando wx, requests, lÃ³gica de negÃ³cio...
```

CORRETO:
```python:globalPlugins/meuAddon/transcricao_service.py
import threading
# REGRA NVDA-022: imports de pacotes 3rd party (requests, openai, googleapiclient,
# google_auth_oauthlib, etc.) NUNCA no nivel de modulo em arquivos de servico.
# Import em nivel de modulo faz o __init__.py crashar se lib/ estiver incompleta,
# e o NVDA silencia o erro — o addon inteiro deixa de carregar silenciosamente.
# Coloque SEMPRE dentro do metodo que usa o pacote (lazy import).

class TranscricaoService:
	def __init__(self, api_key: str):
		self._api_key = api_key

	def transcrever_async(self, audio_path: str, on_done, on_error):
		# Roda em background -- nunca bloqueia a thread do NVDA.
		def _worker():
			try:
				resultado = self._chamar_api(audio_path)
				import wx
				wx.CallAfter(on_done, resultado)
			except Exception as exc:
				import wx
				wx.CallAfter(on_error, str(exc))
		threading.Thread(target=_worker, daemon=True).start()

	def _chamar_api(self, audio_path: str) -> str:
		# logica de API isolada aqui — testavel sem NVDA
		import requests  # lazy — NVDA-022: nao importar no nivel de modulo
		resp = requests.post(
			"https://api.exemplo.com/transcrever",
			headers={{"Authorization": f"Bearer {{self._api_key}}"}},
			files={{"audio": open(audio_path, "rb")}},
			timeout=30,
		)
		resp.raise_for_status()
		return resp.json()["text"]

	# NVDA-023: quando o tipo retornado e de import lazy, use string literal.
	# Errado: def buscar_credenciais() -> Credentials:  # NameError — Credentials nao no escopo
	# Correto: def buscar_credenciais() -> "Credentials":
	def buscar_credenciais(self) -> "Credentials":  # noqa: F821
		from google.oauth2.credentials import Credentials  # lazy — NVDA-022
		return Credentials.from_authorized_user_file(self._token_path, self._scopes)
```

```python:globalPlugins/meuAddon/__init__.py
import wx, gui, globalPluginHandler, addonHandler, config, ui
from scriptHandler import script
from gui.settingsDialogs import NVDASettingsDialog
from .transcricao_service import TranscricaoService
from ..gui.settings_panel import MeuAddonSettingsPanel

addonHandler.initTranslation()

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	scriptCategory = "MeuAddon"

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		# NVDA-015: spec obrigatorio — registrar ANTES de qualquer acesso a config.conf['addonIdReal']
		config.conf.spec["addonIdReal"] = {{
			"apiKey": "string(default='')",
		}}
		if MeuAddonSettingsPanel not in NVDASettingsDialog.categoryClasses:
			NVDASettingsDialog.categoryClasses.append(MeuAddonSettingsPanel)
		self._servico: TranscricaoService | None = None

	def _get_servico(self) -> TranscricaoService:
		if self._servico is None:
			# NVDA-025: substitua "addonIdReal" pelo addonId do manifest.ini
			api_key = config.conf["addonIdReal"].get("apiKey", "")
			self._servico = TranscricaoService(api_key)
		return self._servico

	# Translators: Descricao do script de transcricao no dialogo de gestos de entrada
	@script(gesture="kb:NVDA+shift+t", description=_("Transcreve audio atual"))
	def script_transcrever(self, gesture):
		# Translators: Mensagem falada ao iniciar a transcricao de audio
		ui.message(_("Iniciando transcricao..."))
		self._get_servico().transcrever_async(
			"caminho/audio.wav",
			on_done=lambda txt: ui.message(txt),
			on_error=self._on_erro_transcricao,  # NVDA-019: sem _() em lambdas
		)

	def _on_erro_transcricao(self, err: str) -> None:
		# Translators: Mensagem falada quando a transcricao falha
		ui.message(_("Erro: ") + err)

	def terminate(self):
		super().terminate()
		if MeuAddonSettingsPanel in NVDASettingsDialog.categoryClasses:
			NVDASettingsDialog.categoryClasses.remove(MeuAddonSettingsPanel)
```

2. BACKGROUND THREAD CORRETO (ARCH-002):
Toda operacao > 1 segundo DEVE rodar em threading.Thread com wx.CallAfter para UI.
NUNCA: requests.get() ou arquivo.read() na thread principal (trava o NVDA inteiro).
```python
def _processar_em_background(self, dados, callback):
	def _worker():
		try:
			resultado = self._servico.processar(dados)
			wx.CallAfter(callback, resultado)
		except Exception as exc:
			# Translators: Mensagem falada quando o processamento em background falha
			wx.CallAfter(ui.message, _("Erro: ") + str(exc))
	threading.Thread(target=_worker, daemon=True).start()
```

3. SETTINGS PANEL PARA API KEY (ARCH-001 + ARCH-005):
Qualquer addon com API externa OBRIGATORIAMENTE gera settings_panel.py:
```python:globalPlugins/meuAddon/settings_panel.py
import wx
import config
from gui.settingsDialogs import SettingsPanel
from gui import guiHelper

class MeuAddonSettingsPanel(SettingsPanel):
	# Translators: Titulo do painel de configuracoes do addon no dialogo de configuracoes do NVDA
	title = _("Meu Addon")

	def makeSettings(self, sizer):
		helper = guiHelper.BoxSizerHelper(self, sizer=sizer)
		# Translators: Label do campo de chave de API no painel de configuracoes
		self._api_key = helper.addLabeledControl(
			_("&Chave de API:"), wx.TextCtrl,
			# NVDA-025: substitua "addonIdReal" pelo addonId do manifest.ini
			value=config.conf["addonIdReal"].get("apiKey", ""),
		)
		# Translators: Nome acessivel do campo de chave de API (lido por leitores de tela)
		self._api_key.SetName(_("Chave de API"))

	def onSave(self):
		# NVDA-025: mesmo addonId — deve ser identico ao manifest.ini
		config.conf["addonIdReal"]["apiKey"] = self._api_key.GetValue()
```
E no GlobalPlugin.__init__, REGISTRAR via:
```python
if MeuAddonSettingsPanel not in NVDASettingsDialog.categoryClasses:
    NVDASettingsDialog.categoryClasses.append(MeuAddonSettingsPanel)
```
E no GlobalPlugin.terminate, REMOVER via:
```python
if MeuAddonSettingsPanel in NVDASettingsDialog.categoryClasses:
    NVDASettingsDialog.categoryClasses.remove(MeuAddonSettingsPanel)
```

4. INTEGRACAO COM PROVEDORES DE IA/LLM - PADRAO ATUAL (2026) POR PROVEDOR:
Quando o addon integra com um LLM/IA externa, use requests.post() (ou httpx,
se ja vendorizado) dentro de threading.Thread (ARCH-002 - chamada de rede
NUNCA na thread principal). auth via chave salva no SettingsPanel (secao 3).
Os 5 provedores abaixo tem o formato de request/response auditado contra a
documentacao oficial em 2026-07-20 - use estes formatos, NAO o conhecimento
generico de treinamento (Chat Completions da OpenAI, por exemplo, foi
substituido pela Responses API como caminho recomendado). Para QUALQUER
provedor fora desta lista (Groq, ElevenLabs, DeepL, AssemblyAI, etc.) - ou
se o pedido mencionar uma versao/recurso especifico que voce nao tem certeza
absoluta de conhecer atualizado - marque requires_web_research=true em vez
de inventar o formato do request.

OpenAI (Responses API, nao Chat Completions):
  POST https://api.openai.com/v1/responses
  Headers: Authorization: Bearer <key>
  Body minimo: {{"model": "gpt-5.6-luna", "input": [{{"role": "user", "content": "..."}}]}}
  Texto da resposta: response["output"][0]["content"][0]["text"] (item type="message")
  Streaming: "stream": true, eventos SSE nomeados (response.output_text.delta traz o
  texto incremental no campo "delta").

xAI / Grok (mesmo padrao da OpenAI, endpoint proprio):
  POST https://api.x.ai/v1/responses
  Headers: Authorization: Bearer <key>
  Body e parsing de resposta identicos ao formato OpenAI acima.

Anthropic / Claude (Messages API):
  POST https://api.anthropic.com/v1/messages
  Headers: x-api-key: <key>, anthropic-version: 2023-06-01
  Body minimo: {{"model": "claude-haiku-4-5", "max_tokens": 1024, "messages": [{{"role": "user", "content": "..."}}]}}
  Texto da resposta: concatene response["content"][i]["text"] para blocos type="text".

Google Gemini (Interactions API, nao generateContent):
  POST https://generativelanguage.googleapis.com/v1/interactions
  Headers: x-goog-api-key: <key>
  Body minimo: {{"model": "gemini-3.5-flash", "input": [{{"role": "user", "parts": [{{"text": "..."}}]}}]}}
  Texto da resposta: response["output_text"] (campo de conveniencia ja concatenado).

Ollama Cloud:
  POST https://ollama.com/api/chat
  Headers: Authorization: Bearer <key>
  Body minimo: {{"model": "kimi-k2.7-code", "messages": [{{"role": "user", "content": "..."}}], "stream": false}}
  Texto da resposta: response["message"]["content"].

IMPORTANTE - os 5 formatos acima cobrem so o CHAT BASICO (uma mensagem,
uma resposta de texto). Os 5 provedores tambem suportam nativamente, cada
um com sintaxe propria que NAO esta detalhada aqui: streaming de verdade
(deltas incrementais), tool/function calling, entrada de imagem/visao,
saida estruturada com JSON schema, extended thinking/reasoning, cache de prompt,
ferramentas nativas do provedor (busca web, execucao de codigo) e, em
alguns casos, audio/video. Se o pedido do usuario precisar de QUALQUER uma
dessas funcionalidades alem do chat de texto simples - mesmo que o
provedor esteja nesta lista de 5 - marque requires_web_research=true para
confirmar a sintaxe exata e atual em vez de inventar o formato de tool
calling, visao ou structured output a partir de memoria. So pule a
pesquisa quando o pedido for realmente so enviar uma mensagem de texto e
receber uma resposta de texto.

5. APPMODULE — ADDON PARA UM APP ESPECIFICO (ARCH-003):
Use AppModule quando o pedido menciona UM aplicativo especifico (Notepad, Firefox, Word, etc.).
Arquivo: appModules/<nome_do_exe>.py  (ex: notepad.py para notepad.exe)
NUNCA use o nome exibido ao usuario — use o nome do processo .exe SEM a extensao.
NVDA-033: event_NVDAObject_init so funciona em AppModule, NUNCA em GlobalPlugin.
NVDA-034: se o app for self-voicing (TTS proprio), adicione sleepMode = True.
```python:appModules/notepad.py
import appModuleHandler
import addonHandler
import ui
from scriptHandler import script
from NVDAObjects import NVDAObject

addonHandler.initTranslation()

class AppModule(appModuleHandler.AppModule):
	APP_MODULE_ALLOW_SKIPINFO = True   # permite pular info padrao do NVDA no foco

	def event_gainFocus(self, obj: NVDAObject, nextHandler) -> None:
		# Chamado quando o foco entra em qualquer elemento do notepad.exe.
		# SEMPRE chame nextHandler() para nao quebrar a cadeia de eventos (NVDA-001).
		nextHandler()

	def event_NVDAObject_init(self, obj: NVDAObject) -> None:
		# Chamado ao criar qualquer NVDAObject dentro deste app.
		# APENAS em AppModule (skill: nvda-addon-dev §5) — silencioso em GlobalPlugin.
		# Corrija propriedades antes que o NVDA as leia em voz alta.
		if obj.role == 8 and obj.name is None:  # papel: document sem nome
			obj.name = "Documento do Bloco de Notas"

	def chooseNVDAObjectOverlayClasses(self, obj: NVDAObject, clsList: list) -> None:
		# Injeta classes de overlay para personalizar objetos especificos.
		# Chame super() para nao remover classes ja adicionadas por outros modulos.
		super().chooseNVDAObjectOverlayClasses(obj, clsList)
		# Exemplo: adiciona comportamento de texto editavel em campos de editar
		# clsList.insert(0, MinhaClasseCustom)

	# Translators: Descricao do script para o Bloco de Notas no dialogo de gestos de entrada
	@script(
		gesture="kb:NVDA+shift+n",
		description=_("Anuncia info do documento atual no Notepad"),
	)
	def script_anunciarInfo(self, gesture: object) -> None:
		obj = self.productName  # nome do processo
		# Translators: Mensagem falada ao anunciar informacao do documento no Notepad
		ui.message(_("Bloco de Notas ativo"))

	def terminate(self) -> None:
		super().terminate()
```
INFERENCIA ARCH-003: qual tipo de addon gerar?
Regra 1 — pede para app especifica â†’ AppModule
  "addon para Notepad" â†’ appModules/notepad.py
  "addon para Firefox" â†’ appModules/firefox.py (ou waterfox, librewolf, etc.)
  "addon para wwahost" â†’ NVDA-040: use nvdaBuiltin.appModules.wwahost.AppModule como base
  "addon para msedgewebview2" â†’ NVDA-027: inclua disableBrowseModeByDefault = True
  "app com TTS proprio / self-voicing" â†’ NVDA-034: inclua sleepMode = True
Regra 2 — funcionalidade global (qualquer app) â†’ GlobalPlugin
  "anunciar area de transferencia", "atalho global", "addon de traducao", etc.
Regra 3 — driver de sintetizador â†’ SynthDriver
  "novo sintetizador", "TTS", "engine de fala", "driver de voz", etc.
  Arquivo: synthDrivers/<nome>.py. Requer: speak(), cancel() (NVDA-031), pause(), check().
Regra 4 — driver de display braille â†’ BrailleDisplayDriver
  "display braille", "linha braille", "braille display", "driver braille", etc.
  Arquivo: brailleDisplayDrivers/<nome>.py. Requer: campos obrigatorios (NVDA-037).
Regra 5 — ambiguidade â†’ pergunte ao Clarifier antes de gerar.
  Se o tipo nao puder ser inferido, o Clarifier coleta o contexto necessario.

6. EXTENSION POINTS — CUSTOMIZACAO GLOBAL DE SPEECH/FOCO (ARCH-006):
Use extensionPoints quando precisar filtrar ou modificar fala, foco ou braille GLOBALMENTE.
NVDA-032: TODO .register() em __init__ DEVE ter .unregister() em terminate() — memory leak garantido.
```python:globalPlugins/meuAddon/__init__.py
import speech
import globalPluginHandler
import addonHandler

addonHandler.initTranslation()

class GlobalPlugin(globalPluginHandler.GlobalPlugin):

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		# Registra filtro de sequencia de fala.
		# NVDA-032: OBRIGATORIO ter .unregister() em terminate().
		speech.filter_speechSequence.register(self._filtrar_fala)

	def _filtrar_fala(self, seq: list, *, user: bool) -> list:
		# Modifica a sequencia de fala antes de chegar ao sintetizador.
		# user=True: iniciado pelo usuario; user=False: automatico.
		# Retorne a lista (modificada ou nao) — nunca retorne None.
		return seq

	def terminate(self) -> None:
		# NVDA-032: unregister ANTES de super().terminate()
		speech.filter_speechSequence.unregister(self._filtrar_fala)
		super().terminate()
```
Ordem de propagacao de evento (NVDA-001, por que nextHandler() importa):
  Um evento (ex: gainFocus) passa por 4 estagios em sequencia, cada um podendo
  processar e repassar via nextHandler(): GlobalPlugin -> AppModule ->
  TreeInterceptor -> NVDAObject. Se qualquer estagio esquecer nextHandler(),
  os estagios seguintes (inclusive o proprio NVDAObject) NUNCA recebem o evento.
  Assinatura tambem muda por nivel: em GlobalPlugin/AppModule/TreeInterceptor e
  event_<nome>(self, obj, nextHandler); em NVDAObject e so event_<nome>(self)
  -- SEM nextHandler, porque e o ultimo estagio da cadeia.

Outros extension points uteis (skill: nvda-addon-dev §7):
  extensionPoints.Action  — notifica observadores (sem retorno)
  extensionPoints.Filter  — transforma valores (com retorno, como filter_speechSequence)
  extensionPoints.Decider — um handler decide, primeiro que retornar bool decide
  extensionPoints.AccumulatingDecider — TODOS os handlers votam; decide() acumula os votos
    (use quando varios addons/partes do NVDA precisam opinar sobre a mesma decisao, nao so um)
  extensionPoints.Chain — cada handler retorna um iteravel (geralmente generator);
    os resultados de todos os handlers registrados sao concatenados em sequencia
    (achado de auditoria 2026-08-04: 5o tipo documentado no Developer Guide oficial,
    faltava aqui -- mesma regra de register()/unregister() em terminate() se aplica)
  speech.speechCanceled   — (Action) disparado quando fala e cancelada
  braille.pre_writeCells  — (Filter) filtra celulas antes de escrever no display

Padrao de propriedade automatica do NVDAObject (getters/setters lazy):
  _get_<propName>(self)          — chamado automaticamente ao acessar obj.<propName>
  _set_<propName>(self, value)   — chamado automaticamente ao atribuir obj.<propName> = value
  Exemplos reais: _get_name(self), _get_role(self), _get_states(self) em overlay classes
  usadas com chooseNVDAObjectOverlayClasses. NUNCA sobrescreva name/role diretamente no
  __init__ — sempre via _get_<propName>, senao o valor fica congelado e nao atualiza.

TreeInterceptor (modo de navegacao/browse mode para conteudo rico — paginas web, documentos):
  Classe base: treeInterceptorHandler.TreeInterceptor (geralmente via DocumentTreeInterceptor
  ou cursorManager.CursorManager, nao TreeInterceptor puro na pratica).
  Metodos principais a sobrescrever: _get_documentText(self), _get_currentNode(self) e os
  event handlers de navegacao (event_caret, event_gainFocus dentro do TreeInterceptor).
  So use TreeInterceptor se o addon precisa oferecer navegacao por virtual buffer sobre
  conteudo que o app nao expoe via UI Automation/IAccessible padrao (ex: apps com rendering
  customizado). Para a maioria dos addons (GlobalPlugin/AppModule simples) isso NAO se aplica.

7. ORGANIZACAO POR FUNCIONALIDADE, NAO POR ARQUIVOS SOLTOS (ARCH-007):
Pesquisa dedicada 2026 (vertical slice / feature-based organization): quando o addon tem
3 ou mais features/servicos substanciais e distintos (ex: integra Spotify + faz transcricao
+ gerencia playlists — dominios diferentes, nao metodos da mesma API), cada um vai em seu
proprio subpacote nomeado pela funcionalidade dentro de globalPlugins/<addon_name>/, NAO em
arquivos soltos genericos (helper.py, utils.py, misc.py) nem tudo direto na raiz do pacote.
```text
globalPlugins/MeuAddon/
  __init__.py            <- so orquestra: importa e usa cada subpacote, nunca implementa a feature
  spotify/
    __init__.py
    client.py             <- chamadas HTTP pra Spotify Web API
  transcricao/
    __init__.py
    servico.py             <- integracao com biblioteca de transcricao
  playlists/
    __init__.py
    gerenciador.py
```
Para 1-2 features (caso mais comum), continua bastando arquivo(s) soltos na raiz do pacote
(ver ARCH-004) — nao crie um subpacote pra uma unica classe de servico.

AO GERAR UM ADDON, SEMPRE FORNECA:
manifest.ini completo com anotacao de arquivo no bloco de codigo.
arquivo Python completo com docstrings e terminate().
verificacao de todas as regras NVDA-001 a NVDA-040, NVDA-042..NVDA-062 e WX-A11Y-001 a WX-A11Y-014.
Aplique ARCH-001..009: inferencia arquitetural antes de gerar o codigo.
explicacao em texto puro sem markdown.

Responda sempre em portugues do Brasil. Texto puro, sem markdown.
"""

# Dicas rapidas exibidas na sidebar do dialog
NVDA_QUICK_TIPS = [
	("GlobalPlugin", "Funciona em qualquer app. Herda de globalPluginHandler.GlobalPlugin"),
	("AppModule", "Especifico para um .exe. Herda de appModuleHandler.AppModule"),
	("ui.message()", "Faz o NVDA falar um texto imediatamente"),
	("wx.CallAfter()", "Obrigatorio para abrir dialogs de dentro de scripts (WX-A11Y-009)"),
	("prePopup/postPopup", "Use ao redor de ShowModal() no gui.mainFrame"),
	("api.getFocusObject()", "Retorna o objeto com foco de teclado atual"),
	("manifest.ini", f"Todo addon novo aqui usa baseline minimo {PROJECT_MIN_NVDA}"),
	(".nvda-addon", "Formato ZIP renomeado. Instale via Menu NVDA > Ferramentas > Addons"),
	("addonHandler", "Chame addonHandler.initTranslation() para suporte a traducoes (NVDA-003)"),
	("@script()", "Decorator para registrar atalhos. Sempre inclua description= (NVDA-008)"),
	("terminate()", "Implemente sempre para limpar recursos persistentes (NVDA-004)"),
	("nextHandler()", "Chame em todo event handler para nao quebrar cadeia (NVDA-001)"),
	("wx.StaticText", "Fix primario pra WX-A11Y-001: adicione imediatamente antes de controle sem label visivel"),
	("SetName()", "Complemento (nao substituto) de wx.StaticText pra acessibilidade (WX-A11Y-001)"),
	("2026.1+", f"Baseline oficial do projeto: {PROJECT_SUPPORTED_RANGE} sem compatibilidade legada"),
	("2026.1", "Forward-compatibility: Python 3.13 64-bit torna DLLs 32-bit incompativeis (NVDA-017)"),
]

# 2026-08-16: achado real de auditoria -- _NVDA_DOCS_DIR apontava pra um
# caminho absoluto do Windows (c:\docs_nvda) que so existia manualmente na
# maquina de um desenvolvedor especifico, sem nenhum script de setup/
# provisionamento. Pra QUALQUER usuario real que instala o NVDAStudio,
# esse caminho nunca existia -- get_docs_code_generation()/
# _build_nvda_addon_chat_system() e todos os outros get_docs_*() abaixo
# degradavam silenciosamente pra string vazia (fail-open de _read_docs_file),
# entao nem o chat nem nenhum sub-agente jamais recebiam o contexto real de
# codigo-fonte do NVDA -- so o catalogo de regras hardcoded (NVDA-001..062
# etc, prosa fixa no proprio arquivo) continuava funcionando. Corrigido:
# aponta pra uma copia BUNDLADA junto do proprio pacote do addon
# (nvda_docs_cache/, ver README la dentro pra como atualizar), caminho
# relativo ao modulo -- funciona em qualquer instalacao, sem setup manual.
_NVDA_DOCS_DIR = os.path.join(
	os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
	"nvda_docs_cache",
)


def _read_docs_file(path: str, max_chars: int = 30000) -> str:
	"""Le um arquivo de docs, retornando string vazia se nao encontrado."""
	try:
		with open(path, encoding="utf-8", errors="replace") as fp:
			return fp.read(max_chars)
	except OSError:
		return ""


def _strip_html_tags(html: str) -> str:
	"""Remove tags HTML e decodifica entidades comuns."""
	text = re.sub(r"<[^>]+>", "", html)
	for ent, rep in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
					 ("&quot;", '"'), ("&nbsp;", " "), ("&#39;", "'")]:
		text = text.replace(ent, rep)
	return re.sub(r"\n{3,}", "\n\n", text).strip()


def _build_nvda_addon_chat_system(docs_dir: str = _NVDA_DOCS_DIR) -> str:
	"""Constroi o system prompt do chat carregando conhecimento de docs_dir."""
	# --- instrucoes comportamentais (sempre presentes, nao vem dos docs) ---
	instructions = (
		"Você é o NVDAStudio Chat, um assistente especialista em criação, modificação e análise de addons NVDA "
		"embutido no próprio NVDA.\n"
		"Sua função é criar novos addons, modificar addons existentes e ajudar o usuário a entender, "
		"planejar, analisar e melhorar seus complementos NVDA.\n"
		"O usuário é o próprio desenvolvedor e parceiro de programação.\n\n"
		"Sempre responda em português do Brasil correto, com todos os acentos e cedilhas. "
		"Nunca omita ou simplifique os acentos das palavras na conversa (escreva 'você', 'usuário', 'interação', "
		"'concluído', 'criação', 'função', etc.).\n\n"
		"Preste atenção especial a estas palavras que costumam sair sem acento por engano: "
		"'criação' (nunca 'criacao'), 'início' (nunca 'inicio'), 'fim' (verifique acentos em palavras vizinhas como 'até'), "
		"'não' (nunca 'nao'), 'está' (nunca 'esta' quando for o verbo), 'código' (nunca 'codigo'), "
		"'análise' (nunca 'analise'), 'após', 'válido', 'possível'. "
		"Antes de finalizar sua resposta, releia mentalmente cada palavra e confirme que nenhum acento ou cedilha foi omitido.\n\n"
		"FORMATO OBRIGATÓRIO:\n"
		"Texto puro, sem markdown. O NVDA leria símbolos como asteriscos e sustenidos em "
		"voz alta.\n"
		"Proibido: ** negrito **, # títulos, --- linhas, > blockquote, - ou * no início de "
		"linhas.\n"
		"Permitido: blocos ```codigo``` para trechos de código.\n\n"
		"COMO RESPONDER:\n"
		"Há duas situações distintas:\n\n"
		"1. ANÁLISE, PERGUNTA OU DISCUSSÃO — responda diretamente:\n"
		"   Exemplos: O que esse addon faz? / Por que o atalho não funciona? / Como "
		"melhorar isso? / Revise esse addon.\n"
		"   Use seu conhecimento em NVDA para dar respostas úteis e precisas, mas sempre em "
		"conversa natural — como um colega de programação explicando algo, nunca como um "
		"relatório de auditoria.\n"
		"   Mesmo quando o usuário pedir para revisar, analisar ou avaliar o addon, responda em "
		"texto corrido e direto ao ponto, sem seções formais de auditoria (tipo listas de "
		"suposições, casos de falha, restrições críticas numeradas ou contrato de "
		"implementação) e sem checklists com IDs de regra tipo NVDA-001 — isso é formato de "
		"documento interno de engenharia, não de conversa com o usuário. Se identificar vários "
		"problemas, escolha os 2 ou 3 mais importantes e explique em linguagem simples, como você "
		"explicaria para um amigo que está aprendendo.\n\n"
		"2. Responda sempre com um objeto JSON válido compatível com o esquema fornecido pela aplicação. "
		"Nunca envolva o JSON em markdown.\n"
		"3. Escolha action pela intenção completa, nunca procurando palavras, prefixos ou marcadores. "
		"Use reply para conversar ou analisar, clarify quando faltar uma decisão essencial e run_pipeline "
		"quando houver uma solicitação suficientemente clara para criar ou modificar o addon.\n"
		"4. message é a única parte mostrada e falada ao usuário. Escreva português do Brasil natural, "
		"curto e acolhedor. Não use markdown, títulos, listas decorativas, separadores, emojis, nomes de "
		"agentes, raciocínio interno, identificadores de regras nem nomes de arquivos.\n"
		"5. task_specification é um canal interno. Deixe-o vazio em reply e clarify. Em run_pipeline, "
		"descreva com precisão o resultado solicitado e as restrições relevantes para a construção.\n"
		"6. Não gere código diretamente em message. Se o pedido estiver ambíguo, use clarify e faça uma "
		"pergunta conversacional específica em message.\n\n"
		"Revise acentos e cedilhas antes de responder."
	)

	parts = [instructions]

	# 1. Guia do desenvolvedor NVDA
	# 2026-08-16: achado de auditoria -- "nvda_developer_guide_2025.html"
	# nunca foi bundlado (nome de arquivo generico demais, provavelmente de
	# um download manual antigo). A fonte REAL e o Developer Guide oficial
	# do proprio repo nvaccess/nvda (projectDocs/dev/developerGuide/
	# developerGuide.md, Markdown, nao HTML) -- bundlado com o nome real.
	# _strip_html_tags() e um no-op inofensivo pra Markdown (nao ha tags
	# <> pra remover), mantido por simplicidade.
	dev_guide = _read_docs_file(os.path.join(docs_dir, "developerGuide.md"), max_chars=90000)
	if dev_guide:
		parts.append("=== GUIA DO DESENVOLVEDOR NVDA ===\n" + _strip_html_tags(dev_guide))

	# 2. Template manifest.ini
	# 2026-08-16: template oficial ainda inclui "updateChannel" (nao existe
	# no configspec real do NVDA, ver manifest_builder.py 1.12.0/
	# get_docs_manifest_builder() acima) -- aviso pro chat nao ensinar isso
	# como campo valido se o usuario perguntar sobre manifest.ini.
	manifest = _read_docs_file(
		os.path.join(docs_dir, "AddonTemplate-master", "manifest.ini.tpl")
	)
	if manifest:
		parts.append(
			"=== TEMPLATE: manifest.ini ===\n"
			"(AVISO: o campo 'updateChannel' abaixo e placeholder do template "
			"oficial mas NAO existe no configspec real validado pelo NVDA -- "
			"nao ensine como campo valido.)\n" + manifest
		)

	# 3. Template buildVars.py
	bv = _read_docs_file(os.path.join(docs_dir, "AddonTemplate-master", "buildVars.py"))
	if bv:
		parts.append("=== TEMPLATE: buildVars.py ===\n" + bv)

	# 4. scriptHandler.py — decorator @script
	sh = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "scriptHandler.py"), max_chars=20000
	)
	if sh:
		parts.append("=== NVDA SOURCE: scriptHandler.py ===\n" + sh)

	# 5. addonHandler/__init__.py — ciclo de vida, initTranslation
	ah = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "addonHandler", "__init__.py"),
		max_chars=25000,
	)
	if ah:
		parts.append("=== NVDA SOURCE: addonHandler/__init__.py ===\n" + ah)

	# 6. AddonTemplate readme.md — guia completo de uso do template
	at_readme = _read_docs_file(
		os.path.join(docs_dir, "AddonTemplate-master", "readme.md")
	)
	if at_readme:
		parts.append("=== GUIA: AddonTemplate readme.md ===\n" + at_readme)

	# 7. DevGuide readme.md — contexto da comunidade de addons
	dg_readme = _read_docs_file(os.path.join(docs_dir, "DevGuide-master", "readme.md"))
	if dg_readme:
		parts.append("=== GUIA: DevGuide readme.md ===\n" + dg_readme)

	# 8. globalPluginHandler.py — classe base GlobalPlugin
	gph = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "globalPluginHandler.py")
	)
	if gph:
		parts.append("=== NVDA SOURCE: globalPluginHandler.py ===\n" + gph)

	# 9. appModules/__init__.py — classe base AppModule
	am_init = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "appModules", "__init__.py")
	)
	if am_init:
		parts.append("=== NVDA SOURCE: appModules/__init__.py ===\n" + am_init)

	# 10. addonAPIVersion.py — constantes de versao da API
	api_ver = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "addonAPIVersion.py")
	)
	if api_ver:
		parts.append("=== NVDA SOURCE: addonAPIVersion.py ===\n" + api_ver)

	# 11. controlTypes/__init__.py — constantes de tipo de controle
	ct = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "controlTypes", "__init__.py")
	)
	if ct:
		parts.append("=== NVDA SOURCE: controlTypes/__init__.py ===\n" + ct)

	# 12. speech/__init__.py — API de fala (speak, speakObject, etc.)
	sp = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "speech", "__init__.py")
	)
	if sp:
		parts.append("=== NVDA SOURCE: speech/__init__.py ===\n" + sp)

	# 13. ui.py — ui.message, ui.browseableMessage
	ui_src = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "ui.py")
	)
	if ui_src:
		parts.append("=== NVDA SOURCE: ui.py ===\n" + ui_src)

	# 14. Exemplos reais de appModules
	for ex_name in ("notepad.py", "calc.py", "calculator.py", "explorer.py",
					"foobar2000.py", "outlook.py"):
		max_ex = 15000 if ex_name in ("explorer.py", "outlook.py") else 30000
		ex = _read_docs_file(
			os.path.join(docs_dir, "nvda", "source", "appModules", ex_name),
			max_chars=max_ex,
		)
		if ex:
			parts.append(f"=== EXEMPLO REAL appModule: {ex_name} ===\n" + ex)

	# 15. NVDAObjects/__init__.py — classe base NVDAObject, eventos, propriedades
	nvda_obj = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "NVDAObjects", "__init__.py"),
		max_chars=25000,
	)
	if nvda_obj:
		parts.append("=== NVDA SOURCE: NVDAObjects/__init__.py ===\n" + nvda_obj)

	# 16. api.py — getFocusObject, getDesktopObject, API central
	api_src = _read_docs_file(os.path.join(docs_dir, "nvda", "source", "api.py"))
	if api_src:
		parts.append("=== NVDA SOURCE: api.py ===\n" + api_src)

	# 17. appModuleHandler.py — ciclo de vida AppModule
	amh = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "appModuleHandler.py"),
		max_chars=25000,
	)
	if amh:
		parts.append("=== NVDA SOURCE: appModuleHandler.py ===\n" + amh)

	# 18. inputCore.py — sistema de gestos, InputGesture, bindGesture
	ic = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "inputCore.py"),
		max_chars=25000,
	)
	if ic:
		parts.append("=== NVDA SOURCE: inputCore.py ===\n" + ic)

	# 19. eventHandler.py — disparo de eventos NVDA, requestEvents
	eh = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "eventHandler.py")
	)
	if eh:
		parts.append("=== NVDA SOURCE: eventHandler.py ===\n" + eh)

	# 20. gui/__init__.py — mainFrame, messageBox, padroes de GUI
	gui_src = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "gui", "__init__.py"),
		max_chars=20000,
	)
	if gui_src:
		parts.append("=== NVDA SOURCE: gui/__init__.py ===\n" + gui_src)

	# 21. gui/guiHelper.py — helpers para construcao de dialogs
	gh = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "gui", "guiHelper.py")
	)
	if gh:
		parts.append("=== NVDA SOURCE: gui/guiHelper.py ===\n" + gh)

	# 22. gui/message.py — nova API de dialogs de mensagem (NVDA 2024.2+)
	gm = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "gui", "message.py"),
		max_chars=20000,
	)
	if gm:
		parts.append("=== NVDA SOURCE: gui/message.py ===\n" + gm)

	# 23. tones.py — tones.beep()
	tones_src = _read_docs_file(os.path.join(docs_dir, "nvda", "source", "tones.py"))
	if tones_src:
		parts.append("=== NVDA SOURCE: tones.py ===\n" + tones_src)

	# 24. extensionPoints/__init__.py — Action, Filter, Decider
	ep = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "extensionPoints", "__init__.py")
	)
	if ep:
		parts.append("=== NVDA SOURCE: extensionPoints/__init__.py ===\n" + ep)

	# 25. baseObject.py — AutoPropertyObject, base de NVDAObject
	bo = _read_docs_file(os.path.join(docs_dir, "nvda", "source", "baseObject.py"))
	if bo:
		parts.append("=== NVDA SOURCE: baseObject.py ===\n" + bo)

	# 26. NVDAObjects/behaviors.py — mixins: EditableText, RowWithFakeNavigation, etc.
	behaviors = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "NVDAObjects", "behaviors.py"),
		max_chars=20000,
	)
	if behaviors:
		parts.append("=== NVDA SOURCE: NVDAObjects/behaviors.py ===\n" + behaviors)

	# 27. speech/commands.py — objetos de comando de fala (PitchCommand, etc.)
	speech_cmds = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "speech", "commands.py")
	)
	if speech_cmds:
		parts.append("=== NVDA SOURCE: speech/commands.py ===\n" + speech_cmds)

	# 28. textInfos/__init__.py — API TextInfo para navegacao de texto/cursor
	ti = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "textInfos", "__init__.py"),
		max_chars=20000,
	)
	if ti:
		parts.append("=== NVDA SOURCE: textInfos/__init__.py ===\n" + ti)

	# 29. keyboardHandler.py — tratamento de teclas, KeyboardInputGesture
	kh = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "keyboardHandler.py"),
		max_chars=20000,
	)
	if kh:
		parts.append("=== NVDA SOURCE: keyboardHandler.py ===\n" + kh)

	# 30. manifest-translated.ini.tpl — template manifest traduzido
	mt = _read_docs_file(
		os.path.join(docs_dir, "AddonTemplate-master", "manifest-translated.ini.tpl")
	)
	if mt:
		parts.append("=== TEMPLATE: manifest-translated.ini.tpl ===\n" + mt)

	# 31. config/__init__.py — config.conf, ConfigManager, spec (CRITICO para addons)
	cfg = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "config", "__init__.py"),
		max_chars=20000,
	)
	if cfg:
		parts.append("=== NVDA SOURCE: config/__init__.py ===\n" + cfg)

	# 32. config/configSpec.py — formato de spec de configuracao
	cfg_spec = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "config", "configSpec.py"),
		max_chars=15000,
	)
	if cfg_spec:
		parts.append("=== NVDA SOURCE: config/configSpec.py ===\n" + cfg_spec)

	# 33. globalVars.py — globalVars.appArgs, globalVars.appDir, paths
	gv = _read_docs_file(os.path.join(docs_dir, "nvda", "source", "globalVars.py"))
	if gv:
		parts.append("=== NVDA SOURCE: globalVars.py ===\n" + gv)

	# 34. NVDAState.py — shouldWriteToDisk(), NVDA em secure mode (NVDA-016)
	nvda_state = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "NVDAState.py")
	)
	if nvda_state:
		parts.append("=== NVDA SOURCE: NVDAState.py ===\n" + nvda_state)

	# 35. queueHandler.py — queueFunction para main thread (evitar bloqueio)
	qh = _read_docs_file(os.path.join(docs_dir, "nvda", "source", "queueHandler.py"))
	if qh:
		parts.append("=== NVDA SOURCE: queueHandler.py ===\n" + qh)

	# 36. logHandler.py — API de logging (log.debug, log.info, log.error)
	lh = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "logHandler.py"),
		max_chars=15000,
	)
	if lh:
		parts.append("=== NVDA SOURCE: logHandler.py ===\n" + lh)

	# 37. versionInfo.py — constantes de versao do NVDA em runtime
	vi = _read_docs_file(os.path.join(docs_dir, "nvda", "source", "versionInfo.py"))
	if vi:
		parts.append("=== NVDA SOURCE: versionInfo.py ===\n" + vi)

	# 38. gui/nvdaControls.py — controles wx especializados para NVDA
	nc_gui = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "gui", "nvdaControls.py"),
		max_chars=15000,
	)
	if nc_gui:
		parts.append("=== NVDA SOURCE: gui/nvdaControls.py ===\n" + nc_gui)

	# 39. gui/addonGui.py — GUI de gerenciamento de addons
	ag_gui = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "gui", "addonGui.py")
	)
	if ag_gui:
		parts.append("=== NVDA SOURCE: gui/addonGui.py ===\n" + ag_gui)

	# 40. synthDriverHandler.py — base para drivers de sintetizador
	sdh = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "synthDriverHandler.py"),
		max_chars=15000,
	)
	if sdh:
		parts.append("=== NVDA SOURCE: synthDriverHandler.py ===\n" + sdh)

	# 41. editableText.py — EditableText, caret, selecao de texto
	et = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "editableText.py"),
		max_chars=15000,
	)
	if et:
		parts.append("=== NVDA SOURCE: editableText.py ===\n" + et)

	# 42. windowUtils.py — utilitarios de janela
	wu = _read_docs_file(os.path.join(docs_dir, "nvda", "source", "windowUtils.py"))
	if wu:
		parts.append("=== NVDA SOURCE: windowUtils.py ===\n" + wu)

	# 44. braille.py — BrailleDisplayDriver base, handler, regioes braille
	# 2026-08-16: achado de auditoria (clone real de nvaccess/nvda) -- em
	# NVDA 2026.3, braille.py deixou de ser um arquivo unico e virou o
	# pacote braille/, com BrailleDisplayDriver agora em
	# braille/display/driver.py (braille.BrailleDisplayDriver continua
	# existindo como alias de compatibilidade, mas o codigo real mudou de
	# lugar). Tenta os dois caminhos -- qualquer snapshot local de docs
	# mais antigo que 2026.3 ainda tem braille.py; um snapshot atualizado
	# tera o pacote novo.
	braille_src = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "braille.py"),
		max_chars=20000,
	)
	if not braille_src:
		braille_src = _read_docs_file(
			os.path.join(docs_dir, "nvda", "source", "braille", "display", "driver.py"),
			max_chars=20000,
		)
	if braille_src:
		parts.append("=== NVDA SOURCE: braille.py (ou braille/display/driver.py em 2026.3+) ===\n" + braille_src)

	# 45. bdDetect.py — auto-deteccao USB/Bluetooth de displays braille
	bddetect_src = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "bdDetect.py"),
		max_chars=15000,
	)
	if bddetect_src:
		parts.append("=== NVDA SOURCE: bdDetect.py ===\n" + bddetect_src)

	# 46-50: modulos referenciados por assinatura publica em arquivos ja
	# bundlados acima (aria.py por NVDAObjects/__init__.py._get_liveRegionPoliteness,
	# diffHandler.py por behaviors.py._get_diffAlgo, documentBase.py por
	# api.py/NVDAObjects/__init__.py/textInfos/__init__.py via forward-ref,
	# locationHelper.py por textInfos/__init__.py._get_location, speech/priorities.py
	# pelo tipo speech.Spri usado em ui.message/ui.reviewMessage) mas que ate
	# 2026-08-17 nao estavam bundlados -- a IA tinha que adivinhar esses tipos
	# pela memoria de treino em vez da fonte real, contra a propria filosofia
	# deste arquivo. Achado via varredura sistematica de cross-reference
	# pedida pelo Felipe. Todos pequenos (1-20KB), lidos sem truncamento.
	aria_src = _read_docs_file(os.path.join(docs_dir, "nvda", "source", "aria.py"))
	if aria_src:
		parts.append("=== NVDA SOURCE: aria.py ===\n" + aria_src)

	diff_src = _read_docs_file(os.path.join(docs_dir, "nvda", "source", "diffHandler.py"))
	if diff_src:
		parts.append("=== NVDA SOURCE: diffHandler.py ===\n" + diff_src)

	docbase_src = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "documentBase.py"),
		max_chars=20000,
	)
	if docbase_src:
		parts.append("=== NVDA SOURCE: documentBase.py ===\n" + docbase_src)

	loc_src = _read_docs_file(
		os.path.join(docs_dir, "nvda", "source", "locationHelper.py"),
		max_chars=20000,
	)
	if loc_src:
		parts.append("=== NVDA SOURCE: locationHelper.py ===\n" + loc_src)

	spri_src = _read_docs_file(os.path.join(docs_dir, "nvda", "source", "speech", "priorities.py"))
	if spri_src:
		parts.append("=== NVDA SOURCE: speech/priorities.py ===\n" + spri_src)

	# 43. Regras de deteccao (referencia rapida a partir das constantes do modulo)
	nvda_rules = "\n".join(f"{r[0]} {r[1]}: {r[2]}" for r in NVDA_DETECTION_RULES)
	wx_rules_text = "\n".join(f"{r[0]} {r[1]}: {r[2]}" for r in WX_A11Y_RULES)
	dtk_rules_text = "\n".join(f"{r[0]} {r[1]}: {r[2]}" for r in DTK_A11Y_RULES)
	parts.append(
		f"=== REGRAS DE DETECCAO (referencia rapida) ===\n"
		f"NVDA:\n{nvda_rules}\n\nWX-A11Y:\n{wx_rules_text}\n\nDTK-A11Y:\n{dtk_rules_text}"
	)
	parts.append(
		f"=== MATRIZ DE FALLBACK POR REGRA ===\n{RULE_FALLBACK_MATRIX_TEXT}"
	)

	return "\n\n".join(parts)


# ------------------------------------------------------------------
# Sistema de chat especializado para a aba Conversar / Iterar
# Carregado dinamicamente de c:\docs_nvda em tempo de importacao.
# Versao: 2.9.0 (2026-03-27)
# ------------------------------------------------------------------

NVDA_ADDON_CHAT_SYSTEM = _build_nvda_addon_chat_system()


# ------------------------------------------------------------------
# System prompt LITE para o chat conversacional.
# O NVDA_ADDON_CHAT_SYSTEM completo pode passar de 600K chars.
# Este limite garante que instrucoes + arquivos essenciais cabem com
# margem para historico e resposta.
# ------------------------------------------------------------------
_CHAT_SYSTEM_MAX_CHARS = 70_000

NVDA_ADDON_CHAT_SYSTEM_LITE: str = NVDA_ADDON_CHAT_SYSTEM[:_CHAT_SYSTEM_MAX_CHARS]


# ------------------------------------------------------------------
# Contexto cirurgico por dominio — para sub-agentes especializados.
# Cada funcao retorna apenas os arquivos relevantes para aquele agente,
# evitando inflar o contexto de LLMs que so precisam de uma fatia.
# Versao: 2.9.0
# ------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Contexto NVDA por TOPICO, para geracao de codigo.
#
# MOTIVO (medido em 2026-08-30): `get_docs_code_generation()` injetava os 26
# arquivos-fonte SEMPRE, em toda chamada -- 362 mil chars, ~90 mil tokens. Com o
# _SYSTEM do gerador, o custo FIXO por tentativa passava de 100 mil tokens.
#
# Nos relatorios E2E reais isso aparecia assim: um unico code_generation que
# falhava 3 vezes consumia 412 mil tokens -- 41% do orcamento inteiro do addon --
# antes de qualquer trabalho util. E o step que geraria o `__init__.py` nunca
# chegava a rodar, o que fazia o addon ser recusado por falta de ponto de
# entrada. O gargalo nao era o modelo nem o loop: era o pedagio de entrada.
#
# Pior: a decomposicao por arquivo (planner 2.33.0), correta em si, MULTIPLICA
# esse custo -- cada step novo paga o pedagio de novo.
#
# Um step que gera `gemini/client.py` (cliente HTTP puro) nao precisa de
# speech/commands, tones, aria nem documentBase. Um que gera `settings_panel.py`
# precisa de gui/settingsDialogs e config, nao de inputCore.
#
# QUEM DECIDE (Regra 7): a IA declara os topicos no plano (`step.nvda_topics`);
# este modulo apenas MONTA o que foi declarado. Sem declaracao, devolve tudo --
# mesmo comportamento de antes, porque o custo de um contexto faltando e maior
# que o de um contexto sobrando.
# ---------------------------------------------------------------------------

# Sempre incluidos: os arquivos que QUALQUER arquivo de addon precisa conhecer,
# todos pequenos. O piso de contexto, nao um topico.
_DOCS_CORE: tuple[str, ...] = (
	"globalPluginHandler.py", "addonHandler/__init__.py", "api.py",
	"ui.py", "NVDAState.py", "queueHandler.py", "config/configSpec.py",
	"TEMPLATE: buildVars.py",
)

NVDA_DOC_TOPICS: dict[str, tuple[str, ...]] = {
	# Atalhos, scripts e captura de teclado.
	"scripts": ("scriptHandler.py", "inputCore.py", "keyboardHandler.py", "globalCommands.py"),
	# Qualquer interface wx: dialogos, paineis, painel de configuracoes do NVDA.
	"gui": ("gui/__init__.py", "gui/guiHelper.py", "gui/message.py", "gui/settingsDialogs.py"),
	# Persistencia de preferencias.
	"config": ("config/__init__.py",),
	# Navegacao pela arvore de objetos e eventos do NVDA.
	"objects": ("NVDAObjects/__init__.py", "baseObject.py", "eventHandler.py",
				"documentBase.py", "aria.py"),
	# Fala, prioridades e sinais sonoros.
	"speech": ("speech/commands.py", "speech/priorities.py", "tones.py"),
	# Addon especifico de aplicativo.
	"appmodule": ("appModuleHandler.py",),
	# Timers, restart, janelas e extension points.
	"system": ("core.py", "windowUtils.py", "extensionPoints/__init__.py"),
}


_NVDA_TOPICS_MARKER = "[NVDA-TOPICS:"


def nvda_topics_marker(topics: list[str] | None) -> str:
	"""
	Marcador de roteamento deterministico prependido ao prompt do step.

	Mesmo padrao ja usado por `controller_client_context.project_type_marker()`:
	o orchestrator sabe o topico (esta no plano), o sub-agente nao recebe o
	objeto do step -- so o prompt. O marcador e o canal.

	Lista vazia devolve string vazia: sem marcador, o gerador injeta TUDO, que e
	o comportamento seguro de antes.
	"""
	limpos = [str(t).strip().lower() for t in (topics or []) if str(t).strip()]
	if not limpos:
		return ""
	return f"{_NVDA_TOPICS_MARKER}{','.join(limpos)}]" + chr(10)


def extract_nvda_topics(prompt: str) -> list[str]:
	"""
	Le o marcador do prompt. Deterministico (Regra 5), nunca decisao do LLM.

	Ausente ou malformado devolve lista vazia -> contexto completo. Nunca
	levanta: uma falha aqui trocaria "prompt grande" por "step morto".
	"""
	if not prompt or _NVDA_TOPICS_MARKER not in prompt:
		return []
	try:
		inicio = prompt.index(_NVDA_TOPICS_MARKER) + len(_NVDA_TOPICS_MARKER)
		fim = prompt.index("]", inicio)
		return [t.strip() for t in prompt[inicio:fim].split(",") if t.strip()]
	except ValueError:
		return []


def get_docs_code_generation(
	docs_dir: str = _NVDA_DOCS_DIR, topics: list[str] | None = None,
) -> str:
	"""
	Contexto para CodeGenerator: codigo-fonte real do NVDA.

	topics: nomes de NVDA_DOC_TOPICS declarados pelo plano para ESTE step. O
	grupo _DOCS_CORE entra sempre. `None` ou lista vazia devolve TUDO -- o
	comportamento anterior, e o padrao seguro: contexto faltando custa mais caro
	que contexto sobrando, e um planner que nao declarou topicos nao deve gerar
	codigo as cegas.

	Topico desconhecido e ignorado em silencio: nome errado vindo do modelo nao
	pode derrubar a geracao.
	"""
	src = os.path.join(docs_dir, "nvda", "source")
	pairs = [
		("scriptHandler.py",                    os.path.join(src, "scriptHandler.py"),               20000),
		("globalPluginHandler.py",              os.path.join(src, "globalPluginHandler.py"),          0),
		("appModuleHandler.py",                 os.path.join(src, "appModuleHandler.py"),             20000),
		("api.py",                              os.path.join(src, "api.py"),                          0),
		("eventHandler.py",                     os.path.join(src, "eventHandler.py"),                 0),
		("gui/guiHelper.py",                    os.path.join(src, "gui", "guiHelper.py"),             0),
		("gui/message.py",                      os.path.join(src, "gui", "message.py"),               15000),
		("gui/__init__.py",                     os.path.join(src, "gui", "__init__.py"),               35000),
		# L1: settingsDialogs.py — SettingsPanel + MultiCategorySettingsDialog
		# Necessario para addons que adicionam painel ao NVDA Settings (NVDA-015).
		# Sem esse arquivo, a IA gera dialogs isolados em vez do painel nativo.
		("gui/settingsDialogs.py",              os.path.join(src, "gui", "settingsDialogs.py"),        28000),
		# L3: globalCommands.py — atalhos existentes no core do NVDA.
		# Necessario para evitar conflitos de atalho (NVDA-009). 214KB — lemos 20000 chars
		# (cobre os atalhos mais comuns: NVDA+letras, F-keys, etc.).
		("globalCommands.py",                   os.path.join(src, "globalCommands.py"),               20000),
		# L4: core.py — core.callLater, core.restart, core.requestPump.
		# Necessario para timers corretos e restart seguro no NVDA.
		("core.py",                             os.path.join(src, "core.py"),                         20000),
		# Layer gestures: inputCore tem bindGestures, clearGestureBindings, getScript
		("inputCore.py",                        os.path.join(src, "inputCore.py"),                    25000),
		("tones.py",                            os.path.join(src, "tones.py"),                        0),
		("config/__init__.py",                  os.path.join(src, "config", "__init__.py"),           15000),
		("config/configSpec.py",                os.path.join(src, "config", "configSpec.py"),         0),
		("NVDAState.py",                        os.path.join(src, "NVDAState.py"),                    0),
		("queueHandler.py",                     os.path.join(src, "queueHandler.py"),                 0),
		("extensionPoints/__init__.py",         os.path.join(src, "extensionPoints", "__init__.py"),  0),
		("NVDAObjects/__init__.py",             os.path.join(src, "NVDAObjects", "__init__.py"),      15000),
		("keyboardHandler.py",                  os.path.join(src, "keyboardHandler.py"),              15000),
		("baseObject.py",                       os.path.join(src, "baseObject.py"),                   0),
		("speech/commands.py",                  os.path.join(src, "speech", "commands.py"),           0),
		("ui.py",                               os.path.join(src, "ui.py"),                           0),
		("windowUtils.py",                      os.path.join(src, "windowUtils.py"),                  0),
		("addonHandler/__init__.py",            os.path.join(src, "addonHandler", "__init__.py"),     15000),
		# aria.py/documentBase.py/speech/priorities.py: tipos referenciados por
		# NVDAObjects/__init__.py/api.py/ui.py (ja acima) mas antes ausentes do
		# cache -- achado em varredura de cross-reference 2026-08-17.
		("aria.py",                             os.path.join(src, "aria.py"),                         0),
		("documentBase.py",                     os.path.join(src, "documentBase.py"),                 20000),
		("speech/priorities.py",                os.path.join(src, "speech", "priorities.py"),         0),
		("TEMPLATE: buildVars.py",              os.path.join(docs_dir, "AddonTemplate-master", "buildVars.py"), 0),
	]

	if topics:
		permitidos = set(_DOCS_CORE)
		for topico in topics:
			permitidos.update(NVDA_DOC_TOPICS.get(str(topico).strip().lower(), ()))
		pairs = [t for t in pairs if t[0] in permitidos]

	sections = []
	for label, path, max_c in pairs:
		content = _read_docs_file(path, max_chars=max_c) if max_c else _read_docs_file(path)
		if content:
			sections.append(f"=== NVDA SOURCE: {label} ===\n{content}")
	return "\n\n".join(sections)

def get_docs_accessibility_audit(docs_dir: str = _NVDA_DOCS_DIR) -> str:
	"""
	Contexto para AccessibilityAuditor: auditoria de acessibilidade NVDA+wxPython.
	Cobre: NVDAObjects/__init__, NVDAObjects/behaviors, gui/__init__, gui/nvdaControls,
	gui/guiHelper, gui/message, eventHandler, controlTypes/__init__,
	speech/__init__, speech/commands, inputCore, keyboardHandler, NVDAState.
	"""
	src = os.path.join(docs_dir, "nvda", "source")
	pairs = [
		("NVDAObjects/__init__.py",       os.path.join(src, "NVDAObjects", "__init__.py"),   20000),
		("NVDAObjects/behaviors.py",      os.path.join(src, "NVDAObjects", "behaviors.py"),  15000),
		("gui/__init__.py",               os.path.join(src, "gui", "__init__.py"),            15000),
		("gui/nvdaControls.py",           os.path.join(src, "gui", "nvdaControls.py"),        15000),
		("gui/guiHelper.py",              os.path.join(src, "gui", "guiHelper.py"),           0),
		("gui/message.py",                os.path.join(src, "gui", "message.py"),             12000),
		("eventHandler.py",               os.path.join(src, "eventHandler.py"),               0),
		("controlTypes/__init__.py",      os.path.join(src, "controlTypes", "__init__.py"),   0),
		("speech/__init__.py",            os.path.join(src, "speech", "__init__.py"),         0),
		("speech/commands.py",            os.path.join(src, "speech", "commands.py"),         0),
		("inputCore.py",                  os.path.join(src, "inputCore.py"),                  15000),
		("keyboardHandler.py",            os.path.join(src, "keyboardHandler.py"),            12000),
		("NVDAState.py",                  os.path.join(src, "NVDAState.py"),                  0),
		# L3: globalCommands.py — auditoria de conflito de atalho (NVDA-009)
		("globalCommands.py",             os.path.join(src, "globalCommands.py"),             18000),
		# gui/settingsDialogs.py — para auditar uso correto de SettingsPanel
		("gui/settingsDialogs.py",        os.path.join(src, "gui", "settingsDialogs.py"),     15000),
		# aria.py/diffHandler.py/documentBase.py: tipos referenciados por
		# NVDAObjects/__init__.py/behaviors.py (ja acima) mas antes ausentes do
		# cache -- achado em varredura de cross-reference 2026-08-17.
		("aria.py",                       os.path.join(src, "aria.py"),                       0),
		("diffHandler.py",                os.path.join(src, "diffHandler.py"),                0),
		("documentBase.py",               os.path.join(src, "documentBase.py"),               20000),
	]
	sections = []
	for label, path, max_c in pairs:
		content = _read_docs_file(path, max_chars=max_c) if max_c else _read_docs_file(path)
		if content:
			sections.append(f"=== NVDA SOURCE: {label} ===\n{content}")
	return "\n\n".join(sections)


# Documentacao por PERSONA do design review. Medido em 2026-09-01: os tres
# estagios recebiam o MESMO bloco de 30 mil tokens, somando 90 mil por revisao
# -- de 9% a 17% do orcamento de um addon complexo, gasto antes de existir uma
# linha de codigo. Nao e contexto demais; e o mesmo contexto tres vezes.
#
# O corte segue o que cada persona de fato produz, nao um teto arbitrario:
#
# - guardian: e quem cita restricoes tecnicas e IDs de regra do NVDA/WX.
#   Recebe TUDO -- e o unico estagio cuja saida depende de ler a fonte.
# - challenger: questiona suposicoes e preve modos de falha. Precisa do ciclo
#   de vida do addon (carga, config, estado, fila), nao da API de gestos.
# - advocate: representa o usuario cego -- fluxo, atalhos, linguagem. Nao cita
#   API nenhuma; o proprio `_strip_rule_ids` existe para REMOVER da saida dele
#   os IDs de regra que ele nao deveria estar citando. Dar fonte do NVDA a esse
#   estagio empurra ele exatamente para o comportamento que o codigo apaga
#   depois.
#
# HIPOTESE, nao medicao: a economia (60 mil tokens por revisao) e certa, o
# efeito na QUALIDADE da revisao nao foi medido -- a comparar pela nota que o
# Critic da ao design_review nas proximas rodadas. Se cair, reverter: cortar
# contexto ja piorou resultado nesta sessao (rodada 6, notas 52.0 -> 15.7).
#
# Persona desconhecida ou vazia recebe tudo: na duvida, contexto sobrando custa
# tokens, contexto faltando custa a revisao.
_DESIGN_REVIEW_PERSONA_DOCS: dict[str, tuple[str, ...]] = {
	"challenger": (
		"config/__init__.py", "NVDAState.py", "queueHandler.py",
		"addonHandler/__init__.py", "addonAPIVersion.py",
		"globalPluginHandler.py",
	),
	"advocate": (),
}


def get_docs_design_review(
	docs_dir: str = _NVDA_DOCS_DIR, persona: str = "",
) -> str:
	"""
	Contexto para DesignReview: analise de riscos de design antes de gerar codigo.
	Cobre: eventHandler, extensionPoints, config, NVDAState, inputCore,
	appModuleHandler, globalPluginHandler, scriptHandler, addonAPIVersion,
	queueHandler, addonHandler.

	`persona` recorta o conjunto por estagio (_DESIGN_REVIEW_PERSONA_DOCS).
	Vazia ou desconhecida devolve TUDO -- o comportamento anterior.
	"""
	permitidos = _DESIGN_REVIEW_PERSONA_DOCS.get((persona or "").strip().lower())
	src = os.path.join(docs_dir, "nvda", "source")
	pairs = [
		("eventHandler.py",               os.path.join(src, "eventHandler.py"),               0),
		("extensionPoints/__init__.py",   os.path.join(src, "extensionPoints", "__init__.py"), 0),
		("config/__init__.py",            os.path.join(src, "config", "__init__.py"),          12000),
		("NVDAState.py",                  os.path.join(src, "NVDAState.py"),                   0),
		("inputCore.py",                  os.path.join(src, "inputCore.py"),                   15000),
		("appModuleHandler.py",           os.path.join(src, "appModuleHandler.py"),            15000),
		("globalPluginHandler.py",        os.path.join(src, "globalPluginHandler.py"),         0),
		("scriptHandler.py",              os.path.join(src, "scriptHandler.py"),               15000),
		("addonAPIVersion.py",            os.path.join(src, "addonAPIVersion.py"),             0),
		("queueHandler.py",               os.path.join(src, "queueHandler.py"),                0),
		("addonHandler/__init__.py",      os.path.join(src, "addonHandler", "__init__.py"),    12000),
	]
	sections = []
	for label, path, max_c in pairs:
		if permitidos is not None and label not in permitidos:
			continue
		content = _read_docs_file(path, max_chars=max_c) if max_c else _read_docs_file(path)
		if content:
			sections.append(f"=== NVDA SOURCE: {label} ===\n{content}")
	return "\n\n".join(sections)


def get_docs_manifest_builder(docs_dir: str = _NVDA_DOCS_DIR) -> str:
	"""
	Contexto para ManifestBuilder: geracao de manifest.ini correto.
	Cobre: addonAPIVersion, addonHandler, manifest.ini.tpl,
	manifest-translated.ini.tpl, buildVars.py, AddonTemplate readme.

	2026-08-16: manifest.ini.tpl (oficial, nvaccess/addonTemplate) ainda
	inclui "updateChannel" como placeholder -- CONFIRMADO CONTRA O FONTE
	REAL (addonHandler/__init__.py, AddonManifest.configspec) que esse
	campo NAO existe no configspec validado pelo NVDA (achado ja corrigido
	em manifest_builder.py 1.12.0). Injeta um aviso deterministico logo
	ANTES do template pra nao deixar o LLM reintroduzir o campo so por ver
	o template oficial mencionando-o -- a fonte de verdade sobre o que e
	VALIDADO e addonHandler, nao o template.
	"""
	src = os.path.join(docs_dir, "nvda", "source")
	tpl = os.path.join(docs_dir, "AddonTemplate-master")
	pairs = [
		("addonAPIVersion.py",                  os.path.join(src, "addonAPIVersion.py"),       0),
		("addonHandler/__init__.py",            os.path.join(src, "addonHandler", "__init__.py"), 12000),
		("TEMPLATE: manifest.ini.tpl",          os.path.join(tpl, "manifest.ini.tpl"),         0),
		("TEMPLATE: manifest-translated.ini.tpl", os.path.join(tpl, "manifest-translated.ini.tpl"), 0),
		("TEMPLATE: buildVars.py",              os.path.join(tpl, "buildVars.py"),              0),
		("GUIA: AddonTemplate readme.md",       os.path.join(tpl, "readme.md"),                10000),
	]
	sections = [
		"AVISO: o TEMPLATE oficial abaixo (manifest.ini.tpl) inclui um "
		"placeholder \"updateChannel\" -- esse campo NAO existe no "
		"configspec real do NVDA (AddonManifest em addonHandler/__init__.py, "
		"secao 'addonHandler/__init__.py' logo abaixo) e NUNCA deve ser "
		"incluido no manifest.ini gerado. Use o template so pra estrutura "
		"geral (ordem de campos, formato), nunca copiando 'updateChannel' "
		"literalmente."
	]
	for label, path, max_c in pairs:
		content = _read_docs_file(path, max_chars=max_c) if max_c else _read_docs_file(path)
		if content:
			sections.append(f"=== {label} ===\n{content}")
	return "\n\n".join(sections)


def get_docs_doc_generator(docs_dir: str = _NVDA_DOCS_DIR) -> str:
	"""
	Contexto para DocGenerator: geracao de userGuide.html acessivel.
	Cobre: addonHandler, AddonTemplate readme, DevGuide readme,
	guia do desenvolvedor NVDA.
	"""
	src = os.path.join(docs_dir, "nvda", "source")
	pairs = [
		("addonHandler/__init__.py",  os.path.join(src, "addonHandler", "__init__.py"),   10000),
		("GUIA: AddonTemplate readme.md", os.path.join(docs_dir, "AddonTemplate-master", "readme.md"), 0),
		("GUIA: DevGuide readme.md",  os.path.join(docs_dir, "DevGuide-master", "readme.md"), 0),
		("GUIA DESENVOLVEDOR NVDA",   os.path.join(docs_dir, "developerGuide.md"), 0),
	]
	sections = []
	for label, path, max_c in pairs:
		raw = _read_docs_file(path, max_chars=max_c) if max_c else _read_docs_file(path)
		if raw:
			content = _strip_html_tags(raw) if path.endswith(".html") else raw
			sections.append(f"=== {label} ===\n{content}")
	return "\n\n".join(sections)


def get_docs_assembler(docs_dir: str = _NVDA_DOCS_DIR) -> str:
	"""
	Contexto para Assembler: montagem e validacao do output final.
	Cobre: addonHandler, NVDAState, addonAPIVersion, manifest.ini.tpl,
	estrutura esperada de um addon valido.

	2026-08-16: mesmo aviso de get_docs_manifest_builder() -- o TEMPLATE
	oficial tem "updateChannel", que NAO existe no configspec real.
	"""
	src = os.path.join(docs_dir, "nvda", "source")
	pairs = [
		("addonHandler/__init__.py",  os.path.join(src, "addonHandler", "__init__.py"),  10000),
		("NVDAState.py",              os.path.join(src, "NVDAState.py"),                  0),
		("addonAPIVersion.py",        os.path.join(src, "addonAPIVersion.py"),            0),
		("TEMPLATE: manifest.ini.tpl", os.path.join(docs_dir, "AddonTemplate-master", "manifest.ini.tpl"), 0),
	]
	sections = [
		"AVISO: o TEMPLATE oficial abaixo (manifest.ini.tpl) inclui um "
		"placeholder \"updateChannel\" que NAO existe no configspec real do "
		"NVDA (AddonManifest, addonHandler/__init__.py) -- nunca validar/gerar "
		"manifest.ini com esse campo."
	]
	for label, path, max_c in pairs:
		content = _read_docs_file(path, max_chars=max_c) if max_c else _read_docs_file(path)
		if content:
			sections.append(f"=== {label} ===\n{content}")
	return "\n\n".join(sections)


def get_docs_test_generator(docs_dir: str = _NVDA_DOCS_DIR) -> str:
	"""
	Contexto para TestGenerator: geracao de testes unitarios para addons NVDA.

	Saber como esses modulos funcionam e essencial para gerar testes corretos:
	o TestGenerator precisa mockar apenas o que e externo (nao pode existir
	fora do NVDA), conhecer os contratos reais de cada API, e escrever asserts
	que reflitam comportamento esperado em runtime.

	Cobre: scriptHandler (@script, gestureBindings), globalPluginHandler
	(GlobalPlugin base class), appModuleHandler (AppModule), addonHandler
	(ciclo de vida — terminate), NVDAObjects (eventos, propriedades),
	api (getFocusObject), eventHandler (requestEvents), keyboardHandler
	(KeyboardInputGesture), config (config.conf.spec + persistencia),
	NVDAState (shouldWriteToDisk — modo seguro), speech/commands
	(tipos de SpeechCommand), baseObject (AutoPropertyObject), ui.py.

	Limite total de contexto: ~60k chars (skill: context-compression).
	Para test_generator apenas assinaturas e contratos sao necessarios —
	nao o corpo completo dos arquivos.
	"""
	src = os.path.join(docs_dir, "nvda", "source")
	pairs = [
		("scriptHandler.py",             os.path.join(src, "scriptHandler.py"),              8000),
		("globalPluginHandler.py",       os.path.join(src, "globalPluginHandler.py"),        5000),
		("appModuleHandler.py",          os.path.join(src, "appModuleHandler.py"),            6000),
		("addonHandler/__init__.py",     os.path.join(src, "addonHandler", "__init__.py"),    6000),
		("NVDAObjects/__init__.py",      os.path.join(src, "NVDAObjects", "__init__.py"),     6000),
		("api.py",                       os.path.join(src, "api.py"),                         4000),
		("eventHandler.py",              os.path.join(src, "eventHandler.py"),                4000),
		("keyboardHandler.py",           os.path.join(src, "keyboardHandler.py"),             5000),
		("config/__init__.py",           os.path.join(src, "config", "__init__.py"),          5000),
		("NVDAState.py",                 os.path.join(src, "NVDAState.py"),                   3000),
		("speech/commands.py",           os.path.join(src, "speech", "commands.py"),          4000),
		("baseObject.py",                os.path.join(src, "baseObject.py"),                  4000),
		("extensionPoints/__init__.py",  os.path.join(src, "extensionPoints", "__init__.py"), 4000),
		("ui.py",                        os.path.join(src, "ui.py"),                          3000),
	]
	sections = []
	for label, path, max_c in pairs:
		content = _read_docs_file(path, max_chars=max_c)
		if content:
			sections.append(f"=== NVDA SOURCE: {label} ===\n{content}")
	return "\n\n".join(sections)


def get_docs_agent_runner(docs_dir: str = _NVDA_DOCS_DIR) -> str:
	"""
	Contexto para AgentRunnerAgent: geracao de agent_runner.py para addons
	que embarcam agentes de IA (LLM, historico de conversa, logica de orquestracao).

	Cobre: addonHandler (ciclo de vida — quando destruir o runner), globalPluginHandler
	(onde o runner e instanciado), queueHandler (despachar respostas LLM para a
	thread principal do NVDA), NVDAState (nao escrever em secure mode),
	config/__init__ (persistir api_key e model_id), logHandler (logging correto),
	ui.py (messageBox, browseableMessage para feedback ao usuario).
	"""
	src = os.path.join(docs_dir, "nvda", "source")
	pairs = [
		("addonHandler/__init__.py",  os.path.join(src, "addonHandler", "__init__.py"),  12000),
		("globalPluginHandler.py",    os.path.join(src, "globalPluginHandler.py"),         0),
		("queueHandler.py",           os.path.join(src, "queueHandler.py"),                0),
		("NVDAState.py",              os.path.join(src, "NVDAState.py"),                   0),
		("config/__init__.py",        os.path.join(src, "config", "__init__.py"),         10000),
		("logHandler.py",             os.path.join(src, "logHandler.py"),                 10000),
		("ui.py",                     os.path.join(src, "ui.py"),                          0),
	]
	sections = []
	for label, path, max_c in pairs:
		content = _read_docs_file(path, max_chars=max_c) if max_c else _read_docs_file(path)
		if content:
			sections.append(f"=== NVDA SOURCE: {label} ===\n{content}")
	return "\n\n".join(sections)


def get_docs_agent_template(docs_dir: str = _NVDA_DOCS_DIR) -> str:
	"""
	Contexto para AgentTemplateAgent: geracao de templates .md de agentes
	especializados no padrao Community Access / NVDAStudio.

	O AgentTemplateAgent precisa saber quais APIs existem e como o ecossistema
	de addons funciona para gerar templates tecnicamente corretos, com secoes
	de Invariantes e Referencias que apontem para as APIs reais do NVDA.

	Cobre: addonHandler (ciclo de vida — o agente opera nesse contexto),
	globalPluginHandler (onde agentes de addons sao registrados),
	addonAPIVersion (versoes de API suportadas — para documentar compatibilidade),
	DevGuide readme (convencoes da comunidade NVDA),
	AddonTemplate readme (estrutura padrao de addon para referencia no template).
	"""
	src = os.path.join(docs_dir, "nvda", "source")
	tpl = os.path.join(docs_dir, "AddonTemplate-master")
	pairs = [
		("addonHandler/__init__.py",       os.path.join(src, "addonHandler", "__init__.py"),       10000),
		("globalPluginHandler.py",         os.path.join(src, "globalPluginHandler.py"),             0),
		("addonAPIVersion.py",             os.path.join(src, "addonAPIVersion.py"),                 0),
		("GUIA: DevGuide readme.md",       os.path.join(docs_dir, "DevGuide-master", "readme.md"),  8000),
		("GUIA: AddonTemplate readme.md",  os.path.join(tpl, "readme.md"),                          8000),
	]
	sections = []
	for label, path, max_c in pairs:
		content = _read_docs_file(path, max_chars=max_c) if max_c else _read_docs_file(path)
		if content:
			sections.append(f"=== {label} ===\n{content}")
	return "\n\n".join(sections)
