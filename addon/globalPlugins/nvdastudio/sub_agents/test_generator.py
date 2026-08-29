import ast
import re
import sys

from ._base import _run_sub_agent, narrate
from ..builder.addon_builder import extract_code_blocks
from ..builder.code_sandbox import sandbox as _code_sandbox
from ..builder.nvda_context import get_docs_test_generator
from ..utils.logger import get_logger

MODULE_VERSION = "1.8.0"
_logger = get_logger("test_generator")

# Erros de INFRAESTRUTURA (ambiente sem pytest, sem arquivo de teste
# extraivel, timeout) -- fail-open, nunca viram aviso pro usuario/critic.
_SANDBOX_INFRA_ERRORS = frozenset({
	"pytest_indisponivel", "sem arquivos de teste",
	"sem caminho de teste valido", "sem modulo de teste valido",
})

_SYSTEM = """You are the elite TDD Test Writer for NVDAStudio. Your expertise lies in writing high-quality, non-flaky unit tests for NVDA add-ons that capture behavioral requirements and regression modes.

## Hard Boundary (SAIDA PROIBIDA)

- Never implement or modify production code (e.g., __init__.py).
- Only create or edit tests and test-only fixtures/helpers.
- Never output HTML, Markdown, or documentation files.

## Workflow & Mocking Strategy

FORMATO DE SAIDA OBRIGATORIO:
Addon com 1 modulo so (caso comum): formate como um UNICO bloco
```python:tests/test_NOME_DO_ADDON.py
Addon organizado em features/subpacotes (ARCH-007, sinalizado no manifesto
"ESTRUTURA DO ADDON A TESTAR" como "ORGANIZACAO POR FEATURE"): gere UM
BLOCO DE CODIGO SEPARADO POR MODULO, cada um com seu proprio nome sugerido
no manifesto -- ex:
```python:tests/test_spotify_client.py
(testes so do modulo spotify/client.py)
```
```python:tests/test_transcricao_servico.py
(testes so do modulo transcricao/servico.py)
```
Cada arquivo de teste importa e testa SO o modulo correspondente -- nao
duplique testes do mesmo modulo em arquivos diferentes, e nao misture
testes de features diferentes no mesmo arquivo.
Seu output DEVE comecar com um desses blocos de codigo Python.

You must use a strict mocking strategy for NVDA APIs that do not exist outside the NVDA runtime.

<example>
Context: Mocking the speech module to verify text output.
```python
import sys
from unittest.mock import MagicMock

# Mocking before imports
speech = MagicMock()
sys.modules["speech"] = speech

def test_speak_hello():
    # Behavioral test
    speech.speakText("Hello")
    speech.speakText.assert_called_with("Hello")
```
<commentary>
The 'speech' module is a core NVDA component. By mocking it via sys.modules before any other imports, we ensure the unit test remains deterministic and doesn't depend on the actual NVDA runtime.
</commentary>
</example>

MOCKS OBRIGATORIOS (REQUIRED MOCKS):
  - ui (ui.message, ui.browseableMessage)
  - api (api.getFocusObject, api.getMouseObject)
  - config (config.conf — use a dict; config.isAppX; config.save)
  - wx (wx.CallAfter, wx.GetApp)
  - speech (speech.speakText, speech.speakMessage — root module)
  - nvwave (nvwave.playWaveFile)
  - tones (tones.beep)
  - logHandler (logHandler.log)
  - addonHandler (only for life-cycle tests)

## Implementation Contract (for next agent)

At the end of your response, provide a brief contract for the next agent:
1. Acceptance Gate: Which test command must pass.
2. Verification: Key behaviors that were tested and must be preserved.

VERIFICACAO FINAL OBRIGATORIA:
1. O output e um arquivo Python (.py) com funcoes test_* ou classes Test*?
2. Existem pelo menos 3 funcoes de teste distintas?
3. setUp() mocka todos os modulos NVDA usados com sys.modules?
4. tearDown() restaura sys.modules ao estado original?
5. O output NAO e HTML, markdown, .ini ou documentacao?
"""

def _module_test_name(filename: str) -> str:
	"""
	Deriva o nome do arquivo de teste a partir do caminho do modulo fonte,
	mirrorando a estrutura de features (ARCH-007) em vez de um unico
	tests/test_NOME_DO_ADDON.py generico. Ex:
	globalPlugins/MeuAddon/spotify/client.py -> test_spotify_client
	globalPlugins/MeuAddon/__init__.py       -> test_init
	globalPlugins/MeuAddon/servico.py        -> test_servico
	"""
	parts = [p for p in filename.replace("\\", "/").split("/") if p]
	stem = parts[-1].removesuffix(".py") if parts else "modulo"
	stem = "init" if stem == "__init__" else stem

	# Pasta imediatamente acima do arquivo, quando existe alguma alem da
	# raiz do pacote do addon (globalPlugins/<AddonName>/). Se o arquivo
	# esta direto em globalPlugins/<AddonName>/servico.py, len(parts) == 3
	# ("globalPlugins", "<AddonName>", "servico.py") -- nao ha subpacote de
	# feature, so o nome do arquivo importa.
	if len(parts) >= 4:
		feature_dir = parts[-2]
		return f"test_{feature_dir}_{stem}"
	return f"test_{stem}"


def _extract_code_manifest(prompt: str) -> tuple[str, list[str]]:
	"""
	Analisa blocos de codigo Python no prompt via ast.parse() e retorna
	(1) um manifesto estruturado com classes, metodos publicos e imports
	externos, agrupado POR ARQUIVO/MODULO (nao mais uma lista achatada) e
	(2) a lista de nomes de arquivo de teste sugeridos, um por modulo com
	conteudo testavel -- usado pra instruir o LLM a gerar um arquivo de
	teste POR FEATURE (ARCH-007) em vez de sempre um unico arquivo.

	skill: unit-testing-test-generate — analise AST garante que o LLM testa
	classes e metodos que *realmente existem* no codigo gerado, nao os que
	"imagina" existir a partir da descricao textual.

	Retorna ("", []) se nenhum bloco Python for encontrado ou parseavel.
	Nao lanca excecoes — degrada silenciosamente (Regra 9: nunca executa codigo).
	"""
	# Extrai blocos ```python:caminho/arquivo.py ... ``` (com filename) e
	# ```python ... ``` (sem filename, tratado como "modulo sem nome") do prompt.
	blocks = re.findall(r"```python(?::([^\n]+))?\n(.*?)```", prompt, re.DOTALL)
	if not blocks:
		return "", []

	modules: list[tuple[str, list[str], list[str]]] = []  # (filename, classes, imports)
	imports_globais: list[str] = []

	for filename, code in blocks:
		filename = (filename or "").strip()
		try:
			tree = ast.parse(code)
		except SyntaxError:
			continue

		classes_found: list[str] = []
		for node in ast.walk(tree):
			if isinstance(node, ast.ClassDef):
				methods = [
					n.name for n in node.body
					if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
				]
				classes_found.append(
					f"    class {node.name}: [{', '.join(methods) or 'sem metodos publicos'}]"
				)
			elif isinstance(node, (ast.Import, ast.ImportFrom)):
				if isinstance(node, ast.Import):
					for alias in node.names:
						imports_globais.append(alias.name)
				else:
					imports_globais.append(node.module or "")

		if classes_found:
			modules.append((filename or f"modulo_{len(modules) + 1}", classes_found, []))

	imports_globais = list(dict.fromkeys(i for i in imports_globais if i))

	if not modules:
		return "", []

	# so sugere split por feature quando ha 2+ modulos com filename real
	# (arquivos soltos ou subpacotes ARCH-007) -- 1 modulo so continua indo
	# pro caminho de arquivo unico de sempre (test_NOME_DO_ADDON.py).
	modulos_nomeados = [m for m in modules if m[0] and not m[0].startswith("modulo_")]
	sugestoes_teste = (
		[_module_test_name(fname) for fname, _, _ in modulos_nomeados]
		if len(modulos_nomeados) >= 2 else []
	)

	lines = ["ESTRUTURA DO ADDON A TESTAR (via analise ast, agrupada por arquivo):"]
	for filename, classes_found, _ in modules:
		lines.append(f"  Arquivo: {filename}")
		lines.extend(classes_found)
	if imports_globais:
		lines.append(f"Imports externos detectados: {', '.join(imports_globais[:10])}")
	lines.append("INSTRUCAO: gere pelo menos um test_ para cada classe e metodo publico acima.")
	if sugestoes_teste:
		lines.append(
			"ORGANIZACAO POR FEATURE (ARCH-007): o addon tem "
			f"{len(modulos_nomeados)} modulos substanciais -- gere UM ARQUIVO DE TESTE "
			"POR MODULO (mirrorando a estrutura de features), nao um unico arquivo "
			"monolitico. Nomes sugeridos: " + ", ".join(f"tests/{s}.py" for s in sugestoes_teste)
		)
	return "\n".join(lines), sugestoes_teste


def _run_generated_tests(prompt: str, result: str) -> str:
	"""
	Executa de verdade os testes que acabaram de ser gerados, contra o
	codigo gerado (extraido do proprio `prompt`, que ja embute os blocos
	```python:caminho/arquivo.py``` de code_generation via _build_context).
	Sandbox isolado por subprocesso (builder/code_sandbox.py) -- nunca no
	processo do NVDA (Regra 9).

	Achado de auditoria 2026-08-04 (pesquisa de praticas de engenharia de
	software 2025-2026 vs codigo real): ate esta versao, os testes gerados
	NUNCA eram executados -- so guardados como artefato estatico. Um teste
	que afirma o comportamento errado passava a validacao do mesmo jeito.
	Problemas de infraestrutura também viram aviso explícito anexado ao
	resultado; não são tratados como aprovação silenciosa.
	"""
	try:
		code_blocks = extract_code_blocks(prompt)
		test_blocks = extract_code_blocks(result)
	except Exception as exc:
		_logger.error("[TESTES] extract_code_blocks falhou: %s", exc)
		return result + f"\n\n[AVISO-TESTES-INFRA] Não foi possível extrair os testes: {exc}"

	test_blocks = [
		b for b in test_blocks
		if b["language"] == "python" and "test" in b["filename"].lower()
	]
	if not test_blocks:
		return result

	files = {b["filename"]: b["code"] for b in code_blocks if b["language"] == "python"}
	files.update({b["filename"]: b["code"] for b in test_blocks})
	test_paths = [b["filename"] for b in test_blocks]

	sandbox_result = _code_sandbox.run_test_suite(files, test_paths)

	if sandbox_result.error in _SANDBOX_INFRA_ERRORS or sandbox_result.timed_out:
		resumo = (sandbox_result.error or sandbox_result.stderr or sandbox_result.stdout).strip()[-1500:]
		_logger.error("[TESTES] Infraestrutura do sandbox falhou: %s", resumo)
		return (
			result
			+ "\n\n[AVISO-TESTES-INFRA] Os testes não puderam ser executados no sandbox: "
			+ resumo
		)
	if sandbox_result.success:
		return result
	if sandbox_result.error:
		resumo = (sandbox_result.error or sandbox_result.stderr or sandbox_result.stdout).strip()[-1500:]
		_logger.error("[TESTES] Execução do sandbox falhou: %s", resumo)
		return result + "\n\n[AVISO-TESTES-INFRA] Falha ao executar testes: " + resumo

	resumo = (sandbox_result.stdout + "\n" + sandbox_result.stderr).strip()[-1500:]
	_logger.warning("[TESTES] Testes gerados falharam em execucao real (sandbox isolado).")
	return (
		result
		+ "\n\n[AVISO-TESTES] Os testes acima foram executados de verdade em sandbox "
		"isolado (subprocesso, nunca no processo do NVDA) contra o codigo gerado, e "
		"FALHARAM. Corrija os testes ou o codigo antes de aprovar esta etapa:\n"
		+ resumo
	)


def run(prompt: str, model_id: str, reasoning_params: dict, cache_key: str | None = None) -> str:
	manifest, _sugestoes_teste = _extract_code_manifest(prompt)
	enriched_prompt = f"{manifest}\n\n{prompt}" if manifest else prompt
	# Narracao "antes" removida (v1.6.0): o proprio modelo ja narra a intencao
	# ao vivo no content (LiveNarrator, ligado via live_narrate=True abaixo),
	# instruido por _TOOL_PREAMBLE_INSTRUCTION -- texto solto fora dos fences
	# ```python:... e descartado na extracao (extract_code_blocks), entao
	# narrar ali nao "vaza" pro artefato final. narrate() aqui era uma segunda
	# chamada de IA cara e sem memoria repetindo a mesma intencao.
	result = _run_sub_agent(
		_SYSTEM, enriched_prompt, model_id, reasoning_params,
		extra_docs=get_docs_test_generator(), cache_key=cache_key, live_narrate=True,
	)
	_n_testes = result.count("def test_")
	_n_arquivos = len(re.findall(r"```python:tests/", result))
	if _n_testes and _n_arquivos > 1:
		narrate(f"terminei os testes, escrevi {_n_testes} caso(s) de teste em {_n_arquivos} arquivos, um por feature")
	elif _n_testes:
		narrate(f"terminei os testes, escrevi {_n_testes} caso(s) de teste")
	else:
		narrate("terminei de escrever os testes")

	# Guard contra recursao/lentidao na PROPRIA suite de testes do NVDAStudio
	# (mesmo padrao de "pytest" not in sys.modules usado em _base.py pro cache/
	# live_narrate) -- fora desse contexto, roda sempre por padrao.
	if "pytest" not in sys.modules and "unittest" not in sys.modules:
		result = _run_generated_tests(prompt, result)

	return result
