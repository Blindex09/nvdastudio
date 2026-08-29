import ast
from dataclasses import dataclass
from dataclasses import field

MODULE_VERSION = "1.3.0"

# Widgets wx que exigem SetName() logo apos instanciacao
_WX_INTERACTIVE_WIDGETS: frozenset[str] = frozenset(
    ["Button", "TextCtrl", "CheckBox", "Choice", "ListBox"]
)


@dataclass
class ASTValidationResult:
    """Resultado de uma validacao AST.

    ok:        True se nenhuma violacao encontrada.
    violacoes: Lista de descricoes legíveis das violacoes (vazia se ok=True).
    """

    ok: bool
    violacoes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# NVDA-019 — # Translators: obrigatorio imediatamente antes de _()
# ---------------------------------------------------------------------------


def validate_nvda019(codigo: str) -> ASTValidationResult:
    """Verifica NVDA-019: toda _() deve ter '# Translators:' na linha imediatamente anterior.

    Detecta:
      - _("texto")               — chamada direta
      - ui.message(_("texto"))   — aninhada em outra chamada
      - description=_("texto")   — em argumento keyword
      - return _("texto")        — em return
      - msg = _("texto")         — em atribuicao

    Fail-open: SyntaxError retorna ok=True.
    """
    if not codigo or not codigo.strip():
        return ASTValidationResult(ok=True, violacoes=[])

    try:
        tree = ast.parse(codigo)
    except SyntaxError:
        return ASTValidationResult(ok=True, violacoes=[])

    linhas = codigo.splitlines()
    violacoes: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        # Detecta _() como ast.Name(id='_') ou como ast.Attribute(attr='_')
        is_gettext = False
        if isinstance(node.func, ast.Name) and node.func.id == "_":
            is_gettext = True
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "_":
            is_gettext = True

        if not is_gettext:
            continue

        lineno = node.lineno  # 1-indexed
        # Linha imediatamente anterior: lineno - 1 (1-indexed) = lineno - 2 (0-indexed)
        idx_anterior = lineno - 2

        if idx_anterior < 0:
            trecho = linhas[lineno - 1].strip() if lineno <= len(linhas) else "_(...)"
            violacoes.append(
                f"linha {lineno}: {trecho!r} — sem '# Translators:' (primeira linha do arquivo)"
            )
            continue

        linha_anterior = linhas[idx_anterior].strip()
        if not linha_anterior.startswith("# Translators:"):
            trecho = linhas[lineno - 1].strip() if lineno <= len(linhas) else "_(...)"
            violacoes.append(
                f"linha {lineno}: {trecho!r} — sem '# Translators:' na linha anterior"
            )

    return ASTValidationResult(ok=len(violacoes) == 0, violacoes=violacoes)


# ---------------------------------------------------------------------------
# WX-A11Y — SetName() obrigatorio logo apos instanciacao de widget interativo
# ---------------------------------------------------------------------------


def _get_var_name(target: ast.expr) -> str | None:
    """Extrai a representacao textual do target de uma atribuicao para relatorio."""
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        if isinstance(target.value, ast.Name):
            return f"{target.value.id}.{target.attr}"
        return target.attr
    return None


def _is_wx_widget_call(node: ast.expr) -> tuple[bool, str]:
    """Retorna (True, nome_widget) se node e instanciacao de widget wx interativo."""
    if not isinstance(node, ast.Call):
        return False, ""
    func = node.func
    if isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name) and func.value.id == "wx":
            if func.attr in _WX_INTERACTIVE_WIDGETS:
                return True, func.attr
    return False, ""


def _stmt_is_setname_for(stmt: ast.stmt, var_name: str | None) -> bool:
    """Retorna True se stmt e uma chamada var_name.SetName(...) no mesmo objeto."""
    if not isinstance(stmt, ast.Expr):
        return False
    call = stmt.value
    if not isinstance(call, ast.Call):
        return False
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr != "SetName":
        return False
    if var_name is None:
        return True  # sem info suficiente — aceita (fail-open)
    # Verifica chamada em self.btn (ast.Attribute)
    if isinstance(func.value, ast.Attribute):
        if isinstance(func.value.value, ast.Name):
            caller = f"{func.value.value.id}.{func.value.attr}"
            if caller == var_name:
                return True
    # Verifica chamada em variavel simples (ast.Name)
    if isinstance(func.value, ast.Name) and func.value.id == var_name:
        return True
    return False


def _stmt_is_static_text(stmt: ast.stmt) -> bool:
    """Retorna True se stmt e uma atribuicao a partir de wx.StaticText(...)."""
    if not isinstance(stmt, ast.Assign):
        return False
    call = stmt.value
    if not isinstance(call, ast.Call):
        return False
    func = call.func
    return isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) \
        and func.value.id == "wx" and func.attr == "StaticText"


def _call_has_label_kwarg_or_arg(call: ast.Call) -> bool:
    """Retorna True se a chamada tem label= (kwarg) ou um 2o argumento posicional
    (wx.Button(parent, label="...") -- label costuma ser o 2o arg posicional)."""
    for kw in call.keywords:
        if kw.arg == "label":
            return True
    return len(call.args) >= 2


def _check_block_for_wx(stmts: list[ast.stmt]) -> list[str]:
    """
    Percorre lista de statements e detecta widgets wx interativos sem rotulo
    acessivel.

    1.2.0: achado real ao vivo (2026-08-17, comparacao direta com a fonte
    citada -- github.com/Community-Access/accessibility-agents .github/
    agents/wxpython-specialist.agent.md, a fonte REAL de WX-A11Y-001): a
    regra oficial exige wx.StaticText IMEDIATAMENTE ANTES do controle (ou
    label= num wx.Button) -- o exemplo de correcao da fonte NUNCA usa
    SetName(). Um agente irmao do mesmo projeto (desktop-a11y-specialist.
    agent.md) e explicito: "SetName() does NOT affect screen readers -- it
    only sets the internal widget name". A versao anterior desta checagem
    (1.1.0) so verificava SetName() apos o widget -- podia aprovar codigo
    que "parece" acessivel mas nao tem rotulo de verdade pro leitor de tela.
    Agora aceita QUALQUER UM dos 3 sinais (StaticText antes, label= no
    Button, ou SetName() -- mantido como complemento aceitavel, nao mais
    o unico caminho) -- StaticText/label= sao o fix PRIMARIO ensinado pela
    fonte real; SetName() sozinho ainda passa (nao quebra codigo existente
    que ja usa esse padrao amplamente documentado no proprio projeto), mas
    a mensagem de violacao agora recomenda StaticText primeiro.
    """
    violacoes: list[str] = []
    for i, stmt in enumerate(stmts):
        if not isinstance(stmt, ast.Assign):
            continue
        if len(stmt.targets) != 1:
            continue
        is_widget, widget_type = _is_wx_widget_call(stmt.value)
        if not is_widget:
            continue
        var = _get_var_name(stmt.targets[0])
        has_static_text_before = i > 0 and _stmt_is_static_text(stmts[i - 1])
        has_label = widget_type == "Button" and isinstance(stmt.value, ast.Call) \
            and _call_has_label_kwarg_or_arg(stmt.value)
        has_setname_after = i + 1 < len(stmts) and _stmt_is_setname_for(stmts[i + 1], var)
        if has_static_text_before or has_label or has_setname_after:
            continue  # OK — pelo menos 1 sinal de rotulo acessivel presente
        lineno = stmt.lineno
        var_repr = var or "?"
        violacoes.append(
            f"linha {lineno}: {var_repr} = wx.{widget_type}(...) — sem wx.StaticText "
            f"imediatamente antes (fix primario), label= (para Button), nem SetName() logo apos"
        )
    return violacoes


def validate_wx_a11y(codigo: str) -> ASTValidationResult:
    """Verifica WX-A11Y-001: todo widget wx interativo deve ter SetName() logo apos.

    Widgets verificados: wx.Button, wx.TextCtrl, wx.CheckBox, wx.Choice, wx.ListBox.
    Nao verificados (nao-interativos): wx.StaticText, wx.BoxSizer, wx.Panel.

    Fail-open: SyntaxError retorna ok=True.
    """
    if not codigo or not codigo.strip():
        return ASTValidationResult(ok=True, violacoes=[])

    try:
        tree = ast.parse(codigo)
    except SyntaxError:
        return ASTValidationResult(ok=True, violacoes=[])

    violacoes: list[str] = []

    for node in ast.walk(tree):
        # Verifica o bloco de statements direto de cada container
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.Module,
                ast.ClassDef,
            ),
        ):
            violacoes.extend(_check_block_for_wx(node.body))
        elif isinstance(node, (ast.If, ast.For, ast.While)):
            violacoes.extend(_check_block_for_wx(node.body))
            if node.orelse:
                # orelse de if/elif nao e um bloco direto de widgets —
                # sera visitado por ast.walk como nos filhos
                pass
        elif isinstance(node, ast.With):
            violacoes.extend(_check_block_for_wx(node.body))
        elif isinstance(node, ast.Try):
            violacoes.extend(_check_block_for_wx(node.body))
            for handler in node.handlers:
                violacoes.extend(_check_block_for_wx(handler.body))
            if node.orelse:
                violacoes.extend(_check_block_for_wx(node.orelse))
            if node.finalbody:
                violacoes.extend(_check_block_for_wx(node.finalbody))

    return ASTValidationResult(ok=len(violacoes) == 0, violacoes=violacoes)


def _is_wx_panel_or_frame_call(node: ast.expr) -> tuple[bool, str]:
    """Retorna (True, tipo) se node e instanciacao de wx.Panel/wx.Frame."""
    if not isinstance(node, ast.Call):
        return False, ""
    func = node.func
    if isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name) and func.value.id == "wx":
            if func.attr in ("Panel", "Frame"):
                return True, func.attr
    return False, ""


def _collect_set_accelerator_targets(tree: ast.AST) -> set[str]:
    """Coleta objetos que recebem chamada SetAcceleratorTable(...)."""
    targets: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr != "SetAcceleratorTable":
            continue
        obj = func.value
        if isinstance(obj, ast.Name):
            targets.add(obj.id)
        elif isinstance(obj, ast.Attribute) and isinstance(obj.value, ast.Name):
            targets.add(f"{obj.value.id}.{obj.attr}")
    return targets


def validate_wx_a11y_002_accelerators(codigo: str) -> ASTValidationResult:
    """Verifica WX-A11Y-002: wx.Panel/wx.Frame sem SetAcceleratorTable.

    Regra aplicada:
      - Cada atribuicao var = wx.Panel(...) ou var = wx.Frame(...)
        deve ter var.SetAcceleratorTable(...) em algum ponto do codigo.
      - Tambem aceita self.var = wx.Panel(...) seguido de self.var.SetAcceleratorTable(...).

    Fail-open: SyntaxError retorna ok=True.
    """
    if not codigo or not codigo.strip():
        return ASTValidationResult(ok=True, violacoes=[])

    try:
        tree = ast.parse(codigo)
    except SyntaxError:
        return ASTValidationResult(ok=True, violacoes=[])

    with_accel = _collect_set_accelerator_targets(tree)
    violacoes: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        is_panel_or_frame, widget_type = _is_wx_panel_or_frame_call(node.value)
        if not is_panel_or_frame:
            continue
        var = _get_var_name(node.targets[0])
        if var and var in with_accel:
            continue
        lineno = node.lineno
        var_repr = var or "?"
        violacoes.append(
            f"linha {lineno}: {var_repr} = wx.{widget_type}(...) — sem SetAcceleratorTable()"
        )

    return ASTValidationResult(ok=len(violacoes) == 0, violacoes=violacoes)


# ---------------------------------------------------------------------------
# Gestures: normalizacao canonica + verificacao de funcionalidade entregue
#
# LACUNA FECHADA (auditoria 2026-08-29): o pipeline garantia que o addon
# importa, instancia, sobrevive a fault injection, passa no lint e empacota --
# mas NADA garantia que a funcionalidade pedida estava la. `_check_reserved_
# gestures` (addon_builder.py) detecta CONFLITO com atalhos do core; ausencia
# do atalho PEDIDO nao era verificada por ninguem.
#
# DIVISAO SEMANTICO/DETERMINISTICO (README Regra 7): extrair o atalho do pedido
# em linguagem natural com regex seria "simular entendimento semantico", que a
# Regra 7 proibe explicitamente. Entao quem INTERPRETA o pedido e a LLM, no
# campo `expected_gestures` do plano; o codigo aqui so CONFERE que o que foi
# declarado existe de verdade no AST do addon gerado.
# ---------------------------------------------------------------------------

# Nomes de decorator aceitos como declaracao de script do NVDA.
_SCRIPT_DECORATORS: frozenset[str] = frozenset(["script"])


def normalize_gesture(bruto: str) -> str:
    """
    Forma canonica de um gesture do NVDA: fonte em minusculas, prefixo
    explicito, combo em minusculas.

    "NVDA+H" e "kb:nvda+h" sao o MESMO atalho -- tratar como diferentes
    transformaria divergencia de formatacao em falha de funcionalidade.
    Fonte unica: `core/planner.py::_normalize_gestures` importa daqui.
    """
    texto = (bruto or "").strip()
    if not texto:
        return ""
    if ":" not in texto:
        texto = "kb:" + texto
    fonte, _, combo = texto.partition(":")
    return f"{fonte.strip().lower()}:{combo.strip().lower()}"


def _gestures_de_decorator(deco: ast.expr) -> list[str]:
    """Extrai gestures de um decorator @script(gesture=... / gestures=[...])."""
    if not isinstance(deco, ast.Call):
        return []
    nome = deco.func
    alvo = ""
    if isinstance(nome, ast.Name):
        alvo = nome.id
    elif isinstance(nome, ast.Attribute):
        alvo = nome.attr
    if alvo not in _SCRIPT_DECORATORS:
        return []

    achados: list[str] = []
    for kw in deco.keywords:
        if kw.arg == "gesture" and isinstance(kw.value, ast.Constant):
            if isinstance(kw.value.value, str):
                achados.append(kw.value.value)
        elif kw.arg == "gestures" and isinstance(kw.value, (ast.List, ast.Tuple)):
            for elt in kw.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    achados.append(elt.value)
    return achados


def extract_declared_gestures(codigo: str) -> set[str]:
    """
    Coleta todos os gestures que o codigo realmente declara, em forma canonica.

    Cobre os dois padroes validos do NVDA:
      - @script(gesture="kb:NVDA+h") / @script(gestures=["kb:a", "kb:b"])
      - __gestures = {"kb:NVDA+h": "script_x"}  (dict de classe)

    Fail-open: SyntaxError devolve conjunto vazio -- a sintaxe ja e reprovada
    antes, por outro degrau; nao cabe a este validador reportar duas vezes.
    """
    if not codigo or not codigo.strip():
        return set()
    try:
        tree = ast.parse(codigo)
    except SyntaxError:
        return set()

    encontrados: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for deco in node.decorator_list:
                for g in _gestures_de_decorator(deco):
                    canonico = normalize_gesture(g)
                    if canonico:
                        encontrados.add(canonico)
        elif isinstance(node, ast.Assign):
            # __gestures = {...} -- o name mangling da classe vira _Classe__gestures
            # no atributo, mas no AST do ASSIGN o alvo ainda e "__gestures".
            alvos = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if not any(a.endswith("__gestures") or a == "gestures" for a in alvos):
                continue
            if not isinstance(node.value, ast.Dict):
                continue
            for chave in node.value.keys:
                if isinstance(chave, ast.Constant) and isinstance(chave.value, str):
                    canonico = normalize_gesture(chave.value)
                    if canonico:
                        encontrados.add(canonico)

    return encontrados


def validate_declared_gestures(codigo: str, esperados: list[str]) -> ASTValidationResult:
    """
    Confere que cada gesture DECLARADO pela IA no plano existe no codigo gerado.

    `esperados` vem de `ExecutionPlan.expected_gestures` -- ja normalizado pelo
    planner. Lista vazia (addon sem atalho: so menu, so AppModule reagindo a
    evento, controller_client) devolve ok=True sem verificar nada.

    Nao reclama de gesture EXTRA no codigo: um addon pode legitimamente expor
    atalhos auxiliares que o usuario nao enumerou. O que nunca pode faltar e o
    que foi pedido.
    """
    if not esperados:
        return ASTValidationResult(ok=True, violacoes=[])
    if not codigo or not codigo.strip():
        return ASTValidationResult(ok=True, violacoes=[])

    # Fail-open explicito em SyntaxError, igual aos outros validadores deste
    # arquivo. Sem esta checagem o codigo quebrado caia no caminho de
    # "nenhum gesture declarado" e era reprovado por FUNCIONALIDADE FALTANDO --
    # diagnostico errado para um erro de sintaxe, que outro degrau (mais
    # barato e mais preciso) ja reporta corretamente. Bug real pego pelo
    # proprio teste desta funcao antes de ela entrar no pipeline.
    try:
        ast.parse(codigo)
    except SyntaxError:
        return ASTValidationResult(ok=True, violacoes=[])

    declarados = extract_declared_gestures(codigo)
    # Sem NENHUM gesture no codigo o addon pode estar dividido em varios
    # blocos/arquivos e este ser o que nao tem script -- reportar aqui geraria
    # falso positivo em addon multi-arquivo. O orchestrator agrega os blocos
    # antes de chamar, entao "nenhum declarado" so acontece de verdade quando o
    # addon inteiro nao tem script; ainda assim, so reportamos o que falta.
    faltando = [g for g in esperados if normalize_gesture(g) not in declarados]
    if not faltando:
        return ASTValidationResult(ok=True, violacoes=[])

    violacoes = [
        f"atalho '{g}' foi pedido mas nao existe no codigo -- nenhum "
        f"@script(gesture=\"{g}\") nem entrada em __gestures"
        for g in faltando
    ]
    if declarados:
        violacoes.append(
            "atalhos encontrados no codigo: " + ", ".join(sorted(declarados))
        )
    return ASTValidationResult(ok=False, violacoes=violacoes)


# ---------------------------------------------------------------------------
# NVDA-060 — controlTypes.ROLE_*/STATE_* (API REMOVIDA no NVDA 2022.1)
# ---------------------------------------------------------------------------

def validate_nvda060_controltypes(codigo: str) -> ASTValidationResult:
    """
    Detecta o uso da API `controlTypes.ROLE_*` / `controlTypes.STATE_*`.

    Nao e depreciacao: essas constantes foram REMOVIDAS no NVDA 2022.1 e
    substituidas por `controlTypes.Role.*` / `controlTypes.State.*` (enums). Um
    addon que as usa levanta AttributeError em runtime -- para o usuario cego,
    a funcionalidade simplesmente nao acontece, sem nenhuma mensagem.

    Cobre os dois caminhos de uso:
      - acesso por atributo:  controlTypes.ROLE_BUTTON
      - import direto:        from controlTypes import ROLE_BUTTON

    Escolhido para validacao deterministica por ser decidivel sem ambiguidade:
    o nome ou existe no AST ou nao existe. Zero falso positivo possivel, contra
    um defeito que quebra o addon inteiro.

    Fail-open: SyntaxError retorna ok=True.
    """
    if not codigo or not codigo.strip():
        return ASTValidationResult(ok=True, violacoes=[])
    try:
        tree = ast.parse(codigo)
    except SyntaxError:
        return ASTValidationResult(ok=True, violacoes=[])

    violacoes: list[str] = []
    vistos: set[str] = set()

    def _reportar(nome: str, forma: str) -> None:
        if nome in vistos:
            return
        vistos.add(nome)
        moderno = nome.replace("ROLE_", "Role.", 1) if nome.startswith("ROLE_") else nome.replace("STATE_", "State.", 1)
        violacoes.append(
            f"{forma} usa `{nome}`, removido no NVDA 2022.1 -- "
            f"use `controlTypes.{moderno}` (enum)"
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr.startswith(("ROLE_", "STATE_")):
                base = node.value
                if isinstance(base, ast.Name) and base.id == "controlTypes":
                    _reportar(node.attr, f"controlTypes.{node.attr}")
        elif isinstance(node, ast.ImportFrom):
            if node.module != "controlTypes":
                continue
            for alias in node.names:
                if alias.name.startswith(("ROLE_", "STATE_")):
                    _reportar(alias.name, f"from controlTypes import {alias.name}")

    return ASTValidationResult(ok=len(violacoes) == 0, violacoes=violacoes)


# ---------------------------------------------------------------------------
# WX-A11Y-013 — EVT_KEY_DOWN/EVT_CHAR em controles de lista/arvore
# ---------------------------------------------------------------------------

_LIST_TREE_WIDGETS: frozenset[str] = frozenset(
    ["ListBox", "ListCtrl", "TreeCtrl", "DataViewCtrl", "CheckListBox", "ListView"]
)
_EVENTOS_PROIBIDOS: frozenset[str] = frozenset(["EVT_KEY_DOWN", "EVT_CHAR"])


def _alvo_como_texto(node: ast.expr) -> str:
    """Nome legivel de `x`, `self.x` ou `a.b.c` para rastrear a variavel."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _alvo_como_texto(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def validate_wx_a11y_013_key_events(codigo: str) -> ASTValidationResult:
    """
    Detecta `Bind(wx.EVT_KEY_DOWN | wx.EVT_CHAR)` em ListBox/ListCtrl/TreeCtrl/
    DataViewCtrl.

    Nesses controles o wx entrega EVT_KEY_DOWN/EVT_CHAR de forma inconsistente
    quando um leitor de tela esta ativo -- o NVDA e o JAWS interceptam a
    navegacao por setas, e o handler do addon simplesmente nao dispara. E uma
    falha SILENCIOSA: o desenvolvedor testa sem leitor de tela e funciona, o
    usuario cego usa e nao funciona. O evento correto e `EVT_LIST_KEY_DOWN`,
    `EVT_TREE_KEY_DOWN` ou o evento de selecao do proprio controle.

    Rastreia a variavel: so reporta quando o objeto que recebe `.Bind()` foi
    atribuido a partir de um dos widgets da lista acima. `algumaCoisa.Bind(
    wx.EVT_KEY_DOWN, ...)` num wx.Panel ou wx.Dialog NAO e reportado -- nesses
    o evento funciona normalmente.

    Fail-open: SyntaxError retorna ok=True.
    """
    if not codigo or not codigo.strip():
        return ASTValidationResult(ok=True, violacoes=[])
    try:
        tree = ast.parse(codigo)
    except SyntaxError:
        return ASTValidationResult(ok=True, violacoes=[])

    # 1) mapeia variaveis atribuidas a partir de um widget de lista/arvore
    lista_vars: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        tipo = ""
        if isinstance(func, ast.Attribute) and func.attr in _LIST_TREE_WIDGETS:
            tipo = func.attr
        elif isinstance(func, ast.Name) and func.id in _LIST_TREE_WIDGETS:
            tipo = func.id
        if not tipo:
            continue
        for alvo in node.targets:
            nome = _alvo_como_texto(alvo)
            if nome:
                lista_vars[nome] = tipo

    if not lista_vars:
        return ASTValidationResult(ok=True, violacoes=[])

    # 2) procura .Bind(wx.EVT_KEY_DOWN/EVT_CHAR) nessas variaveis
    violacoes: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "Bind" or not node.args:
            continue
        objeto = _alvo_como_texto(node.func.value)
        # Nome distinto do `tipo` do laco acima de proposito: la ele e str
        # (vindo do AST), aqui e str | None (vindo do .get()) -- reusar o mesmo
        # nome faria o mypy reclamar de atribuicao incompativel, com razao.
        tipo_widget = lista_vars.get(objeto)
        if not tipo_widget:
            continue
        evento = node.args[0]
        nome_evt = evento.attr if isinstance(evento, ast.Attribute) else (
            evento.id if isinstance(evento, ast.Name) else ""
        )
        if nome_evt not in _EVENTOS_PROIBIDOS:
            continue
        sugestao = "EVT_TREE_KEY_DOWN" if "Tree" in tipo_widget else "EVT_LIST_KEY_DOWN"
        violacoes.append(
            f"{objeto} (wx.{tipo_widget}) faz Bind de wx.{nome_evt} -- falha silenciosa "
            f"com NVDA/JAWS, que interceptam a navegacao por setas nesse controle. "
            f"Use wx.{sugestao} ou o evento de selecao do proprio controle."
        )

    return ASTValidationResult(ok=len(violacoes) == 0, violacoes=violacoes)


# ---------------------------------------------------------------------------
# NVDA-056 — wx.MessageDialog fora da thread GUI
# ---------------------------------------------------------------------------

def _funcoes_alvo_de_thread(tree: ast.AST) -> set[str]:
    """
    Nomes de funcoes passadas como `target=` para threading.Thread.

    Cobre `target=self.metodo`, `target=metodo` e `target=obj.metodo`. Nao
    resolve lambdas nem callables construidos dinamicamente -- nesses casos a
    checagem simplesmente nao dispara (fail-open por construcao).
    """
    alvos: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        nome_chamada = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else ""
        )
        if nome_chamada != "Thread":
            continue
        for kw in node.keywords:
            if kw.arg != "target":
                continue
            if isinstance(kw.value, ast.Attribute):
                alvos.add(kw.value.attr)
            elif isinstance(kw.value, ast.Name):
                alvos.add(kw.value.id)
    return alvos


def validate_nvda056_messagedialog_thread(codigo: str) -> ASTValidationResult:
    """
    Detecta `wx.MessageDialog` criado ou exibido dentro de uma funcao que roda
    como thread de background, sem `wx.CallAfter`.

    Toda API de UI do wx precisa rodar na thread GUI. Um MessageDialog criado
    numa thread de trabalho e o caso mais comum e mais grave: costuma travar o
    processo do NVDA INTEIRO -- o usuario cego perde a fala e o braille, sem
    nenhuma mensagem, e so recupera reiniciando o leitor de telas.

    Escopo estrito para nao gerar falso positivo: so reporta quando a funcao e
    comprovadamente alvo de `threading.Thread(target=...)` no mesmo arquivo E
    nao ha `wx.CallAfter` dentro dela. MessageDialog na thread principal (o uso
    normal) nunca e reportado.

    Fail-open: SyntaxError retorna ok=True.
    """
    if not codigo or not codigo.strip():
        return ASTValidationResult(ok=True, violacoes=[])
    try:
        tree = ast.parse(codigo)
    except SyntaxError:
        return ASTValidationResult(ok=True, violacoes=[])

    alvos = _funcoes_alvo_de_thread(tree)
    if not alvos:
        return ASTValidationResult(ok=True, violacoes=[])

    violacoes: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in alvos:
            continue

        usa_dialog = False
        usa_callafter = False
        for interno in ast.walk(node):
            if not isinstance(interno, ast.Call):
                continue
            f = interno.func
            if isinstance(f, ast.Attribute):
                if f.attr == "MessageDialog":
                    usa_dialog = True
                elif f.attr == "CallAfter":
                    usa_callafter = True
            elif isinstance(f, ast.Name) and f.id == "MessageDialog":
                usa_dialog = True

        if usa_dialog and not usa_callafter:
            violacoes.append(
                f"{node.name}() roda como threading.Thread e cria wx.MessageDialog "
                f"sem wx.CallAfter -- UI do wx fora da thread GUI costuma travar o "
                f"processo do NVDA inteiro, deixando o usuario sem fala nem braille. "
                f"Envolva a exibicao em wx.CallAfter(...)."
            )

    return ASTValidationResult(ok=len(violacoes) == 0, violacoes=violacoes)
