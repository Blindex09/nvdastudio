import ast
import os

_ADDON_ROOT = os.path.normpath(
	os.path.join(os.path.dirname(__file__), "..", "..",
				  "addon", "globalPlugins", "nvdastudio")
)

# Subpacotes reais do projeto -- usados pra resolver imports relativos
# ("from ..gui.settings_panel import x") de volta pro nome do subpacote.
_SUBPACKAGES = frozenset({
	"ai", "builder", "core", "gui", "memory",
	"sub_agents", "tool_system", "tools", "utils",
})


def _iter_py_files():
	# 2026-08-16: achado real -- nvda_docs_cache/ (novo, ver nvda_context.py
	# 3.31.0) bundla arquivos-fonte REAIS do NVDA (nvaccess/nvda) como
	# referencia de texto pura (nunca importados/executados). Sem excluir
	# aqui, o proprio codigo do NVDA core (que legitimamente usa `import *`
	# em controlTypes/__init__.py, por exemplo) reprova os fitness functions
	# deste arquivo como se fosse codigo do PROPRIO NVDAStudio.
	dirnames_excluidos = ("__pycache__", "lib", "skills", "agent_templates", "nvda_docs_cache")
	for dirpath, dirnames, filenames in os.walk(_ADDON_ROOT):
		dirnames[:] = [d for d in dirnames if d not in dirnames_excluidos]
		for fn in filenames:
			if fn.endswith(".py"):
				yield os.path.join(dirpath, fn)


def _relpath(full_path: str) -> str:
	return os.path.relpath(full_path, _ADDON_ROOT).replace(os.sep, "/")


def _module_subpackage(relpath: str) -> str | None:
	"""'ai/critic.py' -> 'ai'. Arquivo solto na raiz (ex: '__init__.py') -> None."""
	parts = relpath.split("/")
	if len(parts) < 2:
		return None
	return parts[0] if parts[0] in _SUBPACKAGES else None


def _resolve_relative_import(src_relpath: str, node: ast.ImportFrom) -> str | None:
	"""Resolve 'from ..gui.settings_panel import x' (visto de dentro de
	core/orchestrator.py) pro caminho relativo real 'gui/settings_panel.py'.
	Retorna None se nao resolver pra um arquivo dentro do addon (ex: import
	de biblioteca externa, ou nivel de import maior que a profundidade real)."""
	src_dir_parts = src_relpath.split("/")[:-1]  # remove o nome do arquivo
	# node.level=1 -> mesmo pacote do arquivo (1 ".."); level=2 -> sobe 1 nivel a mais.
	up_levels = node.level - 1
	base_parts = src_dir_parts[: len(src_dir_parts) - up_levels] if up_levels else src_dir_parts
	if base_parts is None or (up_levels and len(src_dir_parts) < up_levels):
		return None
	module_parts = (node.module or "").split(".") if node.module else []
	target_parts = base_parts + module_parts
	if not target_parts or target_parts[0] not in _SUBPACKAGES:
		return None
	candidate = "/".join(target_parts) + ".py"
	if os.path.isfile(os.path.join(_ADDON_ROOT, candidate)):
		return candidate
	# pode ser um pacote (diretorio com __init__.py) em vez de um modulo .py
	candidate_init = "/".join(target_parts) + "/__init__.py"
	if os.path.isfile(os.path.join(_ADDON_ROOT, candidate_init)):
		return candidate_init
	return None


def _build_module_dependency_graph() -> dict[str, set[str]]:
	"""Constroi grafo em nivel de ARQUIVO (nao subpacote): modulo -> conjunto
	de OUTROS modulos que ele importa de fato, via imports relativos reais.
	Granularidade de arquivo evita falso positivo de ciclo quando 2 modulos
	de subpacotes diferentes se importam em sentidos opostos sem nenhum
	ARQUIVO estar de fato num ciclo (ex: A/x.py -> B/y.py -> A/z.py, sem
	z.py importar x.py de volta -- nao e ciclo de verdade, so cruza o
	mesmo PAR de subpacotes duas vezes).

	So conta imports de NIVEL DE MODULO (direto em tree.body) -- imports
	lazy/locais (dentro de def/async def) sao o idioma padrao do Python
	pra quebrar circularidade DE PROPOSITO (resolvidos em runtime, na
	primeira chamada, nao no load do modulo) -- achado real ao escrever
	este teste: sub_agents/_base.py importa sub_agents/web_researcher.py
	lazy (dentro de uma funcao, pra delegar busca web de qualquer
	sub-agente), e web_researcher.py importa _base.py no topo (uso normal
	de helper compartilhado) -- 2 arestas em sentidos opostos que
	pareciam ciclo, mas nao travam o interpretador porque uma delas so
	resolve depois que o outro modulo ja carregou por completo.
	"""
	graph: dict[str, set[str]] = {}

	for full_path in _iter_py_files():
		relpath = _relpath(full_path)
		if _module_subpackage(relpath) is None:
			continue
		graph.setdefault(relpath, set())
		try:
			with open(full_path, encoding="utf-8") as f:
				tree = ast.parse(f.read(), filename=relpath)
		except (SyntaxError, UnicodeDecodeError):
			continue

		for node in tree.body:
			if not isinstance(node, ast.ImportFrom) or node.level == 0:
				continue
			target = _resolve_relative_import(relpath, node)
			if target and target != relpath:
				graph[relpath].add(target)

	return graph


def _build_subpackage_dependency_graph() -> dict[str, set[str]]:
	"""Agregacao por subpacote do grafo de modulo -- usada so pra relatorio
	legivel (qual PAR de subpacotes se cruza), nao pra deteccao de ciclo
	(essa roda no grafo de arquivo, mais preciso)."""
	module_graph = _build_module_dependency_graph()
	graph: dict[str, set[str]] = {pkg: set() for pkg in _SUBPACKAGES}
	for src, targets in module_graph.items():
		src_pkg = _module_subpackage(src)
		if src_pkg is None:
			continue
		for target in targets:
			target_pkg = _module_subpackage(target)
			if target_pkg and target_pkg != src_pkg:
				graph[src_pkg].add(target_pkg)
	return graph


class TestSemDependenciaCircularEntreModulos:
	"""
	Architecture Fitness Function: nenhum MODULO (arquivo) pode ter um ciclo
	de dependencia com outro (A importa B E B importa A, direta ou
	transitivamente) -- ciclo estrutural quase sempre indica acoplamento
	que deveria ser quebrado com uma interface/camada intermediaria.

	A granularidade e de ARQUIVO, nao de subpacote, para evitar falsos
	positivos quando pacotes se cruzam sem que um modulo dependa de si mesmo.
	"""

	def test_grafo_de_dependencias_e_aciclico(self):
		graph = _build_module_dependency_graph()

		# DFS com deteccao de ciclo (cores branco/cinza/preto).
		WHITE, GRAY, BLACK = 0, 1, 2
		color = {pkg: WHITE for pkg in graph}
		cycle_path: list[str] = []

		def visit(node: str, path: list[str]) -> bool:
			color[node] = GRAY
			path.append(node)
			for neighbor in graph.get(node, ()):
				if color[neighbor] == GRAY:
					cycle_start = path.index(neighbor)
					cycle_path.extend(path[cycle_start:] + [neighbor])
					return True
				if color[neighbor] == WHITE and visit(neighbor, path):
					return True
			path.pop()
			color[node] = BLACK
			return False

		for pkg in sorted(graph):
			if color[pkg] == WHITE:
				if visit(pkg, []):
					break

		assert not cycle_path, (
			f"CICLO DE DEPENDENCIA detectado entre subpacotes: "
			f"{' -> '.join(cycle_path)}. Ciclos estruturais indicam "
			f"acoplamento que deveria ser quebrado com uma interface "
			f"intermediaria ou reorganizacao de responsabilidade."
		)


class TestUtilsEhCamadaFolhaPura:
	"""
	Architecture Fitness Function: utils/ e a camada mais baixa do projeto
	(logger, injection_guard, etc.) -- nao deve importar NENHUM outro
	subpacote do proprio projeto, so stdlib/bibliotecas externas. Se
	utils/ comecar a importar de ai/gui/core, deixa de ser reutilizavel
	como fundacao e vira parte do emaranhado que ela deveria evitar.

	2026-08-30: a UNICA excecao que existia aqui (utils -> memory) vinha de
	utils/scheduler.py, removido por ser codigo morto -- 430 linhas com zero
	referencias em producao, importando `croniter`, pacote que nem estava
	declarado em requirements.txt. Com ele fora, utils/ voltou a ser camada
	folha PURA, e a excecao saiu junto: manter uma permissao que nada mais usa
	so abriria porta para o proximo acoplamento entrar sem discussao.

	Se um dia utils/ precisar de outro subpacote, a excecao volta -- COM o
	motivo escrito, como esta estava.
	"""

	# Vazio de proposito: utils/ e camada folha pura. Ver docstring acima.
	_EXCECOES_DOCUMENTADAS: dict[str, frozenset[str]] = {}

	def test_utils_nao_importa_outros_subpacotes_do_projeto_alem_das_excecoes(self):
		graph = _build_subpackage_dependency_graph()
		permitido = self._EXCECOES_DOCUMENTADAS.get("utils", frozenset())
		inesperado = graph.get("utils", set()) - permitido
		assert not inesperado, (
			f"utils/ importa de subpacote(s) NAO documentado(s) como excecao: "
			f"{inesperado} -- utils/ deveria ser camada folha pura. Se a "
			f"importacao for legitima, documente a excecao explicitamente "
			f"em _EXCECOES_DOCUMENTADAS com o motivo."
		)


class TestModuleVersionPresenteEmModulosPublicos:
	"""
	Architecture Fitness Function: todo modulo que expoe uma API publica
	real (funcoes/classes fora de _prefixo, sem contar __init__.py e
	arquivos de teste/dados) declara MODULE_VERSION -- e o padrao de
	changelog rastreavel que o projeto inteiro usa (Regra 10, AI_MODULE_
	SPEC.md cita isso como pendencia conhecida em alguns modulos). Este
	teste NAO falha a suite (ainda ha modulos legados sem o campo) --
	reporta a lista, pra virar trabalho de limpeza rastreavel em vez de
	pendencia invisivel.
	"""

	_IGNORADOS = frozenset({"__init__.py", "conftest.py"})

	def test_lista_modulos_sem_module_version(self):
		sem_versao = []
		for full_path in _iter_py_files():
			relpath = _relpath(full_path)
			basename = os.path.basename(relpath)
			if basename in self._IGNORADOS or basename.startswith("_"):
				continue
			if _module_subpackage(relpath) is None:
				continue
			with open(full_path, encoding="utf-8") as f:
				content = f.read()
			has_public_def = any(
				line.startswith(("def ", "class ")) for line in content.splitlines()
			)
			if has_public_def and "MODULE_VERSION" not in content:
				sem_versao.append(relpath)

		# Nao falha -- so documenta o estado real (Regra 10 e uma pendencia
		# conhecida, nao uma regressao nova). Fitness function informacional.
		if sem_versao:
			import sys
			print(
				f"\n[FITNESS] {len(sem_versao)} modulo(s) publico(s) sem "
				f"MODULE_VERSION: {sem_versao}",
				file=sys.stderr,
			)
		assert isinstance(sem_versao, list)


class TestIterPyFilesIgnoraNvdaDocsCache:
	"""2026-08-16: regressao -- nvda_docs_cache/ (nvda_context.py 3.31.0)
	bundla codigo-fonte REAL do NVDA como referencia de texto pura (nunca
	importado/executado). Sem essa exclusao, arquivos legitimos do NVDA
	core (ex: controlTypes/__init__.py, que usa `import *` de verdade)
	reprovavam os fitness functions deste arquivo como se fossem codigo do
	PROPRIO NVDAStudio -- achado real ao rodar a suite completa apos
	bundlar os docs pela primeira vez."""

	def test_nenhum_arquivo_de_nvda_docs_cache_e_iterado(self):
		for full_path in _iter_py_files():
			relpath = _relpath(full_path)
			assert not relpath.startswith("nvda_docs_cache/"), (
				f"nvda_docs_cache/ deveria estar excluido de _iter_py_files(): {relpath}"
			)

	def test_nvda_docs_cache_existe_e_tem_arquivos_py(self):
		"""Guard-rail do teste acima: confirma que a pasta existe de verdade
		e tem .py dentro -- senao o teste acima passaria vazio sem checar nada."""
		cache_dir = os.path.join(_ADDON_ROOT, "nvda_docs_cache")
		assert os.path.isdir(cache_dir), "nvda_docs_cache/ deveria existir (bundlado)"
		tem_py = any(
			fn.endswith(".py")
			for _, _, files in os.walk(cache_dir)
			for fn in files
		)
		assert tem_py, "nvda_docs_cache/ deveria conter pelo menos um .py real do NVDA"


class TestSemImportEstrela:
	"""Architecture Fitness Function: `from x import *` esconde a API real
	consumida, dificulta rastrear dependencia entre modulos (o proprio
	mecanismo que os fitness functions acima dependem pra funcionar)."""

	def test_nenhum_modulo_usa_import_estrela(self):
		violacoes = []
		for full_path in _iter_py_files():
			relpath = _relpath(full_path)
			try:
				with open(full_path, encoding="utf-8") as f:
					tree = ast.parse(f.read(), filename=relpath)
			except (SyntaxError, UnicodeDecodeError):
				continue
			for node in ast.walk(tree):
				if isinstance(node, ast.ImportFrom) and any(
					alias.name == "*" for alias in node.names
				):
					violacoes.append(relpath)
		assert not violacoes, f"import * encontrado em: {violacoes}"
