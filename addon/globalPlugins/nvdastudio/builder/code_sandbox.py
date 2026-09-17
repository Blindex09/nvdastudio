import ast
import re
import subprocess
import sys
import tempfile
import os
import shutil
import zipfile
from dataclasses import dataclass

from ..utils.hidden_process import CREATE_NO_WINDOW, find_python
from ..utils.logger import get_logger

MODULE_VERSION = "1.14.0"
_logger = get_logger("code_sandbox")

# Interpretador Python REAL para os subprocessos de validacao. DENTRO do NVDA,
# sys.executable e o nvda.exe -- rodar ele como python falha com WinError 740
# (requer elevacao), e era isso que jogava a validacao de execucao num loop de
# "Erro de execucao real". None => nao ha python usavel: as validacoes por
# subprocesso PULAM (ausencia de interpretador nao e defeito do codigo gerado).
_PYTHON = find_python()


def _run_hidden(*args, **kwargs):
	"""subprocess.run com a janela de console suprimida no Windows -- senao
	cada validacao/pytest/pip abre um terminal que rouba o foco do NVDA
	(ver utils/hidden_process.py). Chama o subprocess.run DESTE modulo de
	proposito: os testes que dao patch em code_sandbox.subprocess.run
	continuam valendo."""
	kwargs["creationflags"] = kwargs.get("creationflags", 0) | CREATE_NO_WINDOW
	return subprocess.run(*args, **kwargs)

_SANDBOX_TIMEOUT = 10  # segundos
_TEST_SUITE_TIMEOUT = 25  # segundos — varios arquivos/imports, mais folga que uma checagem simples
_LINT_TIMEOUT = 20  # segundos -- ruff/mypy sobre o addon gerado inteiro

# Config de lint aplicada ao codigo GERADO (nunca a do proprio NVDAStudio).
# Escolha deliberada de escopo: so regras que apontam DEFEITO real
# (F=pyflakes: nome indefinido, import nao usado, f-string sem placeholder;
# E9=erro de sintaxe/IO; B=bugbear: default mutavel, loop capturando
# variavel). Regras de ESTILO ficam de fora de proposito -- o NVDA usa TABs
# (W191/E101) e linhas longas sao comuns no core, entao ligar pycodestyle
# inteiro produziria dezenas de avisos que nao sao bugs e empurrariam o
# pipeline para retries infinitos sem ganho de qualidade.
# builtins: _/ngettext/pgettext/npgettext sao injetados em tempo de execucao
# por addonHandler.initTranslation() -- sem declara-los aqui, TODO addon
# traduzido (isto e, todo addon correto pela NVDA-019) levaria F821
# "undefined name" em cada string traduzivel. E chave top-level no schema do
# ruff, nao dentro de [lint] (confirmado contra ruff 0.16.5).
_GENERATED_RUFF_CONFIG = """builtins = ["_", "ngettext", "pgettext", "npgettext"]

[lint]
select = ["F", "E9", "B"]
ignore = ["B904"]
"""

# Config de mypy aplicada ao codigo GERADO.
#
# `name-defined` desligado de proposito, e a autoridade sobre nome indefinido
# fica com o ruff (F821), que suporta declarar builtins injetados em tempo de
# execucao -- ver `builtins` em _GENERATED_RUFF_CONFIG. O mypy nao tem esse
# mecanismo, entao para ele `_("texto")` de TODO addon traduzido (isto e, de
# todo addon correto pela NVDA-019) aparece como nome indefinido.
#
# Auditoria de 2026-09-02: rodados os NOVE portoes contra um addon
# canonicamente correto, este era o UNICO que reprovava, com
# `Name "_" is not defined` em cada string traduzivel. Nao bloqueia (mypy e
# advisory), mas o resultado vai como CONTEXTO para a proxima tentativa: o
# modelo recebia uma lista de problemas inexistentes para corrigir.
#
# Duas ferramentas opinando sobre a mesma coisa, uma delas mal informada, e
# pior que uma so: a Regra 5 vale tambem para verificacao.
_GENERATED_MYPY_CONFIG = """[mypy]
ignore_missing_imports = True
follow_imports = silent
disable_error_code = name-defined
"""


# Roda em SUBPROCESSO isolado (nunca no processo deste modulo) -- instala
# nvda_runtime_stubs.py (copiado pro mesmo diretorio temporario), importa o
# modulo principal do addon gerado e tenta instanciar a classe principal
# (GlobalPlugin/AppModule/SynthDriver/SettingsPanel). {dotted} e
# substituido pelo caminho de import ja calculado em Python real (repr()
# do proprio validate_addon_execution()), nunca por texto vindo da IA --
# format() so recebe uma string ja validada como caminho de modulo.
_RUNNER_TEMPLATE = '''\
import sys, os, inspect, traceback, importlib, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nvda_runtime_stubs
nvda_runtime_stubs.install()

DOTTED = "{dotted}"

try:
	mod = importlib.import_module(DOTTED)
except Exception:
	print("IMPORT_FALHOU")
	traceback.print_exc()
	sys.exit(1)

_BASE_NAMES = {{"GlobalPlugin", "AppModule", "SynthDriver", "SettingsPanel"}}
candidates = []
for _name, obj in vars(mod).items():
	if inspect.isclass(obj) and getattr(obj, "__module__", None) == DOTTED:
		base_names = {{b.__name__ for b in obj.__mro__}}
		if base_names & _BASE_NAMES:
			candidates.append(obj)

if not candidates:
	print("SEM_CLASSE_PRINCIPAL_ENCONTRADA")
	sys.exit(0)

_ACHADOS_SMOKE = []
_ADDON_DIR = os.path.dirname(os.path.abspath(__file__))

# Mensagens de TypeError que provam DISCORDANCIA entre chamador e definicao.
# Qualquer outro TypeError pode ser dado ruim vindo do stub, nao defeito.
_PADROES_ASSINATURA = (
	"unexpected keyword argument",
	"required positional argument",
	"required keyword-only argument",
	"positional arguments but",
	"positional argument but",
	"takes no arguments",
	"got multiple values for argument",
)


def _e_defeito_estrutural(exc_type, exc_value):
	"""So conta defeito de CODIGO, nunca falha de ambiente.

	NameError e sempre defeito. TypeError so quando a mensagem e de
	assinatura -- e o unico TypeError que prova que um chamador e uma
	definicao discordam. ImportError fica de fora DE PROPOSITO: o par
	`try: import openai / except ImportError` e o padrao CORRETO da
	NVDA-022 e apareceria em todo addon bem escrito.
	"""
	if exc_type is NameError:
		return True
	if exc_type is TypeError:
		msg = str(exc_value)
		for _p in _PADROES_ASSINATURA:
			if _p in msg:
				return True
	return False


def _trace_local(frame, event, arg):
	if event == "exception":
		_et, _ev, _tb = arg
		if _e_defeito_estrutural(_et, _ev):
			_achado = _et.__name__ + ": " + str(_ev)
			if _achado not in _ACHADOS_SMOKE:
				_ACHADOS_SMOKE.append(_achado)
	return _trace_local


def _trace_global(frame, event, arg):
	# So traceia frame do proprio addon: fora dele o custo nao se paga e
	# stub/stdlib levantam excecao que nao e defeito do addon.
	_fn = frame.f_code.co_filename
	if not _fn.startswith(_ADDON_DIR) or _fn.endswith("_sandbox_runner.py"):
		return None
	return _trace_local


def _smoke_comandos(cls, instance):
	"""Executa os comandos (@script) do addon e testemunha o que levantam.

	Instanciar prova que o addon CARREGA; nao prova que ele FAZ. O defeito
	medido em 2026-09-03 (AssistenteEscrita) passou inteiro por import,
	instanciacao e terminate, e os dois atalhos morriam na primeira tecla:
	__init__.py chamava proofread(text, model, api_key, on_done, on_error)
	e openai_service.py definia proofread(self, text, callback).

	Chamar o script e ver "se levantou" NAO basta: o addon NVDA correto
	engole a propria excecao (`except Exception` + ui.message) para nunca
	derrubar o leitor de tela -- foi exatamente o que escondeu o defeito.
	Por isso o testemunho e por sys.settrace, que registra a excecao no
	instante em que ela e LEVANTADA, antes de qualquer except do addon.
	"""
	# Sob falha injetada o alvo e a resiliencia do carregamento, nao a
	# assinatura; rodar o smoke ali so gastaria o orcamento de 3s.
	if os.environ.get("NVDASTUDIO_FAULT_SCENARIO"):
		return

	_nomes = []
	for _n in dir(cls):
		if not _n.startswith("script_"):
			continue
		# getattr no CLS, nunca na instancia: GlobalPlugin.__getattr__ do
		# stub devolve _Permissive para qualquer nome, e todo addon teria
		# "comandos" que nao existem.
		if inspect.isfunction(getattr(cls, _n, None)):
			_nomes.append(_n)
	if not _nomes:
		return

	# Modo seguro DESLIGADO de proposito: com o stub permissivo,
	# globalVars.appArgs.secure e verdadeiro, e todo script guardado por
	# NVDA-062 retornaria na primeira linha -- o smoke passaria sem
	# executar nada. O caminho que interessa aqui e o normal.
	try:
		import globalVars

		class _AppArgs:
			secure = False

			def __getattr__(self, _n):
				return nvda_runtime_stubs._Permissive()

		globalVars.appArgs = _AppArgs()
	except Exception:
		pass

	import threading

	_gesture = nvda_runtime_stubs._Permissive()
	sys.settrace(_trace_global)
	threading.settrace(_trace_global)
	try:
		for _n in _nomes:
			try:
				getattr(instance, _n)(_gesture)
			except Exception:
				# Levantar aqui nao condena o addon: sob stub, faltar dado
				# de ambiente e esperado. Quem julga e o testemunho.
				pass
		# Da tempo do trabalho em thread (padrao NVDA-002) levantar.
		time.sleep(0.2)
	finally:
		sys.settrace(None)
		threading.settrace(None)

	if _ACHADOS_SMOKE:
		print("SMOKE_FALHOU: " + cls.__name__ + " -- " + " | ".join(_ACHADOS_SMOKE))
		sys.exit(1)

for cls in candidates:
	# Injecao de falha controlada: acontece dentro do subprocesso que executa
	# o addon, depois do import e antes da instanciação. Isso exercita o codigo
	# real do addon sem tocar no NVDA ou no sistema do usuario.
	_fault = os.environ.get("NVDASTUDIO_FAULT_SCENARIO", "")
	if _fault == "api_401":
		try:
			import urllib.error
			import urllib.request
			urllib.request.urlopen = lambda *args, **kwargs: (_ for _ in ()).throw(
				urllib.error.HTTPError("http://fault.local", 401, "Unauthorized", {{}}, None)
			)
		except Exception:
			pass
	elif _fault == "missing_file":
		import builtins
		_real_open = builtins.open
		def _fault_open(file, *args, **kwargs):
			if isinstance(file, str) and not file.endswith("_sandbox_runner.py"):
				raise FileNotFoundError(2, "arquivo ausente injetado", file)
			return _real_open(file, *args, **kwargs)
		builtins.open = _fault_open
	elif _fault == "timeout":
		try:
			import socket
			import urllib.request
			def _fault_urlopen(*args, **kwargs):
				raise socket.timeout("timeout injetado")
			urllib.request.urlopen = _fault_urlopen
		except Exception:
			pass

	try:
		instance = cls()
	except Exception:
		print("INSTANCIACAO_FALHOU: " + cls.__name__)
		traceback.print_exc()
		sys.exit(1)

	# Entre instanciar e terminar: o addon esta VIVO, que e a unica janela
	# em que os comandos podem ser exercitados.
	_smoke_comandos(cls, instance)

	try:
		if hasattr(instance, "terminate"):
			instance.terminate()
	except Exception:
		print("INSTANCIACAO_FALHOU: " + cls.__name__)
		traceback.print_exc()
		sys.exit(1)

	# Verificacao de bind/unbind de teclado (Keyboard/Focus Management):
	# bindGesture() via dict de classe __gestures e o padrao estatico normal
	# do NVDA -- limpo automaticamente quando a instancia e destruida, nao
	# precisa de unbind. O risco real e bindGesture() chamado DINAMICAMENTE
	# (self.bindGesture(...) fora do dict __gestures, tipicamente em
	# resposta a mudanca de configuracao) sem removeGestureBinding()
	# correspondente em lugar nenhum da classe -- cada rebind acumula um
	# gesture duplicado apontando pro mesmo script. So roda se a
	# instanciacao/terminate ja passaram (nao bloqueia o addon por isso --
	# aviso, nao falha).
	try:
		src = inspect.getsource(cls)
		if "self.bindGesture(" in src and "removeGestureBinding" not in src:
			print("AVISO_BINDGESTURE_SEM_UNBIND: " + cls.__name__)
	except (OSError, TypeError):
		pass

print("OK")
sys.exit(0)
'''


@dataclass
class SandboxResult:
    """Resultado da execucao em sandbox."""
    success: bool
    stdout: str
    stderr: str
    error: str = ""
    exit_code: int = -1
    timed_out: bool = False
    isolated: bool = False
    isolation_backend: str = ""


_DIRS_DE_ENTRADA = (
	"globalPlugins", "appModules", "synthDrivers", "brailleDisplayDrivers",
	"visionEnhancementProviders",
)


def _e_ponto_de_entrada_de_addon(rel: str) -> bool:
	"""globalPlugins/<Addon>/__init__.py e o modulo do plugin, nao um pacote de
	re-export -- a excecao do ruff para __init__.py nao vale aqui."""
	partes = rel.replace(chr(92), "/").lstrip("/").split("/")
	return (
		len(partes) == 3
		and partes[0] in _DIRS_DE_ENTRADA
		and partes[-1] == "__init__.py"
	)


def _result_evidence(result: SandboxResult) -> str:
	"""Consolida a saída observável de uma execução isolada."""
	parts = [result.error, result.stderr, result.stdout]
	return " | ".join(part for part in parts if part) or f"exit_code={result.exit_code}"


# Operacoes de arquivo IRREVERSIVEIS. Varridas so no que roda ao CARREGAR o
# addon (nivel de modulo + __init__): um `os.remove`/`shutil.rmtree` ali quase
# nunca e legitimo e apagaria arquivos reais durante a validacao -- o subprocesso
# roda com as permissoes do usuario (isolamento de processo, nao de blast
# radius). Metodos de script (so rodam quando o usuario aciona o atalho) NAO sao
# varridos: la o codigo nao roda na validacao, e reprovar seria falso positivo.
_ATTR_DESTRUTIVOS_DE_ARQUIVO = {"rmtree", "unlink", "rmdir", "removedirs"}


def _op_destrutiva_no_carregamento(files: dict[str, str]) -> str:
	"""Descreve a 1a operacao destrutiva de arquivo que rodaria ao CARREGAR o
	addon (nivel de modulo ou __init__), ou "" se nenhuma."""

	def _perigo(call: ast.Call) -> str:
		f = call.func
		if not isinstance(f, ast.Attribute):
			return ""
		base = f.value.id if isinstance(f.value, ast.Name) else ""
		if f.attr in _ATTR_DESTRUTIVOS_DE_ARQUIVO:
			return f"{base + '.' if base else ''}{f.attr}"
		if base == "os" and f.attr in ("remove", "system"):
			return f"os.{f.attr}"
		return ""

	def _scan(stmts: list) -> str:
		for st in stmts:
			for node in ast.walk(st):
				if isinstance(node, ast.Call):
					achado = _perigo(node)
					if achado:
						return achado
		return ""

	for caminho, codigo in (files or {}).items():
		if not caminho.endswith(".py"):
			continue
		try:
			tree = ast.parse(codigo or "")
		except SyntaxError:
			continue  # sintaxe ja e reprovada por outro degrau, mais preciso
		modulo = [
			n for n in tree.body
			if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
		]
		achado = _scan(modulo)
		if achado:
			return f"{achado} em nivel de modulo de {caminho}"
		for node in ast.walk(tree):
			if isinstance(node, ast.FunctionDef) and node.name == "__init__":
				achado = _scan(node.body)
				if achado:
					return f"{achado} em __init__ de {caminho}"
	return ""


class CodeSandbox:
    """
    Sandbox para execucao segura de codigo Python.

    Executa em contêiner isolado — nunca no processo NVDA.
    Timeout rigido para evitar loops infinitos.
    Sem acesso a rede, arquivos do sistema ou modulos NVDA.
    """

    def __init__(self, timeout_sec: int = _SANDBOX_TIMEOUT):
        self.default_timeout = timeout_sec

    @staticmethod
    def _isolated_python(
        arguments: list[str], cwd: str, timeout: int, env: dict[str, str] | None = None,
    ):
        from .isolation import IsolationRunner
        return IsolationRunner().run_python(arguments, workspace=cwd, timeout=timeout, env=env)

    def run_python_code(self, code: str, timeout: int | None = None) -> SandboxResult:
        """
        Executa codigo Python em sandbox isolado.

        Args:
            code: Codigo Python a ser executado
            timeout: Timeout em segundos

        Returns:
            SandboxResult com saida e erros
        """
        if timeout is None:
            timeout = self.default_timeout

        tmpdir = tempfile.mkdtemp(prefix="nvdastudio_code_")
        try:
            temp_path = os.path.join(tmpdir, "generated.py")
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(code)
            result = self._run_subprocess(temp_path, timeout)
            return result

        except Exception as exc:
            _logger.error("[Sandbox] Erro ao criar/executar sandbox: %s", exc)
            return SandboxResult(
                success=False,
                stdout="",
                stderr="",
                error=str(exc),
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _run_subprocess(self, script_path: str, timeout: int) -> SandboxResult:
        """Executa script em subprocesso com timeout."""
        proc = self._isolated_python(
            [os.path.basename(script_path)], os.path.dirname(script_path), timeout,
            {"PYTHONPATH": ""},
        )
        return SandboxResult(
            success=proc.isolated and proc.returncode == 0,
            stdout=proc.stdout, stderr=proc.stderr, error=proc.error,
            exit_code=proc.returncode, timed_out=proc.timed_out,
            isolated=proc.isolated, isolation_backend=proc.backend,
        )

    def validate_addon_imports(self, code: str) -> SandboxResult:
        """
        Valida se os imports do addon funcionam.

        Executa apenas os imports do codigo, sem executar logica.
        Util para detectar ModuleNotFoundError antes de empacotar.
        """
        # Extrai apenas linhas de import
        import_lines = []
        for line in code.split("\n"):
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                import_lines.append(stripped)

        if not import_lines:
            return SandboxResult(success=True, stdout="", stderr="")

        import_code = "\n".join(import_lines)
        return self.run_python_code(import_code, timeout=5)

    def validate_addon_execution(
        self, files: dict[str, str], timeout: int | None = None,
        fault_scenario: str | None = None,
    ) -> SandboxResult:
        """
        Tenta IMPORTAR e INSTANCIAR de verdade a classe principal do addon
        (GlobalPlugin/AppModule/SynthDriver/SettingsPanel), em subprocesso
        isolado com os modulos NVDA simulados (nvda_runtime_stubs.py) --
        pega NameError/AttributeError/assinatura de construtor errada que
        syntax_check() (so AST, nao executa nada) nunca detecta.

        Diferente de syntax_check() (rapido, sempre roda no critic) e
        run_test_suite() (so roda se test_generation gerou testes E o
        proprio teste exercitar o bug), esta verificacao roda direto sobre
        o output de code_generation, sem depender de nenhum outro step --
        fecha a lacuna real: validate_addon_imports()/run_python_code() ja
        existiam desde 1.0.0 mas nunca eram chamados por ninguem porque
        rodar import puro contra os modulos REAIS do NVDA sempre falha
        (ModuleNotFoundError -- eles so existem dentro do processo do
        NVDA). nvda_runtime_stubs.py resolve isso com stand-ins seguros.

        Regra 9: subprocesso isolado, sem rede, sem acesso ao NVDA real.
        """
        if timeout is None:
            timeout = self.default_timeout

        main_relpath = self._find_main_module(files)
        if main_relpath is None:
            return SandboxResult(
                success=True, stdout="", stderr="",
                error="nenhum globalPlugins/*/__init__.py encontrado -- nada pra validar",
            )

        # 1.11.0 -- NAO executar codigo que apaga arquivos ao carregar.
        #
        # O subprocesso roda com as permissoes do usuario (isolamento de
        # processo, nao de blast radius). Um os.remove/shutil.rmtree em nivel de
        # modulo ou __init__ apagaria arquivos reais durante a validacao. Pular a
        # execucao contem o dano; sintaxe/lint/Critic seguem julgando o codigo.
        _perigo = _op_destrutiva_no_carregamento(files)
        if _perigo:
            _logger.warning(
                "[Sandbox] Execucao de validacao PULADA por seguranca: %s", _perigo,
            )
            return SandboxResult(
                success=True,
                stdout=f"PULADO_POR_SEGURANCA: operacao destrutiva de arquivo no carregamento ({_perigo})",
                stderr="",
                error="",
            )

        tmpdir = tempfile.mkdtemp(prefix="nvdastudio_execcheck_")
        try:
            self._write_files(tmpdir, files)

            stubs_src_path = os.path.join(os.path.dirname(__file__), "nvda_runtime_stubs.py")
            shutil.copy(stubs_src_path, os.path.join(tmpdir, "nvda_runtime_stubs.py"))

            dotted = main_relpath[: -len("/__init__.py")].replace("/", ".")
            runner_path = os.path.join(tmpdir, "_sandbox_runner.py")
            with open(runner_path, "w", encoding="utf-8") as f:
                f.write(_RUNNER_TEMPLATE.format(dotted=dotted))

            env = {"PYTHONPATH": "/workspace"}
            if fault_scenario:
                env["NVDASTUDIO_FAULT_SCENARIO"] = fault_scenario
            proc = self._isolated_python(["_sandbox_runner.py"], tmpdir, timeout, env)
            stdout, stderr = proc.stdout, proc.stderr
            return SandboxResult(
                success=proc.isolated and proc.returncode == 0,
                stdout=stdout, stderr=stderr, error=proc.error,
                exit_code=proc.returncode, timed_out=proc.timed_out,
                isolated=proc.isolated, isolation_backend=proc.backend,
            )
        except Exception as exc:
            _logger.error("[Sandbox] Erro ao preparar validate_addon_execution: %s", exc)
            return SandboxResult(success=False, stdout="", stderr="", error=str(exc))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def validate_addon_resilience(
        self, files: dict[str, str], timeout: int | None = None,
    ) -> SandboxResult:
        """Executa o addon real sob falhas injetadas no subprocesso isolado."""
        scenarios = ("api_401", "timeout", "missing_file")
        evidence: list[str] = []
        for scenario in scenarios:
            result = self.validate_addon_execution(files, timeout, scenario)
            evidence.append(f"{scenario}: {_result_evidence(result)}")
            if not result.success:
                return SandboxResult(
                    success=False,
                    stdout="\n".join(evidence),
                    stderr=result.stderr,
                    error=f"falha no cenário real {scenario}: {_result_evidence(result)}",
                    exit_code=result.exit_code,
                    timed_out=result.timed_out,
                )
        return SandboxResult(success=True, stdout="\n".join(evidence), stderr="", exit_code=0)

    def validate_final_package(self, package_path: str) -> SandboxResult:
        """Valida o arquivo .nvda-addon final, não apenas os blocos da IA."""
        if not os.path.isfile(package_path) or not zipfile.is_zipfile(package_path):
            return SandboxResult(False, "", "", error="pacote final ausente ou ZIP inválido")

        temp_root = tempfile.mkdtemp(prefix="nvdastudio_final_package_")
        try:
            with zipfile.ZipFile(package_path) as archive:
                bad_member = archive.testzip()
                if bad_member:
                    return SandboxResult(False, "", "", error=f"ZIP corrompido: {bad_member}")
                root = os.path.abspath(temp_root)
                for member in archive.infolist():
                    target = os.path.abspath(os.path.join(temp_root, member.filename))
                    if target != root and not target.startswith(root + os.sep):
                        return SandboxResult(
                            False, "", "", error=f"ZIP rejeitado por path traversal: {member.filename}"
                        )
                archive.extractall(temp_root)

            from .addon_builder import validate_addon_structure

            # O pacote do proprio NVDAStudio inclui fontes de REFERENCIA da
            # API do NVDA em nvda_docs_cache/ e o buildVars.py usado apenas
            # para construir o pacote. Eles terminam em .py, mas nao sao
            # importados pelo addon em runtime. Validá-los como modulos do
            # GlobalPlugin produz NVDA-003 falsos (gettext sem initTranslation)
            # e rejeita um pacote funcional. A remocao ocorre somente nesta
            # copia temporaria extraida; o ZIP original permanece intacto e ja
            # teve sua integridade e seus caminhos conferidos acima.
            build_vars = os.path.join(temp_root, "buildVars.py")
            if os.path.isfile(build_vars):
                os.remove(build_vars)
            global_plugins = os.path.join(temp_root, "globalPlugins")
            if os.path.isdir(global_plugins):
                for plugin_name in os.listdir(global_plugins):
                    docs_cache = os.path.join(
                        global_plugins, plugin_name, "nvda_docs_cache",
                    )
                    if os.path.isdir(docs_cache):
                        shutil.rmtree(docs_cache)

            problems = validate_addon_structure(temp_root)
            if problems:
                return SandboxResult(
                    False, "", "", error="estrutura do pacote final inválida: " + " | ".join(problems[:8])
                )

            files: dict[str, str] = {}
            for root, _, names in os.walk(temp_root):
                for name in names:
                    path = os.path.join(root, name)
                    rel = os.path.relpath(path, temp_root).replace("\\", "/")
                    if name.endswith(".py"):
                        with open(path, encoding="utf-8") as source:
                            files[rel] = source.read()

            runtime = self.validate_addon_execution(files)
            if not runtime.success:
                return SandboxResult(
                    False,
                    runtime.stdout,
                    runtime.stderr,
                    error="execução do pacote final falhou: " + _result_evidence(runtime),
                    exit_code=runtime.exit_code,
                    timed_out=runtime.timed_out,
                    isolated=runtime.isolated,
                    isolation_backend=runtime.isolation_backend,
                )
            return SandboxResult(
                True,
                "pacote íntegro; estrutura válida; execução do pacote final aprovada",
                "",
                exit_code=0,
                isolated=runtime.isolated,
                isolation_backend=runtime.isolation_backend,
            )
        except (OSError, zipfile.BadZipFile) as exc:
            return SandboxResult(False, "", "", error=f"falha ao validar pacote final: {exc}")
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    @staticmethod
    def _find_main_module(files: dict[str, str]) -> str | None:
        """Localiza globalPlugins/<Addon>/__init__.py entre os arquivos
        gerados -- convencao ja usada por builder/addon_builder.py."""
        gp_re = re.compile(r"^globalPlugins/([^/]+)/__init__\.py$")
        for relpath in files:
            norm = relpath.replace("\\", "/").lstrip("/")
            if gp_re.match(norm):
                return norm
        return None

    def run_test_suite(
        self, files: dict[str, str], test_relpaths: list[str], timeout: int | None = None,
    ) -> SandboxResult:
        """
        Escreve `files` (relpath -> conteudo) num diretorio temporario e
        executa de verdade os arquivos de teste em `test_relpaths` contra
        eles, via subprocesso isolado (mesma garantia de seguranca de
        run_python_code() -- nunca no processo do NVDA).

        Tenta `python -m pytest` primeiro (roda tanto `def test_*()` soltos
        quanto `class Test*(unittest.TestCase)`, os 2 estilos que o prompt
        de test_generator.py aceita). Se pytest nao estiver instalado no
        interpretador (comum: o Python embutido de uma instalacao real do
        NVDA pode nao ter pytest), cai pra `python -m unittest discover`
        (stdlib, sempre disponivel, mas so descobre TestCase — funcoes test_*
        soltas fora de uma classe nao sao coletadas por unittest puro).

        Nunca levanta excecao — degrada pra SandboxResult(success=False,
        error=...) em qualquer falha de infraestrutura (sem Python no PATH,
        diretorio nao gravavel, etc), pra nao derrubar o pipeline principal.
        """
        if timeout is None:
            timeout = _TEST_SUITE_TIMEOUT
        if not test_relpaths:
            return SandboxResult(success=True, stdout="", stderr="", error="sem arquivos de teste")

        tmpdir = tempfile.mkdtemp(prefix="nvdastudio_testrun_")
        try:
            self._write_files(tmpdir, files)

            safe_test_paths = [p for p in (self._safe_relpath(r) for r in test_relpaths) if p]
            if not safe_test_paths:
                return SandboxResult(success=True, stdout="", stderr="", error="sem caminho de teste valido")

            result = self._run_pytest(tmpdir, safe_test_paths, timeout)
            if result.error == "pytest_indisponivel":
                result = self._run_unittest(tmpdir, safe_test_paths, timeout)
            return result
        except Exception as exc:
            _logger.error("[Sandbox] Erro ao preparar run_test_suite: %s", exc)
            return SandboxResult(success=False, stdout="", stderr="", error=str(exc))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _write_files(self, tmpdir: str, files: dict[str, str]) -> None:
        """Escreve `files` (relpath -> conteudo) no diretorio temporario,
        rejeitando caminhos inseguros (compartilhado por run_test_suite() e
        validate_addon_execution())."""
        for relpath, content in files.items():
            safe_rel = self._safe_relpath(relpath)
            if safe_rel is None:
                continue
            full_path = os.path.join(tmpdir, safe_rel)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)

    @staticmethod
    def _safe_relpath(relpath: str) -> str | None:
        """Normaliza e rejeita caminhos absolutos ou com `..` (path traversal)."""
        normalized = relpath.replace("\\", "/").lstrip("/")
        parts = [p for p in normalized.split("/") if p not in ("", ".")]
        if not parts or ".." in parts or any(":" in p for p in parts):
            return None
        return os.path.join(*parts)

    def _run_pytest(self, cwd: str, test_relpaths: list[str], timeout: int) -> SandboxResult:
        try:
            # 2026-08-26: achado real de auditoria -- medido ao vivo, este
            # subprocess levava 3.9s de wall-clock pra rodar UM teste
            # trivial (assert 1==1), contra 0.58s com plugin autoload
            # desligado (7x mais rapido; o tempo interno do proprio pytest
            # caiu de 0.87s pra 0.01s). O ambiente herdado (env real
            # completo, ver comentario abaixo) faz o subprocess descobrir e
            # importar TODOS os plugins de terceiros instalados no
            # interpretador (hypothesis/langsmith/anyio/flask/cov/mock),
            # nenhum dos quais os testes gerados por test_generator.py
            # (asserts simples, unittest.mock.patch) precisam. Sob
            # contencao real de CPU (suite completa do NVDAStudio rodando
            # em paralelo), essa sobrecarga sozinha ja passava perto do
            # teto de _TEST_SUITE_TIMEOUT (25s) -- root cause do timeout
            # flaky, nao falta de tempo de execucao real. Plugins BUILT-IN
            # do pytest (fixtures, mocks via unittest.mock stdlib)
            # continuam funcionando -- so entry points de terceiros
            # deixam de autocarregar.
            env = os.environ.copy()
            env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
            proc = self._isolated_python(
                ["-m", "pytest", "-q", "--no-header", *test_relpaths], cwd, timeout,
                {"PYTEST_DISABLE_PLUGIN_AUTOLOAD": env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"]},
            )
        except Exception as exc:
            return SandboxResult(success=False, stdout="", stderr="", error=str(exc))

        if proc.error:
            return SandboxResult(
                False, proc.stdout, proc.stderr, error=proc.error,
                timed_out=proc.timed_out, isolated=proc.isolated,
                isolation_backend=proc.backend,
            )
        stdout, stderr = proc.stdout, proc.stderr
        if proc.returncode != 0 and re.search(r"No module named .?pytest", stdout + stderr):
            return SandboxResult(False, stdout, stderr, error="pytest_indisponivel", isolated=True, isolation_backend=proc.backend)
        return SandboxResult(proc.returncode == 0, stdout, stderr, exit_code=proc.returncode, isolated=True, isolation_backend=proc.backend)

    def _run_unittest(self, cwd: str, test_relpaths: list[str], timeout: int) -> SandboxResult:
        modules = []
        for relpath in test_relpaths:
            if not relpath.endswith(".py"):
                continue
            dotted = relpath[:-3].replace("/", ".").replace(os.sep, ".")
            modules.append(dotted)
        if not modules:
            return SandboxResult(success=True, stdout="", stderr="", error="sem modulo de teste valido")
        proc = self._isolated_python(["-m", "unittest", *modules, "-v"], cwd, timeout)

        return SandboxResult(
            success=proc.isolated and proc.returncode == 0,
            stdout=proc.stdout, stderr=proc.stderr, error=proc.error,
            exit_code=proc.returncode, timed_out=proc.timed_out,
            isolated=proc.isolated, isolation_backend=proc.backend,
        )

    def lint_check(
        self, files: dict[str, str], timeout: int | None = None,
    ) -> SandboxResult:
        """
        Roda `ruff check` sobre o codigo Python GERADO, num diretorio
        temporario isolado, com a config curada de _GENERATED_RUFF_CONFIG
        (so regras de defeito real -- ver comentario na constante).

        Fecha a assimetria historica do projeto: o CI do NVDAStudio exige
        `ruff check` limpo no proprio codigo, mas o addon entregue ao
        usuario nunca passava por lint nenhum -- so AST, import e pytest.

        FAIL-OPEN (mesma politica de `pytest_indisponivel` em _run_pytest):
        se o ruff nao estiver instalado no interpretador -- caso normal no
        Python embutido de uma instalacao real do NVDA -- retorna
        success=True com error="ruff_indisponivel". Ausencia de ferramenta
        e falha de INFRAESTRUTURA, nunca defeito do addon; bloquear o
        pipeline por isso quebraria o addon de quem nao tem dev tooling.

        Regra 9: nao executa o addon. `ruff` faz analise estatica.
        """
        return self._run_static_tool(
            files,
            timeout,
            tool_argv=["-m", "ruff", "check", "--output-format=concise", "--no-cache", "."],
            prefix="nvdastudio_lint_",
            missing_pattern=r"No module named .?ruff",
            missing_error="ruff_indisponivel",
            config_filename="ruff.toml",
            config_content=_GENERATED_RUFF_CONFIG,
        )

    def lint_autofix(
        self, files: dict[str, str], timeout: int | None = None,
    ) -> dict[str, str]:
        """
        Aplica as correcoes SEGURAS do ruff no codigo gerado e devolve o
        conteudo corrigido, arquivo a arquivo.

        Medido nos 391 relatorios E2E: 9 steps de code_generation reprovados
        por lint, 3.298.179 tokens. Das 60 ocorrencias citadas, 49 sao F401
        (import nao usado, 43x), F841 (variavel nao usada) e B007 -- defeitos
        reais, mas SEM decisao semantica nenhuma: apagar uma linha. Pagar
        tres tentativas de um modelo a ~140 mil tokens cada para remover um
        import e o mesmo erro que ja custou caro com indentacao e gettext.

        As 11 restantes (F821 nome indefinido, F823 uso antes da atribuicao)
        NAO tem correcao mecanica -- sao bug de verdade, e continuam indo pro
        modelo via lint_check(). Corrigir o mecanico limpa o ruido e deixa o
        retry falando so do que exige julgamento.

        So correcoes seguras: `--fix` sem `--unsafe-fixes`. O ruff classifica
        como insegura toda correcao que pode mudar comportamento (remover uma
        atribuicao com efeito colateral, por exemplo) -- essas ficam de fora
        de proposito.

        Nunca levanta e nunca piora: arquivo cujo resultado nao compile, ou
        que o ruff nao consiga processar, volta identico ao original. Ruff
        ausente devolve tudo intacto (mesma politica fail-open de
        lint_check()).

        Regra 9: nao executa o addon. `ruff` faz analise estatica.
        """
        corrigidos = dict(files)
        for rel, conteudo in files.items():
            if not rel.replace("\\", "/").endswith(".py") or not conteudo:
                continue
            novo = self._ruff_fix_um_arquivo(rel, conteudo, timeout)
            if novo is None or novo == conteudo:
                continue
            # A correcao NUNCA pode piorar o arquivo. O `--fix` do ruff remove
            # import "nao usado", e ha import que existe por EFEITO COLATERAL --
            # verificado: `import gui` sozinho e apagado. Se a remocao deixar
            # algum nome indefinido que antes nao existia, o arquivo volta ao
            # original: trocar um aviso de estilo por um NameError em execucao no
            # NVDA do usuario seria um pessimo negocio.
            if self._nomes_indefinidos(rel, novo, timeout) > self._nomes_indefinidos(
                rel, conteudo, timeout,
            ):
                _logger.warning(
                    "[LINT-FIX] %s: a correcao criaria nome indefinido -- descartada.",
                    rel,
                )
                continue
            corrigidos[rel] = novo
        return corrigidos

    def _ruff_fix_reexport(
        self, rel: str, conteudo: str, timeout: int | None = None,
    ) -> str:
        """
        Segunda passada de F401 para o ponto de entrada do addon.

        A recusa do ruff em remover import nao usado de `__init__.py` e amarrada
        ao NOME do arquivo, nao ao conteudo -- verificado: `--unsafe-fixes` e
        `ignore-init-module-imports` (deprecado) nao mudam nada. Lintar o MESMO
        conteudo sob outro nome remove os imports normalmente.

        Isso e legitimo aqui e so aqui: a excecao do ruff existe porque
        `__init__.py` de pacote costuma re-exportar. O
        globalPlugins/<Addon>/__init__.py de um addon NVDA nao re-exporta nada --
        e o modulo do plugin, o arquivo que o NVDA carrega e executa.
        Subpacote (`<Addon>/<sub>/__init__.py`) NAO entra aqui, porque ali o
        re-export e legitimo.

        A guarda de nome indefinido continua valendo por cima: se a remocao
        quebrar algo, o arquivo volta ao original.
        """
        apelido = rel.rsplit("/", 1)[0] + "/_entrada_para_lint.py"
        with tempfile.TemporaryDirectory(prefix="nvdastudio_reexp_") as tmpdir:
            cfg = os.path.join(tmpdir, "ruff.toml")
            with open(cfg, "w", encoding="utf-8") as f:
                f.write(_GENERATED_RUFF_CONFIG)
            try:
                proc = _run_hidden(
                    [(_PYTHON or sys.executable), "-m", "ruff", "check", "--fix", "--no-cache",
                     "--select", "F401", "--config", cfg,
                     "--stdin-filename", apelido, "-"],
                    input=conteudo, capture_output=True, text=True,
                    timeout=timeout or _LINT_TIMEOUT,
                )
            except (subprocess.TimeoutExpired, OSError):
                return ""
        return proc.stdout if proc.stdout.strip() else ""

    def _nomes_indefinidos(
        self, rel: str, conteudo: str, timeout: int | None = None,
    ) -> int:
        """Quantos F821/F823 o ruff acha neste conteudo. -1 quando nao da para
        saber (ruff ausente, timeout) -- e nesse caso a comparacao nunca acusa
        piora, porque duas medidas desconhecidas sao iguais."""
        with tempfile.TemporaryDirectory(prefix="nvdastudio_undef_") as tmpdir:
            cfg = os.path.join(tmpdir, "ruff.toml")
            with open(cfg, "w", encoding="utf-8") as f:
                f.write(_GENERATED_RUFF_CONFIG)
            try:
                proc = _run_hidden(
                    [(_PYTHON or sys.executable), "-m", "ruff", "check", "--no-cache",
                     "--config", cfg, "--select", "F821,F823",
                     "--output-format=concise", "--stdin-filename", rel, "-"],
                    input=conteudo, capture_output=True, text=True,
                    timeout=timeout or _LINT_TIMEOUT,
                )
            except (subprocess.TimeoutExpired, OSError):
                return -1
        if proc.returncode not in (0, 1):
            return -1
        return sum(
            1 for linha in proc.stdout.splitlines()
            if "F821" in linha or "F823" in linha
        )

    def _ruff_fix_um_arquivo(
        self, rel: str, conteudo: str, timeout: int | None = None,
    ) -> str | None:
        """Conteudo corrigido, ou None quando nao da para confiar no resultado."""
        import ast

        with tempfile.TemporaryDirectory(prefix="nvdastudio_fix_") as tmpdir:
            cfg = os.path.join(tmpdir, "ruff.toml")
            with open(cfg, "w", encoding="utf-8") as f:
                f.write(_GENERATED_RUFF_CONFIG)
            try:
                proc = _run_hidden(
                    [(_PYTHON or sys.executable), "-m", "ruff", "check", "--fix", "--no-cache",
                     "--config", cfg, "--stdin-filename", rel, "-"],
                    input=conteudo, capture_output=True, text=True,
                    timeout=timeout or _LINT_TIMEOUT,
                )
            except (subprocess.TimeoutExpired, OSError) as exc:
                _logger.info("[LINT-FIX] %s: %s", rel, exc)
                return None

        saida = proc.stdout

        # O ruff NAO remove import nao usado em __init__.py: assume que pode
        # ser re-export de pacote, e marca a correcao como insegura. Mas o
        # globalPlugins/<Addon>/__init__.py de um addon NVDA nao e pacote de
        # re-export -- e o modulo do plugin, o arquivo que o NVDA carrega e
        # executa. A excecao do ruff nao se aplica a ele.
        #
        # Medido na rodada 8: cg_core reprovado por "F401 `os` imported but
        # unused" no __init__.py, 336.994 tokens, enquanto o mesmo defeito era
        # corrigido sem drama nos outros arquivos do mesmo addon.
        #
        # A guarda de nome indefinido (_nomes_indefinidos) continua valendo por
        # cima disto: se a remocao quebrar algo, o arquivo volta ao original.
        if saida.strip() and _e_ponto_de_entrada_de_addon(rel):
            saida = self._ruff_fix_reexport(rel, saida, timeout) or saida

        if not saida.strip():
            # ruff ausente, ou erro antes de escrever o arquivo corrigido.
            return None
        try:
            ast.parse(saida)
        except SyntaxError:
            _logger.warning("[LINT-FIX] %s: resultado nao compila -- descartado.", rel)
            return None
        return saida

    def typecheck(
        self, files: dict[str, str], timeout: int | None = None,
    ) -> SandboxResult:
        """
        Roda `mypy` sobre o codigo Python GERADO, em diretorio isolado.

        --ignore-missing-imports e obrigatorio aqui: os modulos que o addon
        importa (globalPluginHandler, addonHandler, ui, wx, config...) sao
        injetados pelo PROCESSO do NVDA em tempo de execucao e nao existem
        no interpretador de dev -- exatamente o mesmo motivo que levou o
        mypy.ini da raiz a declarar `ignore_missing_imports` para cada um
        deles. Sem a flag, 100% do resultado seria import-not-found.

        FAIL-OPEN identico a lint_check() quando o mypy nao esta instalado.

        Regra 9: nao executa o addon. `mypy` faz analise estatica.
        """
        return self._run_static_tool(
            files,
            timeout,
            tool_argv=[
                "-m", "mypy",
                "--ignore-missing-imports",
                "--follow-imports=silent",
                "--no-error-summary",
                "--no-color-output",
                "--cache-dir", os.devnull,
                ".",
            ],
            prefix="nvdastudio_typecheck_",
            missing_pattern=r"No module named .?mypy",
            missing_error="mypy_indisponivel",
            config_filename="mypy.ini",
            config_content=_GENERATED_MYPY_CONFIG,
        )

    def _run_static_tool(
        self,
        files: dict[str, str],
        timeout: int | None,
        tool_argv: list[str],
        prefix: str,
        missing_pattern: str,
        missing_error: str,
        config_filename: str | None = None,
        config_content: str | None = None,
    ) -> SandboxResult:
        """
        Escreve `files` num tmpdir e roda uma ferramenta de analise ESTATICA
        (ruff/mypy) sobre ele, em subprocesso isolado com timeout.

        Compartilhado por lint_check() e typecheck() -- a unica diferenca
        real entre as duas e o argv e o arquivo de config, entao duplicar
        toda a preparacao de tmpdir/subprocesso/degradacao seria a
        duplicacao de fluxo que a Regra 5 do README proibe.

        Nunca levanta excecao: qualquer falha de infraestrutura vira
        SandboxResult(success=True, error=...) -- fail-open.
        """
        if timeout is None:
            timeout = _LINT_TIMEOUT

        py_files = {
            rel: content for rel, content in files.items()
            if rel.replace("\\", "/").endswith(".py")
        }
        if not py_files:
            return SandboxResult(success=True, stdout="", stderr="", error="sem arquivo Python")

        tmpdir = tempfile.mkdtemp(prefix=prefix)
        try:
            self._write_files(tmpdir, py_files)
            if config_filename and config_content:
                with open(os.path.join(tmpdir, config_filename), "w", encoding="utf-8") as f:
                    f.write(config_content)

            try:
                proc = _run_hidden(
                    [(_PYTHON or sys.executable), *tool_argv],
                    capture_output=True, text=True, timeout=timeout, cwd=tmpdir,
                    # Ambiente REAL herdado, mesmo motivo ja documentado em
                    # _run_pytest(): ruff/mypy costumam estar instalados como
                    # --user e vivem num site-packages que so e resolvido via
                    # APPDATA/USERPROFILE no Windows.
                    env=os.environ.copy(),
                )
            except subprocess.TimeoutExpired:
                # Timeout de ferramenta estatica e infraestrutura lenta, nao
                # defeito do addon -- fail-open igual a ausencia da ferramenta.
                return SandboxResult(
                    success=True, stdout="", stderr="",
                    error=f"analise estatica excedeu {timeout}s", timed_out=True,
                )
            except OSError:
                return SandboxResult(success=True, stdout="", stderr="", error=missing_error)

            stdout, stderr = proc.stdout[:5000], proc.stderr[:5000]
            if re.search(missing_pattern, stdout + stderr):
                return SandboxResult(success=True, stdout="", stderr="", error=missing_error)

            return SandboxResult(
                success=proc.returncode == 0, stdout=stdout, stderr=stderr,
                exit_code=proc.returncode,
            )
        except Exception as exc:
            _logger.error("[Sandbox] Erro ao preparar analise estatica: %s", exc)
            return SandboxResult(success=True, stdout="", stderr="", error=str(exc))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def syntax_check(self, code: str) -> SandboxResult:
        """
        Verifica sintaxe Python via ast.parse (rapido, sem subprocesso).

        Returns:
            SandboxResult com resultado da verificacao
        """
        try:
            import ast
            ast.parse(code)
            return SandboxResult(success=True, stdout="", stderr="")
        except SyntaxError as exc:
            return SandboxResult(
                success=False,
                stdout="",
                stderr=str(exc),
                error=f"SyntaxError: linha {exc.lineno}, {exc.msg}",
            )


# Instancia global
sandbox = CodeSandbox()
