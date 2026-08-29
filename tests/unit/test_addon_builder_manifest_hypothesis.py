import keyword

from hypothesis import given, settings, strategies as st

from nvdastudio.builder.addon_builder import (
	validate_manifest,
	validate_python_structure,
	validate_python_syntax,
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


class TestValidatePythonSyntaxNuncaLevantaExcecao:
	@given(codigo=_ARBITRARY_TEXT)
	@settings(max_examples=200, deadline=None)
	def test_nunca_levanta_excecao(self, codigo):
		resultado = validate_python_syntax(codigo)
		assert resultado is None or isinstance(resultado, str)

	@given(codigo=st.text(alphabet=st.characters(whitelist_categories=("L", "N", "Zs")), max_size=50))
	@settings(max_examples=100, deadline=None)
	def test_codigo_python_valido_gerado_retorna_none(self, codigo):
		"""Atribuicoes simples de identificador->identificador sao sempre
		sintaticamente validas em Python (quando ambos os lados sao
		identificadores nao-vazios comecando por letra)."""
		nome = "".join(c for c in codigo if c.isidentifier() or c == "_")
		if not nome or not nome[0].isalpha():
			return
		if keyword.iskeyword(nome) or keyword.issoftkeyword(nome):
			return
		valor = "1"
		snippet = f"{nome} = {valor}"
		resultado = validate_python_syntax(snippet)
		assert resultado is None
