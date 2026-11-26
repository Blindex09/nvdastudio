MODULE_VERSION = "1.1.0"

# Official baseline of the project. The current NVDAStudio does not actively
# maintain compatibility with versions older than this line.
PROJECT_MIN_NVDA = "2026.1.1"
PROJECT_LAST_TESTED_NVDA = "2026.3.1"
PROJECT_SUPPORTED_RANGE = "2026.1.1+"

# Entry-point folders that NVDA loads; any one of them is enough for the add-on to exist.
ENTRY_POINT_DIRS = (
	"globalPlugins", "appModules", "synthDrivers", "brailleDisplayDrivers",
	"visionEnhancementProviders",
)

# Absolute technical floor of the historical NVDA rules (Python 3).
ABSOLUTE_MIN_NVDA = "2019.3.0"


def parse_version_tuple(version: str) -> tuple[int, int, int]:
	"""
	Converts '2025.3' or '2026.1.1' into a tuple of 3 integers.
	Invalid values return (0, 0, 0).
	"""
	parts = str(version).strip().replace("-", ".").split(".")
	try:
		major = int(parts[0]) if len(parts) > 0 and parts[0] else 0
		minor = int(parts[1]) if len(parts) > 1 and parts[1] else 0
		patch = int(parts[2]) if len(parts) > 2 and parts[2] else 0
	except ValueError:
		return (0, 0, 0)
	return (major, minor, patch)
