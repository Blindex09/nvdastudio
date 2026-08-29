import ast
import inspect

from nvdastudio.core import orchestrator


def _find_partial_ready_blocks(source: str) -> list[ast.If]:
	"""Acha os blocos `if _presult.approved or pstep.step_type in
	_NON_BLOCKING_STEP_TYPES:` dentro do source de um metodo -- e a
	assinatura textual unica dos 2 loops de contexto parcial."""
	tree = ast.parse(source)
	blocks = []
	for node in ast.walk(tree):
		if not isinstance(node, ast.If):
			continue
		try:
			condition_src = ast.unparse(node.test)
		except Exception:
			continue
		if "_presult.approved" in condition_src and "_NON_BLOCKING_STEP_TYPES" in condition_src:
			blocks.append(node)
	return blocks


class TestLoopsDeContextoParcialTemElseQueMarcaFalha:
	def test_run_pipeline_principal_tem_2_blocos_de_contexto_parcial(self):
		"""Guard-rail: confirma que ha 2 loops de contexto parcial no
		modulo (_run_pipeline e a variante de resume) -- se esse numero
		cair, o teste abaixo pode estar checando menos do que deveria."""
		src = inspect.getsource(orchestrator)
		blocks = _find_partial_ready_blocks(src)
		assert len(blocks) == 2, (
			f"esperado 2 blocos de contexto parcial (_run_pipeline + resume), "
			f"encontrado {len(blocks)} -- ajuste este teste se a estrutura mudou"
		)

	def test_ambos_os_blocos_tem_else_que_remove_de_remaining_e_marca_failed(self):
		src = inspect.getsource(orchestrator)
		blocks = _find_partial_ready_blocks(src)
		for i, node in enumerate(blocks):
			assert node.orelse, (
				f"bloco de contexto parcial #{i+1} nao tem `else` -- um step "
				f"que falha com contexto parcial ficaria retentando pra "
				f"sempre, silenciosamente, sem nunca ser marcado como "
				f"bloqueado (bug real achado em 2026-08-09, ver changelog "
				f"orchestrator.py 5.49.0)"
			)
			else_src = "\n".join(ast.unparse(n) for n in node.orelse)
			assert "remaining.remove(pstep)" in else_src, (
				f"bloco #{i+1}: else nao remove pstep de `remaining` -- "
				f"step ficaria elegivel pra tentar de novo indefinidamente"
			)
			assert "failed_step_ids.add(pstep.step_id)" in else_src, (
				f"bloco #{i+1}: else nao marca pstep em `failed_step_ids` -- "
				f"outros steps dependentes nunca saberiam que ele falhou"
			)
