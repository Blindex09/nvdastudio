import ast
import re
import subprocess
import sys
import tempfile
import os
import shutil
import zipfile
from dataclasses import dataclass

from .hidden_process import CREATE_NO_WINDOW, find_python
from .logger import get_logger

MODULE_VERSION = "1.14.0"
_logger = get_logger("code_sandbox")

# REAL Python interpreter for the validation subprocesses. INSIDE NVDA,
# sys.executable is nvda.exe -- running it as python fails with WinError 740
# (requires elevation), and that is what threw execution validation into a loop of
# "real execution error". None => no usable python: the validations by
# subprocess SKIP (absence of an interpreter is not a defect of the generated code).
_PYTHON = find_python()


def _run_hidden(*args, **kwargs):
	"""subprocess.run with the console window suppressed on Windows -- otherwise
	every validation/pytest/pip opens a terminal that steals NVDA's focus
	(see hidden_process.py). It calls the subprocess.run OF THIS module on
	purpose: the tests that patch code_sandbox.subprocess.run
	keep working."""
	kwargs["creationflags"] = kwargs.get("creationflags", 0) | CREATE_NO_WINDOW
	# The server's stdin is the MCP protocol: a child must never inherit or read it.
	kwargs.setdefault("stdin", subprocess.DEVNULL)
	return subprocess.run(*args, **kwargs)

_SANDBOX_TIMEOUT = 10  # seconds
_TEST_SUITE_TIMEOUT = 25  # seconds — several files/imports, more slack than a simple check
_LINT_TIMEOUT = 20  # seconds -- ruff/mypy over the whole generated add-on

# Lint config applied to the GENERATED code (never NVDAStudio's own).
# Deliberate choice of scope: only rules that point at a real DEFECT
# (F=pyflakes: undefined name, unused import, f-string without placeholder;
# E9=syntax/IO error; B=bugbear: mutable default, loop capturing a
# variable). STYLE rules are left out on purpose -- NVDA uses TABs
# (W191/E101) and long lines are common in the core, so turning on all of
# pycodestyle would produce dozens of warnings that are not bugs and would push the
# builtins: _/ngettext/pgettext/npgettext are injected at runtime
# by addonHandler.initTranslation() -- without declaring them here, EVERY
# translated add-on (that is, every add-on correct per NVDA-019) would get F821
# "undefined name" on each translatable string. It is a top-level key in the
# ruff schema, not inside [lint] (confirmed against ruff 0.16.5).
_GENERATED_RUFF_CONFIG = """builtins = ["_", "ngettext", "pgettext", "npgettext"]

[lint]
select = ["F", "E9", "B"]
ignore = ["B904"]
"""

# mypy config applied to the GENERATED code.
#
# `name-defined` is turned off on purpose, and the authority on undefined names
# stays with ruff (F821), which supports declaring builtins injected at
# runtime -- see `builtins` in _GENERATED_RUFF_CONFIG. mypy has no such
# mechanism, so for it `_("text")` of EVERY translated add-on (that is, of
# every add-on correct per NVDA-019) shows up as an undefined name.
#
# canonically correct, this was the ONLY one that failed, with
# `Name "_" is not defined` on each translatable string. It does not block (mypy is
# advisory), but the result goes as CONTEXT for the next attempt: the
# model received a list of nonexistent problems to fix.
#
# Two tools giving opinions on the same thing, one of them poorly informed, and
_GENERATED_MYPY_CONFIG = """[mypy]
ignore_missing_imports = True
follow_imports = silent
disable_error_code = name-defined
"""


# Runs in an isolated SUBPROCESS (never in this module's process) -- installs
# nvda_runtime_stubs.py (copied into the same temporary directory), imports the
# main module of the generated add-on and tries to instantiate the main class
# (GlobalPlugin/AppModule/SynthDriver/SettingsPanel). {dotted} is
# replaced by the import path already computed in real Python (repr()
# format() only receives a string already validated as a module path.
_RUNNER_TEMPLATE = '''\
import sys, os, inspect, traceback, importlib, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nvda_runtime_stubs
nvda_runtime_stubs.install()

DOTTED = "{dotted}"

try:
	mod = importlib.import_module(DOTTED)
except Exception:
	print("IMPORT_FAILED")
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
	print("NO_MAIN_CLASS_FOUND")
	sys.exit(0)

_ACHADOS_SMOKE = []
_ADDON_DIR = os.path.dirname(os.path.abspath(__file__))

# TypeError messages that prove a MISMATCH between caller and definition.
# Any other TypeError may be bad data coming from the stub, not a defect.
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
	"""Only counts CODE defects, never environment failures.

	NameError is always a defect. TypeError only when the message is about
	a signature -- it is the only TypeError that proves a caller and a
	definition disagree. ImportError is left out ON PURPOSE: the pair
	`try: import openai / except ImportError` is the CORRECT pattern of
	NVDA-022 and would show up in every well-written add-on.
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
	# Only traces frames of the add-on itself: outside it the cost does not pay off and
	# stub/stdlib raise exceptions that are not an add-on defect.
	_fn = frame.f_code.co_filename
	if not _fn.startswith(_ADDON_DIR) or _fn.endswith("_sandbox_runner.py"):
		return None
	return _trace_local


def _smoke_comandos(cls, instance):
	"""Runs the add-on's commands (@script) and witnesses what they raise.

	Instantiating proves the add-on LOADS; it does not prove it WORKS. The defect
	got through import,
	instantiation and terminate, and both shortcuts died on the first keypress:
	__init__.py called proofread(text, model, api_key, on_done, on_error)
	and openai_service.py defined proofread(self, text, callback).

	Calling the script and checking "did it raise" is NOT enough: a correct NVDA add-on
	swallows its own exception (`except Exception` + ui.message) so it never
	brings the screen reader down -- that is exactly what hid the defect.
	So the witness is sys.settrace, which records the exception at the
	moment it is RAISED, before any except in the add-on.
	"""
	# Under an injected fault the target is load resilience, not the
	# signature; running the smoke there would only burn the 3s budget.
	if os.environ.get("NVDASTUDIO_FAULT_SCENARIO"):
		return

	_nomes = []
	for _n in dir(cls):
		if not _n.startswith("script_"):
			continue
		# getattr on CLS, never on the instance: the stub's GlobalPlugin.__getattr__
		# returns _Permissive for any name, and every add-on would have
		# "commands" that do not exist.
		if inspect.isfunction(getattr(cls, _n, None)):
			_nomes.append(_n)
	if not _nomes:
		return

	# Secure mode OFF on purpose: with the permissive stub,
	# globalVars.appArgs.secure is truthy, and every script guarded by
	# NVDA-062 would return on the first line -- the smoke would pass without
	# running anything. The path that matters here is the normal one.
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
				# Raising here does not condemn the add-on: under a stub, missing
				# environment data is expected. The witness is what judges.
				pass
		# Gives thread work (NVDA-002 pattern) time to raise.
		time.sleep(0.2)
	finally:
		sys.settrace(None)
		threading.settrace(None)

	if _ACHADOS_SMOKE:
		print("SMOKE_FAILED: " + cls.__name__ + " -- " + " | ".join(_ACHADOS_SMOKE))
		sys.exit(1)

for cls in candidates:
	# Controlled fault injection: it happens inside the subprocess that runs
	# the add-on, after the import and before the instantiation. This exercises the real
	# add-on code without touching NVDA or the user's system.
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
				raise FileNotFoundError(2, "injected missing file", file)
			return _real_open(file, *args, **kwargs)
		builtins.open = _fault_open
	elif _fault == "timeout":
		try:
			import socket
			import urllib.request
			def _fault_urlopen(*args, **kwargs):
				raise socket.timeout("injected timeout")
			urllib.request.urlopen = _fault_urlopen
		except Exception:
			pass

	try:
		instance = cls()
	except Exception:
		print("INSTANTIATION_FAILED: " + cls.__name__)
		traceback.print_exc()
		sys.exit(1)

	# Between instantiating and terminating: the add-on is ALIVE, which is the only window
	# in which the commands can be exercised.
	_smoke_comandos(cls, instance)

	try:
		if hasattr(instance, "terminate"):
			instance.terminate()
	except Exception:
		print("INSTANTIATION_FAILED: " + cls.__name__)
		traceback.print_exc()
		sys.exit(1)

	# Keyboard bind/unbind check (Keyboard/Focus Management):
	# bindGesture() via the class dict __gestures is NVDA's normal static
	# pattern -- cleaned up automatically when the instance is destroyed, it
	# needs no unbind. The real risk is bindGesture() called DYNAMICALLY
	# (self.bindGesture(...) outside the __gestures dict, typically in
	# response to a configuration change) without a matching removeGestureBinding()
	# anywhere in the class -- every rebind accumulates a
	# duplicate gesture pointing at the same script. It only runs if
	# instantiation/terminate already passed (it does not block the add-on for this --
	# warning, not failure).
	try:
		src = inspect.getsource(cls)
		if "self.bindGesture(" in src and "removeGestureBinding" not in src:
			print("WARNING_BINDGESTURE_WITHOUT_UNBIND: " + cls.__name__)
	except (OSError, TypeError):
		pass

print("OK")
sys.exit(0)
'''


@dataclass
class SandboxResult:
    """Result of the sandbox execution."""
    success: bool
    stdout: str
    stderr: str
    error: str = ""
    exit_code: int = -1
    timed_out: bool = False
    isolated: bool = False
    isolation_backend: str = ""






def _result_evidence(result: SandboxResult) -> str:
	"""Consolidates the observable output of an isolated execution."""
	parts = [result.error, result.stderr, result.stdout]
	return " | ".join(part for part in parts if part) or f"exit_code={result.exit_code}"


# IRREVERSIBLE file operations. Scanned only in what runs when the add-on LOADS
# (module level + __init__): an `os.remove`/`shutil.rmtree` there is almost
# never legitimate and would delete real files during validation -- the subprocess
# runs with the user's permissions (process isolation, not blast
# radius isolation). Script methods (which only run when the user triggers the shortcut) are NOT
# scanned: there the code does not run in validation, and failing it would be a false positive.
_ATTR_DESTRUTIVOS_DE_ARQUIVO = {"rmtree", "unlink", "rmdir", "removedirs"}


def _op_destrutiva_no_carregamento(files: dict[str, str]) -> str:
	"""Describes the 1st destructive file operation that would run when the
	add-on LOADS (module level or __init__), or "" if none."""

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
			continue  # syntax is already rejected by another, more precise, step
		modulo = [
			n for n in tree.body
			if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
		]
		achado = _scan(modulo)
		if achado:
			return f"{achado} at module level in {caminho}"
		for node in ast.walk(tree):
			if isinstance(node, ast.FunctionDef) and node.name == "__init__":
				achado = _scan(node.body)
				if achado:
					return f"{achado} in __init__ of {caminho}"
	return ""


class CodeSandbox:
    """
    Sandbox for safe execution of Python code.

    Runs in an isolated container — never in the NVDA process.
    Strict timeout to avoid infinite loops.
    No access to the network, system files or NVDA modules.
    """

    def __init__(self, timeout_sec: int = _SANDBOX_TIMEOUT):
        self.default_timeout = timeout_sec

    @staticmethod
    def _isolated_python(
        arguments: list[str], cwd: str, timeout: int, env: dict[str, str] | None = None,
    ):
        from .isolation import IsolationRunner
        return IsolationRunner().run_python(arguments, workspace=cwd, timeout=timeout, env=env)




    def validate_addon_execution(
        self, files: dict[str, str], timeout: int | None = None,
        fault_scenario: str | None = None,
    ) -> SandboxResult:
        """
        Actually tries to IMPORT and INSTANTIATE the add-on's main class
        (GlobalPlugin/AppModule/SynthDriver/SettingsPanel), in an isolated
        subprocess with the simulated NVDA modules (nvda_runtime_stubs.py) --
        it catches NameError/AttributeError/wrong constructor signature that
        a syntax-only check never detects.

        run_test_suite() (only runs if tests exist AND the test itself
        exercises the bug), this check runs directly over the code and
        closes the real gap: the checks
        existed since 1.0.0 but were never called by anyone because
        running a plain import against the REAL NVDA modules always fails
        (ModuleNotFoundError -- they only exist inside the NVDA
        process). nvda_runtime_stubs.py solves this with safe stand-ins.

        Isolated subprocess, no network, no access to the real NVDA.
        """
        if timeout is None:
            timeout = self.default_timeout

        entries = self._find_entry_modules(files)
        if not entries:
            return SandboxResult(
                success=True, stdout="", stderr="",
                error="no entry point found (globalPlugins/, appModules/, synthDrivers/, "
                      "brailleDisplayDrivers/) -- nothing to validate",
            )

        # 1.11.0 -- do NOT execute code that deletes files on load.
        #
        # The subprocess runs with the user's permissions (process
        # isolation, not blast radius isolation). An os.remove/shutil.rmtree at module level
        # or in __init__ would delete real files during validation. Skipping the
        # execution contains the damage; syntax and lint keep judging the code.
        _perigo = _op_destrutiva_no_carregamento(files)
        if _perigo:
            _logger.warning(
                "[Sandbox] Validation execution SKIPPED for safety: %s", _perigo,
            )
            motivo = f"SKIPPED_FOR_SAFETY: destructive file operation on load ({_perigo})"
            # nothing was executed: success with `error` filled in is read as not_run
            return SandboxResult(success=True, stdout=motivo, stderr="", error=motivo)

        results = [self._run_entry(files, entry, timeout, fault_scenario) for entry in entries]
        failed = [r for r in results if not r.success]
        if failed:
            return failed[0]
        return SandboxResult(
            success=True, stdout=chr(10).join(r.stdout for r in results if r.stdout), stderr="",
            exit_code=0, isolated=all(r.isolated for r in results),
            isolation_backend=results[0].isolation_backend,
        )

    def _run_entry(
        self, files: dict[str, str], main_relpath: str, timeout: int, fault_scenario: str | None,
    ) -> SandboxResult:
        """Imports and instantiates ONE entry point, in a container."""
        tmpdir = tempfile.mkdtemp(prefix="nvdastudio_execcheck_")
        try:
            self._write_files(tmpdir, files)

            stubs_src_path = os.path.join(os.path.dirname(__file__), "nvda_runtime_stubs.py")
            shutil.copy(stubs_src_path, os.path.join(tmpdir, "nvda_runtime_stubs.py"))

            module_path = main_relpath[: -len("/__init__.py")] if main_relpath.endswith("/__init__.py") else main_relpath[: -len(".py")]
            dotted = module_path.replace("/", ".")
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
            _logger.error("[Sandbox] Error preparing validate_addon_execution: %s", exc)
            return SandboxResult(success=False, stdout="", stderr="", error=str(exc))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def validate_addon_resilience(
        self, files: dict[str, str], timeout: int | None = None,
    ) -> SandboxResult:
        """Runs the real add-on under faults injected into the isolated subprocess."""
        scenarios = ("api_401", "timeout", "missing_file")
        evidence: list[str] = []
        for scenario in scenarios:
            result = self.validate_addon_execution(files, timeout, scenario)
            if result.success and result.error:
                return result  # nothing was executed (e.g. no globalPlugins): not a success
            evidence.append(f"{scenario}: {_result_evidence(result)}")
            if not result.success:
                return SandboxResult(
                    success=False,
                    stdout="\n".join(evidence),
                    stderr=result.stderr,
                    error=f"failure in the real scenario {scenario}: {_result_evidence(result)}",
                    exit_code=result.exit_code,
                    timed_out=result.timed_out,
                )
        return SandboxResult(success=True, stdout="\n".join(evidence), stderr="", exit_code=0)

    def validate_final_package(self, package_path: str) -> SandboxResult:
        """Validates the final .nvda-addon file, not just the source blocks."""
        if not os.path.isfile(package_path) or not zipfile.is_zipfile(package_path):
            return SandboxResult(False, "", "", error="final package missing or invalid ZIP")

        temp_root = tempfile.mkdtemp(prefix="nvdastudio_final_package_")
        try:
            with zipfile.ZipFile(package_path) as archive:
                bad_member = archive.testzip()
                if bad_member:
                    return SandboxResult(False, "", "", error=f"Corrupted ZIP: {bad_member}")
                root = os.path.abspath(temp_root)
                for member in archive.infolist():
                    target = os.path.abspath(os.path.join(temp_root, member.filename))
                    if target != root and not target.startswith(root + os.sep):
                        return SandboxResult(
                            False, "", "", error=f"ZIP rejected for path traversal: {member.filename}"
                        )
                archive.extractall(temp_root)

            from .addon_builder import validate_addon_structure

            # NVDAStudio's own package includes REFERENCE sources of the
            # NVDA API in nvda_docs_cache/ and the buildVars.py used only
            # to build the package. They end in .py, but are not
            # imported by the add-on at runtime. Validating them as GlobalPlugin
            # modules produces false NVDA-003 (gettext without initTranslation)
            # and rejects a working package. The removal happens only in this
            # temporary extracted copy; the original ZIP stays intact and has already
            # had its integrity and paths checked above.
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
                    False, "", "", error="invalid final package structure: " + " | ".join(problems[:8])
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
                    error="final package execution failed: " + _result_evidence(runtime),
                    exit_code=runtime.exit_code,
                    timed_out=runtime.timed_out,
                    isolated=runtime.isolated,
                    isolation_backend=runtime.isolation_backend,
                )
            return SandboxResult(
                True,
                "package intact; structure valid; final package execution passed",
                "",
                exit_code=0,
                isolated=runtime.isolated,
                isolation_backend=runtime.isolation_backend,
            )
        except (OSError, zipfile.BadZipFile) as exc:
            return SandboxResult(False, "", "", error=f"failed to validate the final package: {exc}")
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    @staticmethod
    def _find_entry_modules(files: dict[str, str]) -> list[str]:
        """Entry points that NVDA loads: globalPlugins/<A>/__init__.py,
        appModules/<app>.py (or folder), synthDrivers/<s>.py and brailleDisplayDrivers/<d>.py."""
        patterns = (
            re.compile(r"^globalPlugins/[^/]+/__init__\.py$"),
            re.compile(r"^appModules/[^/]+(/__init__)?\.py$"),
            re.compile(r"^synthDrivers/[^/]+(/__init__)?\.py$"),
            re.compile(r"^brailleDisplayDrivers/[^/]+(/__init__)?\.py$"),
        )
        found: list[str] = []
        for relpath in files:
            norm = relpath.replace("\\", "/").lstrip("/")
            if any(p.match(norm) for p in patterns) and norm not in found:
                found.append(norm)
        return found

    def run_test_suite(
        self, files: dict[str, str], test_relpaths: list[str], timeout: int | None = None,
    ) -> SandboxResult:
        """
        Writes `files` (relpath -> content) to a temporary directory and
        actually runs the test files in `test_relpaths` against
        them, through an isolated subprocess (same safety guarantee:
        never in the NVDA process).

        Tries `python -m pytest` first (it runs both loose `def test_*()`
        functions and TestCase classes). If pytest is not installed in the
        interpreter, it falls back to `python -m unittest discover`
        (stdlib, always available, but it only discovers TestCase — loose test_*
        functions outside a class are not collected by plain unittest).

        Never raises — degrades to SandboxResult(success=False,
        error=...) on any infrastructure failure (no Python on PATH,
        """
        if timeout is None:
            timeout = _TEST_SUITE_TIMEOUT
        if not test_relpaths:
            return SandboxResult(success=True, stdout="", stderr="", error="no test files")

        tmpdir = tempfile.mkdtemp(prefix="nvdastudio_testrun_")
        try:
            self._write_files(tmpdir, files)

            safe_test_paths = [p for p in (self._safe_relpath(r) for r in test_relpaths) if p]
            if not safe_test_paths:
                return SandboxResult(success=True, stdout="", stderr="", error="no valid test path")

            result = self._run_pytest(tmpdir, safe_test_paths, timeout)
            if result.error == "pytest_unavailable":
                result = self._run_unittest(tmpdir, safe_test_paths, timeout)
            return result
        except Exception as exc:
            _logger.error("[Sandbox] Error preparing run_test_suite: %s", exc)
            return SandboxResult(success=False, stdout="", stderr="", error=str(exc))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _write_files(self, tmpdir: str, files: dict[str, str]) -> None:
        """Writes `files` (relpath -> content) to the temporary directory,
        rejecting unsafe paths (shared by run_test_suite() and
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
        """Normalizes and rejects absolute paths or paths with `..` (path traversal)."""
        normalized = relpath.replace("\\", "/").lstrip("/")
        parts = [p for p in normalized.split("/") if p not in ("", ".")]
        if not parts or ".." in parts or any(":" in p for p in parts):
            return None
        return os.path.join(*parts)

    def _run_pytest(self, cwd: str, test_relpaths: list[str], timeout: int) -> SandboxResult:
        try:
            # the subprocess took 3.9s of wall-clock to run ONE trivial
            # test (assert 1==1), against 0.58s with plugin autoload
            # turned off (7x faster; pytest's own internal time
            # dropped from 0.87s to 0.01s). The inherited environment (full real
            # env, see comment below) makes the subprocess discover and
            # import ALL third-party plugins installed in the
            # interpreter (hypothesis/langsmith/anyio/flask/cov/mock),
            # none of which the generated tests (simple asserts,
            # unittest.mock.patch) need. Under real CPU
            # contention (the full NVDAStudio suite running in
            # parallel), this overhead alone was already close to the
            # _TEST_SUITE_TIMEOUT ceiling (25s) -- root cause of the flaky
            # timeout, not a lack of real execution time. pytest BUILT-IN
            # plugins (fixtures, mocks via stdlib unittest.mock)
            # keep working -- only third-party entry points
            # stop autoloading.
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
            return SandboxResult(False, stdout, stderr, error="pytest_unavailable", isolated=True, isolation_backend=proc.backend)
        return SandboxResult(proc.returncode == 0, stdout, stderr, exit_code=proc.returncode, isolated=True, isolation_backend=proc.backend)

    def _run_unittest(self, cwd: str, test_relpaths: list[str], timeout: int) -> SandboxResult:
        modules = []
        for relpath in test_relpaths:
            if not relpath.endswith(".py"):
                continue
            dotted = relpath[:-3].replace("/", ".").replace(os.sep, ".")
            modules.append(dotted)
        if not modules:
            return SandboxResult(success=True, stdout="", stderr="", error="no valid test module")
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
        Runs `ruff check` over the GENERATED Python code, in an isolated
        temporary directory, with the curated config _GENERATED_RUFF_CONFIG
        (only real-defect rules -- see the comment on the constant).

        Closes the project's historical asymmetry: NVDAStudio's CI requires a clean
        `ruff check` on its own code, but the add-on delivered to the
        user never went through any lint -- only AST, import and pytest.

        FAIL-OPEN (same policy as `pytest_unavailable` in _run_pytest):
        if ruff is not installed in the interpreter -- the normal case in the
        embedded Python of a real NVDA installation -- it returns
        success=True with error="ruff_unavailable". The absence of a tool
        is an INFRASTRUCTURE failure, never an add-on defect; blocking the

        does not execute the add-on. `ruff` does static analysis.
        """
        return self._run_static_tool(
            files,
            timeout,
            tool_argv=["-m", "ruff", "check", "--output-format=concise", "--no-cache", "."],
            prefix="nvdastudio_lint_",
            missing_pattern=r"No module named .?ruff",
            missing_error="ruff_unavailable",
            config_filename="ruff.toml",
            config_content=_GENERATED_RUFF_CONFIG,
        )





    def typecheck(
        self, files: dict[str, str], timeout: int | None = None,
    ) -> SandboxResult:
        """
        Runs `mypy` over the GENERATED Python code, in an isolated directory.

        --ignore-missing-imports is mandatory here: the modules the add-on
        imports (globalPluginHandler, addonHandler, ui, wx, config...) are
        injected by the NVDA PROCESS at runtime and do not exist
        in the dev interpreter -- exactly the same reason that led the
        root mypy.ini to declare `ignore_missing_imports` for each one of
        them. Without the flag, 100% of the result would be import-not-found.

        FAIL-OPEN identical to lint_check() when mypy is not installed.

        does not execute the add-on. `mypy` does static analysis.
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
            missing_error="mypy_unavailable",
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
        Writes `files` to a tmpdir and runs a STATIC analysis tool
        (ruff/mypy) over it, in an isolated subprocess with a timeout.

        Shared by lint_check() and typecheck() -- the only real difference
        between the two is the argv and the config file, so duplicating
        all the tmpdir/subprocess/degradation preparation would be the

        Never raises: any infrastructure failure becomes
        SandboxResult(success=True, error=...) -- fail-open.
        """
        if timeout is None:
            timeout = _LINT_TIMEOUT

        py_files = {
            rel: content for rel, content in files.items()
            if rel.replace("\\", "/").endswith(".py")
        }
        if not py_files:
            return SandboxResult(success=True, stdout="", stderr="", error="no Python file")

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
                    # REAL inherited environment, same reason already documented in
                    # _run_pytest(): ruff/mypy are usually installed as
                    # --user and live in a site-packages that is only resolved via
                    # APPDATA/USERPROFILE on Windows.
                    env=os.environ.copy(),
                )
            except subprocess.TimeoutExpired:
                # A static tool timeout is slow infrastructure, not an
                # add-on defect -- fail-open like the absence of the tool.
                return SandboxResult(
                    success=True, stdout="", stderr="",
                    error=f"static analysis exceeded {timeout}s", timed_out=True,
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
            _logger.error("[Sandbox] Error preparing static analysis: %s", exc)
            return SandboxResult(success=True, stdout="", stderr="", error=str(exc))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)



# Global instance
sandbox = CodeSandbox()
