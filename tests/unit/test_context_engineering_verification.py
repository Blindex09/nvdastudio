import ast
import inspect

from nvdastudio.core import orchestrator


def _find_evaluate_two_stage_calls(tree: ast.AST) -> list[ast.Call]:
	calls = []
	for node in ast.walk(tree):
		if not isinstance(node, ast.Call):
			continue
		func = node.func
		if isinstance(func, ast.Attribute) and func.attr == "evaluate_two_stage":
			calls.append(node)
	return calls


class TestTodaChamadaAoCriticPassaContextoCompleto:
	"""
	Fitness function: nenhuma chamada a evaluate_two_stage() em
	orchestrator.py pode passar `context` cru como ultimo argumento --
	todas devem passar por _critic_context(step, context) (ou uma funcao
	equivalente que inclua o objetivo do step), senao o Critic volta a
	julgar as-cegas como no bug real desta sessao.
	"""

	def test_existe_pelo_menos_uma_chamada_ao_critic(self):
		"""Guard-rail do proprio teste: se este numero cair pra 0, o teste
		abaixo passaria vazio sem checar nada -- confirma que ha algo pra
		verificar de verdade."""
		src = inspect.getsource(orchestrator)
		tree = ast.parse(src)
		calls = _find_evaluate_two_stage_calls(tree)
		assert len(calls) >= 3, (
			f"esperado >= 3 pontos de chamada a evaluate_two_stage() "
			f"(loop principal, escalacao, resgate cross-provider), "
			f"encontrado {len(calls)} -- fitness function pode ter perdido "
			f"cobertura de algum ponto real."
		)

	def test_nenhuma_chamada_passa_context_cru_como_ultimo_argumento(self):
		src = inspect.getsource(orchestrator)
		tree = ast.parse(src)
		calls = _find_evaluate_two_stage_calls(tree)

		violacoes = []
		for call in calls:
			if not call.args:
				continue
			ultimo_arg = call.args[-1]
			# Passa a checagem se o ultimo argumento e uma CHAMADA a
			# _critic_context(...) -- qualquer outra forma (Name "context"
			# cru, outra expressao) e suspeita e deve ser investigada.
			eh_wrapper_correto = (
				isinstance(ultimo_arg, ast.Call)
				and isinstance(ultimo_arg.func, ast.Name)
				and ultimo_arg.func.id == "_critic_context"
			)
			if not eh_wrapper_correto:
				linha = getattr(call, "lineno", "?")
				violacoes.append(f"linha {linha}: {ast.dump(ultimo_arg)[:80]}")

		assert not violacoes, (
			f"chamada(s) a evaluate_two_stage() SEM passar por "
			f"_critic_context() -- o Critic vai julgar sem saber o "
			f"objetivo do step (mesma classe do bug real ARCH-010/2026-08-09): "
			f"{violacoes}"
		)

	def test_critic_context_existe_e_e_chamavel(self):
		assert hasattr(orchestrator, "_critic_context")
		assert callable(orchestrator._critic_context)
