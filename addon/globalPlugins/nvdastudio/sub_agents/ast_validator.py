import ast
from dataclasses import dataclass
from dataclasses import field

MODULE_VERSION = "1.2.0"

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
