MODULE_VERSION = "1.1.0"

# Baseline oficial do projeto. O NVDAStudio atual nao mantem compatibilidade
# ativa com versoes anteriores a esta linha.
PROJECT_MIN_NVDA = "2026.1.1"
PROJECT_LAST_TESTED_NVDA = "2026.2.0"
PROJECT_SUPPORTED_RANGE = "2026.1.1+"

# Piso tecnico absoluto das regras historicas do NVDA (Python 3).
ABSOLUTE_MIN_NVDA = "2019.3.0"


def parse_version_tuple(version: str) -> tuple[int, int, int]:
	"""
	Converte '2025.3' ou '2026.1.1' em tupla de 3 inteiros.
	Valores invalidos retornam (0, 0, 0).
	"""
	parts = str(version).strip().replace("-", ".").split(".")
	try:
		major = int(parts[0]) if len(parts) > 0 and parts[0] else 0
		minor = int(parts[1]) if len(parts) > 1 and parts[1] else 0
		patch = int(parts[2]) if len(parts) > 2 and parts[2] else 0
	except ValueError:
		return (0, 0, 0)
	return (major, minor, patch)


PROJECT_MIN_NVDA_TUPLE = parse_version_tuple(PROJECT_MIN_NVDA)
PROJECT_LAST_TESTED_NVDA_TUPLE = parse_version_tuple(PROJECT_LAST_TESTED_NVDA)
ABSOLUTE_MIN_NVDA_TUPLE = parse_version_tuple(ABSOLUTE_MIN_NVDA)


def is_below_project_baseline(version: str) -> bool:
	"""Retorna True se a versao estiver abaixo do baseline oficial do projeto."""
	return parse_version_tuple(version) < PROJECT_MIN_NVDA_TUPLE


