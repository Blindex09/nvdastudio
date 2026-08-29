from nvdastudio.builder.context_compressor import _model_token_limit


def test_kimi_k2_7_code_tem_limite_proprio_nao_generico():
	assert _model_token_limit("kimi-k2.7-code") == 256000
	assert _model_token_limit("kimi-k2.7-code") != _model_token_limit("modelo-totalmente-desconhecido")


def test_deepseek_v4_flash_janela_real_1m_nao_64k():
	"""Bug real: a tabela antiga tinha 64000 pra este modelo; a janela real e 1M."""
	assert _model_token_limit("deepseek-v4-flash") == 1_000_000


def test_modelo_desconhecido_usa_fallback_conservador():
	assert _model_token_limit("modelo-que-nao-existe") == 32000


def test_modelos_dos_5_provedores_tem_janela_real_nao_fallback():
	"""Antes de v3.0.0, so kimi-k2.7-code/kimi-k2.6/deepseek-v4-flash tinham
	entrada -- todo o resto (Claude/GPT/Gemini/Grok) caia no fallback de
	32000, comprimindo contexto desnecessariamente."""
	modelos_esperados = [
		"claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5",
		"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
		"gemini-3.1-pro-preview", "gemini-3.6-flash",
		"grok-build-0.1", "grok-4.5", "grok-4.3",
	]
	for model_id in modelos_esperados:
		limite = _model_token_limit(model_id)
		assert limite > 32000, f"{model_id} deveria ter janela real, nao o fallback de 32000 (tem {limite})"
