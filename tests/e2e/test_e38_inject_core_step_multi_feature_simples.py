import os

import pytest

from .test_criacao_completa import _rodar_pipeline_e2e, _E2E_OUTPUT_DIR

HAS_OLLAMA = os.environ.get("OLLAMA_API_KEY", "").strip()
# 2026-08-17: critic.py 3.19.0 -- o Critic agora SEMPRE usa OpenCode Go
# (prompt caching), independente do provider ativo. Sem essa chave, TODA
# avaliacao de step falha com "Chave API para opencode_go nao configurada"
# -- achado real ao vivo (madrugada 2026-08-17/18, rodada 1 do loop): os
# 2 casos deste arquivo rodaram e "passaram" no pytest (test_e36 nao exige
# success=True) mas o pipeline inteiro falhou em segundos, 0 tokens gastos,
# nenhum sinal real coletado -- so desperdicou tempo/custo do Ollama sem
# testar nada. Adicionado ao skip guard pra nao rodar (e enganar) sem as
# 2 chaves.
HAS_OPENCODE_GO = os.environ.get("OPENCODE_GO_API_KEY", "").strip()
skip_unless_ollama = pytest.mark.skipif(
	not HAS_OLLAMA or not HAS_OPENCODE_GO,
	reason=("Ollama Cloud token nao disponivel" if not HAS_OLLAMA else "OpenCode Go token nao disponivel (necessario pro Critic, ver critic.py 3.19.0)")
)

_QUERY_3_FEATURES_TRIVIAIS = (
	"Crie um addon NVDA chamado UtilitariosRapidos com 3 funcionalidades "
	"independentes e simples, cada uma so lendo informacao ja disponivel no "
	"sistema (sem API externa, sem rede, sem tela de configuracoes): "
	"(1) NVDA+Shift+H anuncia a hora e data atuais; "
	"(2) NVDA+Shift+B anuncia o nivel de bateria e se esta carregando "
	"(via psutil ou win32 API); "
	"(3) NVDA+Shift+V anuncia o nome da janela em primeiro plano no momento. "
	"Cada funcionalidade deve morar no seu proprio subpacote dentro de "
	"globalPlugins/UtilitariosRapidos/. Mantenha o codigo minimo e direto."
)


class TestInjectCoreStepMultiFeatureSimples:
	"""
	Pedido com 3 features triviais e independentes -- gatilho minimo de
	ARCH-010 (decomposicao paralela), sem o custo de um pedido complexo real
	com integracao de API externa. Verifica que o addon final SEMPRE tem
	__init__.py com GlobalPlugin, mesmo quando o LLM decompoe em multiplos
	code_generation -- a classe de bug corrigida em planner.py 2.28.0.
	"""

	@skip_unless_ollama
	def test_addon_final_tem_init_com_globalplugin(self):
		report = _rodar_pipeline_e2e(
			"UtilitariosRapidos",
			_QUERY_3_FEATURES_TRIVIAIS,
			output_dir=_E2E_OUTPUT_DIR,
		)

		assert not report.error, f"Pipeline falhou com erro: {report.error}"
		assert report.has_init_py, (
			f"BUG 5.52.0/2.28.0 (test_e36) NAO deveria mais acontecer: addon "
			f"final sem __init__.py raiz -- NVDA nunca carregaria. "
			f"Problemas estruturais: {report.struct_problems}"
		)
		estrutura008 = [p for p in report.struct_problems if p.startswith("ESTRUTURA-008")]
		assert estrutura008 == [], (
			f"ESTRUTURA-008 (globalPlugins/<addon>/ sem __init__.py) nao "
			f"deveria mais aparecer: {estrutura008}"
		)

		# Confirma que o __init__.py raiz de verdade tem a classe GlobalPlugin
		# (nao so existe como arquivo vazio/placeholder).
		init_path_candidates = [
			os.path.join(report.addon_folder, "globalPlugins", "UtilitariosRapidos", "__init__.py"),
		]
		init_encontrado = next((p for p in init_path_candidates if os.path.isfile(p)), None)
		assert init_encontrado is not None, (
			f"__init__.py raiz nao encontrado em nenhum dos caminhos esperados: "
			f"{init_path_candidates}"
		)
		with open(init_encontrado, encoding="utf-8", errors="replace") as fh:
			conteudo = fh.read()
		assert "class GlobalPlugin" in conteudo, (
			f"__init__.py raiz existe mas nao contem 'class GlobalPlugin' -- "
			f"addon nao seria reconhecido pelo NVDA. Conteudo: {conteudo[:500]}"
		)
