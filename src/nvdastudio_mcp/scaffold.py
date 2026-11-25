"""Esqueleto de um addon NVDA novo, ja conforme as regras do validador.

O esqueleto e so o ponto de partida: o Claude decide o que o addon faz e
reescreve o codigo. Aqui fica apenas o que e fato do formato do NVDA
(manifest, estrutura de pastas, ganchos obrigatorios).
"""

import re
from dataclasses import dataclass

from .project_policy import PROJECT_LAST_TESTED_NVDA, PROJECT_MIN_NVDA

KINDS = ("globalPlugin", "appModule")

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9]{1,39}$")
_APP = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


class ScaffoldError(ValueError):
    """Parametro de esqueleto invalido."""


@dataclass(frozen=True)
class ScaffoldFiles:
    files: dict[str, str]


def _tabs(text: str) -> str:
    """Converte a indentacao de 4 espacos do molde em TAB (padrao do NVDA)."""
    out = []
    for line in text.split("\n"):
        stripped = line.lstrip(" ")
        depth = (len(line) - len(stripped)) // 4
        out.append("\t" * depth + stripped)
    return "\n".join(out)


_GLOBAL_PLUGIN = '''import addonHandler
import globalPluginHandler
import ui
from scriptHandler import script

addonHandler.initTranslation()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    # Translators: Nome da categoria dos comandos do addon em Gestos de entrada
    scriptCategory = _("{name}")

    # Translators: Descricao do comando de exemplo em Gestos de entrada
    @script(description=_("Diz que o addon esta funcionando"), gesture="kb:NVDA+shift+{key}")
    def script_dizerOla(self, gesture):
        # Translators: Mensagem falada pelo comando de exemplo
        ui.message(_("{name} esta funcionando"))

    def terminate(self):
        super().terminate()
'''

_APP_MODULE = '''import addonHandler
import appModuleHandler
import ui
from scriptHandler import script

addonHandler.initTranslation()


class AppModule(appModuleHandler.AppModule):
    # Translators: Nome da categoria dos comandos do addon em Gestos de entrada
    scriptCategory = _("{name}")

    # Translators: Descricao do comando de exemplo em Gestos de entrada
    @script(description=_("Diz que o addon do aplicativo esta ativo"), gesture="kb:NVDA+shift+{key}")
    def script_dizerOla(self, gesture):
        # Translators: Mensagem falada pelo comando de exemplo
        ui.message(_("{name} esta ativo neste aplicativo"))
'''

_GUIDE = """<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="UTF-8"><title>{name}</title></head>
<body>
<h1>{name}</h1>
<p>{summary}</p>
<h2>Comandos</h2>
<p>Os comandos ficam em Preferencias, Gestos de entrada, na categoria {name}.</p>
</body>
</html>
"""


def build_scaffold(
    name: str,
    kind: str = "globalPlugin",
    summary: str = "",
    author: str = "Autor <autor@example.com>",
    app_name: str = "",
    url: str = "https://github.com/autor/addon",
) -> ScaffoldFiles:
    """Monta os arquivos do esqueleto (caminho relativo -> conteudo)."""
    if not _NAME.match(name):
        raise ScaffoldError(
            "nome do addon: comece com letra, use so letras e digitos (2 a 40 caracteres)"
        )
    if kind not in KINDS:
        raise ScaffoldError(f"tipo invalido: {kind!r}. Use um de {', '.join(KINDS)}")
    summary = " ".join(summary.split()) or f"Addon {name} para o NVDA"
    author = " ".join(author.split()) or "Autor <autor@example.com>"
    if kind == "appModule":
        if not _APP.match(app_name):
            raise ScaffoldError(
                "appModule precisa de app_name: o nome do executavel em minusculas, "
                "sem .exe (por exemplo: notepad)"
            )
        entry = f"appModules/{app_name}.py"
        code = _APP_MODULE
    else:
        entry = f"globalPlugins/{name}/__init__.py"
        code = _GLOBAL_PLUGIN
    manifest = (
        f"name = {name}\n"
        f"summary = {summary}\n"
        f"description = {summary}\n"
        f"author = {author}\n"
        f"url = {url}\n"
        f"version = 0.1.0\n"
        f"docFileName = readme.html\n"
        f"minimumNVDAVersion = {PROJECT_MIN_NVDA}\n"
        f"lastTestedNVDAVersion = {PROJECT_LAST_TESTED_NVDA}\n"
    )
    files = {
        "manifest.ini": manifest,
        entry: _tabs(code.format(name=name, key="o")),
        "doc/pt_BR/readme.html": _GUIDE.format(name=name, summary=summary),
    }
    return ScaffoldFiles(files)
