"""Skeleton of a new NVDA add-on, already compliant with the validator rules.

The skeleton is only a starting point: Claude decides what the add-on does and
rewrites the code. Only facts about the NVDA format live here (manifest,
folder structure, required hooks).
"""

import re
from dataclasses import dataclass

from .project_policy import PROJECT_LAST_TESTED_NVDA, PROJECT_MIN_NVDA

KINDS = ("globalPlugin", "appModule")

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9]{1,39}$")
_APP = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


class ScaffoldError(ValueError):
    """Invalid skeleton parameter."""


@dataclass(frozen=True)
class ScaffoldFiles:
    files: dict[str, str]


def _tabs(text: str) -> str:
    """Converts the 4-space indentation of the template to TAB (NVDA convention)."""
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
    # Translators: Name of the add-on's command category in Input gestures
    scriptCategory = _("{name}")

    # Translators: Description of the example command in Input gestures
    @script(description=_("Says the add-on is working"), gesture="kb:NVDA+control+shift+{key}")
    def script_sayHello(self, gesture):
        # Translators: Message spoken by the example command
        ui.message(_("{name} is working"))

    def terminate(self):
        super().terminate()
'''

_APP_MODULE = '''import addonHandler
import appModuleHandler
import ui
from scriptHandler import script

addonHandler.initTranslation()


class AppModule(appModuleHandler.AppModule):
    # Translators: Name of the add-on's command category in Input gestures
    scriptCategory = _("{name}")

    # Translators: Description of the example command in Input gestures
    @script(description=_("Says the application add-on is active"), gesture="kb:NVDA+control+shift+{key}")
    def script_sayHello(self, gesture):
        # Translators: Message spoken by the example command
        ui.message(_("{name} is active in this application"))
'''

_GUIDE = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>{name}</title></head>
<body>
<h1>{name}</h1>
<p>{summary}</p>
<h2>Commands</h2>
<p>The commands are in Preferences, Input gestures, under the {name} category.</p>
</body>
</html>
"""


def build_scaffold(
    name: str,
    kind: str = "globalPlugin",
    summary: str = "",
    author: str = "Author <author@example.com>",
    app_name: str = "",
    url: str = "",
) -> ScaffoldFiles:
    """Builds the skeleton files (relative path -> content)."""
    if not _NAME.match(name):
        raise ScaffoldError(
            "add-on name: start with a letter, use only letters and digits (2 to 40 characters)"
        )
    if kind not in KINDS:
        raise ScaffoldError(f"invalid kind: {kind!r}. Use one of {', '.join(KINDS)}")
    summary = " ".join(summary.split()) or f"Add-on {name} for NVDA"
    author = " ".join(author.split()) or "Author <author@example.com>"
    if kind == "appModule":
        if not _APP.match(app_name):
            raise ScaffoldError(
                "appModule needs app_name: the executable name in lowercase, "
                "without .exe (for example: notepad)"
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
        + (f"url = {url}\n" if url else "")
        + "version = 0.1.0\n"
        f"docFileName = readme.html\n"
        f"minimumNVDAVersion = {PROJECT_MIN_NVDA}\n"
        f"lastTestedNVDAVersion = {PROJECT_LAST_TESTED_NVDA}\n"
    )
    files = {
        "manifest.ini": manifest,
        entry: _tabs(code.format(name=name, key="o")),
        "doc/en/readme.html": _GUIDE.format(name=name, summary=summary),
    }
    return ScaffoldFiles(files)
