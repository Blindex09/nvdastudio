from hypothesis import given, settings, strategies as st

from nvdastudio.builder.addon_builder import (
	validate_manifest,
	validate_python_structure,
	_MANIFEST_REQUIRED_FIELDS,
)

_ARBITRARY_TEXT = st.text(max_size=500)


class TestValidateManifestNuncaLevantaExcecao:
	@given(codigo=_ARBITRARY_TEXT)
	@settings(max_examples=200, deadline=None)
	def test_nunca_levanta_excecao_e_retorna_lista(self, codigo):
		resultado = validate_manifest(codigo)
		assert isinstance(resultado, list)
		assert all(isinstance(campo, str) for campo in resultado)

	@given(codigo=_ARBITRARY_TEXT)
	@settings(max_examples=100, deadline=None)
	def test_campos_ausentes_sao_subconjunto_dos_obrigatorios(self, codigo):
		resultado = validate_manifest(codigo)
		assert set(resultado).issubset(set(_MANIFEST_REQUIRED_FIELDS))


class TestValidateManifestComCamposGerados:
	"""Propriedade dirigida: para qualquer subconjunto dos campos
	obrigatorios presentes no texto, os campos AUSENTES relatados devem
	ser exatamente o complemento -- nunca a mais, nunca a menos."""

	_SUBCONJUNTOS = st.lists(
		st.sampled_from(_MANIFEST_REQUIRED_FIELDS), unique=True, max_size=len(_MANIFEST_REQUIRED_FIELDS)
	)

	@given(presentes=_SUBCONJUNTOS)
	@settings(max_examples=100, deadline=None)
	def test_ausentes_e_exatamente_o_complemento(self, presentes):
		manifest_text = "\n".join(f"{campo} = valor_qualquer" for campo in presentes)
		resultado = validate_manifest(manifest_text)
		esperado_ausente = set(_MANIFEST_REQUIRED_FIELDS) - set(presentes)
		assert set(resultado) == esperado_ausente

	def test_todos_os_campos_presentes_retorna_lista_vazia(self):
		manifest_text = "\n".join(f"{campo} = x" for campo in _MANIFEST_REQUIRED_FIELDS)
		assert validate_manifest(manifest_text) == []

	def test_manifest_vazio_retorna_todos_os_campos(self):
		assert set(validate_manifest("")) == set(_MANIFEST_REQUIRED_FIELDS)


class TestValidatePythonStructureNuncaLevantaExcecao:
	@given(codigo=_ARBITRARY_TEXT)
	@settings(max_examples=200, deadline=None)
	def test_nunca_levanta_excecao_e_retorna_lista(self, codigo):
		resultado = validate_python_structure(codigo)
		assert isinstance(resultado, list)
