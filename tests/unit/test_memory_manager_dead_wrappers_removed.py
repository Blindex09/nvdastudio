from nvdastudio.memory.memory_manager import MemoryManager


class TestWrappersProativosRemovidos:
	def test_record_user_correction_nao_existe_mais(self):
		assert not hasattr(MemoryManager, "record_user_correction")

	def test_record_preference_nao_existe_mais(self):
		assert not hasattr(MemoryManager, "record_preference")

	def test_record_environment_fact_nao_existe_mais(self):
		assert not hasattr(MemoryManager, "record_environment_fact")

	def test_record_convention_nao_existe_mais(self):
		assert not hasattr(MemoryManager, "record_convention")

	def test_api_real_permanece(self):
		assert hasattr(MemoryManager, "add")
		assert hasattr(MemoryManager, "replace")
		assert hasattr(MemoryManager, "remove")
		assert hasattr(MemoryManager, "learn_from_session")
