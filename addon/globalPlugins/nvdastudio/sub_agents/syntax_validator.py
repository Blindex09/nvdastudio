import ast
import re
from ._base import _tl
from ..utils.logger import get_logger, log_decision

MODULE_VERSION = "2.0.0"
_logger = get_logger("syntax_validator")

# Pattern para extrair blocos Python com caminho anotado
_PYTHON_BLOCK_RE = re.compile(
	r"```python:([^\n]+)\n(.*?)```",
	re.DOTALL,
)


def _extract_python_blocks(text: str) -> list[tuple[str, str]]:
	"""
	Extrai blocos Python anotados com caminho do arquivo.
	Retorna lista de (caminho, codigo).
	Regra 9: nao executa o codigo — apenas extrai texto.
	"""
	return [
		(m.group(1).strip(), m.group(2))
		for m in _PYTHON_BLOCK_RE.finditer(text)
	]


def run(prompt: str, model_id: str, reasoning_params: dict, cache_key: str | None = None) -> str:
	"""
	Valida sintaxe Python do codigo gerado via ast.parse() local.

	Zero chamadas de rede. Deterministica.
	Retorna relatorio de validacao em texto (PASS / FAIL / SKIP).

	Regra 9: nao executa o addon — apenas chama ast.parse().
	"""
	blocks = _extract_python_blocks(prompt)
	if not blocks:
		_logger.info("[OK] syntax_validator: nenhum bloco Python no prompt. SKIP.")
		_tl.last_tokens = 0
		return "RESULTADO: SKIP\nNenhum bloco Python encontrado no input para validar."

	_logger.info(
		"[OK] syntax_validator: %d bloco(s) Python encontrado(s). Iniciando validacao.",
		len(blocks)
	)

	errors: list[str] = []
	for path, code in blocks:
		try:
			ast.parse(code)
		except SyntaxError as exc:
			errors.append(f"Arquivo {path}: SyntaxError: {exc.msg} (line {exc.lineno})")
		except Exception as exc:
			errors.append(f"Arquivo {path}: {type(exc).__name__}: {exc}")

	_tl.last_tokens = 0  # validacao local, sem LLM

	if not errors:
		log_decision(_logger, "syntax_pass", f"blocks={len(blocks)}")
		return "RESULTADO: PASS\nTodos os blocos Python sao sintaticamente validos."

	errs_str = "; ".join(errors[:3])
	log_decision(_logger, "syntax_fail", f"errors={len(errors)}: {errs_str}")
	error_lines = "\n".join(f"- {e}" for e in errors)
	return f"RESULTADO: FAIL\nErros encontrados:\n{error_lines}"
