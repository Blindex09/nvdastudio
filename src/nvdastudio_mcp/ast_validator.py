import ast
from dataclasses import dataclass
from dataclasses import field

MODULE_VERSION = "1.5.0"

# wx widgets that require SetName() right after instantiation
_WX_INTERACTIVE_WIDGETS: frozenset[str] = frozenset(
    ["Button", "TextCtrl", "CheckBox", "Choice", "ListBox"]
)


@dataclass
class ASTValidationResult:
    """Result of an AST validation.

    ok:        True if no violation was found.
    violacoes: List of readable descriptions of the violations (empty if ok=True).
    """

    ok: bool
    violacoes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# NVDA-019 — # Translators: required immediately before _()
# ---------------------------------------------------------------------------


def validate_nvda019(codigo: str) -> ASTValidationResult:
    """Checks NVDA-019: every _() must have '# Translators:' on the immediately preceding line.

    Detects:
      - _("texto")               — direct call
      - ui.message(_("texto"))   — nested in another call
      - description=_("texto")   — in a keyword argument
      - return _("texto")        — in a return
      - msg = _("texto")         — in an assignment

    Fail-open: SyntaxError returns ok=True.
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

        # Detects _() as ast.Name(id='_') or as ast.Attribute(attr='_')
        is_gettext = False
        if isinstance(node.func, ast.Name) and node.func.id == "_":
            is_gettext = True
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "_":
            is_gettext = True

        if not is_gettext:
            continue

        lineno = node.lineno  # 1-indexed
        # Immediately preceding line: lineno - 1 (1-indexed) = lineno - 2 (0-indexed)
        idx_anterior = lineno - 2

        if idx_anterior < 0:
            trecho = linhas[lineno - 1].strip() if lineno <= len(linhas) else "_(...)"
            violacoes.append(
                f"line {lineno}: {trecho!r} — no '# Translators:' (first line of the file)"
            )
            continue

        linha_anterior = linhas[idx_anterior].strip()
        if not linha_anterior.startswith("# Translators:"):
            trecho = linhas[lineno - 1].strip() if lineno <= len(linhas) else "_(...)"
            violacoes.append(
                f"line {lineno}: {trecho!r} — no '# Translators:' on the previous line"
            )

    return ASTValidationResult(ok=len(violacoes) == 0, violacoes=violacoes)


# ---------------------------------------------------------------------------
# WX-A11Y — SetName() required right after instantiating an interactive widget
# ---------------------------------------------------------------------------


def _get_var_name(target: ast.expr) -> str | None:
    """Extracts the textual representation of an assignment target for reporting."""
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        if isinstance(target.value, ast.Name):
            return f"{target.value.id}.{target.attr}"
        return target.attr
    return None


def _is_wx_widget_call(node: ast.expr) -> tuple[bool, str]:
    """Returns (True, widget_name) if node is the instantiation of an interactive wx widget."""
    if not isinstance(node, ast.Call):
        return False, ""
    func = node.func
    if isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name) and func.value.id == "wx":
            if func.attr in _WX_INTERACTIVE_WIDGETS:
                return True, func.attr
    return False, ""


def _stmt_is_setname_for(stmt: ast.stmt, var_name: str | None) -> bool:
    """Returns True if stmt is a var_name.SetName(...) call on the same object."""
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
        return True  # not enough info — accept (fail-open)
    # Checks a call on self.btn (ast.Attribute)
    if isinstance(func.value, ast.Attribute):
        if isinstance(func.value.value, ast.Name):
            caller = f"{func.value.value.id}.{func.value.attr}"
            if caller == var_name:
                return True
    # Checks a call on a simple variable (ast.Name)
    if isinstance(func.value, ast.Name) and func.value.id == var_name:
        return True
    return False


def _stmt_is_static_text(stmt: ast.stmt) -> bool:
    """Returns True if stmt is an assignment from wx.StaticText(...)."""
    if not isinstance(stmt, ast.Assign):
        return False
    call = stmt.value
    if not isinstance(call, ast.Call):
        return False
    func = call.func
    return isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) \
        and func.value.id == "wx" and func.attr == "StaticText"


def _call_has_label_kwarg_or_arg(call: ast.Call) -> bool:
    """Returns True if the call has label= (kwarg) or a 2nd positional argument
    (wx.Button(parent, label="...") -- label is usually the 2nd positional arg)."""
    for kw in call.keywords:
        if kw.arg == "label":
            return True
    return len(call.args) >= 2


def _check_block_for_wx(stmts: list[ast.stmt]) -> list[str]:
    """
    Walks a list of statements and detects interactive wx widgets without an
    accessible label.

    cited -- github.com/Community-Access/accessibility-agents .github/
    agents/wxpython-specialist.agent.md, the REAL source of WX-A11Y-001): the
    official rule requires wx.StaticText IMMEDIATELY BEFORE the control (or
    label= on a wx.Button) -- the source's fix example NEVER uses
    SetName(). A sibling agent of the same project (desktop-a11y-specialist.
    agent.md) is explicit: "SetName() does NOT affect screen readers -- it
    only sets the internal widget name". The previous version of this check
    (1.1.0) only verified SetName() after the widget -- it could approve code
    that "looks" accessible but has no real label for the screen reader.
    It now accepts ANY ONE of 3 signals (StaticText before, label= on
    Button, or SetName() -- kept as an acceptable complement, no longer
    the only path) -- StaticText/label= are the PRIMARY fix taught by the
    real source; SetName() alone still passes (it does not break existing
    code that already uses this pattern, widely documented in the project
    itself), but the violation message now recommends StaticText first.
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
            continue  # OK — at least 1 accessible label signal present
        lineno = stmt.lineno
        var_repr = var or "?"
        violacoes.append(
            f"line {lineno}: {var_repr} = wx.{widget_type}(...) — no wx.StaticText "
            f"immediately before (primary fix), label= (for Button), nor SetName() right after"
        )
    return violacoes


def validate_wx_a11y(codigo: str) -> ASTValidationResult:
    """Checks WX-A11Y-001: every interactive wx widget must have SetName() right after.

    Widgets checked: wx.Button, wx.TextCtrl, wx.CheckBox, wx.Choice, wx.ListBox.
    Not checked (non-interactive): wx.StaticText, wx.BoxSizer, wx.Panel.

    Fail-open: SyntaxError returns ok=True.
    """
    if not codigo or not codigo.strip():
        return ASTValidationResult(ok=True, violacoes=[])

    try:
        tree = ast.parse(codigo)
    except SyntaxError:
        return ASTValidationResult(ok=True, violacoes=[])

    violacoes: list[str] = []

    for node in ast.walk(tree):
        # Checks the direct statement block of each container
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
                # the orelse of if/elif is not a direct block of widgets —
                # it will be visited by ast.walk as child nodes
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
    """Returns (True, type) if node is the instantiation of wx.Panel/wx.Frame."""
    if not isinstance(node, ast.Call):
        return False, ""
    func = node.func
    if isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name) and func.value.id == "wx":
            if func.attr in ("Panel", "Frame"):
                return True, func.attr
    return False, ""


def _collect_set_accelerator_targets(tree: ast.AST) -> set[str]:
    """Collects objects that receive a SetAcceleratorTable(...) call."""
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
    """Checks WX-A11Y-002: wx.Panel/wx.Frame without SetAcceleratorTable.

    Rule applied:
      - Each assignment var = wx.Panel(...) or var = wx.Frame(...)
        must have var.SetAcceleratorTable(...) somewhere in the code.
        - Also accepts self.var = wx.Panel(...) followed by self.var.SetAcceleratorTable(...).

    Fail-open: SyntaxError returns ok=True.
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
            f"line {lineno}: {var_repr} = wx.{widget_type}(...) — no SetAcceleratorTable()"
        )

    return ASTValidationResult(ok=len(violacoes) == 0, violacoes=violacoes)


# ---------------------------------------------------------------------------
# NVDA-060 — controlTypes.ROLE_*/STATE_* (legacy aliases, kept only for compatibility)
# ---------------------------------------------------------------------------

def validate_nvda060_controltypes(codigo: str) -> ASTValidationResult:
    """
    Detects the use of the `controlTypes.ROLE_*` / `controlTypes.STATE_*` API.

    These constants were replaced by `controlTypes.Role.*` / `controlTypes.State.*`
    (enums). NVDA still exposes them in controlTypes/deprecatedAliases.py, "only for
    compatibility with add-ons"; they work today, but they are legacy and must not be
    used in new code.

    Covers both usage paths:
      - attribute access:  controlTypes.ROLE_BUTTON
      - direct import:     from controlTypes import ROLE_BUTTON

    It is decidable without ambiguity: the name either exists in the AST or it does not.

    Fail-open: SyntaxError returns ok=True.
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
            f"{forma} uses `{nome}`, a legacy alias kept only for compatibility -- "
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
# WX-A11Y-013 — EVT_KEY_DOWN/EVT_CHAR on list/tree controls
# ---------------------------------------------------------------------------

_LIST_TREE_WIDGETS: frozenset[str] = frozenset(
    ["ListBox", "ListCtrl", "TreeCtrl", "DataViewCtrl", "CheckListBox", "ListView"]
)
_EVENTOS_PROIBIDOS: frozenset[str] = frozenset(["EVT_KEY_DOWN", "EVT_CHAR"])


def _alvo_como_texto(node: ast.expr) -> str:
    """Readable name of `x`, `self.x` or `a.b.c` for tracking the variable."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _alvo_como_texto(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def validate_wx_a11y_013_key_events(codigo: str) -> ASTValidationResult:
    """
    Detects `Bind(wx.EVT_KEY_DOWN | wx.EVT_CHAR)` on ListBox/ListCtrl/TreeCtrl/
    DataViewCtrl.

    On these controls wx delivers EVT_KEY_DOWN/EVT_CHAR inconsistently
    when a screen reader is active -- NVDA and JAWS intercept arrow-key
    navigation, and the add-on's handler simply does not fire. It is a SILENT
    failure: the developer tests without a screen reader and it works, the
    screen reader user tries it and it does not. The right event is `EVT_LIST_KEY_DOWN`,
    `EVT_TREE_KEY_DOWN` or the control's own selection event.

    Tracks the variable: it only reports when the object that receives `.Bind()` was
    assigned from one of the widgets listed above. `something.Bind(
    wx.EVT_KEY_DOWN, ...)` on a wx.Panel or wx.Dialog is NOT reported -- on those
    the event works normally.

    Fail-open: SyntaxError returns ok=True.
    """
    if not codigo or not codigo.strip():
        return ASTValidationResult(ok=True, violacoes=[])
    try:
        tree = ast.parse(codigo)
    except SyntaxError:
        return ASTValidationResult(ok=True, violacoes=[])

    # 1) maps variables assigned from a list/tree widget
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

    # 2) looks for .Bind(wx.EVT_KEY_DOWN/EVT_CHAR) on those variables
    violacoes: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "Bind" or not node.args:
            continue
        objeto = _alvo_como_texto(node.func.value)
        # Name deliberately distinct from `tipo` in the loop above: there it is str
        # (from the AST), here it is str | None (from .get()) -- reusing the same
        # name would make mypy complain about an incompatible assignment, rightly.
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
            f"{objeto} (wx.{tipo_widget}) binds wx.{nome_evt} -- silent failure "
            f"with NVDA/JAWS, which intercept arrow-key navigation on this control. "
            f"Use wx.{sugestao} or the control's own selection event."
        )

    return ASTValidationResult(ok=len(violacoes) == 0, violacoes=violacoes)


# ---------------------------------------------------------------------------
# NVDA-056 — wx.MessageDialog outside the GUI thread
# ---------------------------------------------------------------------------

def _funcoes_alvo_de_thread(tree: ast.AST) -> set[str]:
    """
    Names of functions passed as `target=` to threading.Thread.

    Covers `target=self.metodo`, `target=metodo` and `target=obj.metodo`. It does not
    resolve lambdas or dynamically built callables -- in those cases the
    check simply does not fire (fail-open by construction).
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
    Detects `wx.MessageDialog` created or shown inside a function that runs
    as a background thread, without `wx.CallAfter`.

    Every wx UI API must run on the GUI thread. A MessageDialog created
    on a worker thread is the most common and most serious case: it tends to freeze the
    ENTIRE NVDA process -- the screen reader user loses speech and braille, with
    no message, and only recovers by restarting the screen reader.

    Strict scope to avoid false positives: it only reports when the function is
    provably the target of `threading.Thread(target=...)` in the same file AND
    there is no `wx.CallAfter` inside it. A MessageDialog on the main thread (the
    normal use) is never reported.

    Fail-open: SyntaxError returns ok=True.
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
                f"{node.name}() runs as a threading.Thread and creates a wx.MessageDialog "
                f"without wx.CallAfter -- wx UI outside the GUI thread tends to freeze the "
                f"entire NVDA process, leaving the user without speech or braille. "
                f"Wrap the display in wx.CallAfter(...)."
            )

    return ASTValidationResult(ok=len(violacoes) == 0, violacoes=violacoes)


# ---------------------------------------------------------------------------
# NVDA-064 -- button callback of gui.message.MessageDialog
# ---------------------------------------------------------------------------

_DIALOG_BUTTON_METHODS = frozenset({
    "addButton", "addOkButton", "addCancelButton", "addYesButton", "addNoButton",
    "addSaveButton", "addApplyButton", "addCloseButton", "addHelpButton",
    "addDontSaveButton",
})


def _accepts_one_positional(args: ast.arguments, skip_self: bool) -> bool:
    positional = [*args.posonlyargs, *args.args]
    if skip_self and positional:
        positional = positional[1:]
    if args.vararg is not None:
        return True
    required = len(positional) - len(args.defaults)
    return len(positional) >= 1 and required <= 1


def validate_nvda064_dialog_callback(codigo: str) -> ASTValidationResult:
    """
    NVDA calls the callback of a MessageDialog button with ONE positional argument
    (a `Payload`): `callback(payload)` (gui/message.py). `lambda: ...` or a method with no
    parameter besides `self` raises TypeError when the button is activated, and the button
    simply does nothing for the screen reader user.

    It only reports when the callback is a lambda or a function/method defined in the
    file itself, where the signature is a fact. Fail-open: SyntaxError returns ok=True.
    """
    if not codigo or not codigo.strip():
        return ASTValidationResult(ok=True, violacoes=[])
    try:
        tree = ast.parse(codigo)
    except SyntaxError:
        return ASTValidationResult(ok=True, violacoes=[])

    definicoes: dict[str, tuple[ast.arguments, bool]] = {}
    for classe in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        for item in classe.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                definicoes.setdefault(item.name, (item.args, True))
    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            definicoes[item.name] = (item.args, False)

    violacoes: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        nome = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        if nome not in _DIALOG_BUTTON_METHODS and nome != "Button":
            continue
        for kw in node.keywords:
            if kw.arg != "callback":
                continue
            valor = kw.value
            if isinstance(valor, ast.Lambda):
                if not _accepts_one_positional(valor.args, skip_self=False):
                    violacoes.append(
                        f"line {node.lineno}: the callback=lambda of {nome}() does not accept the argument "
                        f"that NVDA passes (payload); use `lambda payload: ...`."
                    )
                continue
            alvo = ""
            if isinstance(valor, ast.Name):
                alvo = valor.id
            elif isinstance(valor, ast.Attribute) and isinstance(valor.value, ast.Name) and valor.value.id == "self":
                alvo = valor.attr
            if alvo in definicoes:
                args, eh_metodo = definicoes[alvo]
                skip = eh_metodo and isinstance(valor, ast.Attribute)
                if not _accepts_one_positional(args, skip_self=skip):
                    violacoes.append(
                        f"line {node.lineno}: the callback '{alvo}' of {nome}() does not accept the argument "
                        f"that NVDA passes (payload); declare `def {alvo}(self, payload)`."
                    )
    return ASTValidationResult(ok=len(violacoes) == 0, violacoes=violacoes)


# ---------------------------------------------------------------------------
# Full set, used by the MCP server in addon_validate
# ---------------------------------------------------------------------------

AST_RULES = (
    ("NVDA-019", validate_nvda019),
    ("WX-A11Y-001", validate_wx_a11y),
    ("WX-A11Y-002", validate_wx_a11y_002_accelerators),
    ("NVDA-060", validate_nvda060_controltypes),
    ("WX-A11Y-013", validate_wx_a11y_013_key_events),
    ("NVDA-056", validate_nvda056_messagedialog_thread),
    ("NVDA-064", validate_nvda064_dialog_callback),
)


def validate_all(codigo: str) -> list[tuple[str, str]]:
    """Runs all AST rules and returns (rule code, violation) pairs."""
    found: list[tuple[str, str]] = []
    for rule_id, validator in AST_RULES:
        found.extend((rule_id, v) for v in validator(codigo).violacoes)
    return found
