import os
import threading

import wx
import config
import gui
import ui

from gui.settingsDialogs import SettingsPanel
from gui.guiHelper import BoxSizerHelper

from ..utils.logger import get_logger
from ..ai.model_registry import ALTO_MODEL, get_provider_step_models, registry

MODULE_VERSION = "6.11.0"
_logger = get_logger("settings_panel")

CONFIG_SECTION = "nvdastudio"
CONFIG_KEY_PROVIDER   = "llmProvider"
CONFIG_KEY_MODEL      = "llmModel"
CONFIG_KEY_OUTPUT_DIR = "outputDir"
CONFIG_KEY_LANGUAGE   = "uiLanguage"

# Provedores disponiveis no dropdown "Provedor de IA". OpenCode Go
# DELIBERADAMENTE ausente daqui (pedido do Felipe, 2026-08-16): roda so
# nos bastidores como resgate automatico quando o Ollama (provider ativo)
# nao tem uma capacidade nativa disponivel -- nunca um provider que o
# usuario escolhe/configura como principal. Chave de API continua
# configuravel (ver campo dedicado em makeSettings(), mesmo padrao de
# tavily/exa) porque o resgate precisa da chave real do Felipe pra
# funcionar, so nao aparece como opcao selecionavel aqui.
_PROVIDERS = [
    ("Ollama Cloud",  "ollama"),
    ("OpenAI",        "openai"),
    ("Google Gemini", "gemini"),
    ("Anthropic",     "anthropic"),
    ("xAI",           "xai"),
    # Factory Droid via CLI headless (`droid exec`). Selecionavel porque e
    # provedor de LLM de verdade: serve os MESMOS ids que o projeto ja
    # roteia (kimi-k2.7-code, gpt-5.6-luna, glm-5.2, deepseek-v4-flash-0731)
    # com prompt caching, que a Ollama Cloud nao tem em nenhum modelo.
    ("Factory Droid", "factory"),
]
_PROVIDER_CODES = [code for _, code in _PROVIDERS]

# Chaves API por provedor
_API_KEY_CONFIG_KEYS: dict[str, str] = {
    "ollama":    "apiKeyOllama",
    "openai":    "apiKeyOpenAI",
    "gemini":    "apiKeyGemini",
    "anthropic": "apiKeyAnthropic",
    "xai":       "apiKeyXAI",
    "opencode_go": "apiKeyOpenCodeGo",
    # Factory Droid: chave OPCIONAL -- o droid tambem autentica pelo login
    # do proprio CLI. Preencher so quando quiser forcar outra conta.
    "factory":   "apiKeyFactory",
    # Nao sao provedores de LLM (nao aparecem no dropdown "Provedor de IA") --
    # chaves de busca web usadas como FALLBACK em web_researcher.py quando o
    # provedor de IA ativo nao tem busca nativa disponivel para o modelo em
    # uso. Pedido do Felipe (2026-08-04): "se algum modelo do ollama nao
    # pesquisar na web, tem tavily e exa search que podemos usar tambem".
    "tavily":    "apiKeyTavily",
    "exa":       "apiKeyExa",
}

_API_KEY_LABELS: dict[str, str] = {
    "ollama":    "Chave Ollama API:",
    "openai":    "Chave OpenAI API:",
    "gemini":    "Chave Google Gemini API:",
    "anthropic": "Chave Anthropic API:",
    "xai":       "Chave xAI API:",
    "opencode_go": "Chave OpenCode Go API:",
    "factory":   "Chave Factory API (opcional, ha login do droid CLI):",
    "tavily":    "Chave Tavily API (busca web, opcional):",
    "exa":       "Chave Exa API (busca web, opcional):",
}

_API_KEY_ENV_VARS: dict[str, str] = {
    "ollama":    "OLLAMA_API_KEY",
    "openai":    "OPENAI_API_KEY",
    "gemini":    "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "xai":       "XAI_API_KEY",
    "opencode_go": "OPENCODE_GO_API_KEY",
    "factory":   "FACTORY_API_KEY",
    "tavily":    "TAVILY_API_KEY",
    "exa":       "EXA_API_KEY",
}

# Achado de auditoria 2026-08-04: NVDAStudio impoe a regra NVDA-015 ("nenhum
# addon gerado pode usar config.conf sem declarar config.conf.spec") nos
# addons que ele mesmo gera, mas nunca declarava um spec pra sua PROPRIA
# secao "nvdastudio" -- violacao real da propria regra, nao so estilistica.
# Sem spec: sem validacao de tipo, sem default declarado, sem rede de
# seguranca de migracao -- funcionava ate agora so porque ConfigObj tolera
# secoes ad-hoc criadas via dict puro (ver ensure_config_section() abaixo).
_CONFIG_SPEC: dict[str, str] = {
    CONFIG_KEY_PROVIDER: "string(default='ollama')",
    CONFIG_KEY_MODEL: "string(default='')",
    CONFIG_KEY_OUTPUT_DIR: "string(default='')",
    CONFIG_KEY_LANGUAGE: "string(default='pt_BR')",
    **{key: "string(default='')" for key in _API_KEY_CONFIG_KEYS.values()},
}
# config.conf.spec so existe no runtime real do NVDA (ConfigObj) -- os
# testes de unidade stubam config.conf como dict puro (conftest.py), sem
# .spec. Fail-open: registrar o spec e um bonus de robustez no NVDA real,
# nunca deve impedir a suite de rodar fora dele.
try:
    config.conf.spec[CONFIG_SECTION] = _CONFIG_SPEC
except AttributeError:
    pass

# Rotulos amigaveis pra modelos conhecidos -- modelos novos sem entrada
# aqui caem em _prettify_model_id() (fallback generico), nunca ficam
# ausentes da UI (ver changelog 6.5.0).
_MODEL_DISPLAY_NAMES: dict[str, str] = {
    "kimi-k2.7-code": "Kimi K2.7 Code",
    "kimi-k2.6": "Kimi K2.6",
    "deepseek-v4-flash": "DeepSeek V4 Flash",
    "glm-5.2": "GLM 5.2",
    "minimax-m3": "MiniMax M3",
    "gpt-oss:20b": "GPT-OSS 20B",
    "gpt-5.6-sol": "GPT 5.6 Sol",
    "gpt-5.6-terra": "GPT 5.6 Terra",
    "gpt-5.6-luna": "GPT 5.6 Luna",
    "gemini-3.1-pro-preview": "Gemini 3.1 Pro Preview",
    "gemini-3.6-flash": "Gemini 3.6 Flash",
    "gemini-3.5-flash": "Gemini 3.5 Flash",
    "gemini-3.5-flash-lite": "Gemini 3.5 Flash Lite",
    "gemini-3.1-flash-lite": "Gemini 3.1 Flash Lite",
    "claude-opus-5": "Claude Opus 5",
    "claude-sonnet-5": "Claude Sonnet 5",
    "claude-haiku-4-5": "Claude Haiku 4.5",
    "grok-build-0.1": "Grok Build 0.1",
    "grok-4.5": "Grok 4.5",
    "grok-4.3": "Grok 4.3",
    # gpt-5.6-luna ja tem rotulo acima (compartilhado com o provedor
    # OpenAI real -- _MODEL_DISPLAY_NAMES e keyed por model_id NU, o
    # dropdown ja esta agrupado por provedor entao nao ha ambiguidade).
}


def _prettify_model_id(model_id: str) -> str:
    """Rotulo generico pra modelo sem entrada em _MODEL_DISPLAY_NAMES --
    garante que um modelo novo no registry SEMPRE aparece na UI, mesmo
    antes de alguem curar um nome bonito pra ele."""
    return model_id.replace("-", " ").replace(":", " ").replace("_", " ").title()


def _build_models_for_provider(ui_provider: str) -> list[tuple[str, str]]:
    """
    Monta a lista (rotulo, model_id) pro dropdown de modelo, a partir do
    registry real (fonte unica de verdade -- ver model_registry.py
    ModelRegistry.get_active_models_for_ui_provider()). "Alto" sempre
    primeiro; depois o heavy/light default do provedor; depois o resto em
    ordem alfabetica.
    """
    tier_models = get_provider_step_models(ui_provider)
    heavy, light = tier_models.get("heavy", ""), tier_models.get("light", "")

    def _sort_key(model_id: str) -> tuple[int, str]:
        if model_id == heavy:
            return (0, model_id)
        if model_id == light:
            return (1, model_id)
        return (2, model_id)

    ativos = sorted(
        registry.get_active_models_for_ui_provider(ui_provider),
        key=lambda info: _sort_key(info.model_id),
    )
    result = [("Alto (recomendado)", ALTO_MODEL)]
    for info in ativos:
        label = _MODEL_DISPLAY_NAMES.get(info.model_id, _prettify_model_id(info.model_id))
        result.append((label, info.model_id))
    return result


# Modelos por provedor -- construido em tempo real a partir do registry,
# nao mais hand-maintained (ver _build_models_for_provider acima).
_MODELS_BY_PROVIDER: dict[str, list[tuple[str, str]]] = {
    ui_provider: _build_models_for_provider(ui_provider)
    # "factory" estava em _PROVIDERS (selecionavel) mas fora desta lista: o
    # dropdown de modelo ficava VAZIO ao escolher Factory -- nem "Alto"
    # aparecia. A Factory nao expoe catalogo por-modelo de proposito
    # (_UI_PROVIDER_TO_REGISTRY_PROVIDERS vazio: ids diferem do Ollama, so o
    # tier e verificado), entao _build_models_for_provider("factory") devolve
    # so [("Alto (recomendado)", ALTO_MODEL)] -- que e exatamente o certo:
    # Factory roda no Alto/automatico, roteando pro modelo verificado.
    for ui_provider in ("ollama", "openai", "gemini", "anthropic", "xai", "factory")
}

_DEFAULT_MODELS = {
    "ollama":    ALTO_MODEL,
    "openai":    ALTO_MODEL,
    "gemini":    ALTO_MODEL,
    "anthropic": ALTO_MODEL,
    "xai":       ALTO_MODEL,
    "factory":   ALTO_MODEL,
}

_LANGUAGES = [
    ("Portugues do Brasil (PT-BR)", "pt_BR"),
    ("English (EN)",                "en"),
    ("Espanol (ES)",                "es"),
]
_LANGUAGE_CODES = [code for _, code in _LANGUAGES]

_DEFAULT_OUTPUT_DIR = os.path.join(
    os.path.expanduser("~"), "Documents", "NVDAStudio", "addons_gerados"
)


def _validate_provider_key(provider: str, key: str, model_id: str) -> None:
    """Faz uma chamada minima pelo mesmo cliente usado em producao."""
    from ..ai.model_registry import resolve_provider_tier_model
    concrete_model = resolve_provider_tier_model(provider, "light", model_id)
    from ..ai.llm_client import LLMClientProtocol
    if provider == "ollama":
        from ..ai.ollama_client import OllamaClient
        client: LLMClientProtocol = OllamaClient(api_key=key, model_id=concrete_model)
    elif provider == "factory":
        # Factory NAO e HTTP: fala pelo `droid` CLI (FactoryClient). O else
        # abaixo usa ProviderClient (openai/anthropic/gemini/xai), que nao sabe
        # o que e "factory" -- mandar a Factory pra la fazia o botao Testar
        # falhar sempre. A chave e opcional (o droid autentica pelo proprio
        # login); testar com chave vazia valida que o droid esta instalado e
        # logado, que e exatamente o que precisa funcionar.
        from ..ai.factory_client import FactoryClient
        client = FactoryClient(api_key=key, model_id=concrete_model)
    else:
        from ..ai.provider_client import ProviderClient
        client = ProviderClient(provider=provider, api_key=key, model_id=concrete_model)
    response = client.chat("Responda apenas OK.")
    if not response.content.strip():
        raise RuntimeError("O provedor respondeu sem conteudo.")

def ensure_config_section():
    if CONFIG_SECTION not in config.conf:
        config.conf[CONFIG_SECTION] = {}

def get_llm_provider() -> str:
    ensure_config_section()
    provider = config.conf[CONFIG_SECTION].get(CONFIG_KEY_PROVIDER, "ollama").strip()
    return provider if provider in _PROVIDER_CODES else "ollama"

def get_llm_model() -> str:
    ensure_config_section()
    model = config.conf[CONFIG_SECTION].get(CONFIG_KEY_MODEL, "").strip()
    if not model:
        return ALTO_MODEL
    provider = get_llm_provider()
    allowed_models = {code for _, code in _MODELS_BY_PROVIDER.get(provider, [])}
    return model if model in allowed_models else ALTO_MODEL

def get_api_key(provider: str) -> str:
    """Retorna a chave API salva para o provedor (ou via env como fallback)."""
    ensure_config_section()
    env_var = _API_KEY_ENV_VARS.get(provider, "")
    if env_var and os.getenv(env_var, "").strip():
        return os.getenv(env_var, "").strip()
    key_name = _API_KEY_CONFIG_KEYS.get(provider, "")
    if key_name:
        return config.conf[CONFIG_SECTION].get(key_name, "").strip()
    return ""

def get_output_dir() -> str:
    ensure_config_section()
    saved = config.conf[CONFIG_SECTION].get(CONFIG_KEY_OUTPUT_DIR, "").strip()
    return saved if saved else _DEFAULT_OUTPUT_DIR

def get_ui_language() -> str:
    ensure_config_section()
    lang = config.conf[CONFIG_SECTION].get(CONFIG_KEY_LANGUAGE, "pt_BR").strip()
    return lang if lang in _LANGUAGE_CODES else "pt_BR"


class NVDAStudioSettingsPanel(SettingsPanel):
    title = "NVDAStudio"

    def makeSettings(self, settingsSizer):
        sizer_helper = BoxSizerHelper(self, sizer=settingsSizer)

        # ---- Provedor LLM ----
        self.provider_ctrl = sizer_helper.addLabeledControl(
            "Pro&vedor de IA:",
            wx.Choice,
            choices=[label for label, _ in _PROVIDERS],
        )
        current_provider = get_llm_provider()
        provider_idx = _PROVIDER_CODES.index(current_provider) if current_provider in _PROVIDER_CODES else 0
        self.provider_ctrl.SetSelection(provider_idx)
        self.provider_ctrl.SetToolTip(
            "Escolha o provedor de IA. Cada provedor exige sua propria chave API."
        )
        self.provider_ctrl.Bind(wx.EVT_CHOICE, self._on_provider_changed)

        # ---- Modelo LLM ----
        self.model_ctrl = sizer_helper.addLabeledControl(
            "Mo&delo:",
            wx.Choice,
            choices=[],
        )
        self.model_ctrl.SetToolTip(
            "Escolha Alto para o NVDAStudio selecionar automaticamente o melhor modelo do provedor."
        )
        self._refresh_model_choices()

        # ---- Chave API ----
        self.api_key_label = wx.StaticText(self, label="")
        sizer_helper.addItem(self.api_key_label)
        self.api_key_ctrl = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self.api_key_ctrl.SetToolTip("Chave de API do provedor selecionado acima.")
        sizer_helper.addItem(self.api_key_ctrl)

        btn_validate = wx.Button(self, label="&Validar chave API")
        btn_validate.SetToolTip("Testa a chave contra a API do provedor selecionado")
        btn_validate.Bind(wx.EVT_BUTTON, self._on_validate_api_key)
        sizer_helper.addItem(btn_validate)

        self._api_key_status = wx.StaticText(self, label="")
        sizer_helper.addItem(self._api_key_status)

        # ---- Chaves de busca web (fallback, opcionais, independentes do
        # provedor de IA escolhido acima) ----
        self.tavily_key_ctrl = sizer_helper.addLabeledControl(
            _API_KEY_LABELS["tavily"],
            wx.TextCtrl,
            style=wx.TE_PASSWORD,
        )
        self.tavily_key_ctrl.SetValue(get_api_key("tavily"))
        self.tavily_key_ctrl.SetToolTip(
            "Opcional. Usada como alternativa de busca web quando o provedor "
            "de IA ativo nao tem busca nativa disponivel para o modelo em uso."
        )

        self.exa_key_ctrl = sizer_helper.addLabeledControl(
            _API_KEY_LABELS["exa"],
            wx.TextCtrl,
            style=wx.TE_PASSWORD,
        )
        self.exa_key_ctrl.SetValue(get_api_key("exa"))
        self.exa_key_ctrl.SetToolTip(
            "Opcional. Segunda alternativa de busca web, tentada se a busca "
            "nativa e a chave Tavily (se configurada) nao estiverem disponiveis."
        )

        # ---- Chave OpenCode Go (resgate automatico, nao um provider
        # selecionavel -- ver nota em _PROVIDERS) ----
        self.opencode_go_key_ctrl = sizer_helper.addLabeledControl(
            _API_KEY_LABELS["opencode_go"],
            wx.TextCtrl,
            style=wx.TE_PASSWORD,
        )
        self.opencode_go_key_ctrl.SetValue(get_api_key("opencode_go"))
        self.opencode_go_key_ctrl.SetToolTip(
            "Opcional. Usada automaticamente como resgate (gpt-5.6-luna) quando "
            "o provedor Ollama Cloud nao tem uma capacidade nativa disponivel "
            "para o step atual. Nao aparece no dropdown de Provedor de IA -- "
            "so roda nos bastidores."
        )

        # ---- Pasta de saida ----
        self.output_dir_ctrl = sizer_helper.addLabeledControl(
            "Pasta de &saida dos addons gerados:",
            wx.TextCtrl
        )
        self.output_dir_ctrl.SetValue(get_output_dir())
        self.output_dir_ctrl.SetToolTip(
            "Onde os arquivos .nvda-addon serao salvos. "
            "Padrao: Documents/NVDAStudio/addons_gerados"
        )

        btn_browse = wx.Button(self, label="&Procurar pasta...")
        btn_browse.SetToolTip("Abre o Explorer para escolher a pasta de saida")
        btn_browse.Bind(wx.EVT_BUTTON, self._on_browse)
        sizer_helper.addItem(btn_browse)

        # ---- Idioma ----
        self.language_ctrl = sizer_helper.addLabeledControl(
            "&Idioma das mensagens do NVDAStudio:",
            wx.Choice,
            choices=[label for label, _ in _LANGUAGES],
        )
        current_lang = get_ui_language()
        current_idx = _LANGUAGE_CODES.index(current_lang) if current_lang in _LANGUAGE_CODES else 0
        self.language_ctrl.SetSelection(current_idx)
        self.language_ctrl.SetToolTip(
            "Idioma usado nas mensagens e avisos do NVDAStudio. "
            "Nao afeta o idioma do addon gerado."
        )

        self._update_provider_ui()

    def _current_provider(self) -> str:
        idx = self.provider_ctrl.GetSelection()
        return _PROVIDER_CODES[idx] if 0 <= idx < len(_PROVIDER_CODES) else "hermes"

    def _refresh_model_choices(self):
        provider = self._current_provider()
        models = _MODELS_BY_PROVIDER.get(provider, [])
        self.model_ctrl.Clear()
        for label, code in models:
            self.model_ctrl.Append(label, code)
        saved_model = get_llm_model()
        for i in range(self.model_ctrl.GetCount()):
            if self.model_ctrl.GetClientData(i) == saved_model:
                self.model_ctrl.SetSelection(i)
                return
        if self.model_ctrl.GetCount() > 0:
            self.model_ctrl.SetSelection(0)

    def _update_provider_ui(self):
        provider = self._current_provider()
        need_key = provider != "hermes"

        label = _API_KEY_LABELS.get(provider, "Chave API:")
        self.api_key_label.SetLabel(label)

        self.api_key_ctrl.Show(need_key)
        self.api_key_label.Show(need_key)
        if need_key:
            self.api_key_ctrl.Enable()
            self.api_key_ctrl.SetValue(get_api_key(provider))
        else:
            self.api_key_ctrl.Disable()
            self.api_key_ctrl.SetValue("")

        self.Layout()
        self.Refresh()

    def _on_provider_changed(self, event):
        self._refresh_model_choices()
        self._update_provider_ui()

    def _on_validate_api_key(self, event):
        provider = self._current_provider()
        key = self.api_key_ctrl.GetValue().strip()
        if not key:
            self._api_key_status.SetLabel("Campo vazio. Insira a chave antes de validar.")
            self.Layout()
            ui.message("NVDAStudio: campo de chave API vazio.")
            return

        self._api_key_status.SetLabel("Validando, aguarde...")
        self.Layout()
        ui.message(f"NVDAStudio: validando chave {provider}, aguarde.")
        model_index = self.model_ctrl.GetSelection()
        model_id = (
            self.model_ctrl.GetClientData(model_index)
            if 0 <= model_index < self.model_ctrl.GetCount()
            else ALTO_MODEL
        )

        def _do_validate():
            try:
                _validate_provider_key(provider, key, model_id)
                wx.CallAfter(self._on_key_validated, True, None)
            except Exception as exc:
                wx.CallAfter(self._on_key_validated, False, str(exc))

        threading.Thread(target=_do_validate, daemon=True).start()

    def _on_key_validated(self, ok: bool, error: str):
        if ok:
            self._api_key_status.SetLabel("Chave valida. Provedor conectado.")
            self.Layout()
            ui.message("NVDAStudio: chave API valida.")
        else:
            msg = error or "Chave invalida."
            self._api_key_status.SetLabel(f"Erro: {msg}")
            self.Layout()
            ui.message(f"NVDAStudio: validacao falhou. {msg}")

    def _on_browse(self, event):
        current = self.output_dir_ctrl.GetValue().strip() or _DEFAULT_OUTPUT_DIR
        dlg = wx.DirDialog(
            self,
            message="Escolha a pasta de saida dos addons gerados:",
            defaultPath=current,
            style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST
        )
        gui.mainFrame.prePopup()
        result = dlg.ShowModal()
        gui.mainFrame.postPopup()
        if result == wx.ID_OK:
            self.output_dir_ctrl.SetValue(dlg.GetPath())
        dlg.Destroy()

    def onSave(self):
        ensure_config_section()
        output_dir = self.output_dir_ctrl.GetValue().strip()

        if output_dir and not os.path.isabs(output_dir):
            gui.messageBox(
                "Caminho de saida invalido. Use um caminho absoluto.",
                "NVDAStudio", wx.OK | wx.ICON_ERROR, self
            )
            return

        config.conf[CONFIG_SECTION][CONFIG_KEY_OUTPUT_DIR] = output_dir

        provider = self._current_provider()
        config.conf[CONFIG_SECTION][CONFIG_KEY_PROVIDER] = provider

        key_name = _API_KEY_CONFIG_KEYS.get(provider, "")
        if key_name:
            config.conf[CONFIG_SECTION][key_name] = self.api_key_ctrl.GetValue().strip()

        config.conf[CONFIG_SECTION][_API_KEY_CONFIG_KEYS["tavily"]] = self.tavily_key_ctrl.GetValue().strip()
        config.conf[CONFIG_SECTION][_API_KEY_CONFIG_KEYS["exa"]] = self.exa_key_ctrl.GetValue().strip()
        config.conf[CONFIG_SECTION][_API_KEY_CONFIG_KEYS["opencode_go"]] = self.opencode_go_key_ctrl.GetValue().strip()

        model_idx = self.model_ctrl.GetSelection()
        if model_idx != wx.NOT_FOUND and 0 <= model_idx < self.model_ctrl.GetCount():
            model_code = self.model_ctrl.GetClientData(model_idx)
            config.conf[CONFIG_SECTION][CONFIG_KEY_MODEL] = model_code or ""
        else:
            config.conf[CONFIG_SECTION][CONFIG_KEY_MODEL] = ""

        lang_idx = self.language_ctrl.GetSelection()
        lang_code = _LANGUAGE_CODES[lang_idx] if 0 <= lang_idx < len(_LANGUAGE_CODES) else "pt_BR"
        config.conf[CONFIG_SECTION][CONFIG_KEY_LANGUAGE] = lang_code

        _logger.info("[OK] Config salva. provider=%s model=%s output_dir=%s lang=%s",
            provider,
            config.conf[CONFIG_SECTION].get(CONFIG_KEY_MODEL, ""),
            output_dir or "(padrao)",
            lang_code
        )


class FirstRunSetupDialog(wx.Dialog):
    """Dialogo exibido na primeira vez que o usuario abre o NVDAStudio."""

    def __init__(self, parent: wx.Window):
        super().__init__(
            parent,
            title="NVDAStudio — Configurar provedor de IA",
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        self._token_ok = False
        self._build_ui()
        self.CentreOnParent()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        intro = wx.StaticText(
            panel,
            label=(
                "Bem-vindo ao NVDAStudio.\n"
                "Escolha seu provedor de IA e insira a chave API correspondente.\n"
                "O NVDAStudio se conecta diretamente ao provedor escolhido."
            ),
        )
        intro.Wrap(440)
        sizer.Add(intro, flag=wx.ALL, border=8)

        lbl_provider = wx.StaticText(panel, label="&Provedor de IA:")
        sizer.Add(lbl_provider, flag=wx.LEFT | wx.RIGHT | wx.TOP, border=8)
        self._provider_ctrl = wx.Choice(panel, choices=[label for label, _ in _PROVIDERS])
        self._provider_ctrl.SetSelection(0)
        self._provider_ctrl.Bind(wx.EVT_CHOICE, self._on_provider_changed)
        sizer.Add(self._provider_ctrl, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=8)

        self._key_label = wx.StaticText(panel, label="Chave API:")
        sizer.Add(self._key_label, flag=wx.LEFT | wx.RIGHT | wx.TOP, border=8)
        self._token_ctrl = wx.TextCtrl(panel, style=wx.TE_PASSWORD, size=(440, -1))
        self._token_ctrl.SetToolTip("Chave de API do provedor selecionado.")
        sizer.Add(self._token_ctrl, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=8)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_validate = wx.Button(panel, label="&Validar chave API")
        btn_sizer.Add(self._btn_validate)
        sizer.Add(btn_sizer, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=8)

        self._status_label = wx.StaticText(panel, label="")
        sizer.Add(self._status_label, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=8)

        dlg_buttons = wx.StdDialogButtonSizer()
        self._btn_ok = wx.Button(panel, wx.ID_OK, label="Salvar e Abrir NVDAStudio")
        self._btn_cancel = wx.Button(panel, wx.ID_CANCEL, label="Cancelar")
        self._btn_ok.SetDefault()
        dlg_buttons.AddButton(self._btn_ok)
        dlg_buttons.AddButton(self._btn_cancel)
        dlg_buttons.Realize()
        sizer.Add(dlg_buttons, flag=wx.ALL | wx.ALIGN_RIGHT, border=8)

        panel.SetSizer(sizer)
        sizer.Fit(self)

        self._btn_validate.Bind(wx.EVT_BUTTON, self._on_validate)
        self._btn_ok.Bind(wx.EVT_BUTTON, self._on_ok)
        self._update_key_ui()

    def _current_provider(self) -> str:
        idx = self._provider_ctrl.GetSelection()
        return _PROVIDER_CODES[idx] if 0 <= idx < len(_PROVIDER_CODES) else "ollama"

    def _update_key_ui(self):
        provider = self._current_provider()
        need_key = True
        label = _API_KEY_LABELS.get(provider, "Chave API:")
        self._key_label.SetLabel(label)
        self._key_label.Show(need_key)
        self._token_ctrl.Show(need_key)
        if not need_key:
            self._token_ctrl.SetValue("")
        self.Layout()
        self.Refresh()

    def _on_provider_changed(self, event):
        self._update_key_ui()

    def _on_validate(self, event) -> None:
        provider = self._current_provider()
        key = self._token_ctrl.GetValue().strip()
        if not key:
            self._set_status("Campo vazio. Insira a chave antes de validar.")
            ui.message("NVDAStudio: campo de chave vazio.")
            return

        self._set_status("Validando, aguarde...")
        self._btn_validate.Disable()
        self._btn_ok.Disable()
        ui.message("NVDAStudio: validando chave API, aguarde.")

        def _do_validate() -> None:
            try:
                _validate_provider_key(provider, key, ALTO_MODEL)
                wx.CallAfter(self._on_validated, True, "")
            except Exception as exc:
                wx.CallAfter(self._on_validated, False, str(exc))

        threading.Thread(target=_do_validate, daemon=True).start()

    def _on_validated(self, ok: bool, error: str) -> None:
        self._btn_validate.Enable()
        if ok:
            self._token_ok = True
            self._btn_ok.Enable()
            self._set_status("Chave valida. Clique em Salvar para continuar.")
            ui.message("NVDAStudio: chave valida.")
        else:
            self._token_ok = False
            self._btn_ok.Disable()
            msg = error or "Chave invalida."
            self._set_status(f"Erro: {msg}")
            ui.message(f"NVDAStudio: validacao falhou. {msg}")

    def _on_ok(self, event) -> None:
        provider = self._current_provider()
        key = self._token_ctrl.GetValue().strip()

        if not key:
            self._set_status("Insira a chave API antes de salvar.")
            ui.message("NVDAStudio: chave API obrigatoria para este provedor.")
            return

        ensure_config_section()
        config.conf[CONFIG_SECTION][CONFIG_KEY_PROVIDER] = provider

        key_name = _API_KEY_CONFIG_KEYS.get(provider, "")
        if key_name and key:
            config.conf[CONFIG_SECTION][key_name] = key

        _logger.info("[OK] First-run config salva. provider=%s", provider)
        self.EndModal(wx.ID_OK)

    def _set_status(self, text: str) -> None:
        self._status_label.SetLabel(text)
        self._status_label.GetParent().Layout()
