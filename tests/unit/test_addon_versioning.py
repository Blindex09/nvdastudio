"""
Ciclo de vida do addon gerado: versionamento semantico e changelog.

Lacuna real fechada (auditoria 2026-08-29): o pipeline tratava toda entrega
como se fosse a primeira. O prompt de manifest_builder trazia `version = 1.0.0`
como unico exemplo e nenhuma orientacao sobre MODIFICAR um addon existente --
que e metade do proposito do projeto. Um addon reentregue ainda como 1.0.0 nao
sinaliza atualizacao nenhuma para o NVDA, e o usuario cego nao tem tela para
perceber a diferenca.

O teste mais importante deste arquivo e TestCosturaComAddonLoader: a extracao
da versao anterior depende do formato EXATO do cabecalho emitido por outro
modulo. Se aquele lado mudar sozinho, o bump vira no-op em silencio -- a classe
de bug que o CLAUDE.md manda travar dos dois lados.
"""

from nvdastudio.builder.addon_loader import AddonContext
from nvdastudio.utils.addon_versioning import (
	MODULE_VERSION,
	changelog_is_uninformative,
	enforce_version_bump,
	extract_previous_version,
	next_version,
	parse_semver,
)

assert MODULE_VERSION == "1.0.0"


class TestCosturaComAddonLoader:
	"""O que addon_loader PROMETE no prompt e o que addon_versioning CONSUME."""

	def test_le_a_versao_do_contexto_real_do_addon_loader(self):
		ctx = AddonContext(
			addon_name="MeuAddon",
			version="2.4.1",
			summary="resumo",
			source_path="C:/x",
			python_files={},
			manifest_raw="name = MeuAddon\nversion = 2.4.1\n",
			doc_content="",
		)
		assert extract_previous_version(ctx.to_prompt_context()) == "2.4.1"

	def test_nome_de_addon_com_espacos_nao_quebra_a_extracao(self):
		ctx = AddonContext(
			addon_name="Meu Addon De Teste",
			version="1.2.3",
			summary="",
			source_path="",
			python_files={},
			manifest_raw="",
			doc_content="",
		)
		assert extract_previous_version(ctx.to_prompt_context()) == "1.2.3"

	def test_addon_novo_nao_tem_versao_anterior(self):
		assert extract_previous_version("cria um addon que anuncia a hora") is None


class TestProximaVersao:
	def test_fix_incrementa_patch(self):
		assert next_version("1.2.3", "fix") == "1.2.4"

	def test_feature_incrementa_minor_e_zera_patch(self):
		assert next_version("1.2.3", "feature") == "1.3.0"

	def test_breaking_incrementa_major_e_zera_o_resto(self):
		assert next_version("1.2.3", "breaking") == "2.0.0"

	def test_tipo_desconhecido_cai_em_feature_sem_levantar(self):
		"""Roda dentro do pipeline -- excecao aqui derrubaria uma entrega
		por causa de um numero."""
		assert next_version("1.2.3", "qualquer_coisa") == "1.3.0"

	def test_versao_nao_semver_cai_no_menor_valor_seguro(self):
		assert next_version("beta", "feature") == "1.0.0"
		assert next_version("0.9", "fix") == "1.0.0"

	def test_parse_semver_rejeita_formato_livre(self):
		assert parse_semver("1.2.3") == (1, 2, 3)
		assert parse_semver("1.2") is None
		assert parse_semver("v1.2.3") is None


class TestEnforcementDeVersao:
	def test_versao_repetida_e_corrigida(self):
		manifest = "name = X\nversion = 1.0.0\nchangelog = mudou algo\n"
		corrigido, aviso = enforce_version_bump(manifest, "1.0.0")
		assert "version = 1.1.0" in corrigido
		assert aviso is not None and "1.0.0" in aviso

	def test_versao_retrocedida_e_corrigida(self):
		"""REGRESSAO: 1.0.9 < 1.1.0 exige comparacao NUMERICA por componente --
		comparacao de string diria que '1.0.9' > '1.1.0'."""
		manifest = "version = 1.0.9\n"
		corrigido, aviso = enforce_version_bump(manifest, "1.1.0")
		assert "version = 1.2.0" in corrigido
		assert aviso is not None

	def test_versao_ja_maior_passa_intacta(self):
		manifest = "name = X\nversion = 2.0.0\n"
		corrigido, aviso = enforce_version_bump(manifest, "1.9.9")
		assert corrigido == manifest
		assert aviso is None

	def test_addon_novo_nao_sofre_bump(self):
		manifest = "version = 1.0.0\n"
		corrigido, aviso = enforce_version_bump(manifest, None)
		assert corrigido == manifest
		assert aviso is None

	def test_manifest_sem_campo_version_passa_intacto(self):
		"""Campo obrigatorio ausente e problema do manifest_builder/critic --
		nao e este modulo que decide reprovar."""
		manifest = "name = X\n"
		corrigido, aviso = enforce_version_bump(manifest, "1.0.0")
		assert corrigido == manifest
		assert aviso is None

	def test_so_a_primeira_ocorrencia_de_version_e_reescrita(self):
		"""minimumNVDAVersion/lastTestedNVDAVersion nao podem ser tocados."""
		manifest = (
			"name = X\nversion = 1.0.0\n"
			"minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.1.1\n"
		)
		corrigido, _ = enforce_version_bump(manifest, "1.0.0")
		assert "minimumNVDAVersion = 2026.1.1" in corrigido
		assert "lastTestedNVDAVersion = 2026.1.1" in corrigido
		assert "version = 1.1.0" in corrigido


class TestChangelog:
	def test_placeholder_e_detectado(self):
		for texto in ("versao inicial", "Melhorias gerais", "n/a", "Bug fixes", "-"):
			assert changelog_is_uninformative(f"changelog = {texto}\n"), texto

	def test_changelog_concreto_passa(self):
		manifest = (
			"changelog = Novo atalho NVDA+shift+t anuncia o tempo restante da faixa.\n"
		)
		assert changelog_is_uninformative(manifest) is False

	def test_campo_ausente_conta_como_nao_informativo(self):
		assert changelog_is_uninformative("name = X\n") is True


class TestIntegracaoComManifestBuilder:
	def test_orientacao_de_ciclo_de_vida_esta_no_prompt(self):
		from nvdastudio.sub_agents import manifest_builder
		from nvdastudio.utils.addon_versioning import ADDON_LIFECYCLE_PROMPT_TEXT

		assert ADDON_LIFECYCLE_PROMPT_TEXT in manifest_builder._SYSTEM

	def test_run_corrige_versao_de_addon_existente(self):
		"""Costura ponta a ponta: prompt com addon existente + saida da LLM
		repetindo a versao -> manifest entregue ja corrigido."""
		from unittest.mock import patch

		from nvdastudio.sub_agents import manifest_builder

		saida_llm = "name = MeuAddon\nversion = 1.0.0\nchangelog = mudou algo\n"
		prompt = "=== ADDON EXISTENTE: MeuAddon v1.0.0 ===\nmodifica pra fazer X"

		with patch.object(manifest_builder, "_run_sub_agent", return_value=saida_llm), \
			 patch.object(manifest_builder, "narrate"), \
			 patch.object(manifest_builder, "get_docs_manifest_builder", return_value=""):
			resultado = manifest_builder.run(prompt, "modelo", {})

		assert "version = 1.1.0" in resultado

	def test_run_nao_mexe_em_addon_novo(self):
		from unittest.mock import patch

		from nvdastudio.sub_agents import manifest_builder

		saida_llm = "name = MeuAddon\nversion = 1.0.0\nchangelog = anuncia a hora\n"

		with patch.object(manifest_builder, "_run_sub_agent", return_value=saida_llm), \
			 patch.object(manifest_builder, "narrate"), \
			 patch.object(manifest_builder, "get_docs_manifest_builder", return_value=""):
			resultado = manifest_builder.run("cria um addon que anuncia a hora", "modelo", {})

		assert "version = 1.0.0" in resultado
