from nvdastudio.ai.ollama_client import _clean_response


class TestPreservaBlocosDeCodigoComTagDeLinguagem:
	def test_preserva_fence_com_filename_anotado(self):
		texto = (
			"```python:globalPlugins/meuAddon/__init__.py\n"
			"def foo(*args, **kwargs):\n"
			"\tresult = a * b\n"
			"\treturn result ** 2\n"
			"```"
		)
		assert _clean_response(texto) == texto

	def test_preserva_multiplos_arquivos_fenced(self):
		texto = (
			"```python:globalPlugins/x/__init__.py\n"
			"def f(*args, **kwargs): pass\n"
			"```\n"
			"```ini:manifest.ini\n"
			"name = X\n"
			"```"
		)
		limpo = _clean_response(texto)
		assert "```python:globalPlugins/x/__init__.py" in limpo
		assert "```ini:manifest.ini" in limpo
		assert "*args" in limpo
		assert "**kwargs" in limpo

	def test_preserva_fence_sem_filename_mas_com_linguagem_conhecida(self):
		texto = "```python\ndef f(*args, **kwargs):\n\tpass\n```"
		assert _clean_response(texto) == texto

	def test_preserva_flag_de_cli_com_dois_tracos(self):
		texto = (
			'```python:globalPlugins/x/cli.py\n'
			'parser.add_argument("--verbose")\n'
			"```"
		)
		limpo = _clean_response(texto)
		assert "--verbose" in limpo


class TestPreservaRespostaAntesDaApresentacao:
	"""O cliente conserva a resposta; somente a camada de UI a simplifica."""

	def test_preserva_markdown_para_json_e_artefatos(self):
		texto = '**Beleza!** use `**kwargs` e --verbose.'
		assert _clean_response(texto) == texto

	def test_preserva_divisores_antes_do_sanitizador_visual(self):
		texto = "Texto\n----\nOutro texto"
		assert _clean_response(texto) == texto

	def test_preserva_fence_generica(self):
		texto = "```\nSo um texto entre crases triplas\n```"
		assert _clean_response(texto) == texto
