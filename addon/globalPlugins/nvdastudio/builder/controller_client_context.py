MODULE_VERSION = "1.1.0"

_MARKER_PREFIX = "[PROJECT_TYPE: controller_client"


def is_controller_client_context(context: str) -> bool:
	"""Deteccao deterministica (Regra 5) do marcador de roteamento injetado
	por orchestrator.py::_critic_context()/_build_step_prompt() quando
	plan.project_type=="controller_client". Nunca decisao do LLM."""
	return bool(context) and context.startswith(_MARKER_PREFIX)


def project_type_marker() -> str:
	"""Marcador prependido ao prompt/contexto quando o plano e do tipo
	controller_client -- usado por orchestrator.py (geracao) e critic.py
	(avaliacao) pra rotear deterministicamente pro catalogo certo."""
	return (
		f"{_MARKER_PREFIX} — PROGRAMA EXTERNO ao NVDA via Controller Client "
		"API, NAO um addon NVDA. Nao gere manifest.ini nem globalPlugins/. "
		"Ver builder/controller_client_context.py.]\n\n"
	)


# =============================================================================
# Catalogo de regras CTRL-CLIENT-00X (paralelo a NVDA-XXX/WX-A11Y-XXX de
# nvda_context.py, mas para o dominio de programa externo)
# =============================================================================

CTRL_CLIENT_RULES: tuple[tuple[str, str, str], ...] = (
	("CTRL-CLIENT-001", "Critico",
	 "nvdaController_testIfRunning() nao chamado antes de qualquer outra "
	 "funcao da API. Sem essa checagem, o programa nao sabe se o NVDA esta "
	 "rodando e chamadas subsequentes falham silenciosamente ou lancam erro "
	 "confuso pro usuario."),
	("CTRL-CLIENT-002", "Critico",
	 "DLL do Controller Client (nvdaControllerClient.dll) carregada sem "
	 "corresponder a arquitetura do PROCESSO CLIENTE (x86/x64/arm64) -- "
	 "usar a DLL da pasta errada causa OSError ao carregar via ctypes."),
	("CTRL-CLIENT-003", "Serio",
	 "Valor de retorno de uma funcao da API (0=sucesso, codigo de erro "
	 "Windows padrao caso contrario) ignorado sem checagem. Toda chamada "
	 "deve verificar o retorno e usar ctypes.WinError(res) para diagnostico."),
	("CTRL-CLIENT-004", "Serio",
	 "Projeto controller_client gerando manifest.ini, pasta globalPlugins/ "
	 "ou qualquer estrutura de addon NVDA. Isso NAO e um addon -- e um "
	 "programa separado, nunca carregado por addonHandler."),
	("CTRL-CLIENT-005", "Serio",
	 "Dados sensiveis (senha, token, PIN) enviados via nvdaController_"
	 "speakText/brailleMessage sem checar se a tela esta bloqueada ou em "
	 "modo seguro. Diferente de addons internos (NVDAState.shouldWriteToDisk() "
	 "nao existe fora do processo NVDA) -- o PROGRAMA CLIENTE e responsavel "
	 "por essa checagem do lado dele (ex: deteccao de estacao de trabalho "
	 "bloqueada via API do Windows) antes de mandar qualquer coisa sensivel."),
	("CTRL-CLIENT-006", "Moderado",
	 "nvdaController_speakSsml/getProcessId (API v2, NVDA 2024.1+) chamadas "
	 "sem tratar o erro 1717 (RPC_S_UNKNOWN_IF), retornado em versoes do "
	 "NVDA anteriores a 2024.1. Sempre ter fallback para "
	 "nvdaController_speakText quando speakSsml devolver esse codigo."),
	("CTRL-CLIENT-007", "Moderado",
	 "Nova fala iniciada sem chamar nvdaController_cancelSpeech() antes, "
	 "quando a intencao e interromper a fala anterior (barge-in). Sem "
	 "isso, falas se acumulam na fila em vez de substituir a anterior."),
	("CTRL-CLIENT-008", "Menor",
	 "Chamada bloqueante a API feita direto na thread de UI de um programa "
	 "com interface grafica propria (Tkinter/PyQt/etc) -- trava a interface "
	 "durante a fala. Rodar em thread separada quando o programa tiver UI."),
)

CTRL_CLIENT_RULE_IDS: tuple[str, ...] = tuple(r[0] for r in CTRL_CLIENT_RULES)


def _format_rule_catalog() -> str:
	lines = ["CATALOGO DE REGRAS CTRL-CLIENT (Controller Client API, programas EXTERNOS ao NVDA):"]
	for rule_id, severity, description in CTRL_CLIENT_RULES:
		lines.append(f"{rule_id} [{severity}] {description}")
	return "\n".join(lines)


CTRL_CLIENT_RULE_CATALOG_TEXT = _format_rule_catalog()


# =============================================================================
# System prompt para code_generation quando project_type=="controller_client"
# =============================================================================

CTRL_CLIENT_SYSTEM_PROMPT = f"""Voce e o NVDAStudio AI gerando um PROGRAMA EXTERNO ao NVDA -- um
aplicativo Windows separado (roda em processo proprio) que usa a NVDA
Controller Client API para fazer o NVDA falar e exibir mensagens em braile
a partir de fora, sem ser um addon. E o mesmo mecanismo usado por
aplicativos reais como TWBlue.

DIFERENCA FUNDAMENTAL vs addon NVDA tradicional:
- NAO gere manifest.ini, NAO gere pasta globalPlugins/<nome>/, NAO crie
  classe GlobalPlugin/AppModule. Nada disso se aplica -- este programa NAO
  e carregado pelo addonHandler, roda como processo Windows normal/independente.
- O programa fala/exibe em braile atraves do NVDA chamando funcoes de uma
  DLL (nvdaControllerClient.dll) via ctypes -- e um CLIENTE da API do NVDA,
  nao um plugin dentro dele.

{CTRL_CLIENT_RULE_CATALOG_TEXT}

## API disponivel (fonte: extras/controllerClient/readme.md e
## nvdaController.h do repositorio oficial nvaccess/nvda)

Sempre disponiveis (API v1):
- nvdaController_testIfRunning() -> int: 0 se NVDA esta rodando, codigo de
  erro Windows caso contrario. SEMPRE chame primeiro.
- nvdaController_speakText(text: str) -> int: fala o texto.
- nvdaController_cancelSpeech() -> int: interrompe a fala atual.
- nvdaController_brailleMessage(text: str) -> int: exibe no display braile.

Disponiveis a partir do NVDA 2024.1 (API v2) -- retornam erro 1717
(RPC_S_UNKNOWN_IF) em versoes mais antigas, SEMPRE trate esse caso com
fallback para speakText:
- nvdaController_getProcessId(...) -> int: PID do processo NVDA.
- nvdaController_speakSsml(ssml: str, symbolLevel: int, priority: int, asynchronous: bool) -> int:
  fala com marcacao SSML (prosody, mark, break, etc).
- nvdaController_setOnSsmlMarkReachedCallback(callback) -> None: registra
  callback WINFUNCTYPE chamado quando um <mark> do SSML e alcancado.

Todas as funcoes retornam 0 em sucesso e um codigo de erro Windows padrao
em falha -- SEMPRE cheque o retorno, use ctypes.WinError(res) pro diagnostico
(ver template abaixo, identico ao exemplo oficial).

## Distribuicao da DLL

A DLL e distribuida em subpastas por arquitetura (x86/x64/arm64) dentro do
pacote `*controllerClient.zip` (download.nvaccess.org/releases/stable/).
O programa gerado DEVE carregar a DLL que corresponde a arquitetura do
PROPRIO PROCESSO CLIENTE (nao da maquina) -- normalmente basta bundlar a
pasta certa (ex: `x64/nvdaControllerClient.dll`) junto do programa e
carregar com caminho relativo.

## Seguranca (fonte: readme.md, secao "Security practices")

O NVDA roda tambem na tela de bloqueio e em telas seguras (UAC). Antes de
enviar informacao sensivel ao usuario via nvdaController_speakText, o
PROGRAMA CLIENTE deve checar se o Windows esta bloqueado/em tela segura
para evitar vazamento de dado sensivel nessas telas (ver CTRL-CLIENT-005).

## Template real (baseado no exemplo oficial extras/controllerClient/examples/example_python.py)

```python:nvda_client.py
import ctypes
import os


class NvdaControllerError(RuntimeError):
	\"\"\"Erro ao chamar a NVDA Controller Client API.\"\"\"


class NvdaClient:
	\"\"\"Wrapper fino sobre nvdaControllerClient.dll (Controller Client API).

	CTRL-CLIENT-002: carrega a DLL da subpasta que corresponde a arquitetura
	deste processo (x86/x64), bundlada junto do programa.
	\"\"\"

	def __init__(self, dll_dir: str | None = None) -> None:
		arch = "x64" if ctypes.sizeof(ctypes.c_void_p) == 8 else "x86"
		base = dll_dir or os.path.dirname(os.path.abspath(__file__))
		dll_path = os.path.join(base, arch, "nvdaControllerClient.dll")
		self._lib = ctypes.windll.LoadLibrary(dll_path)

	def _check(self, result: int) -> None:
		# CTRL-CLIENT-003: nunca ignora o codigo de retorno.
		if result != 0:
			raise NvdaControllerError(str(ctypes.WinError(result)))

	def ensure_running(self) -> None:
		# CTRL-CLIENT-001: sempre a primeira chamada.
		self._check(self._lib.nvdaController_testIfRunning())

	def speak(self, text: str, interrupt: bool = False) -> None:
		if interrupt:
			# CTRL-CLIENT-007: barge-in explicito.
			self._check(self._lib.nvdaController_cancelSpeech())
		self._check(self._lib.nvdaController_speakText(text))

	def braille(self, text: str) -> None:
		self._check(self._lib.nvdaController_brailleMessage(text))

	def cancel_speech(self) -> None:
		self._check(self._lib.nvdaController_cancelSpeech())
```

Cada arquivo Python gerado deve usar anotacao de bloco padrao
```python:caminho/do/arquivo.py``` como qualquer outro output do NVDAStudio.
Gere tambem um README.md curto explicando como rodar o programa e onde
colocar a DLL bundlada (pastas x86/x64), e um requirements.txt se houver
dependencias pip alem de ctypes (stdlib, sem dependencia externa).
"""


# =============================================================================
# Addendum de rubrica para ai/critic.py quando is_controller_client_context()
# =============================================================================

CTRL_CLIENT_CRITIC_ADDENDUM = f"""

REGRAS PARA project_type=="controller_client" (programa EXTERNO ao NVDA,
NAO um addon -- este contexto substitui as regras NVDA-XXX/manifest.ini
normais para este step, elas NAO se aplicam aqui):

{CTRL_CLIENT_RULE_CATALOG_TEXT}

APROVADO se: testIfRunning() chamado antes de qualquer outra funcao da API,
todo retorno de funcao da API checado (0=sucesso), DLL carregada por
arquitetura (x86/x64), sem manifest.ini nem globalPlugins/ gerados.
CORRIGIR se: falta alguma dessas checagens mas a estrutura geral esta correta.
REJEITAR se: nenhuma chamada real a API do Controller Client, ou o codigo
gerado e na verdade um addon NVDA tradicional (GlobalPlugin/manifest.ini) --
isso indica que o roteamento de project_type falhou e precisa ser corrigido,
nao o codigo em si.
NAO aplique NVDA-XXX, WX-A11Y-XXX ou ARCH-XXX aqui -- sao regras de addon
interno, nao deste dominio.

SUBSTITUI a regra de "assembly" da rubrica generica acima (que exige
manifest.ini) -- para project_type=="controller_client", assembly e
APROVADO se o programa cliente + README + (se houver) requirements.txt
estao presentes e coerentes. NAO exija manifest.ini nem qualquer coisa
especifica de addon aqui.
"""

