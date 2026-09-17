import ast
import os
import re
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime

import pytest

# ---------------------------------------------------------------------------
# Chave e skip
# ---------------------------------------------------------------------------

HAS_OLLAMA = os.environ.get("OLLAMA_API_KEY", "").strip()
# 2026-08-17: critic.py 3.19.0 -- o Critic agora SEMPRE usa OpenCode Go
# (prompt caching), independente do provider ativo. Sem essa chave, TODA
# avaliacao de step falha com "Chave API para opencode_go nao configurada"
# -- achado real ao vivo (madrugada 2026-08-17/18, rodada 1 do loop): os
# 2 casos deste arquivo rodaram e "passaram" no pytest (test_e36 nao exige
# success=True) mas o pipeline inteiro falhou em segundos, 0 tokens gastos,
# nenhum sinal real coletado -- so desperdicou tempo/custo do Ollama sem
# testar nada. Adicionado ao skip guard pra nao rodar (e enganar) sem as
# 2 chaves.
HAS_OPENCODE_GO = os.environ.get("OPENCODE_GO_API_KEY", "").strip()
skip_unless_ollama = pytest.mark.skipif(
	not HAS_OLLAMA or not HAS_OPENCODE_GO,
	reason=("Ollama Cloud token nao disponivel" if not HAS_OLLAMA else "OpenCode Go token nao disponivel (necessario pro Critic, ver critic.py 3.19.0)"),
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Formato de versao valido: MAJOR.MINOR ou MAJOR.MINOR.PATCH
_VERSION_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")

# Regex para detectar caminhos locais em dependencies
_DEP_LOCAL_PATH_RE = re.compile(r"^\.{1,2}/")
# Regex para detectar URLs em dependencies
_DEP_URL_RE = re.compile(r"^https?://")
# Regex para nome PyPI valido (letras, digitos, hifens, underscores, pontos)
_DEP_PYPI_NAME_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$")

# ---------------------------------------------------------------------------
# Output dir
# ---------------------------------------------------------------------------

_E2E_OUTPUT_DIR = os.path.join(
	os.path.expanduser("~"), "Documents", "NVDAStudio", "addons_gerados", "e2e_configuracoes"
)
_REPORT_DIR = os.path.join(os.path.dirname(__file__), "relatorios")

# ---------------------------------------------------------------------------
# Dataclasses de rastreamento (espelho do fluxo completo)
# ---------------------------------------------------------------------------

@dataclass
class StepTrace:
	step_id: str
	step_type: str
	model_used: str
	approved: bool
	score: int
	retries_used: int
	tokens_used: int
	issues: list[str] = field(default_factory=list)
	output_preview: str = ""


@dataclass
class FluxoReport:
	"""Relatorio estruturado do fluxo de configuracoes."""
	addon_name: str
	query: str
	timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
	plan_id: str = ""
	complexity: str = ""
	duration_seconds: float = 0.0
	total_tokens: int = 0
	total_retries: int = 0
	replan_count: int = 0
	success: bool = False
	error: str = ""

	events: list[tuple[str, str]] = field(default_factory=list)
	steps: list[StepTrace] = field(default_factory=list)

	addon_folder: str = ""
	files_saved: list[str] = field(default_factory=list)
	nvda_addon_path: str = ""
	zip_names: list[str] = field(default_factory=list)

	struct_problems: list[str] = field(default_factory=list)
	has_init_py: bool = False
	has_manifest: bool = False
	has_doc: bool = False

	blocks_collected: list[dict] = field(default_factory=list)

	@property
	def event_types(self) -> list[str]:
		return [e[0] for e in self.events]

	@property
	def approved_steps(self) -> list[StepTrace]:
		return [s for s in self.steps if s.approved]

	@property
	def failed_steps(self) -> list[StepTrace]:
		return [s for s in self.steps if not s.approved]

	@property
	def avg_score(self) -> float:
		if not self.steps:
			return 0.0
		return sum(s.score for s in self.steps) / len(self.steps)

	@property
	def models_used(self) -> set[str]:
		return {s.model_used for s in self.steps if s.model_used}

	def print_report(self) -> None:
		sep = "=" * 72
		print(f"\n{sep}")
		print(f"CONFIGURACOES NVDA E2E — {self.addon_name}")
		print(f"  Query:       {self.query[:80]}")
		print(f"  Timestamp:   {self.timestamp}")
		print(f"  Duracao:     {self.duration_seconds:.1f}s")
		print(f"  Sucesso:     {self.success}")
		if self.error:
			print(f"  ERRO:        {self.error}")
		print("\n--- PIPELINE ---")
		print(f"  Steps total: {len(self.steps)}")
		print(f"  Aprovados:   {len(self.approved_steps)}/{len(self.steps)}")
		print(f"  Tokens:      {self.total_tokens:,}")
		print("\n--- ARTEFATOS ---")
		print(f"  Pasta:    {self.addon_folder}")
		print(f"  .nvda-addon: {self.nvda_addon_path}")
		print(sep)


# ---------------------------------------------------------------------------
# Motor E2E (mesma logica do fluxo completo)
# ---------------------------------------------------------------------------

def _executar_fluxo_completo(
	addon_name: str,
	query: str,
	output_dir: str = _E2E_OUTPUT_DIR,
) -> FluxoReport:
	"""
	Executa o fluxo inteiro do app e retorna FluxoReport detalhado.
	Regra 9: codigo gerado nunca executado.
	"""
	from nvdastudio.core.orchestrator import Orchestrator, OrchestrationResult
	from nvdastudio.builder.addon_builder import (
		extract_code_blocks,
		save_addon_files,
		package_addon,
		validate_addon_structure,
	)

	report = FluxoReport(addon_name=addon_name, query=query)
	orch_results: list[OrchestrationResult] = []
	t0 = time.time()

	os.makedirs(output_dir, exist_ok=True)
	os.makedirs(_REPORT_DIR, exist_ok=True)

	orch = Orchestrator()
	orch.initialize()
	orch.set_callbacks(
		on_progress=lambda ev, det: report.events.append((ev, det)),
		on_complete=lambda r: orch_results.append(r),
	)

	try:
		orch._run_until_complete(query)
	except Exception as exc:
		report.error = f"Pipeline excecao: {exc}"
		report.duration_seconds = time.time() - t0
		report.print_report()
		return report

	report.duration_seconds = time.time() - t0

	if not orch_results:
		report.error = "on_complete nao foi chamado pelo pipeline"
		report.print_report()
		return report

	result = orch_results[0]
	report.success = result.success
	report.plan_id = result.plan_id
	report.total_tokens = getattr(result, "total_tokens", 0)
	report.total_retries = result.total_retries
	report.replan_count = getattr(result, "replan_count", 0)
	report.error = result.error or ""

	for sr in result.step_results:
		report.steps.append(StepTrace(
			step_id=sr.step_id,
			step_type=sr.step_type,
			model_used=sr.model_used,
			approved=sr.approved,
			score=sr.score,
			retries_used=sr.retries_used,
			tokens_used=getattr(sr, "tokens_used", 0),
			issues=list(sr.issues),
			output_preview=sr.output[:300] if sr.output else "",
		))

	for ev, det in report.events:
		if ev == "PLANO_CRIADO":
			report.complexity = det
			break

	if not result.success:
		report.print_report()
		return report

	_PRIO = ["code_generation", "manifest_builder", "documentation",
			 "agent_runner", "agent_template", "assembly"]

	def _prio(sr) -> int:
		try:
			return _PRIO.index(sr.step_type)
		except ValueError:
			return len(_PRIO)

	sorted_steps = sorted(
		[sr for sr in result.step_results if sr.approved and sr.output],
		key=_prio,
	)
	seen_fnames: set[str] = set()
	all_blocks: list[dict] = []
	for sr in sorted_steps:
		for blk in extract_code_blocks(sr.output):
			fname = blk.get("filename", "").strip()
			if fname and fname not in seen_fnames:
				seen_fnames.add(fname)
				all_blocks.append(blk)
			elif not fname:
				all_blocks.append(blk)

	if not all_blocks and getattr(result, "assembly_output", ""):
		all_blocks = extract_code_blocks(result.assembly_output)
	if not all_blocks and result.final_output:
		all_blocks = extract_code_blocks(result.final_output)

	report.blocks_collected = all_blocks

	if not all_blocks:
		report.error = "Nenhum bloco de codigo extraido dos steps aprovados"
		report.print_report()
		return report

	try:
		addon_folder, saved_paths = save_addon_files(all_blocks, output_dir, addon_name)
		report.addon_folder = addon_folder
		report.files_saved = saved_paths
	except Exception as exc:
		report.error = f"save_addon_files falhou: {exc}"
		report.print_report()
		return report

	try:
		nvda_addon_path = package_addon(addon_folder)
		report.nvda_addon_path = nvda_addon_path
		if os.path.isfile(nvda_addon_path):
			with zipfile.ZipFile(nvda_addon_path, "r") as zf:
				report.zip_names = zf.namelist()
	except Exception as exc:
		report.error = f"package_addon falhou: {exc}"

	problems = validate_addon_structure(addon_folder)
	report.struct_problems = problems

	# Achado real de auditoria (2026-08-09, test_e36 GeminiMultimodal):
	# checar so o basename casava com QUALQUER __init__.py, inclusive de um
	# SUBPACOTE de feature (ex: globalPlugins/Addon/audio/__init__.py) --
	# reportava has_init_py=True mesmo sem o __init__.py RAIZ (com a classe
	# GlobalPlugin de verdade) nunca ter sido gerado. Exige exatamente 2
	# niveis relativos a addon_folder (globalPlugins/<NomeAddon>/__init__.py).
	report.has_init_py = any(
		os.path.relpath(f, addon_folder).replace("\\", "/").startswith("globalPlugins/")
		and os.path.basename(f) == "__init__.py"
		and os.path.relpath(f, addon_folder).replace("\\", "/").count("/") == 2
		for f in saved_paths
	)
	report.has_manifest = any(
		os.path.basename(f).lower() == "manifest.ini" for f in saved_paths
	)
	report.has_doc = any("doc" in f.lower() and f.endswith(".html") for f in saved_paths)

	report.print_report()
	return report


# ---------------------------------------------------------------------------
# Helpers de validacao (Regra 9: leitura de arquivo como string — sem exec)
# ---------------------------------------------------------------------------

def _ler_init_py(addon_folder: str) -> str:
	"""Retorna o conteudo do __init__.py principal (Regra 9: apenas string)."""
	# Tenta globalPlugins primeiro (GlobalPlugin)
	gp = os.path.join(addon_folder, "globalPlugins")
	if os.path.isdir(gp):
		for subdir in os.listdir(gp):
			init = os.path.join(gp, subdir, "__init__.py")
			if os.path.isfile(init):
				with open(init, encoding="utf-8", errors="replace") as fh:
					return fh.read()
	# Tenta appModules (AppModule)
	am = os.path.join(addon_folder, "appModules")
	if os.path.isdir(am):
		for fname in os.listdir(am):
			if fname.endswith(".py"):
				fpath = os.path.join(am, fname)
				with open(fpath, encoding="utf-8", errors="replace") as fh:
					return fh.read()
	return ""


def _ler_manifest(addon_folder: str) -> str:
	"""Retorna o conteudo do manifest.ini (Regra 9: apenas string)."""
	path = os.path.join(addon_folder, "manifest.ini")
	if os.path.isfile(path):
		with open(path, encoding="utf-8", errors="replace") as fh:
			return fh.read()
	return ""


def _parse_manifest_fields(content: str) -> dict[str, str]:
	"""Extrai pares key=value do manifest.ini sem configparser (mais tolerante)."""
	fields: dict[str, str] = {}
	for line in content.splitlines():
		line = line.strip()
		if not line or line.startswith("#") or line.startswith("["):
			continue
		if "=" in line:
			key, _, value = line.partition("=")
			fields[key.strip().lower()] = value.strip()
	return fields


def _extrair_corpo_funcao(code: str, func_name: str) -> str:
	"""
	Extrai o corpo textual de uma funcao pelo nome usando AST (Regra 9: sem exec).
	Retorna a substring do codigo correspondente ao corpo da funcao,
	ou string vazia se a funcao nao for encontrada.
	"""
	try:
		tree = ast.parse(code)
	except SyntaxError:
		return ""
	linhas = code.splitlines()
	for node in ast.walk(tree):
		if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
			if node.name == func_name:
				inicio = node.body[0].lineno - 1
				fim = node.end_lineno
				return "\n".join(linhas[inicio:fim])
	return ""


def _detectar_classe_pai(code: str) -> list[str]:
	"""
	Retorna a lista de nomes de bases da primeira classe definida no codigo.
	Usa AST para nao executar o codigo (Regra 9).
	"""
	bases: list[str] = []
	try:
		tree = ast.parse(code)
	except SyntaxError:
		return bases
	for node in ast.walk(tree):
		if isinstance(node, ast.ClassDef):
			for base in node.bases:
				if isinstance(base, ast.Attribute):
					bases.append(f"{ast.dump(base.value)}.{base.attr}")
					# Forma legivel: modulo.Classe
					if isinstance(base.value, ast.Name):
						bases.append(f"{base.value.id}.{base.attr}")
				elif isinstance(base, ast.Name):
					bases.append(base.id)
			break  # apenas a primeira classe
	return bases


# ---------------------------------------------------------------------------
# FIXTURE
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def fluxo_report():
	"""
	Executa o fluxo completo UMA VEZ para toda a classe.
	Todos os testes da classe consomem o mesmo FluxoReport.
	Economiza tokens e tempo de API.

	O addon gerado usa SettingsPanel e config.conf.spec para exercitar
	todas as regras de configuracao validadas neste modulo.
	"""
	report = _executar_fluxo_completo(
		addon_name="ConfigNVDA_e2e",
		query=(
			"Crie um GlobalPlugin NVDA chamado 'ConfiguradorAvancado' que permite "
			"ao usuario configurar o nivel de verbosidade via SettingsPanel. "
			"O plugin deve: "
			"1) Usar config.conf.spec para definir o schema de configuracao do addon; "
			"2) Registrar um SettingsPanel em gui.settingsDialogs.NVDASettingsDialog "
			"   via categoryClasses.append() no __init__ e remover no terminate(); "
			"3) Implementar makeSettings() usando acesso direto config.conf[secao][chave] "
			"   (sem .get()); "
			"4) Verificar shouldWriteToDisk() antes de qualquer escrita em arquivo; "
			"5) Ter manifest.ini com version=1.0.0, minimumNVDAVersion=2026.1.1, "
			"   lastTestedNVDAVersion=2026.1.1; "
			"6) Ter dependencies sem caminhos locais ou URLs."
		),
	)
	return report


# ---------------------------------------------------------------------------
# Classe de testes: regras de configuracao/settings
# ---------------------------------------------------------------------------

@skip_unless_ollama
class TestRegrasConfiguracoes:
	"""
	5.1.0: skip_unless_ollama era definido neste arquivo mas nunca aplicado
	-- fluxo_report (fixture de modulo) rodava o pipeline completo (LLM
	real) incondicionalmente e ficava pendurado sem as chaves configuradas,
	em vez de skip limpo. Ver test_e20_regras_qualidade_codigo.py 5.1.0 para
	o achado completo. Mesmo padrao ja usado em test_e35/e36/e37/e38.

	Valida as regras de configuracao/settings de addons NVDA.

	Todos os testes compartilham o mesmo FluxoReport (fixture de modulo).
	Testes condicionais fazem pytest.skip() se a feature nao estiver presente.
	Regra 9: nenhum codigo e executado em nenhuma validacao.
	"""

	# ------------------------------------------------------------------
	# NVDA-015: config.conf.spec (nao dict avulso)
	# ------------------------------------------------------------------

	def test_nvda015_config_conf_usa_spec(self, fluxo_report: FluxoReport):
		"""
		NVDA-015: Se o addon usa config.conf[], deve definir o schema via config.conf.spec.

		Padrao incorreto: config.conf["meuAddon"]["opcao"] sem spec definido.
		Padrao correto:
		  confspec = {"opcao": "boolean(default=False)"}
		  config.conf.spec["meuAddon"] = confspec

		Sem spec, o NVDA nao sabe os tipos/defaults e pode lancar erros de validacao
		ao carregar o profile do usuario.

		Assert (condicional): se usa config.conf[] -> tem config.conf.spec definido.
		"""
		if not fluxo_report.success or not fluxo_report.has_init_py:
			pytest.skip("__init__.py nao disponivel")
		code = _ler_init_py(fluxo_report.addon_folder)

		# Condicao: o addon usa config.conf[
		usa_config_conf = bool(re.search(r'config\.conf\s*\[', code))
		if not usa_config_conf:
			pytest.skip("feature nao presente no addon gerado: config.conf[] nao encontrado")

		# Deve ter config.conf.spec definido
		tem_spec = bool(re.search(r'config\.conf\.spec\s*\[', code))
		assert tem_spec, (
			"NVDA-015: codigo usa config.conf[] mas nao define config.conf.spec. "
			"Sem spec o NVDA nao valida tipos/defaults e pode lancar ConfigspecError. "
			"Padrao correto: confspec = {...}; config.conf.spec['meuAddon'] = confspec"
		)

	# ------------------------------------------------------------------
	# NVDA-016: shouldWriteToDisk() antes de escrever em disco
	# ------------------------------------------------------------------

	def test_nvda016_should_write_to_disk_antes_de_escrita(self, fluxo_report: FluxoReport):
		"""
		NVDA-016: Antes de escrever em arquivo, o codigo deve verificar shouldWriteToDisk().

		O NVDA pode estar em modo somente-leitura (ex: executando de CD-ROM ou com
		profile read-only). Escrever sem verificar causa PermissionError silenciosa.

		Padroes de escrita detectados:
		  - open(..., "w") ou open(..., "wb")
		  - os.path.join(...) combinado com write()

		Assert (condicional): se tem escrita em arquivo -> tem shouldWriteToDisk no codigo.
		"""
		if not fluxo_report.success or not fluxo_report.has_init_py:
			pytest.skip("__init__.py nao disponivel")
		code = _ler_init_py(fluxo_report.addon_folder)

		# Condicao: o addon tem operacao de escrita em arquivo
		tem_open_write = bool(re.search(r'open\s*\([^)]*["\']w[b]?["\']', code))
		tem_path_write = bool(
			re.search(r'os\.path\.join', code) and re.search(r'\.write\s*\(', code)
		)
		tem_escrita = tem_open_write or tem_path_write

		if not tem_escrita:
			pytest.skip("feature nao presente no addon gerado: escrita em arquivo nao encontrada")

		# Deve verificar shouldWriteToDisk
		tem_check = "shouldWriteToDisk" in code
		assert tem_check, (
			"NVDA-016: codigo escreve em arquivo mas nao verifica shouldWriteToDisk(). "
			"O NVDA pode estar em modo somente-leitura — escrever sem verificar "
			"causa PermissionError. Adicione: if config.conf.shouldWriteToDisk(): ..."
		)

	# ------------------------------------------------------------------
	# NVDA-024: dependencies[] com nomes PyPI validos
	# ------------------------------------------------------------------

	def test_nvda024_dependencies_sao_nomes_pypi_validos(self, fluxo_report: FluxoReport):
		"""
		NVDA-024: O campo dependencies no manifest.ini deve conter apenas nomes PyPI validos.

		Invalido:
		  - Caminhos locais: ./minha_lib, ../pacote
		  - URLs: https://github.com/..., http://pypi.org/...
		  - Extras sem nome base: [extra]

		Valido:
		  - requests
		  - requests>=2.28.0
		  - my-package
		  - my_package

		Assert (condicional): se tem dependencies -> sao nomes PyPI validos.
		"""
		if not fluxo_report.success or not fluxo_report.has_manifest:
			pytest.skip("manifest.ini nao disponivel")
		content = _ler_manifest(fluxo_report.addon_folder)
		fields = _parse_manifest_fields(content)

		deps_raw = fields.get("dependencies", "").strip()
		if not deps_raw:
			pytest.skip("feature nao presente no addon gerado: campo dependencies ausente")

		# Separa por virgula ou espaco
		deps = [d.strip() for d in re.split(r"[,\s]+", deps_raw) if d.strip()]
		invalidos: list[str] = []
		for dep in deps:
			# Remove especificadores de versao (>=, ==, <=, ~=, !=, extras [])
			nome_base = re.split(r"[>=<!~\[\s]", dep)[0].strip()
			if not nome_base:
				continue
			if _DEP_LOCAL_PATH_RE.match(dep):
				invalidos.append(f"{dep!r} (caminho local)")
			elif _DEP_URL_RE.match(dep):
				invalidos.append(f"{dep!r} (URL)")
			elif not _DEP_PYPI_NAME_RE.match(nome_base):
				invalidos.append(f"{dep!r} (nome invalido)")

		assert not invalidos, (
			f"NVDA-024: dependencies com entradas invalidas: {invalidos}. "
			"Apenas nomes de pacotes PyPI sao aceitos (ex: requests, my-lib>=1.0). "
			"Caminhos locais e URLs nao sao suportados pelo gerenciador de dependencias do NVDA."
		)

	# ------------------------------------------------------------------
	# NVDA-026: SettingsPanel registrado corretamente
	# ------------------------------------------------------------------

	def test_nvda026_settings_panel_registrado_e_removido(self, fluxo_report: FluxoReport):
		"""
		NVDA-026: Se o addon define um SettingsPanel, ele deve ser registrado no __init__
		e removido no terminate() — sem isso o painel fica duplicado apos recarregar o NVDA.

		Padrao correto:
		  def __init__(self, *args, **kwargs):
		      super().__init__(*args, **kwargs)
		      gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(MeuPanel)

		  def terminate(self):
		      gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(MeuPanel)
		      super().terminate()

		Assert (condicional): se tem SettingsPanel -> tem registro (append) e remocao (remove).
		"""
		if not fluxo_report.success or not fluxo_report.has_init_py:
			pytest.skip("__init__.py nao disponivel")
		code = _ler_init_py(fluxo_report.addon_folder)

		# Condicao: o addon tem SettingsPanel ou NVDASettingsDialog
		tem_settings_panel = bool(
			re.search(r'\bSettingsPanel\b', code)
			or re.search(r'\bNVDASettingsDialog\b', code)
		)
		if not tem_settings_panel:
			pytest.skip("feature nao presente no addon gerado: SettingsPanel nao encontrado")

		# Deve ter append (registro) no categoryClasses
		tem_append = bool(re.search(r'categoryClasses\s*\.\s*append\s*\(', code))
		assert tem_append, (
			"NVDA-026: SettingsPanel presente mas categoryClasses.append() nao encontrado. "
			"O painel deve ser registrado no __init__ via "
			"gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(MinhaClasse)."
		)

		# Deve ter remove (limpeza) no categoryClasses
		tem_remove = bool(re.search(r'categoryClasses\s*\.\s*remove\s*\(', code))
		assert tem_remove, (
			"NVDA-026: SettingsPanel registrado mas categoryClasses.remove() ausente. "
			"O painel deve ser removido no terminate() para evitar duplicacao "
			"quando o NVDA e recarregado. "
			"Adicione: gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(MinhaClasse)"
		)

	# ------------------------------------------------------------------
	# NVDA-027: Sem config.conf.get() dentro de makeSettings
	# ------------------------------------------------------------------

	def test_nvda027_make_settings_sem_config_get(self, fluxo_report: FluxoReport):
		"""
		NVDA-027: Dentro de makeSettings(), nao deve haver config.conf.get().

		config.conf.get() retorna None se a chave nao existir, bypassing a validacao
		do spec e quebrando a tipagem esperada pelos widgets.

		Padrao incorreto:
		  def makeSettings(self, sizer):
		      val = config.conf.get("meuAddon", {}).get("opcao", False)  # ERRADO

		Padrao correto (acesso direto — respeita o spec):
		  def makeSettings(self, sizer):
		      val = config.conf["meuAddon"]["opcao"]  # CORRETO

		Assert (condicional): se tem makeSettings -> sem .get() dentro dela.
		"""
		if not fluxo_report.success or not fluxo_report.has_init_py:
			pytest.skip("__init__.py nao disponivel")
		code = _ler_init_py(fluxo_report.addon_folder)

		# Condicao: o addon tem funcao makeSettings
		tem_make_settings = bool(re.search(r'def\s+makeSettings\s*\(', code))
		if not tem_make_settings:
			pytest.skip("feature nao presente no addon gerado: makeSettings() nao encontrado")

		# Extrai o corpo de makeSettings
		corpo = _extrair_corpo_funcao(code, "makeSettings")
		if not corpo:
			# Fallback: busca textual simples entre def makeSettings e a proxima funcao
			m = re.search(r'def makeSettings\s*\([^)]*\):[^\n]*\n((?:[ \t]+[^\n]*\n?)*)', code)
			corpo = m.group(1) if m else ""

		# Dentro do corpo, nao deve ter config.conf.get(
		tem_conf_get = bool(re.search(r'config\.conf\s*\.get\s*\(', corpo))
		assert not tem_conf_get, (
			"NVDA-027: config.conf.get() encontrado dentro de makeSettings(). "
			"Use acesso direto config.conf['secao']['chave'] para respeitar o spec "
			"e garantir que os tipos definidos pelo ConfigObj sejam mantidos. "
			"config.conf.get() bypassa a validacao e pode retornar None inesperadamente."
		)

	# ------------------------------------------------------------------
	# NVDA-031: chooseNVDAObjectOverlayClasses somente em AppModule
	# ------------------------------------------------------------------

	def test_nvda031_choose_overlay_classes_somente_em_appmodule(self, fluxo_report: FluxoReport):
		"""
		NVDA-031: chooseNVDAObjectOverlayClasses e event_NVDAObject_init devem ser
		implementados SOMENTE em AppModule, nunca em GlobalPlugin.

		GlobalPlugin intercepta TODOS os aplicativos — usar chooseNVDAObjectOverlayClasses
		em GlobalPlugin impacta performance em todo o sistema, nao apenas no app alvo.

		Assert (condicional): se tem chooseNVDAObjectOverlayClasses ->
		  a classe pai e AppModule (appModuleHandler.AppModule), nao GlobalPlugin.
		"""
		if not fluxo_report.success or not fluxo_report.has_init_py:
			pytest.skip("__init__.py nao disponivel")
		code = _ler_init_py(fluxo_report.addon_folder)

		# Condicao: o addon implementa chooseNVDAObjectOverlayClasses
		tem_choose = bool(re.search(r'def\s+chooseNVDAObjectOverlayClasses\s*\(', code))
		if not tem_choose:
			pytest.skip(
				"feature nao presente no addon gerado: "
				"chooseNVDAObjectOverlayClasses nao encontrado"
			)

		# Nao deve herdar de globalPluginHandler.GlobalPlugin
		herda_global_plugin = bool(
			re.search(r'globalPluginHandler\s*\.\s*GlobalPlugin', code)
		)
		assert not herda_global_plugin, (
			"NVDA-031: chooseNVDAObjectOverlayClasses implementado em GlobalPlugin. "
			"Este metodo deve ser usado SOMENTE em AppModule — GlobalPlugin intercepta "
			"todos os aplicativos e usar chooseNVDAObjectOverlayClasses nele degrada "
			"a performance global do NVDA. "
			"Migre para appModuleHandler.AppModule."
		)

		# Deve herdar de appModuleHandler.AppModule
		herda_app_module = bool(
			re.search(r'appModuleHandler\s*\.\s*AppModule', code)
		)
		assert herda_app_module, (
			"NVDA-031: chooseNVDAObjectOverlayClasses presente mas a classe nao herda "
			"de appModuleHandler.AppModule. "
			"Este metodo pertence exclusivamente a AppModule — "
			"verifique a hierarquia de heranca."
		)

	# ------------------------------------------------------------------
	# NVDA-032: AppModule (nao GlobalPlugin) para apps especificas
	# ------------------------------------------------------------------

	def test_nvda032_app_especifico_usa_appmodule(self, fluxo_report: FluxoReport):
		"""
		NVDA-032: Se o nome do arquivo sugere um aplicativo especifico (ex: notepad.py,
		chrome.py, calc.py), o modulo deve herdar de AppModule, nao de GlobalPlugin.

		GlobalPlugin e para plugins que se aplicam a todos os aplicativos.
		AppModule e para customizacoes especificas de um unico executavel.

		Assert (condicional): se nome do arquivo de codigo sugere um executavel especifico
		  -> a classe herda de appModuleHandler.AppModule.

		Executaveis comuns: notepad, chrome, firefox, winword, excel, outlook,
		  calc, mspaint, explorer, cmd, powershell, code (vscode).
		"""
		if not fluxo_report.success or not fluxo_report.has_init_py:
			pytest.skip("__init__.py nao disponivel")

		# Detecta se algum arquivo de codigo tem nome de executavel especifico
		_EXECUTAVEIS_CONHECIDOS = re.compile(
			r'\b(notepad|chrome|firefox|winword|excel|outlook|calc|mspaint'
			r'|explorer|powershell|code|vlc|winamp|steam|discord|teams|zoom)\b',
			re.IGNORECASE,
		)

		arquivo_app: str | None = None
		for fpath in fluxo_report.files_saved:
			basename = os.path.basename(fpath).replace(".py", "")
			if _EXECUTAVEIS_CONHECIDOS.search(basename):
				arquivo_app = fpath
				break

		if arquivo_app is None:
			pytest.skip(
				"feature nao presente no addon gerado: "
				"nenhum arquivo com nome de executavel especifico encontrado"
			)

		# Le o arquivo especifico (Regra 9: apenas string)
		with open(arquivo_app, encoding="utf-8", errors="replace") as fh:
			code_app = fh.read()

		# Nao deve herdar de GlobalPlugin
		herda_global_plugin = bool(
			re.search(r'globalPluginHandler\s*\.\s*GlobalPlugin', code_app)
		)
		assert not herda_global_plugin, (
			f"NVDA-032: arquivo '{os.path.basename(arquivo_app)}' sugere app especifico "
			"mas herda de globalPluginHandler.GlobalPlugin. "
			"Modulos especificos de aplicativo devem usar appModuleHandler.AppModule."
		)

		herda_app_module = bool(
			re.search(r'appModuleHandler\s*\.\s*AppModule', code_app)
		)
		assert herda_app_module, (
			f"NVDA-032: arquivo '{os.path.basename(arquivo_app)}' sugere app especifico "
			"mas nao herda de appModuleHandler.AppModule. "
			"Use AppModule para customizacoes de aplicativo unico."
		)

	# ------------------------------------------------------------------
	# NVDA-005: Formato de versao no manifest
	# ------------------------------------------------------------------

	def test_nvda005_manifest_version_formato_correto(self, fluxo_report: FluxoReport):
		"""
		NVDA-005: O campo version no manifest.ini deve seguir o formato
		MAJOR.MINOR ou MAJOR.MINOR.PATCH.

		Exemplos validos: 1.0, 1.0.0, 2.3.1, 10.2.3
		Exemplos invalidos: 1, v1.0.0, 1.0.0.0, 1.0-beta, 1.0.0.dev0

		Regex de validacao: r"^\\d+\\.\\d+(\\.\\d+)?$"

		Assert: version no manifest segue o formato (nao condicional — sempre verificado).
		"""
		if not fluxo_report.success or not fluxo_report.has_manifest:
			pytest.skip("manifest.ini nao disponivel")
		content = _ler_manifest(fluxo_report.addon_folder)
		fields = _parse_manifest_fields(content)

		version = fields.get("version", "").strip()
		if not version:
			pytest.fail(
				"NVDA-005: campo 'version' ausente no manifest.ini. "
				"O NVDA rejeita addons sem version definida."
			)

		# Remove ponto final acidental (bug comum de geracao por IA)
		version_clean = version.rstrip(".")

		assert _VERSION_RE.match(version_clean), (
			f"NVDA-005: version={version!r} nao segue o formato MAJOR.MINOR ou MAJOR.MINOR.PATCH. "
			"Exemplos validos: 1.0 | 1.0.0 | 2.3.1. "
			"Prefixos (v1.0) e sufixos (-beta, .dev0) nao sao aceitos pelo loader do NVDA."
		)
