from nvdastudio.sub_agents.code_generator import _provider_supports_native_file_editing


def test_file_editor_fallback_respeita_capacidade_nativa_declarada():
	class NativeClient:
		supports_file_editing = True

	class LegacyClient:
		_provider = "ollama"

	assert _provider_supports_native_file_editing(NativeClient()) is True
	assert _provider_supports_native_file_editing(LegacyClient()) is False
