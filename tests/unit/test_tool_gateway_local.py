from nvdastudio.tools.tool_gateway import ToolGateway, ToolSchema


def test_registered_tool_executes_locally():
	gateway = ToolGateway()
	gateway.register(
		"echo",
		lambda value: value,
		ToolSchema("echo", "Echo", {"type": "object"}, ["value"]),
	)
	result, error = gateway.call("echo", {"value": "ok"})
	assert error is None
	assert result == "ok"


def test_register_builtin_tools_nao_engole_import_error():
	"""
	Bug real de auditoria: register_builtin_tools importava file_reader_tool,
	ast_parser_tool, nvda_validator_tool -- nomes que nunca existiram nos
	modulos reais (read_file, parse_python_code, validate_addon_structure).
	O except Exception amplo engolia o ImportError silenciosamente, entao as
	3 tools nativas nunca se registravam de verdade.
	"""
	gateway = ToolGateway()
	gateway.register_builtin_tools()

	for name in ("file_reader", "ast_parser", "nvda_validator"):
		assert name in gateway._tools, f"{name} deveria ter sido registrada"


class TestApprovalFailClosed:
	"""Achado de auditoria full-stack 2026-08-04 (segunda rodada): sem
	callback de aprovacao registrado, uma tool `dangerous` era executada
	sem pedir nada ("modo YOLO" no proprio comentario) -- contradizia a
	Regra 3 do docstring do modulo ("Approval: file_write, execute_code
	precisam de confirmacao") e a doutrina fail-closed ja estabelecida em
	tool_system/approval.py. call() nao tem chamador em producao hoje
	(so set_callbacks() e usado), entao isso era dormant, nao explorado --
	corrigido preventivamente."""

	def _make_gateway_com_tool_perigosa(self):
		gateway = ToolGateway()
		gateway.register(
			"apagar_arquivo",
			lambda path: "apagado",
			ToolSchema("apagar_arquivo", "Apaga um arquivo", {"type": "object"}, ["path"]),
			dangerous=True,
		)
		return gateway

	def test_sem_callback_registrado_nega_tool_perigosa(self):
		gateway = self._make_gateway_com_tool_perigosa()
		result, error = gateway.call("apagar_arquivo", {"path": "x.txt"})
		assert result is None
		assert error is not None
		assert "recusada" in error.lower()

	def test_callback_levantando_excecao_nega_por_seguranca(self):
		gateway = self._make_gateway_com_tool_perigosa()
		gateway.set_callbacks(on_approval_request=lambda name, args: (_ for _ in ()).throw(RuntimeError("boom")))
		result, error = gateway.call("apagar_arquivo", {"path": "x.txt"})
		assert result is None
		assert error is not None

	def test_callback_aprovando_explicitamente_executa(self):
		gateway = self._make_gateway_com_tool_perigosa()
		gateway.set_callbacks(on_approval_request=lambda name, args: True)
		result, error = gateway.call("apagar_arquivo", {"path": "x.txt"})
		assert error is None
		assert result == "apagado"

	def test_callback_negando_explicitamente_bloqueia(self):
		gateway = self._make_gateway_com_tool_perigosa()
		gateway.set_callbacks(on_approval_request=lambda name, args: False)
		result, error = gateway.call("apagar_arquivo", {"path": "x.txt"})
		assert result is None
		assert error is not None

	def test_tool_nao_perigosa_nao_precisa_de_aprovacao(self):
		"""Regressao: o fail-closed e so pra tools dangerous=True -- tools
		normais continuam executando sem pedir aprovacao nenhuma."""
		gateway = ToolGateway()
		gateway.register(
			"echo", lambda value: value,
			ToolSchema("echo", "Echo", {"type": "object"}, ["value"]),
		)
		result, error = gateway.call("echo", {"value": "ok"})
		assert error is None
		assert result == "ok"
