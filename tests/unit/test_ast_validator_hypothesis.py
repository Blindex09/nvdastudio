import keyword

from hypothesis import given, settings, strategies as st

from nvdastudio.sub_agents.ast_validator import (
	validate_nvda019,
	validate_wx_a11y,
	validate_wx_a11y_002_accelerators,
)

# Estrategia de "quase-Python": strings arbitrarias com caracteres tipicos
# de codigo fonte -- a maioria sera SyntaxError, o que exercita o caminho
# fail-open (retorna ok=True) que os testes a mao ja cobrem, mas aqui em
# volume e com combinacoes que ninguem escreveria a mao.
_QUASE_PYTHON = st.text(
	alphabet=st.characters(whitelist_categories=("L", "N", "P", "Zs"), max_codepoint=0x2FF),
	max_size=300,
)


class TestValidateNvda019NuncaLevantaExcecao:
	"""Propriedade: para QUALQUER string de entrada, validate_nvda019 nunca
	lanca excecao -- fail-open documentado no proprio docstring do modulo."""

	@given(codigo=_QUASE_PYTHON)
	@settings(max_examples=200, deadline=None)
	def test_nunca_levanta_excecao_para_texto_arbitrario(self, codigo):
		resultado = validate_nvda019(codigo)
		assert isinstance(resultado.ok, bool)
		assert isinstance(resultado.violacoes, list)

	@given(codigo=st.text(max_size=500))
	@settings(max_examples=100, deadline=None)
	def test_texto_unicode_arbitrario_nao_quebra(self, codigo):
		"""Inclui emojis, RTL, caracteres de controle -- superficie mais ampla
		que a estrategia 'quase-python' acima."""
		resultado = validate_nvda019(codigo)
		assert isinstance(resultado.ok, bool)

	@given(codigo=_QUASE_PYTHON)
	@settings(max_examples=200, deadline=None)
	def test_ok_e_consistente_com_lista_de_violacoes_vazia(self, codigo):
		"""Invariante estrutural: ok=True se e somente se violacoes=[]."""
		resultado = validate_nvda019(codigo)
		assert resultado.ok == (len(resultado.violacoes) == 0)


class TestValidateWxA11yNuncaLevantaExcecao:
	@given(codigo=_QUASE_PYTHON)
	@settings(max_examples=200, deadline=None)
	def test_nunca_levanta_excecao(self, codigo):
		resultado = validate_wx_a11y(codigo)
		assert isinstance(resultado.ok, bool)
		assert resultado.ok == (len(resultado.violacoes) == 0)

	@given(codigo=st.text(max_size=500))
	@settings(max_examples=100, deadline=None)
	def test_texto_unicode_arbitrario_nao_quebra(self, codigo):
		resultado = validate_wx_a11y(codigo)
		assert isinstance(resultado.ok, bool)


class TestValidateWxA11y002NuncaLevantaExcecao:
	@given(codigo=_QUASE_PYTHON)
	@settings(max_examples=200, deadline=None)
	def test_nunca_levanta_excecao(self, codigo):
		resultado = validate_wx_a11y_002_accelerators(codigo)
		assert isinstance(resultado.ok, bool)
		assert resultado.ok == (len(resultado.violacoes) == 0)


class TestValidadoresSaoDeterministicos:
	"""Propriedade: a mesma entrada sempre produz a mesma saida (nenhum
	validador deve depender de estado global, ordem de chamadas ou tempo)."""

	@given(codigo=_QUASE_PYTHON)
	@settings(max_examples=100, deadline=None)
	def test_nvda019_e_deterministico(self, codigo):
		r1 = validate_nvda019(codigo)
		r2 = validate_nvda019(codigo)
		assert r1.ok == r2.ok
		assert r1.violacoes == r2.violacoes

	@given(codigo=_QUASE_PYTHON)
	@settings(max_examples=100, deadline=None)
	def test_wx_a11y_e_deterministico(self, codigo):
		r1 = validate_wx_a11y(codigo)
		r2 = validate_wx_a11y(codigo)
		assert r1.ok == r2.ok
		assert r1.violacoes == r2.violacoes


class TestNvda019ComGettextGerado:
	"""Propriedade dirigida: gera chamadas _() sinteticas COM e SEM o
	comentario '# Translators:' na linha anterior, varia o nome da variavel
	e o texto -- confirma que a regra dispara exatamente quando (e so
	quando) o comentario esta ausente, para qualquer texto/nome validos."""

	_IDENT = st.text(
		alphabet=st.characters(whitelist_categories=("Ll",), max_codepoint=0x7A), min_size=1, max_size=8
	).filter(lambda s: not keyword.iskeyword(s) and not keyword.issoftkeyword(s))
	_TEXTO = st.text(alphabet=st.characters(whitelist_categories=("Ll", "Zs"), max_codepoint=0x7A), max_size=20).filter(
		lambda s: '"' not in s and "'" not in s and "\\" not in s
	)

	@given(nome_var=_IDENT, texto=_TEXTO)
	@settings(max_examples=100, deadline=None)
	def test_sem_translators_sempre_viola(self, nome_var, texto):
		codigo = f'{nome_var} = _("{texto}")'
		resultado = validate_nvda019(codigo)
		assert not resultado.ok
		assert len(resultado.violacoes) == 1

	@given(nome_var=_IDENT, texto=_TEXTO)
	@settings(max_examples=100, deadline=None)
	def test_com_translators_nunca_viola(self, nome_var, texto):
		codigo = f'# Translators: {texto}\n{nome_var} = _("{texto}")'
		resultado = validate_nvda019(codigo)
		assert resultado.ok
		assert resultado.violacoes == []
