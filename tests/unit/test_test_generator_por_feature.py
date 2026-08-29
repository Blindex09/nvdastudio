class TestModuloTestName:
	def test_arquivo_solto_na_raiz_do_addon(self):
		from nvdastudio.sub_agents.test_generator import _module_test_name

		assert _module_test_name("globalPlugins/MeuAddon/servico.py") == "test_servico"

	def test_init_na_raiz_do_addon(self):
		from nvdastudio.sub_agents.test_generator import _module_test_name

		assert _module_test_name("globalPlugins/MeuAddon/__init__.py") == "test_init"

	def test_arquivo_dentro_de_subpacote_de_feature(self):
		from nvdastudio.sub_agents.test_generator import _module_test_name

		assert (
			_module_test_name("globalPlugins/MeuAddon/spotify/client.py")
			== "test_spotify_client"
		)

	def test_normaliza_barra_invertida_windows(self):
		from nvdastudio.sub_agents.test_generator import _module_test_name

		assert (
			_module_test_name("globalPlugins\\MeuAddon\\transcricao\\servico.py")
			== "test_transcricao_servico"
		)


class TestExtractCodeManifestUmModulo:
	def test_um_bloco_sem_filename_nao_sugere_split_por_feature(self):
		from nvdastudio.sub_agents.test_generator import _extract_code_manifest

		prompt = '''```python
class GlobalPlugin:
    def script_announceTime(self, gesture):
        pass
```'''
		manifesto, sugestoes = _extract_code_manifest(prompt)

		assert "GlobalPlugin" in manifesto
		assert sugestoes == []
		assert "ORGANIZACAO POR FEATURE" not in manifesto

	def test_um_bloco_com_filename_tambem_nao_sugere_split(self):
		from nvdastudio.sub_agents.test_generator import _extract_code_manifest

		prompt = '''```python:globalPlugins/MeuAddon/__init__.py
class GlobalPlugin:
    def script_announceTime(self, gesture):
        pass
```'''
		manifesto, sugestoes = _extract_code_manifest(prompt)

		assert "GlobalPlugin" in manifesto
		assert sugestoes == []
		assert "ORGANIZACAO POR FEATURE" not in manifesto


class TestExtractCodeManifestMultiplosModulos:
	def test_dois_modulos_nomeados_sugere_split_por_feature(self):
		from nvdastudio.sub_agents.test_generator import _extract_code_manifest

		prompt = '''```python:globalPlugins/MeuAddon/spotify/client.py
class SpotifyClient:
    def play(self):
        pass
```
```python:globalPlugins/MeuAddon/transcricao/servico.py
class TranscricaoServico:
    def transcrever(self):
        pass
```'''
		manifesto, sugestoes = _extract_code_manifest(prompt)

		assert "SpotifyClient" in manifesto
		assert "TranscricaoServico" in manifesto
		assert sugestoes == ["test_spotify_client", "test_transcricao_servico"]
		assert "ORGANIZACAO POR FEATURE (ARCH-007)" in manifesto
		assert "tests/test_spotify_client.py" in manifesto
		assert "tests/test_transcricao_servico.py" in manifesto

	def test_agrupa_classes_por_arquivo_nao_achata(self):
		from nvdastudio.sub_agents.test_generator import _extract_code_manifest

		prompt = '''```python:globalPlugins/MeuAddon/spotify/client.py
class SpotifyClient:
    def play(self):
        pass
```
```python:globalPlugins/MeuAddon/playlists/gerenciador.py
class GerenciadorPlaylists:
    def criar(self):
        pass
```'''
		manifesto, _sugestoes = _extract_code_manifest(prompt)

		assert "Arquivo: globalPlugins/MeuAddon/spotify/client.py" in manifesto
		assert "Arquivo: globalPlugins/MeuAddon/playlists/gerenciador.py" in manifesto

	def test_um_modulo_nomeado_e_outro_sem_filename_nao_sugere_split(self):
		"""So sugere split quando 2+ modulos tem filename REAL anotado."""
		from nvdastudio.sub_agents.test_generator import _extract_code_manifest

		prompt = '''```python:globalPlugins/MeuAddon/spotify/client.py
class SpotifyClient:
    def play(self):
        pass
```
```python
class Helper:
    def ajuda(self):
        pass
```'''
		manifesto, sugestoes = _extract_code_manifest(prompt)

		assert sugestoes == []
		assert "ORGANIZACAO POR FEATURE" not in manifesto


class TestExtractCodeManifestSemCodigo:
	def test_prompt_sem_blocos_python_retorna_vazio(self):
		from nvdastudio.sub_agents.test_generator import _extract_code_manifest

		manifesto, sugestoes = _extract_code_manifest("Descricao textual sem codigo.")

		assert manifesto == ""
		assert sugestoes == []

	def test_bloco_com_syntaxerror_e_ignorado_silenciosamente(self):
		from nvdastudio.sub_agents.test_generator import _extract_code_manifest

		prompt = '''```python:globalPlugins/MeuAddon/quebrado.py
def def def isso nao e python valido(((
```'''
		manifesto, sugestoes = _extract_code_manifest(prompt)

		assert manifesto == ""
		assert sugestoes == []

	def test_bloco_sem_classes_nao_entra_no_manifesto(self):
		"""So blocos com pelo menos uma classe viram entrada no manifesto."""
		from nvdastudio.sub_agents.test_generator import _extract_code_manifest

		prompt = '''```python:globalPlugins/MeuAddon/util.py
def funcao_solta():
    pass
```'''
		manifesto, sugestoes = _extract_code_manifest(prompt)

		assert manifesto == ""
		assert sugestoes == []


class TestRunGeneratedTestsExecutaDeVerdade:
	"""Achado de auditoria 2026-08-04: os testes gerados nunca eram
	EXECUTADOS, so guardados como artefato estatico -- um teste que afirma
	o comportamento errado passava a validacao do mesmo jeito. Estes testes
	provam que _run_generated_tests() roda de verdade em sandbox isolado e
	so anexa aviso quando os testes REALMENTE falham (nao por infra)."""

	_PROMPT = '''```python:globalPlugins/Foo/__init__.py
def add(a, b):
    return a + b
```'''

	def test_testes_passando_nao_anexa_aviso(self):
		from nvdastudio.sub_agents.test_generator import _run_generated_tests

		result = '''```python:tests/test_foo.py
import sys, os
sys.path.insert(0, os.path.join(os.getcwd(), "globalPlugins", "Foo"))
import __init__ as foo

def test_add():
    assert foo.add(2, 3) == 5
```'''
		out = _run_generated_tests(self._PROMPT, result)
		assert "[AVISO-TESTES]" not in out
		assert out == result

	def test_teste_falhando_de_verdade_anexa_aviso(self):
		from nvdastudio.sub_agents.test_generator import _run_generated_tests

		result = '''```python:tests/test_foo.py
import sys, os
sys.path.insert(0, os.path.join(os.getcwd(), "globalPlugins", "Foo"))
import __init__ as foo

def test_add_errado_de_proposito():
    assert foo.add(2, 2) == 5
```'''
		out = _run_generated_tests(self._PROMPT, result)
		assert "[AVISO-TESTES]" in out
		assert "FALHARAM" in out
		# O bloco de teste original continua intacto, o aviso so e ANEXADO.
		assert result in out

	def test_falha_de_infraestrutura_nao_e_aprovacao_silenciosa(self):
		from types import SimpleNamespace
		from unittest.mock import patch
		from nvdastudio.sub_agents.test_generator import _run_generated_tests

		result = '''```python:tests/test_foo.py
def test_add():
    assert True
```'''
		infra = SimpleNamespace(
			success=False, error="pytest_indisponivel", timed_out=False,
			stdout="", stderr="",
		)
		with patch("nvdastudio.sub_agents.test_generator._code_sandbox.run_test_suite", return_value=infra):
			out = _run_generated_tests(self._PROMPT, result)

		assert "[AVISO-TESTES-INFRA]" in out

	def test_sem_bloco_de_teste_extraivel_nao_quebra(self):
		from nvdastudio.sub_agents.test_generator import _run_generated_tests

		result = "so texto solto, sem fences de codigo nenhum"
		out = _run_generated_tests(self._PROMPT, result)
		assert out == result

	def test_run_pula_execucao_de_testes_durante_a_propria_suite_pytest(self, fake_api_key, monkeypatch):
		"""Guard: chamar run() DENTRO da nossa propria suite pytest nao deve
		disparar sandbox recursivo (mesmo padrao de _base.py pro cache/
		live_narrate) -- sys.modules ja tem 'pytest' durante os testes."""
		import nvdastudio.sub_agents.test_generator as test_generator_mod

		called = []
		monkeypatch.setattr(
			test_generator_mod, "_run_generated_tests",
			lambda prompt, result: called.append(1) or result,
		)
		monkeypatch.setattr(
			test_generator_mod, "_run_sub_agent",
			lambda *a, **k: "```python:tests/test_x.py\ndef test_a():\n    pass\n```",
		)

		test_generator_mod.run("prompt qualquer", "kimi-k2.6", {})

		assert called == [], "nao deveria chamar _run_generated_tests durante a propria suite pytest"
