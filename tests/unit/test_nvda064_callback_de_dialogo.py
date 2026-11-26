"""NVDA-064: o NVDA chama callback(payload) nos botoes de gui.message.MessageDialog."""

from nvdastudio_mcp.ast_validator import validate_nvda064_dialog_callback

NL = chr(10)
TAB = chr(9)


def _codigo(*linhas: str) -> str:
    return NL.join(linhas) + NL


def test_lambda_sem_argumento_e_reportada():
    r = validate_nvda064_dialog_callback(_codigo("dlg.addOkButton(callback=lambda: salvar())"))
    assert not r.ok and "payload" in r.violacoes[0]


def test_lambda_com_payload_passa():
    assert validate_nvda064_dialog_callback(_codigo("dlg.addOkButton(callback=lambda payload: salvar())")).ok


def test_metodo_so_com_self_e_reportado():
    codigo = _codigo(
        "class P:",
        TAB + "def salvar(self):",
        TAB + TAB + "pass",
        TAB + "def abrir(self, dlg):",
        TAB + TAB + "dlg.addButton(callback=self.salvar)",
    )
    r = validate_nvda064_dialog_callback(codigo)
    assert not r.ok and "salvar" in r.violacoes[0]


def test_metodo_com_payload_passa():
    codigo = _codigo(
        "class P:",
        TAB + "def salvar(self, payload):",
        TAB + TAB + "pass",
        TAB + "def abrir(self, dlg):",
        TAB + TAB + "dlg.addButton(callback=self.salvar)",
    )
    assert validate_nvda064_dialog_callback(codigo).ok


def test_callback_desconhecido_nao_e_acusado():
    assert validate_nvda064_dialog_callback(_codigo("dlg.addButton(callback=vem_de_fora)")).ok


def test_codigo_sem_dialogo_e_sintaxe_invalida_sao_ok():
    assert validate_nvda064_dialog_callback("x = 1" + NL).ok
    assert validate_nvda064_dialog_callback("def (:" + NL).ok


def test_staticmethod_com_o_payload_como_unico_parametro_passa():
    """Caso real: gui/__init__.py do NVDA usa @staticmethod def _copyVersionToClipboard(p: Payload)."""
    codigo = _codigo(
        "class P:",
        TAB + "@staticmethod",
        TAB + "def copiar(p):",
        TAB + TAB + "pass",
        TAB + "def abrir(self, dlg):",
        TAB + TAB + "dlg.addButton(callback=self.copiar)",
    )
    assert validate_nvda064_dialog_callback(codigo).ok
