from nvdastudio.tool_system.approval import ApprovalWorkflow


class TestHardlineNuncaEContornavel:
	"""Hardline e bloqueio INCONDICIONAL -- nenhum modo/estado deve driblar."""

	def test_rm_rf_raiz_e_bloqueado_em_modo_padrao(self):
		wf = ApprovalWorkflow()
		approved, reason = wf.should_approve("shell_command", {"command": "rm -rf /"})
		assert approved is False
		assert "hardline" in reason.lower() or "bloqueado" in reason.lower()

	def test_hardline_bloqueado_mesmo_em_modo_off(self):
		wf = ApprovalWorkflow(mode="off")
		approved, reason = wf.should_approve("shell_command", {"command": "shutdown -h now"})
		assert approved is False

	def test_hardline_bloqueado_mesmo_em_yolo(self):
		wf = ApprovalWorkflow()
		wf.enable_yolo("s1")
		approved, reason = wf.should_approve("shell_command", {"command": "reboot"}, session_key="s1")
		assert approved is False

	def test_hardline_bloqueado_mesmo_com_tool_na_allowlist_permanente(self):
		wf = ApprovalWorkflow()
		wf.approve_always("shell_command")
		approved, _reason = wf.should_approve("shell_command", {"command": "poweroff"})
		assert approved is False, (
			"Hardline deve vencer ate uma allowlist permanente -- fail-closed real"
		)

	def test_request_approval_hardline_nunca_chama_callback(self):
		"""Comando hardline nao deve nem chegar a perguntar ao usuario."""
		wf = ApprovalWorkflow()
		chamado = []
		wf.set_approval_callback(lambda req: chamado.append(req) or True)
		result = wf.request_approval("shell_command", {"command": "mkfs.ext4 /dev/sda1"})
		assert result is False
		assert chamado == [], "callback nao deveria ser chamado pra comando hardline"


class TestFailClosedSemCallback:
	def test_sem_callback_definido_nega_por_padrao(self):
		"""Fail-closed: sem callback de aprovacao, tool de risco medio/alto e negada."""
		wf = ApprovalWorkflow()
		result = wf.request_approval("network_request", {"url": "https://example.com"})
		assert result is False

	def test_callback_que_levanta_excecao_nega_por_padrao(self):
		wf = ApprovalWorkflow()
		wf.set_approval_callback(lambda req: (_ for _ in ()).throw(RuntimeError("falhou")))
		result = wf.request_approval("network_request", {"url": "https://example.com"})
		assert result is False

	def test_callback_aprovando_retorna_true(self):
		wf = ApprovalWorkflow()
		wf.set_approval_callback(lambda req: True)
		result = wf.request_approval("network_request", {"url": "https://example.com"})
		assert result is True


class TestAnaliseDeRisco:
	def test_tool_sempre_aprovar_tem_risco_high(self):
		wf = ApprovalWorkflow()
		risk, _reason, _patterns = wf.analyze_risk("code_executor", {})
		assert risk == "high"

	def test_tool_nunca_aprovar_tem_risco_low(self):
		wf = ApprovalWorkflow()
		risk, _reason, _patterns = wf.analyze_risk("file_reader", {})
		assert risk == "low"

	def test_padrao_perigoso_em_argumento_vira_risco_high(self):
		wf = ApprovalWorkflow()
		risk, _reason, patterns = wf.analyze_risk("generic_tool", {"command": "chmod 777 /etc"})
		assert risk == "high"
		assert patterns, "deveria registrar qual padrao disparou"

	def test_argumento_com_path_traversal_vira_risco_medium(self):
		wf = ApprovalWorkflow()
		risk, _reason, _patterns = wf.analyze_risk("generic_tool", {"path": "../../etc/passwd"})
		assert risk == "medium"

	def test_tool_desconhecida_sem_padroes_suspeitos_e_low_com_auto_approve(self):
		wf = ApprovalWorkflow(auto_approve_low_risk=True)
		risk, _reason, _patterns = wf.analyze_risk("tool_qualquer", {"nome": "valor inocuo"})
		assert risk == "low"


class TestAprovacaoPersistente:
	def test_tool_low_risk_e_auto_aprovada_sem_pedir_callback(self):
		wf = ApprovalWorkflow()
		chamado = []
		wf.set_approval_callback(lambda req: chamado.append(req) or True)
		result = wf.request_approval("file_reader", {"path": "x.py"})
		assert result is True
		assert chamado == [], "tool low-risk nao deveria acionar o callback de aprovacao"

	def test_approve_session_persiste_so_para_a_sessao_informada(self):
		wf = ApprovalWorkflow()
		wf.approve_session("code_executor", session_key="s1")

		approved_s1, _ = wf.should_approve("code_executor", {}, session_key="s1")
		approved_s2, _ = wf.should_approve("code_executor", {}, session_key="s2")

		assert approved_s1 is True
		assert approved_s2 is False, "aprovacao de sessao nao deveria vazar pra outra sessao"

	def test_approve_always_persiste_entre_sessoes(self):
		wf = ApprovalWorkflow()
		wf.approve_always("code_executor")

		approved_s1, _ = wf.should_approve("code_executor", {}, session_key="qualquer")
		assert approved_s1 is True

	def test_clear_session_remove_aprovacao_de_sessao(self):
		wf = ApprovalWorkflow()
		wf.approve_session("code_executor", session_key="s1")
		wf.clear_session("s1")

		approved, _ = wf.should_approve("code_executor", {}, session_key="s1")
		assert approved is False


class TestYoloMode:
	def test_yolo_aprova_tool_de_risco_alto_sem_callback(self):
		wf = ApprovalWorkflow()
		wf.enable_yolo("s1")
		approved, reason = wf.should_approve("code_executor", {}, session_key="s1")
		assert approved is True
		assert "yolo" in reason.lower()

	def test_yolo_nao_afeta_outras_sessoes(self):
		wf = ApprovalWorkflow()
		wf.enable_yolo("s1")
		approved, _ = wf.should_approve("code_executor", {}, session_key="s2")
		assert approved is False

	def test_disable_yolo_reverte_o_bypass(self):
		wf = ApprovalWorkflow()
		wf.enable_yolo("s1")
		wf.disable_yolo("s1")
		approved, _ = wf.should_approve("code_executor", {}, session_key="s1")
		assert approved is False


class TestGatewayQueue:
	def test_submit_pending_registra_pedido(self):
		wf = ApprovalWorkflow()
		wf.submit_pending("code_executor", {"code": "x = 1"}, session_key="s1")
		pending = wf.get_pending("s1")
		assert pending is not None
		assert pending["tool_name"] == "code_executor"

	def test_resolve_pending_com_always_aprova_permanentemente(self):
		wf = ApprovalWorkflow()
		wf.submit_pending("code_executor", {}, session_key="s1")
		resolved = wf.resolve_pending("s1", "always")

		assert resolved is True
		approved, _ = wf.should_approve("code_executor", {}, session_key="outra_sessao")
		assert approved is True

	def test_resolve_pending_sem_fila_retorna_false(self):
		wf = ApprovalWorkflow()
		assert wf.resolve_pending("sessao_sem_fila", "always") is False
