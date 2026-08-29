class TestAgentMemoryVersao:
	def test_versao_e_1_1_0(self):
		from nvdastudio.memory.agent_memory import MODULE_VERSION
		assert MODULE_VERSION == "2.0.0"


class TestOutcomeEArmazenadoDeVerdade:
	def test_remember_guarda_outcome_em_entrada_nova(self):
		from nvdastudio.memory.agent_memory import AgentMemory
		mem = AgentMemory()
		mem.remember(
			agent_type="code_generation",
			pattern="Success on gerar addon de clipboard",
			outcome="def foo(): pass",
		)
		from unittest.mock import MagicMock
		client = MagicMock()
		client.chat.return_value.content = '{"selected_ids":[0]}'
		entries = mem.recall("code_generation", "gerar addon de clipboard", semantic_client=client)
		assert len(entries) == 1
		assert entries[0].outcome == "def foo(): pass"

	def test_remember_atualiza_outcome_em_entrada_similar(self):
		from nvdastudio.memory.agent_memory import AgentMemory
		mem = AgentMemory()
		mem.remember(agent_type="code_generation", pattern="Success on gerar addon X", outcome="v1")
		mem.remember(agent_type="code_generation", pattern="Success on gerar addon X", outcome="v2")
		from unittest.mock import MagicMock
		client = MagicMock()
		client.chat.return_value.content = '{"selected_ids":[0]}'
		entries = mem.recall("code_generation", "gerar addon X", semantic_client=client)
		assert len(entries) == 1
		assert entries[0].frequency == 2
		assert entries[0].outcome == "v2"

	def test_get_successful_patterns_usa_outcome_quando_fix_vazio(self):
		"""Regressao direta do bug: fix fica vazio em steps que so tiveram sucesso
		(sem correcao explicita) -- antes a dica saia "SOLUCAO: " vazia."""
		from nvdastudio.memory.agent_memory import AgentMemory
		mem = AgentMemory()
		mem.remember(
			agent_type="manifest_builder",
			pattern="Success on gerar manifest.ini",
			outcome="name = MeuAddon",
		)
		patterns = mem.get_successful_patterns("manifest_builder", limit=1)
		assert len(patterns) == 1
		assert "name = MeuAddon" in patterns[0]
		assert not patterns[0].endswith("SOLUCAO: ")


class TestGetCommonMistakes:
	def test_remember_falha_aparece_em_common_mistakes(self):
		from nvdastudio.memory.agent_memory import AgentMemory
		mem = AgentMemory()
		mem.remember(
			agent_type="code_generation",
			pattern="Output vazio -- o agente nao gerou nenhum conteudo",
			success=False,
		)
		mistakes = mem.get_common_mistakes("code_generation", limit=5)
		assert len(mistakes) == 1
		assert "Output vazio" in mistakes[0]
