"""Regressao: as dependencias detectadas nao chegavam a lugar nenhum.

Os DOIS lados da costura existiam e estavam corretos:
 - orchestrator detecta imports externos e envia em OrchestrationResult.dependencies;
 - studio_dialog tem _bundle_async -> bundle_addon_dependencies, que instala em
   lib/ fixando a ABI do Python embarcado do NVDA (CPython 3.13 win x64).
Faltava a CHAMADA: _bundle_async nao tinha NENHUM chamador em todo o projeto, e
a tela nunca lia result.dependencies.

Medido na entrega ResumoGemini (2026-09-02, primeiro addon complexo entregue):
o addon saiu sem lib/. Sem google-generativeai ele carrega no NVDA e avisa por
voz -- degrada bem -- mas nao resume nada.

wx.Dialog e mockado na suite, entao os metodos de instancia sao verificados por
analise de fonte (convencao ja usada em test_studio_dialog.py) e a decisao pura
foi extraida para deps_pendentes(), exercitada de verdade.
"""
from nvdastudio.gui.studio_dialog import deps_pendentes
from nvdastudio.gui import studio_dialog as sd


def _fonte() -> str:
	with open(sd.__file__, encoding="utf-8") as fh:
		return fh.read()


class TestDepsPendentes:
	def test_sem_declaradas_nao_ha_pendencia(self, tmp_path):
		assert deps_pendentes(None, str(tmp_path)) == []
		assert deps_pendentes([], str(tmp_path)) == []

	def test_lib_inexistente_tudo_pendente(self, tmp_path):
		assert deps_pendentes(["requests"], str(tmp_path / "lib")) == ["requests"]

	def test_hifen_do_pip_vira_underscore_na_pasta(self, tmp_path):
		"""pip grava google_generativeai/ para google-generativeai."""
		lib = tmp_path / "lib"
		(lib / "google_generativeai").mkdir(parents=True)
		assert deps_pendentes(["google-generativeai"], str(lib)) == []

	def test_extra_do_pip_nao_entra_no_nome_da_pasta(self, tmp_path):
		lib = tmp_path / "lib"
		(lib / "requests").mkdir(parents=True)
		assert deps_pendentes(["requests[socks]"], str(lib)) == []

	def test_so_o_que_falta_e_reinstalado(self, tmp_path):
		lib = tmp_path / "lib"
		(lib / "requests").mkdir(parents=True)
		assert deps_pendentes(["requests", "pillow"], str(lib)) == ["pillow"]

	def test_ignora_entradas_vazias(self, tmp_path):
		assert deps_pendentes(["", "  ", "requests"], str(tmp_path / "lib")) == ["requests"]

	def test_lib_ilegivel_nao_derruba_o_empacotamento(self, tmp_path, monkeypatch):
		"""Fail-safe: se nao da pra ler lib/, trata como pendente e pergunta --
		melhor perguntar de novo do que empacotar sem a biblioteca."""
		lib = tmp_path / "lib"
		lib.mkdir()
		monkeypatch.setattr(sd.os, "listdir", lambda _p: (_ for _ in ()).throw(OSError("negado")))
		assert deps_pendentes(["requests"], str(lib)) == ["requests"]


class TestFioLigado:
	def test_bundle_async_tem_chamador(self):
		"""O defeito original: o instalador existia e ninguem chamava."""
		n = _fonte().count("_bundle_async(")
		assert n >= 2, f"_bundle_async aparece {n}x -- definicao sem chamador"

	def test_empacotamento_consulta_o_portao(self):
		assert "self._instalar_dependencias_se_preciso(" in _fonte()

	def test_portao_roda_antes_de_gerar_o_zip(self):
		"""Ordem importa: instalar DEPOIS de zipar nao entra no pacote."""
		f = _fonte()
		assert f.index("if self._instalar_dependencias_se_preciso(") < f.index('f"{safe_name}.nvda-addon"')

	def test_reentra_no_empacotamento_ao_terminar(self):
		"""Sem a reentrada o addon ficaria instalado e nunca empacotado."""
		f = _fonte()
		i = f.index("def _instalar_dependencias_se_preciso")
		assert "self._on_package(None)" in f[i:i + 3000]

	def test_flag_evita_perguntar_de_novo(self):
		"""Guarda contra laco: a reentrada nao pode cair no portao outra vez."""
		f = _fonte()
		assert "_deps_ja_tratadas" in f
		i = f.index("def _instalar_dependencias_se_preciso")
		assert "getattr(self, '_deps_ja_tratadas', False)" in f[i:i + 1200]

	def test_falha_de_instalacao_nao_impede_a_entrega(self):
		"""Degradacao graciosa: entrega o que deu, avisando."""
		f = _fonte()
		i = f.index("def _instalar_dependencias_se_preciso")
		trecho = f[i:i + 3000]
		assert "Nao consegui instalar" in trecho
		assert trecho.index("Nao consegui instalar") < trecho.index("self._on_package(None)")
