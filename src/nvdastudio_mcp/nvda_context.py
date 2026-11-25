import os

from .project_policy import (
	ABSOLUTE_MIN_NVDA,
	PROJECT_LAST_TESTED_NVDA,
	PROJECT_MIN_NVDA,
	PROJECT_SUPPORTED_RANGE,
)


# ------------------------------------------------------------------
# Regras de deteccao NVDA-001..040, NVDA-042..050
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
	# wx.MessageDialog nao e anunciado corretamente pelo NVDA e o foco pode nao funcionar como esperado pelo usuario de leitor de tela.
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
	# oficial (github.com/nvdaaddons/DevGuide, download.nvaccess.org/documentation/developerGuide.html,
	# github.com/nvaccess/AddonTemplate, guia de submissao da Add-on Store). Diferente de
	# NVDA-019..054 (nascidas de bugs reais de producao), estas sao PREVENTIVAS -- praticas
	# que a documentacao oficial exige mas nunca tinham causado um bug real no nvdastudio ainda.
	("NVDA-055", "Serio",    "Import de pacote pip empacotado junto com o NVDA (ex: comtypes, wx, requests da instalacao do NVDA) em vez de bundlar a propria dependencia em lib/ -- pacotes empacotados com o NVDA podem ser atualizados, rebaixados ou removidos a qualquer momento sem aviso; NAO sao API estavel do addon"),
	("NVDA-056", "Critico",  "wx.MessageDialog instanciado, inicializado ou exibido (ShowModal ou Show) fora da thread GUI -- a maioria dos metodos de MessageDialog NAO e thread-safe; chamar de thread nao-GUI pode causar crash ou comportamento imprevisivel, nao so travamento"),
	("NVDA-057", "Moderado", "@script sem usar as constantes SCRCAT_* para o parametro category (usa string livre em vez disso), ou ignora os flags canPropagate/bypassInputHelp/allowInSleepMode/speakOnDemand/resumeSayAllMode quando o script deveria funcionar durante Input Help, modo de sono, modo de fala sob demanda do NVDA, ou precisa retomar o Say All apos ser executado"),
	("NVDA-058", "Moderado", "installTasks.py ou uninstallTasks.py importa modulos alem do estritamente necessario -- onInstall()/onUninstall() rodam num estado restrito (pre-reinicio do NVDA, pasta .pendingInstall); imports desnecessarios aumentam risco de falha nesse estado"),
	("NVDA-059", "Serio",    "manifest.ini com addonId/name contendo caracteres fora de letras, numeros, underscore e hifen (ex: espaco, ponto, unicode) -- a Add-on Store valida o nome com uma regex restrita; caracteres fora desse conjunto rejeitam a submissao"),
	# Developer Guide oficial (download.nvaccess.org/documentation/developerGuide.html
	# 2026.1.1), 2 gaps de conteudo reais encontrados (nao existia regra
	# equivalente, nao e so ajuste de callback/fallback).
	("NVDA-060", "Critico",  "Uso de controlTypes.ROLE_*/controlTypes.STATE_* (API pre-2021.2, REMOVIDA no NVDA 2022.1) em vez de controlTypes.Role.*/controlTypes.State.* -- baseline do projeto e NVDA 2026.1.1, entao codigo com a forma antiga falha ao carregar (AttributeError), nao so gera warning de deprecacao"),
	("NVDA-061", "Moderado", "Character Descriptions ausente ou mal formatado: addon com necessidade de descrever caracteres individualmente (ex: driver de fala, dicionario fonetico) sem locale/<lang>/characterDescriptions.dic em UTF-8 com pares caractere/descricao separados por TAB, linhas em branco e comentarios '#' ignorados (skill: nvda-addon-dev, Developer Guide secao 'Character Descriptions')"),
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
	# ate agora nao mora dentro de arquivo nenhum: mora na costura. O addon
	# entregue tinha __init__.py chamando proofread(text, model, api_key,
	# on_done, on_error) -- assinatura que ele MESMO declarava num
	# comentario de contrato -- e openai_service.py definindo
	# proofread(self, text, callback). Carregou, registrou os atalhos,
	# passou nos nove portoes, e morria de TypeError na primeira tecla.
	("NVDA-063", "Critico", "Chamada entre arquivos do addon com assinatura "
	 "divergente da definicao -- arquivo A chama metodo/funcao de B com argumento "
	 "que B nao aceita, ou sem argumento obrigatorio que B exige. Cada arquivo e "
	 "valido sozinho e o addon carrega normalmente; o TypeError so nasce quando o "
	 "usuario aciona o comando, e o `except Exception` correto do addon (que existe "
	 "para nunca derrubar o leitor de tela) transforma o defeito numa mensagem "
	 "generica. Quando um arquivo DECLARA o contrato que outro implementa, os dois "
	 "lados tem que casar literalmente"),
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
	"""Formata a matriz de fallback por regra para o guia."""
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
# ------------------------------------------------------------------

NVDA_GUIDE = f"""TEXTO HUMANO DO ADDON (summary, description e changelog do manifest.ini, userGuide.html,
mensagens de UI): em portugues do Brasil correto, com todos os acentos e cedilhas.
Isso NAO se aplica a identificadores tecnicos (nomes de campo do manifest, de variavel).

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
NVDA-062 Critico: SECURE MODE em CADA ponto de entrada perigoso.
  Em secure mode (tela de login, UAC, tela segura) os scripts do addon CONTINUAM
  executaveis: eles sao definidos a nivel de classe, entao checar o flag so no
  __init__ e sair cedo NAO impede o script de rodar. Cada entrada que le
  credencial, abre arquivo, salva config ou faz requisicao externa precisa da
  propria checagem, ANTES de tocar no dado sensivel.
  Errado (checa so no __init__ -- o script roda mesmo assim):
    class GlobalPlugin(globalPluginHandler.GlobalPlugin):
      def __init__(self):
        super().__init__()
        if globalVars.appArgs.secure:
          return
      @script(gesture="kb:NVDA+shift+r")
      def script_resumir(self, gesture):
        chave = config.conf["MeuAddon"]["apiKey"]   # roda em secure mode!
  Correto (cada ponto de entrada se protege, e AVISA o usuario):
    import globalVars
    import ui

    def _bloqueado_em_modo_seguro():
      if globalVars.appArgs.secure:
        # Translators: mensagem quando a funcao esta indisponivel na tela segura
        ui.message(_("Indisponivel no modo seguro do NVDA."))
        return True
      return False

    @script(gesture="kb:NVDA+shift+r")
    def script_resumir(self, gesture):
      if _bloqueado_em_modo_seguro():
        return
      chave = config.conf["MeuAddon"]["apiKey"]
  O MESMO vale para makeSettings()/onSave() de um SettingsPanel: NAO leia a
  chave de API para depois desabilitar o controle -- desabilitar depois nao
  desfaz a leitura. Cheque antes de ler.
  E NUNCA logue senha, token ou chave de API, em modo nenhum.

NVDA-UX-002 / NVDA-016: falha bloqueada tem que ser FALADA.
  Quando a gravacao e barrada por modo seguro ou por
  NVDAState.shouldWriteToDisk(), registrar um warning no log nao basta: o
  usuario de leitor de tela apertou salvar e nao ouviu nada, entao para ele a acao funcionou.
  Sempre ui.message() explicando que a alteracao nao foi salva.

WX-A11Y-004 Serio: dialogo precisa de botoes padrao e de Escape.
  Errado (sem sizer padrao -- Escape nao fecha, e a ordem de foco fica errada):
    sizer.Add(wx.Button(self, label=_("OK")))
  Correto:
    botoes = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
    sizer.Add(botoes, flag=wx.EXPAND | wx.ALL, border=5)
  wx.OK/wx.CANCEL dao rotulo traduzido pelo sistema, ordem de tabulacao correta
  e fechamento por Escape sem codigo extra.

NVDA-021 Moderado: Indentacao com espacos em vez de TABS. E o padrao do NVDA e do
  AddonTemplate: use TAB na indentacao de todo arquivo .py do addon.
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
  NOTA DE TERMINOLOGIA: "addonId" abaixo e
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
    manifest.ini: name=GmailSummarizer  ->  config.conf["GmailSummarizer"]
    manifest.ini: name=LeitorRSS        ->  config.conf["LeitorRSS"]
    manifest.ini: name=TraducaoRapida   ->  config.conf["TraducaoRapida"]

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
  Manifest.ini completo (base + brailleTables):
    Arquivo: manifest.ini
```ini
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
    Arquivo: brailleTables/pt-br-grade2.utb
```ini
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
    Arquivo: locale/en/symbols-greek.dic
```ini
    symbols:
    alpha[TAB]alpha[TAB]all[TAB]
    beta[TAB]beta[TAB]all[TAB]
    gamma[TAB]gamma[TAB]all[TAB]
    pi[TAB]pi[TAB]all[TAB]
    ```
  Importante: [TAB] representa um caractere TAB real (0x09) no arquivo gerado.
  Manifest.ini exemplo:
    Arquivo: manifest.ini
```ini
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
    Arquivo: locale/it/gestures.ini
```ini
    [globalCommands.GlobalCommands]
    leftMouseClick = kb(laptop):NVDA+e
    rightMouseClick = kb(laptop):NVDA+plus
    ```
  Use kb(laptop): para gestos especificos do layout laptop.

NVDA-046 Moderado: Speech Dictionaries — corrija pronuncia via speechDicts/.
  OBRIGATORIO: crie o arquivo speechDicts/<nome>.dic. Sem o arquivo fisico nenhuma pronuncia e corrigida.
  O addon DEVE incluir esse arquivo — a ausencia do .dic e um erro fatal.
  CRITICO: cada linha tem EXATAMENTE 4 campos separados por TAB real (U+0009, \t).
  NAO use espacos como separadores. O NVDA rejeita linhas com numero errado de campos.
  Estrutura: padrao\treposicao\tcase_sensitive\ttipo
  Tipos: 0=em qualquer lugar, 1=regex Python, 2=palavra inteira, 3=parte de palavra, 6=wildcards.
  case_sensitive: 0=ignorar maiusculas, 1=sensivel.
  Exemplo speechDicts/pronuncia.dic (cada | representa um TAB real U+0009):
    Arquivo: speechDicts/pronuncia.dic
```ini
    NVDA	NonVisual Desktop Access	1	2
    API	A-P-I	1	2
    HTTP	H-T-T-P	0	2
    ```
  Declare no manifest.ini:
    [speechDictionaries]
    [[pronuncia]]
    displayName = Correcoes de Pronuncia
    mandatory = false
  mandatory=true -> sempre ativo. mandatory=false -> usuario ativa em NVDA Settings > Fala.
  NOTA: os inteiros 0/1/2/3/6 acima sao o FORMATO DO ARQUIVO .dic
  (coluna "tipo", separada por TAB) -- continuam sendo a forma correta e
  estavel de escrever o arquivo .dic em si, nao mudam. O que foi depreciado
  em NVDA 2026.2 e so a API Python interna equivalente (speechDictHandler.
  ENTRY_TYPE_* -> speechDictHandler.types.EntryType) para addons que
  constroem entradas de dicionario PROGRAMATICAMENTE em codigo (raro --
  a grande maioria dos addons so declara o .dic estatico, como acima). Se o
  o codigo algum dia precisar criar entradas via Python em vez do
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
	NOTA: "dependencies[]" e uma estrutura
	INTERNA do NVDAStudio (a lista de pacotes pip declarada pro
	builder.py saber o que baixar/empacotar em lib/) -- nao e um campo do
	manifest.ini real do NVDA (addonHandler/__init__.py, AddonManifest, nao
	define "dependencies"). Nao confundir com nada que o NVDA core valide.

NVDA-040 Serio: AppModule para wwahost.exe (apps UWP) DEVE herdar de nvdaBuiltin.appModules.wwahost.AppModule.
  wwahost.exe hospeda apps UWP (Microsoft Store). O NVDA built-in ja trata IA2 e ativacao especial.
  Herdar APENAS de appModuleHandler.AppModule para wwahost.exe ignora esse comportamento — BUG CRITICO.
  Arquivo obrigatorio: appModules/wwahost.py
  Template:
    Arquivo: appModules/wwahost.py
```python
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
  JUSTIFICATIVA REAL:
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
    Arquivo: brailleDisplayDrivers/NOME.py
```python
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
  wx.MessageDialog/wx.MessageBox nao sao anunciados corretamente pelo NVDA; o foco pode nao funcionar como esperado pelo usuario de leitor de tela.
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

Arquivo: manifest.ini
```ini
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

Arquivo: installTasks.py
```python
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

Arquivo: globalPlugins/nomeAddon/__init__.py
```python
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

Arquivo: globalPlugins/meuAddon/__init__.py
```python
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

Arquivo: globalPlugins/meuAddon/meu_painel.py
```python
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
Arquivo: globalPlugins/meuAddon/__init__.py
```python
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
Arquivo: globalPlugins/meuAddon/__init__.py
```python
# 200+ linhas misturando wx, requests, lÃ³gica de negÃ³cio...
```

CORRETO:
Arquivo: globalPlugins/meuAddon/transcricao_service.py
```python
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

Arquivo: globalPlugins/meuAddon/__init__.py
```python
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
Arquivo: globalPlugins/meuAddon/settings_panel.py
```python
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

5. APPMODULE — ADDON PARA UM APP ESPECIFICO (ARCH-003):
Use AppModule quando o pedido menciona UM aplicativo especifico (Notepad, Firefox, Word, etc.).
Arquivo: appModules/<nome_do_exe>.py  (ex: notepad.py para notepad.exe)
NUNCA use o nome exibido ao usuario — use o nome do processo .exe SEM a extensao.
NVDA-033: event_NVDAObject_init so funciona em AppModule, NUNCA em GlobalPlugin.
NVDA-034: se o app for self-voicing (TTS proprio), adicione sleepMode = True.
Arquivo: appModules/notepad.py
```python
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
INFERENCIA ARCH-003: qual tipo de addon criar?
- pede para app especifica -> AppModule
  "addon para Notepad" -> appModules/notepad.py
  "addon para Firefox" -> appModules/firefox.py (ou waterfox, librewolf, etc.)
  "addon para wwahost" -> NVDA-040: use nvdaBuiltin.appModules.wwahost.AppModule como base
  "addon para msedgewebview2" -> NVDA-027: inclua disableBrowseModeByDefault = True
  "app com TTS proprio / self-voicing" -> NVDA-034: inclua sleepMode = True
- funcionalidade global (qualquer app) -> GlobalPlugin
  "anunciar area de transferencia", "atalho global", "addon de traducao", etc.
- driver de sintetizador -> SynthDriver
  "novo sintetizador", "TTS", "engine de fala", "driver de voz", etc.
  Arquivo: synthDrivers/<nome>.py. Requer: speak(), cancel() (NVDA-031), pause(), check().
- driver de display braille -> BrailleDisplayDriver
  "display braille", "linha braille", "braille display", "driver braille", etc.
  Arquivo: brailleDisplayDrivers/<nome>.py. Requer: campos obrigatorios (NVDA-037).
- ambiguidade -> pergunte a pessoa antes de gerar.
  Se o tipo nao puder ser inferido, colete o contexto necessario.

6. EXTENSION POINTS — CUSTOMIZACAO GLOBAL DE SPEECH/FOCO (ARCH-006):
Use extensionPoints quando precisar filtrar ou modificar fala, foco ou braille GLOBALMENTE.
NVDA-032: TODO .register() em __init__ DEVE ter .unregister() em terminate() — memory leak garantido.
Arquivo: globalPlugins/meuAddon/__init__.py
```python
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
    (5o tipo documentado no Developer Guide oficial,
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

AO ENTREGAR UM ADDON:
manifest.ini completo; codigo Python completo com docstrings e terminate();
verificacao de todas as regras NVDA-001 a NVDA-040, NVDA-042..NVDA-062 e WX-A11Y-001 a WX-A11Y-014 (use addon_validar);
inferencia arquitetural ARCH-001..009 antes de escrever o codigo.
"""

# Copia local do codigo-fonte do NVDA e do AddonTemplate (texto, nunca importada).
NVDA_DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nvda_docs_cache")
