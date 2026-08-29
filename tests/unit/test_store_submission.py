import os
import json
import zipfile
import tempfile
import pytest


def _create_nvda_addon(tmp_path, manifest_content: str) -> str:
    """Cria um .nvda-addon (ZIP) com manifest.ini para testes."""
    addon_path = str(tmp_path / "meuAddon.nvda-addon")
    with zipfile.ZipFile(addon_path, "w") as zf:
        zf.writestr("manifest.ini", manifest_content.encode("utf-8"))
        zf.writestr("globalPlugins/meuAddon/__init__.py", "# addon")
    return addon_path


_MANIFEST_COMPLETO = """name = MeuAddon
summary = Addon de teste para o NVDA
description = Addon que faz coisas incriveis para usuarios cegos.
author = Felipe Dev <felipe@example.com>
url = https://github.com/felipe/meuaddon
version = 1.2.3
minimumNVDAVersion = 2026.1.1
lastTestedNVDAVersion = 2026.1.1
docFileName = userGuide.html
changelog = Versao inicial.
updateChannel = stable
"""


class TestGenerateStoreSubmissionImport:
    def test_importavel(self):
        from nvdastudio.builder.addon_builder import generate_store_submission
        assert callable(generate_store_submission)

    def test_versao_e_1_8_0(self):
        from nvdastudio.builder.addon_builder import MODULE_VERSION
        assert MODULE_VERSION == "4.13.0"


class TestGenerateStoreSubmissionBasico:
    def test_retorna_dict(self, tmp_path):
        from nvdastudio.builder.addon_builder import generate_store_submission
        addon = _create_nvda_addon(tmp_path, _MANIFEST_COMPLETO)
        result = generate_store_submission(addon)
        assert isinstance(result, dict)

    def test_retorna_sha256(self, tmp_path):
        from nvdastudio.builder.addon_builder import generate_store_submission
        addon = _create_nvda_addon(tmp_path, _MANIFEST_COMPLETO)
        result = generate_store_submission(addon)
        assert "sha256" in result
        assert len(result["sha256"]) == 64  # SHA256 hex = 64 chars

    def test_retorna_json_path(self, tmp_path):
        from nvdastudio.builder.addon_builder import generate_store_submission
        addon = _create_nvda_addon(tmp_path, _MANIFEST_COMPLETO)
        result = generate_store_submission(addon)
        assert "json_path" in result
        assert os.path.isfile(result["json_path"])

    def test_retorna_metadata(self, tmp_path):
        from nvdastudio.builder.addon_builder import generate_store_submission
        addon = _create_nvda_addon(tmp_path, _MANIFEST_COMPLETO)
        result = generate_store_submission(addon)
        assert "metadata" in result
        assert isinstance(result["metadata"], dict)

    def test_json_file_e_valido(self, tmp_path):
        from nvdastudio.builder.addon_builder import generate_store_submission
        addon = _create_nvda_addon(tmp_path, _MANIFEST_COMPLETO)
        result = generate_store_submission(addon)
        with open(result["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)
        assert isinstance(data, dict)


class TestGenerateStoreSubmissionCampos:
    """Verifica campos obrigatorios do Add-on Store."""

    def _get_metadata(self, tmp_path):
        from nvdastudio.builder.addon_builder import generate_store_submission
        addon = _create_nvda_addon(tmp_path, _MANIFEST_COMPLETO)
        return generate_store_submission(addon)["metadata"]

    def test_addon_id_presente(self, tmp_path):
        meta = self._get_metadata(tmp_path)
        assert "addonId" in meta
        assert len(meta["addonId"]) > 0

    def test_channel_presente(self, tmp_path):
        meta = self._get_metadata(tmp_path)
        assert "channel" in meta
        assert meta["channel"] in ("stable", "beta", "dev")

    def test_addon_version_number_presente(self, tmp_path):
        meta = self._get_metadata(tmp_path)
        assert "addonVersionNumber" in meta
        v = meta["addonVersionNumber"]
        assert "major" in v and "minor" in v and "patch" in v

    def test_version_parsead_corretamente(self, tmp_path):
        meta = self._get_metadata(tmp_path)
        v = meta["addonVersionNumber"]
        assert v["major"] == 1
        assert v["minor"] == 2
        assert v["patch"] == 3

    def test_display_name_presente(self, tmp_path):
        meta = self._get_metadata(tmp_path)
        assert "displayName" in meta
        assert "Addon" in meta["displayName"]

    def test_publisher_extraido_do_author(self, tmp_path):
        meta = self._get_metadata(tmp_path)
        assert "publisher" in meta
        assert "Felipe" in meta["publisher"]

    def test_description_presente(self, tmp_path):
        meta = self._get_metadata(tmp_path)
        assert "description" in meta

    def test_min_nvda_version_presente(self, tmp_path):
        meta = self._get_metadata(tmp_path)
        assert "minNVDAVersion" in meta
        v = meta["minNVDAVersion"]
        assert v == {"major": 2026, "minor": 1, "patch": 1}

    def test_last_tested_version_presente(self, tmp_path):
        meta = self._get_metadata(tmp_path)
        assert "lastTestedVersion" in meta
        v = meta["lastTestedVersion"]
        assert v == {"major": 2026, "minor": 1, "patch": 1}

    def test_sha256_no_metadata(self, tmp_path):
        from nvdastudio.builder.addon_builder import generate_store_submission
        addon = _create_nvda_addon(tmp_path, _MANIFEST_COMPLETO)
        result = generate_store_submission(addon)
        assert result["metadata"]["sha256"] == result["sha256"]

    def test_license_presente(self, tmp_path):
        meta = self._get_metadata(tmp_path)
        assert "license" in meta

    def test_source_url_presente(self, tmp_path):
        meta = self._get_metadata(tmp_path)
        assert "sourceURL" in meta

    def test_url_download_presente(self, tmp_path):
        meta = self._get_metadata(tmp_path)
        assert "URL" in meta

    def test_channel_default_stable(self, tmp_path):
        from nvdastudio.builder.addon_builder import generate_store_submission
        addon = _create_nvda_addon(tmp_path, _MANIFEST_COMPLETO)
        result = generate_store_submission(addon, channel="stable")
        assert result["metadata"]["channel"] == "stable"

    def test_channel_beta_aceito(self, tmp_path):
        from nvdastudio.builder.addon_builder import generate_store_submission
        addon = _create_nvda_addon(tmp_path, _MANIFEST_COMPLETO)
        result = generate_store_submission(addon, channel="beta")
        assert result["metadata"]["channel"] == "beta"


class TestGenerateStoreSubmissionSHA256:
    def test_sha256_e_string_hex(self, tmp_path):
        from nvdastudio.builder.addon_builder import generate_store_submission
        addon = _create_nvda_addon(tmp_path, _MANIFEST_COMPLETO)
        result = generate_store_submission(addon)
        sha = result["sha256"]
        assert all(c in "0123456789abcdef" for c in sha)

    def test_sha256_tem_64_chars(self, tmp_path):
        from nvdastudio.builder.addon_builder import generate_store_submission
        addon = _create_nvda_addon(tmp_path, _MANIFEST_COMPLETO)
        result = generate_store_submission(addon)
        assert len(result["sha256"]) == 64

    def test_sha256_determinista(self, tmp_path):
        """Mesmo arquivo = mesmo SHA256."""
        from nvdastudio.builder.addon_builder import generate_store_submission
        addon = _create_nvda_addon(tmp_path, _MANIFEST_COMPLETO)
        r1 = generate_store_submission(addon)
        r2 = generate_store_submission(addon)
        assert r1["sha256"] == r2["sha256"]

    def test_arquivos_diferentes_sha256_diferentes(self, tmp_path):
        """Arquivos diferentes = SHA256 diferentes."""
        from nvdastudio.builder.addon_builder import generate_store_submission
        dir_a1 = tmp_path / "a1"
        dir_a1.mkdir()
        a1 = _create_nvda_addon(dir_a1, _MANIFEST_COMPLETO)
        manifest2 = _MANIFEST_COMPLETO.replace("1.2.3", "2.0.0")
        a2 = _create_nvda_addon(tmp_path, manifest2)
        r1 = generate_store_submission(a1)
        r2 = generate_store_submission(a2)
        assert r1["sha256"] != r2["sha256"]

    def test_nao_executa_conteudo_do_addon(self, tmp_path):
        """Regra 9: apenas le e calcula hash — nao executa codigo."""
        from nvdastudio.builder.addon_builder import generate_store_submission
        manifest = _MANIFEST_COMPLETO
        addon = _create_nvda_addon(tmp_path, manifest)
        # Adiciona codigo malicioso no addon — nao deve ser executado
        with zipfile.ZipFile(addon, "a") as zf:
            zf.writestr("malicioso.py", "import os; os.system('del /q')")
        result = generate_store_submission(addon)
        assert isinstance(result["sha256"], str)


class TestGenerateStoreSubmissionErros:
    def test_arquivo_inexistente_levanta_erro(self):
        from nvdastudio.builder.addon_builder import generate_store_submission, AddonBuilderError
        with pytest.raises(AddonBuilderError):
            generate_store_submission("/caminho/inexistente/addon.nvda-addon")

    def test_sem_manifest_levanta_erro(self, tmp_path):
        from nvdastudio.builder.addon_builder import generate_store_submission, AddonBuilderError
        # ZIP sem manifest.ini
        addon_path = str(tmp_path / "sem_manifest.nvda-addon")
        with zipfile.ZipFile(addon_path, "w") as zf:
            zf.writestr("globalPlugins/__init__.py", "# sem manifest")
        with pytest.raises(AddonBuilderError):
            generate_store_submission(addon_path)

    def test_manifest_sem_name_levanta_erro(self, tmp_path):
        from nvdastudio.builder.addon_builder import generate_store_submission, AddonBuilderError
        manifest_sem_name = "summary = Teste\nversion = 1.0.0\n"
        addon = _create_nvda_addon(tmp_path, manifest_sem_name)
        with pytest.raises(AddonBuilderError):
            generate_store_submission(addon)


class TestGenerateStoreSubmissionJSONSalvo:
    def test_json_salvo_ao_lado_do_addon(self, tmp_path):
        from nvdastudio.builder.addon_builder import generate_store_submission
        addon = _create_nvda_addon(tmp_path, _MANIFEST_COMPLETO)
        result = generate_store_submission(addon)
        assert result["json_path"].endswith("_store_submission.json")
        assert os.path.dirname(result["json_path"]) == str(tmp_path)

    def test_json_contem_todos_campos_obrigatorios(self, tmp_path):
        from nvdastudio.builder.addon_builder import generate_store_submission
        addon = _create_nvda_addon(tmp_path, _MANIFEST_COMPLETO)
        result = generate_store_submission(addon)
        with open(result["json_path"], encoding="utf-8") as fh:
            data = json.load(fh)
        campos = ["addonId", "channel", "addonVersionNumber", "displayName",
                  "publisher", "description", "minNVDAVersion",
                  "lastTestedVersion", "URL", "sha256", "sourceURL", "license"]
        for campo in campos:
            assert campo in data, f"Campo ausente: {campo}"

    def test_json_e_utf8(self, tmp_path):
        from nvdastudio.builder.addon_builder import generate_store_submission
        manifest = _MANIFEST_COMPLETO.replace(
            "Addon de teste para o NVDA",
            "Addon com acentos: acessibilidade e inclusao"
        )
        addon = _create_nvda_addon(tmp_path, manifest)
        result = generate_store_submission(addon)
        with open(result["json_path"], encoding="utf-8") as fh:
            content = fh.read()
        assert "acessibilidade" in content


class TestParseVersionHelper:
    """_parse_version converte string de versao em dict {major,minor,patch}."""

    def _parse(self, ver_str):
        from nvdastudio.builder.addon_builder import generate_store_submission
        import zipfile
        import os
        # Usa generate_store_submission com manifest customizado para testar parsing
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = f"name = TestAddon\nversion = {ver_str}\nminimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.1.1\n"
            addon_path = os.path.join(tmpdir, "test.nvda-addon")
            with zipfile.ZipFile(addon_path, "w") as zf:
                zf.writestr("manifest.ini", manifest.encode("utf-8"))
            result = generate_store_submission(addon_path)
            return result["metadata"]["addonVersionNumber"]

    def test_parse_versao_tres_partes(self):
        v = self._parse("1.2.3")
        assert v == {"major": 1, "minor": 2, "patch": 3}

    def test_parse_versao_duas_partes(self):
        v = self._parse("2026.1")
        assert v == {"major": 2026, "minor": 1, "patch": 0}

    def test_parse_versao_uma_parte(self):
        v = self._parse("3")
        assert v["major"] == 3
        assert v["minor"] == 0
        assert v["patch"] == 0
