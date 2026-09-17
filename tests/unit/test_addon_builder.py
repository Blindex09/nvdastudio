import os
import tempfile
import zipfile

import pytest

from nvdastudio.builder.addon_builder import (
    extract_code_blocks,
    save_addon_files,
    package_addon,
    load_artifact_blocks,
    AddonBuilderError,
    name_from_manifest_blocks,
    validate_addon_structure,
    _sanitize_manifest,
    _manifest_scalar_errors,
)


class TestExtractCodeBlocks:
    """Testes de extracao de blocos de codigo da resposta da IA."""

    def test_extrai_bloco_python_anotado(self, ai_response_with_code_blocks):
        blocks = extract_code_blocks(ai_response_with_code_blocks)
        python_blocks = [b for b in blocks if b["language"] == "python"]
        assert len(python_blocks) >= 1

    def test_extrai_bloco_ini_anotado(self, ai_response_with_code_blocks):
        blocks = extract_code_blocks(ai_response_with_code_blocks)
        ini_blocks = [b for b in blocks if b["language"] == "ini"]
        assert len(ini_blocks) >= 1

    def test_bloco_tem_filename(self, ai_response_with_code_blocks):
        blocks = extract_code_blocks(ai_response_with_code_blocks)
        for block in blocks:
            assert block["filename"], "filename nao pode ser vazio"

    def test_bloco_tem_code(self, ai_response_with_code_blocks):
        blocks = extract_code_blocks(ai_response_with_code_blocks)
        for block in blocks:
            assert block["code"].strip(), "code nao pode ser vazio"

    def test_sem_blocos_retorna_lista_vazia(self):
        blocks = extract_code_blocks("Texto sem nenhum bloco de codigo.")
        assert blocks == []

    def test_fallback_sem_anotacao_de_arquivo(self):
        # Blocos Python sem anotacao de filename e sem classe detectavel
        # agora sao preservados como module_N.py (Fix 4.1.1 — anti-descarte).
        texto = "```python\nimport globalPluginHandler\n```"
        blocks = extract_code_blocks(texto)
        assert len(blocks) == 1
        assert blocks[0]["filename"] == "module_1.py"
        assert "import globalPluginHandler" in blocks[0]["code"]

    def test_nao_executa_codigo_extraido(self):
        # Regra 9: extracao nao executa codigo.
        texto = (
            "```python:mal.py\n"
            "import os; os.system('echo EXECUTADO')\n"
            "```"
        )
        blocks = extract_code_blocks(texto)
        assert len(blocks) == 1
        assert "os.system" in blocks[0]["code"]

    def test_multiplos_blocos_extraidos(self):
        texto = (
            "```python:a.py\ncodigo_a\n```\n\n"
            "```ini:manifest.ini\n[add-on]\nname=x\n```\n\n"
            "```python:b.py\ncodigo_b\n```"
        )
        blocks = extract_code_blocks(texto)
        assert len(blocks) == 3

    def test_estrutura_004_manifest_nomeado_python_anonimo(self):
        """
        Regressao ESTRUTURA-004 (2026-03-30): o antigo two-pass com early return
        ignorava blocos Python anonimos quando qualquer bloco nomeado (ex: manifest.ini)
        era encontrado antes. O fix usa single-pass com grupo de filename opcional.
        Caso real: assembly LLM gerava ```ini:manifest.ini + ```python (sem nome).
        """
        texto = (
            "Aqui o manifest:\n\n"
            "```ini:manifest.ini\nname = BlindTranscriber\nversion = 1.0.0\n```\n\n"
            "E o codigo:\n\n"
            "```python\nclass GlobalPlugin: pass\n```"
        )
        blocks = extract_code_blocks(texto)
        fnames = [b["filename"] for b in blocks]
        assert len(blocks) == 2, (
            f"ESTRUTURA-004: esperava 2 blocos (manifest + python), got {len(blocks)}: {fnames}"
        )
        assert "manifest.ini" in fnames, "manifest.ini nao extraido"
        assert any(".py" in f for f in fnames), "Bloco Python nao extraido"

    def test_misto_nomeado_e_anonimo_colecionados(self):
        """Blocos nomeados e anonimos na mesma resposta devem ser todos coletados."""
        texto = (
            "```python:globalPlugins/X/__init__.py\nclass GlobalPlugin: pass\n```\n"
            "```ini:manifest.ini\nname=X\n```\n"
            "```html\n<html><body>Docs</body></html>\n```"
        )
        blocks = extract_code_blocks(texto)
        fnames = [b["filename"] for b in blocks]
        assert len(blocks) == 3, f"Esperava 3 blocos, got {len(blocks)}: {fnames}"
        assert "globalPlugins/X/__init__.py" in fnames
        assert "manifest.ini" in fnames
        assert any(".html" in f for f in fnames)


class TestSaveAddonFiles:
    # v1.0.1: save_addon_files preserva estrutura de diretorios.
    # manifest.ini vai para raiz. Python files vao para globalPlugins/<addon_name>/.

    def test_salva_arquivos_corretamente(self, ai_response_with_code_blocks):
        blocks = extract_code_blocks(ai_response_with_code_blocks)
        with tempfile.TemporaryDirectory() as tmpdir:
            folder, saved = save_addon_files(blocks, tmpdir, "testAddon", garantir_doc=False)
            assert os.path.isdir(folder)
            assert len(saved) == len(blocks)
            for path in saved:
                assert os.path.isfile(path)

    def test_blocos_vazios_levanta_erro(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(AddonBuilderError):
                save_addon_files([], tmpdir, "testAddon")

    def test_nome_addon_sanitizado_no_path(self, ai_response_with_code_blocks):
        blocks = extract_code_blocks(ai_response_with_code_blocks)
        with tempfile.TemporaryDirectory() as tmpdir:
            folder, _ = save_addon_files(blocks, tmpdir, "meu addon invalido/nome")
            assert "/" not in os.path.basename(folder)
            assert "\\" not in os.path.basename(folder)

    def test_sem_path_traversal_no_filename(self):
        # Regra 9: garantia contra path traversal em nomes de arquivo da IA.
        blocks = [{"filename": "../../etc/passwd", "code": "conteudo", "language": "python"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            folder, saved = save_addon_files(blocks, tmpdir, "safe")
            for path in saved:
                assert path.startswith(folder)

    def test_manifest_ini_salvo_na_raiz(self):
        # garantir_doc=False: este teste verifica ONDE o manifest cai, nao a
        # rede de doc (addon_builder 4.22.0), que somaria 2 arquivos.
        # manifest.ini deve ficar na raiz do addon_folder, nao em subpasta.
        blocks = [{"filename": "manifest.ini", "code": "name=x\n", "language": "ini"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            folder, saved = save_addon_files(blocks, tmpdir, "testAddon", garantir_doc=False)
            assert len(saved) == 1
            expected = os.path.join(folder, "manifest.ini")
            assert saved[0] == expected, (
                f"manifest.ini deveria estar em {expected}, mas esta em {saved[0]}"
            )

    def test_python_sem_path_vai_para_globalplugins(self):
        # Arquivo .py sem path vai para globalPlugins/<addon_name>/.
        # v4.1.0+: manifest.ini minimo deterministico e gerado quando ausente.
        blocks = [{"filename": "__init__.py", "code": "import globalPluginHandler\n", "language": "python"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            folder, saved = save_addon_files(blocks, tmpdir, "meuAddon", garantir_doc=False)
            assert len(saved) >= 1  # pelo menos o __init__.py + possivel manifest fallback
            assert "globalPlugins" in saved[-1]  # ultimo salvo e o plugin dir

    def test_python_com_path_preserva_estrutura(self):
        # Arquivo com path globalPlugins/nomeAddon/__init__.py preserva estrutura.
        # v4.1.0+: manifest.ini minimo deterministico e gerado quando ausente.
        blocks = [{
            "filename": "globalPlugins/testeAddon/__init__.py",
            "code": "import globalPluginHandler\n",
            "language": "python"
        }]
        with tempfile.TemporaryDirectory() as tmpdir:
            folder, saved = save_addon_files(blocks, tmpdir, "testeAddon")
            assert len(saved) >= 1
            normalized = " ".join(s.replace("\\", "/") for s in saved)
            assert "globalPlugins/testeAddon/__init__.py" in normalized


class TestAutoFixMissingInitFromModuleFallback:
    """
    addon_builder.py 4.11.0: regressao para bug real achado ao vivo
    (test_e36, AssistenteLeituraGemini, 2026-08-17) -- um step de
    code_generation gerou um bloco sem `class GlobalPlugin` reconhecivel,
    _infer_python_filename() caiu no fallback module_1.py, e o addon final
    saiu sem __init__.py (ESTRUTURA-008, NVDA nunca carrega). save_addon_files()
    agora corrige isso deterministicamente quando o caso e inequivoco.
    """

    def test_cria_init_a_partir_de_module_1_quando_unico_candidato(self):
        blocks = [{"filename": "module_1.py", "code": "import ui\nui.message('ok')\n", "language": "python"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            folder, saved = save_addon_files(blocks, tmpdir, "testeAddon")
            init_path = os.path.join(folder, "globalPlugins", "testeAddon", "__init__.py")
            assert os.path.isfile(init_path), "__init__.py deveria ter sido criado deterministicamente"
            with open(init_path, encoding="utf-8") as fh:
                content = fh.read()
            assert "from .module_1 import *" in content

    def test_nao_mexe_quando_ja_existe_init(self):
        blocks = [
            {"filename": "__init__.py", "code": "class GlobalPlugin:\n\tpass\n", "language": "python"},
            {"filename": "module_1.py", "code": "x = 1\n", "language": "python"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            folder, saved = save_addon_files(blocks, tmpdir, "testeAddon")
            init_path = os.path.join(folder, "globalPlugins", "testeAddon", "__init__.py")
            with open(init_path, encoding="utf-8") as fh:
                content = fh.read()
            assert "class GlobalPlugin" in content
            assert "from .module_1 import *" not in content

    def test_nao_cria_quando_ha_class_globalplugin_em_outro_arquivo(self):
        """Se algum .py da pasta ja tem class GlobalPlugin (com nome de
        arquivo diferente do padrao __init__.py, ex: erro de anotacao),
        nao deve criar um __init__.py sinteticamente por cima -- o caso
        nao e inequivoco o suficiente pra correcao automatica."""
        blocks = [
            {"filename": "plugin_principal.py", "code": "class GlobalPlugin:\n\tpass\n", "language": "python"},
            {"filename": "module_1.py", "code": "x = 1\n", "language": "python"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            folder, saved = save_addon_files(blocks, tmpdir, "testeAddon")
            init_path = os.path.join(folder, "globalPlugins", "testeAddon", "__init__.py")
            assert not os.path.isfile(init_path)

    def test_nao_cria_quando_ha_multiplos_module_n(self):
        """Ambiguidade real (2+ module_N.py, nenhum GlobalPlugin) -- fica
        pro round-trip de LLM (_auto_fix_structural_issues) resolver, nao
        pra correcao deterministica (nao ha candidato claro)."""
        blocks = [
            {"filename": "module_1.py", "code": "x = 1\n", "language": "python"},
            {"filename": "module_2.py", "code": "y = 2\n", "language": "python"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            folder, saved = save_addon_files(blocks, tmpdir, "testeAddon")
            init_path = os.path.join(folder, "globalPlugins", "testeAddon", "__init__.py")
            assert not os.path.isfile(init_path)

    def test_nao_afeta_subpacotes_sem_module_n(self):
        """Subpacotes legitimos (settings_panel.py sozinho, sem module_N.py)
        nao devem disparar a correcao -- so o padrao especifico module_N.py
        e reconhecido como candidato."""
        blocks = [
            {"filename": "__init__.py", "code": "class GlobalPlugin:\n\tpass\n", "language": "python"},
            {"filename": "settings_panel.py", "code": "class SettingsPanel:\n\tpass\n", "language": "python"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            folder, saved = save_addon_files(blocks, tmpdir, "testeAddon")
            problems = validate_addon_structure(folder)
            assert not any("ESTRUTURA-008" in p for p in problems)


class TestPackageAddon:
    # v1.0.1: arcname usa addon_folder como base -- sem prefixo de pasta no ZIP.
    # Estrutura correta: manifest.ini e globalPlugins/ na raiz do ZIP (exigido pelo NVDA).

    def test_gera_arquivo_nvda_addon(self, ai_response_with_code_blocks):
        blocks = extract_code_blocks(ai_response_with_code_blocks)
        with tempfile.TemporaryDirectory() as tmpdir:
            folder, _ = save_addon_files(blocks, tmpdir, "pkgTest")
            zip_path = package_addon(folder)
            assert zip_path.endswith(".nvda-addon")
            assert os.path.isfile(zip_path)

    def test_arquivo_e_zip_valido(self, ai_response_with_code_blocks):
        blocks = extract_code_blocks(ai_response_with_code_blocks)
        with tempfile.TemporaryDirectory() as tmpdir:
            folder, _ = save_addon_files(blocks, tmpdir, "pkgTest2")
            zip_path = package_addon(folder)
            assert zipfile.is_zipfile(zip_path)

    def test_zip_contem_arquivos_gerados(self, ai_response_with_code_blocks):
        blocks = extract_code_blocks(ai_response_with_code_blocks)
        with tempfile.TemporaryDirectory() as tmpdir:
            folder, _ = save_addon_files(blocks, tmpdir, "pkgTest3")
            zip_path = package_addon(folder)
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
            assert len(names) >= len(blocks)

    def test_pasta_inexistente_levanta_erro(self):
        with pytest.raises(AddonBuilderError):
            package_addon("/caminho/que/nao/existe")

    def test_manifest_ini_na_raiz_do_zip(self):
        # manifest.ini deve estar na raiz do ZIP, nao em subpasta.
        # Estrutura exigida pelo NVDA: manifest.ini (raiz) + globalPlugins/...
        blocks = [
            {
                "filename": "manifest.ini",
                "code": "name=nvdatest\nversion=1.0.0\nminimumNVDAVersion=2026.1.1\nlastTestedNVDAVersion=2026.1.1\nsummary=test\n",
                "language": "ini"
            },
            {
                "filename": "globalPlugins/nvdatest/__init__.py",
                "code": "import globalPluginHandler\nclass GlobalPlugin(globalPluginHandler.GlobalPlugin):\n    pass\n",
                "language": "python"
            },
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            folder, _ = save_addon_files(blocks, tmpdir, "nvdatest")
            zip_path = package_addon(folder)
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
        # manifest.ini deve estar na raiz (sem prefixo de pasta)
        assert "manifest.ini" in names, (
            f"manifest.ini ausente na raiz do ZIP. Conteudo: {names}"
        )

    def test_globalplugins_na_raiz_do_zip(self):
        # globalPlugins/ deve estar na raiz do ZIP, nao em subpasta tipo pkgTest4_xxx/globalPlugins/.
        blocks = [
            {"filename": "manifest.ini", "code": "name=x\n", "language": "ini"},
            {"filename": "globalPlugins/myAddon/__init__.py", "code": "pass\n", "language": "python"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            folder, _ = save_addon_files(blocks, tmpdir, "myAddon")
            zip_path = package_addon(folder)
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
        # Nenhum arcname deve comecar com o nome da pasta timestampada
        raiz_validas = (
            "manifest.ini", "globalPlugins", "appModules",
            "synthDrivers", "brailleDisplayDrivers", "locale",
            "doc", "readme.html",
        )
        for name in names:
            parts = name.replace("\\", "/").split("/")
            assert parts[0] in raiz_validas, (
                f"Arcname '{name}' tem prefixo invalido '{parts[0]}' na raiz do ZIP"
            )

    def test_nao_empacota_testes_prompts_caches_ou_pacote_intermediario(self, tmp_path):
        (tmp_path / "manifest.ini").write_text("name = x\n", encoding="utf-8")
        plugin = tmp_path / "globalPlugins" / "x"
        plugin.mkdir(parents=True)
        (plugin / "__init__.py").write_text("pass\n", encoding="utf-8")
        (tmp_path / "prompt.txt").write_text("instrucao privada", encoding="utf-8")
        (tmp_path / "system-prompt.txt").write_text("regras privadas", encoding="utf-8")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("assert True\n", encoding="utf-8")
        (tmp_path / "test_ami.py").write_text("assert True\n", encoding="utf-8")
        (tmp_path / "e2e_tests").mkdir()
        (tmp_path / "e2e_tests" / "scenario.py").write_text("assert True\n", encoding="utf-8")
        (tmp_path / ".pytest_cache").mkdir()
        (tmp_path / ".pytest_cache" / "README.md").write_text("cache", encoding="utf-8")
        (plugin / "__pycache__").mkdir()
        (plugin / "__pycache__" / "x.pyc").write_bytes(b"cache")
        (tmp_path / "old.nvda-addon").write_bytes(b"old")

        package = package_addon(str(tmp_path), str(tmp_path.parent / "x.nvda-addon"))

        with zipfile.ZipFile(package) as archive:
            names = archive.namelist()
        assert "manifest.ini" in names
        assert "globalPlugins/x/__init__.py" in names
        assert not any(name.startswith("tests/") for name in names)
        assert not any(name.startswith("e2e_tests/") for name in names)
        assert not any(name.startswith(".pytest_cache/") for name in names)
        assert not any("__pycache__" in name for name in names)
        assert "prompt.txt" not in names
        assert "system-prompt.txt" not in names
        assert "old.nvda-addon" not in names
        assert "test_ami.py" not in names

    def test_empacotamento_sanitiza_manifesto_vindo_de_artifact_dir(self, tmp_path):
        """Regressao: artifact_dir pulava save_addon_files e o NVDA rejeitava
        description com virgulas como uma lista ConfigObj."""
        (tmp_path / "manifest.ini").write_text(
            "name = x\nsummary = X\nauthor = Tester\nversion = 1.0.0\n"
            "description = Audio, video, imagem e PDF\n"
            "minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.2.0\n",
            encoding="utf-8",
        )
        plugin = tmp_path / "globalPlugins" / "x"
        plugin.mkdir(parents=True)
        (plugin / "__init__.py").write_text("pass\n", encoding="utf-8")

        package = package_addon(str(tmp_path), str(tmp_path.parent / "x.nvda-addon"))

        with zipfile.ZipFile(package) as archive:
            manifest = archive.read("manifest.ini").decode("utf-8")
        assert 'description = "Audio, video, imagem e PDF"' in manifest
        assert _manifest_scalar_errors(manifest) == []


def test_validador_detecta_string_configobj_convertida_em_lista(tmp_path):
    (tmp_path / "manifest.ini").write_text(
        "name = x\nsummary = X\nauthor = Tester\nversion = 1.0.0\n"
        "description = Audio, video, imagem e PDF\n"
        "minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.2.0\n",
        encoding="utf-8",
    )
    problems = validate_addon_structure(str(tmp_path))
    assert any("MANIFEST-001" in problem for problem in problems)


def test_save_addon_files_descarta_teste_na_raiz(tmp_path):
    blocks = [
        {"filename": "test_ami.py", "language": "python", "code": "assert True\n"},
        {"filename": "globalPlugins/x/__init__.py", "language": "python", "code": "pass\n"},
    ]
    _, saved = save_addon_files(blocks, str(tmp_path), "x", garantir_doc=False)
    assert not any(os.path.basename(path) == "test_ami.py" for path in saved)


def test_structured_artifacts_do_not_turn_documentation_fences_into_modules(tmp_path):
    """Regressao da sessao 83: exemplo no readme virava module_1.py."""
    (tmp_path / "manifest.ini").write_text("name = X\n", encoding="utf-8")
    plugin = tmp_path / "globalPlugins" / "X"
    plugin.mkdir(parents=True)
    (plugin / "__init__.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "readme.html").write_text(
        "<pre>```python\nprint('exemplo')\n```</pre>", encoding="utf-8",
    )
    cache = tmp_path / ".pytest_cache"
    cache.mkdir()
    (cache / "README.md").write_text("cache", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text("assert True\n", encoding="utf-8")

    blocks = load_artifact_blocks(str(tmp_path), [
        "manifest.ini", "globalPlugins/X/__init__.py", "readme.html",
        ".pytest_cache/README.md", "tests/test_x.py",
    ])

    assert [block["filename"] for block in blocks] == [
        "manifest.ini", "globalPlugins/X/__init__.py", "readme.html",
    ]
    assert not any(block["filename"].startswith("module_") for block in blocks)


# -----------------------------------------------------------------------
# bundle_addon_dependencies
# -----------------------------------------------------------------------

class TestBundleAddonDependencies:

    def test_sem_pacotes_retorna_lista_vazia(self, tmp_path):
        from nvdastudio.builder.addon_builder import bundle_addon_dependencies
        result = bundle_addon_dependencies(str(tmp_path), [], "meuAddon")
        assert result == []

    def test_lista_vazia_nao_chama_pip(self, tmp_path):
        from nvdastudio.builder.addon_builder import bundle_addon_dependencies
        from unittest.mock import patch
        with patch("subprocess.run") as mock_run:
            bundle_addon_dependencies(str(tmp_path), [], "meuAddon")
            mock_run.assert_not_called()

    def test_pip_alvo_e_runtime_nvda_2026(self, tmp_path):
        from nvdastudio.builder.addon_builder import bundle_addon_dependencies
        from unittest.mock import patch, MagicMock
        ok = MagicMock(returncode=0, stderr="")
        with patch("nvdastudio.builder.addon_builder._resolve_pip_names", return_value={"requests": "requests"}), \
             patch("subprocess.run", return_value=ok) as mock_run:
            bundle_addon_dependencies(
                str(tmp_path), ["requests"], "meuAddon",
                _pypi_checker=lambda _pkg: True,
            )
        command = mock_run.call_args.args[0]
        assert command[command.index("--platform") + 1] == "win_amd64"
        assert command[command.index("--python-version") + 1] == "313"
        assert command[command.index("--abi") + 1] == "cp313"

    def test_retorna_apenas_instalados_com_sucesso(self, tmp_path):
        from nvdastudio.builder.addon_builder import bundle_addon_dependencies
        from unittest.mock import patch, MagicMock
        ok = MagicMock()
        ok.returncode = 0
        fail = MagicMock()
        fail.returncode = 1
        fail.stderr = "erro"
        mock_llm = MagicMock()
        mock_llm_resp = MagicMock()
        mock_llm_resp.content = '{"resolved": {"pacote-ok": "pacote-ok", "pacote-fail": "pacote-fail"}}'
        mock_llm.chat.return_value = mock_llm_resp
        # 3 chamadas: ok (32-bit pacote-ok), fail (32-bit pacote-fail),
        # fail (default fallback pacote-fail, pois 32-bit falhou).
        with patch("nvdastudio.builder.addon_builder.create_llm_client", return_value=mock_llm), \
             patch("subprocess.run", side_effect=[ok, fail, fail]):
            result = bundle_addon_dependencies(
                str(tmp_path), ["pacote-ok", "pacote-fail"], "meuAddon",
                _pypi_checker=lambda p: True,  # evita chamada real ao PyPI nos testes
            )
        # Achado de auditoria 2026-08-04: o teste chamava a funcao mas nunca
        # verificava o retorno -- passaria identico se a funcao devolvesse
        # [], None ou os 2 pacotes. O nome do teste ("retorna apenas
        # instalados com sucesso") promete verificar exatamente isso.
        assert result == ["pacote-ok"], (
            f"Esperado so 'pacote-ok' (unico que teve subprocess.run com "
            f"returncode=0), recebido: {result}"
        )

    def test_webbrowser_stdlib_nao_vai_ao_pip(self, tmp_path):
        """webbrowser e stdlib — bundle deve ignorar sem chamar pip (v3.2.0)."""
        from nvdastudio.builder.addon_builder import bundle_addon_dependencies
        from unittest.mock import patch
        with patch("subprocess.run") as mock_run:
            result = bundle_addon_dependencies(
                str(tmp_path), ["webbrowser", "email", "html", "platform"], "meuAddon"
            )
        mock_run.assert_not_called()
        assert result == []

    def test_nvdahelper_nvda_nao_vai_ao_pip(self, tmp_path):
        """nvdaHelper e NVDAHelper sao modulos NVDA internos — bundle ignora (v3.2.0)."""
        from nvdastudio.builder.addon_builder import bundle_addon_dependencies
        from unittest.mock import patch
        with patch("subprocess.run") as mock_run:
            result = bundle_addon_dependencies(
                str(tmp_path), ["nvdaHelper", "NVDAHelper"], "meuAddon"
            )
        mock_run.assert_not_called()
        assert result == []

    def test_submodule_path_normalizado_antes_do_pip(self, tmp_path):
        """google_auth_oauthlib.flow deve ser normalizado e LLM retorna nome pip correto."""
        from nvdastudio.builder.addon_builder import bundle_addon_dependencies
        from unittest.mock import patch, MagicMock
        ok = MagicMock()
        ok.returncode = 0
        fake_resp = MagicMock()
        fake_resp.content = (
            '{"resolved": {"google_auth_oauthlib": "google-auth-oauthlib",'
            ' "googleapiclient": "google-api-python-client"}}'
        )
        fake_client = MagicMock()
        fake_client.chat.return_value = fake_resp
        with patch("subprocess.run", return_value=ok) as mock_run:
            with patch("nvdastudio.builder.addon_builder.create_llm_client", return_value=fake_client):
                bundle_addon_dependencies(
                    str(tmp_path),
                    ["google_auth_oauthlib.flow", "googleapiclient.discovery"],
                    "meuAddon",
                    _pypi_checker=lambda p: True,  # evita chamada real ao PyPI nos testes
                )
        # pip deve ter sido chamado com os nomes pip corretos, nunca com ".flow" ou ".discovery"
        assert mock_run.call_count >= 1
        all_cmd_args = " ".join(str(a) for call in mock_run.call_args_list for a in call[0][0])
        assert ".flow" not in all_cmd_args, "submodule '.flow' nao deve chegar ao pip"
        assert ".discovery" not in all_cmd_args, "submodule '.discovery' nao deve chegar ao pip"
        assert "google-auth-oauthlib" in all_cmd_args
        assert "google-api-python-client" in all_cmd_args


class TestNameFromManifestBlocks:
    """Testes de name_from_manifest_blocks() — v2.1.0."""

    def test_extrai_nome_simples(self):
        blocks = [{"filename": "manifest.ini", "code": "name = TranscricaoMultimidia\n"}]
        assert name_from_manifest_blocks(blocks) == "TranscricaoMultimidia"

    def test_extrai_nome_com_espaco(self):
        blocks = [{"filename": "manifest.ini", "code": "name = Meu Addon Legal\n"}]
        assert name_from_manifest_blocks(blocks) == "Meu_Addon_Legal"

    def test_extrai_nome_com_aspas(self):
        blocks = [{"filename": "manifest.ini", "code": 'name = "TranscricaoMultimidia"\n'}]
        assert name_from_manifest_blocks(blocks) == "TranscricaoMultimidia"

    def test_extrai_nome_com_caminho_longo(self):
        """Bloco com filename dentro de subpasta tambem deve ser detectado."""
        blocks = [{"filename": "addon/manifest.ini", "code": "name = MinhaFerramentaX\n"}]
        assert name_from_manifest_blocks(blocks) == "MinhaFerramentaX"

    def test_sem_manifest_retorna_string_vazia(self):
        blocks = [{"filename": "globalPlugins/meu/__init__.py", "code": "# code"}]
        assert name_from_manifest_blocks(blocks) == ""

    def test_manifest_sem_campo_name_retorna_string_vazia(self):
        blocks = [{"filename": "manifest.ini", "code": "summary = Algo\nversion = 1.0\n"}]
        assert name_from_manifest_blocks(blocks) == ""

    def test_blocks_vazios_retorna_string_vazia(self):
        assert name_from_manifest_blocks([]) == ""

    def test_nome_com_hifen_preservado(self):
        blocks = [{"filename": "manifest.ini", "code": "name = meu-addon-legal\n"}]
        assert name_from_manifest_blocks(blocks) == "meu-addon-legal"


class TestSaveAddonFilesTestsFilter:
    """Garante que blocos tests/ nunca sao salvos dentro do addon — v2.1.0."""

    def test_bloco_tests_excluido(self, tmp_path):
        """Arquivo tests/test_algo.py nao deve ser salvo na pasta do addon."""
        blocks = [
            {"filename": "globalPlugins/meu/__init__.py", "language": "python", "code": "# ok"},
            {"filename": "tests/test_meu.py", "language": "python", "code": "# teste"},
        ]
        addon_dir = str(tmp_path)
        _, saved_files = save_addon_files(blocks, addon_dir, "meuAddon")
        # Apenas 1 arquivo deve ser salvo (tests/ excluido)
        assert len(saved_files) >= 1, f"Esperado ao menos 1 arquivo, obteve {len(saved_files)}: {saved_files}"
        # O arquivo salvo deve ser o globalPlugins, nao o de testes
        assert all("test_meu.py" not in p for p in saved_files), f"test_meu.py nao devia ser salvo: {saved_files}"

    def test_bloco_tests_barra_invertida_excluido(self, tmp_path):
        """Garante que tests\\ (Windows) tambem e filtrado corretamente."""
        blocks = [
            {"filename": "globalPlugins/meu/__init__.py", "language": "python", "code": "# ok"},
            {"filename": "tests\\test_meu.py", "language": "python", "code": "# teste"},
        ]
        addon_dir = str(tmp_path)
        _, saved_files = save_addon_files(blocks, addon_dir, "meuAddon")
        assert len(saved_files) >= 1, f"Esperado ao menos 1 arquivo, obteve {len(saved_files)}: {saved_files}"
        assert all("test_meu.py" not in p for p in saved_files), f"test_meu.py nao devia ser salvo: {saved_files}"

    def test_bloco_nao_tests_salvo_normalmente(self, tmp_path):
        """Arquivo normal (globalPlugins/) ainda deve ser salvo."""
        blocks = [
            {"filename": "globalPlugins/meu/__init__.py", "language": "python", "code": "# ok"},
        ]
        addon_dir = str(tmp_path)
        _, saved_files = save_addon_files(blocks, addon_dir, "meuAddon")
        assert len(saved_files) >= 1

    def test_modulo_nvda_ignorado_sem_pip(self, tmp_path):
        """ui, speech, addonHandler etc. nao devem ser passados ao pip (v2.0.0)."""
        from nvdastudio.builder.addon_builder import bundle_addon_dependencies
        from unittest.mock import patch
        with patch("subprocess.run") as mock_run:
            bundle_addon_dependencies(
                str(tmp_path), ["ui", "speech", "addonHandler", "globalPluginHandler"], "meuAddon"
            )
        mock_run.assert_not_called()


class TestValidateAddonStructure:
    """Testes de validate_addon_structure() -- ESTRUTURA-009 (imports relativos)."""

    def _criar_addon(self, tmp_path, arquivos: dict) -> str:
        """Cria estrutura minima de addon em tmp_path. arquivos={relpath: conteudo}."""
        import os
        addon = str(tmp_path / "MeuAddon")
        plugin_dir = os.path.join(addon, "globalPlugins", "MeuAddon")
        os.makedirs(plugin_dir, exist_ok=True)
        # manifest.ini obrigatorio
        with open(os.path.join(addon, "manifest.ini"), "w", encoding="utf-8") as f:
            f.write(
                "name = MeuAddon\n"
                "summary = Addon de teste.\n"
                "version = 1.0.0\n"
                "minimumNVDAVersion = 2026.1.1\n"
                "lastTestedNVDAVersion = 2026.1.1\n"
            )
        # doc/ obrigatorio
        os.makedirs(os.path.join(addon, "doc"), exist_ok=True)
        for relpath, conteudo in arquivos.items():
            dest = os.path.join(plugin_dir, relpath)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w", encoding="utf-8") as f:
                f.write(conteudo)
        return addon

    def test_estrutura_009_modulo_relativo_ausente_detectado(self, tmp_path):
        """ESTRUTURA-009: from .gmail_oauth import ... sem gmail_oauth.py detecta erro."""
        init = (
            "import globalPluginHandler\n"
            "import addonHandler\n"
            "addonHandler.initTranslation()\n"
            "from .gmail_service import GmailService\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        gmail_service = "from .gmail_oauth import get_credentials\n"
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "gmail_service.py": gmail_service,
            # gmail_oauth.py AUSENTE
        })
        problems = validate_addon_structure(addon)
        erros_009 = [p for p in problems if "ESTRUTURA-009" in p]
        assert len(erros_009) >= 1, f"Esperava ESTRUTURA-009, obteve: {problems}"
        assert "gmail_oauth" in erros_009[0]
        assert "gmail_service.py" in erros_009[0]

    def test_estrutura_009_modulo_relativo_presente_sem_erro(self, tmp_path):
        """Nenhum ESTRUTURA-009 quando o modulo importado existe."""
        init = (
            "import globalPluginHandler\n"
            "import addonHandler\n"
            "addonHandler.initTranslation()\n"
            "from .gmail_service import GmailService\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        gmail_service = "from .gmail_oauth import get_credentials\n"
        gmail_oauth = "def get_credentials(): pass\n"
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "gmail_service.py": gmail_service,
            "gmail_oauth.py": gmail_oauth,  # PRESENTE
        })
        problems = validate_addon_structure(addon)
        erros_009 = [p for p in problems if "ESTRUTURA-009" in p]
        assert erros_009 == [], f"ESTRUTURA-009 falso positivo: {erros_009}"

    def test_estrutura_009_imports_absolutos_ignorados(self, tmp_path):
        """Imports absolutos (sem ponto) nao sao checados pela regra 009."""
        init = (
            "import globalPluginHandler\n"
            "import addonHandler\n"
            "addonHandler.initTranslation()\n"
            "import requests\n"
            "import openai\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        addon = self._criar_addon(tmp_path, {"__init__.py": init})
        problems = validate_addon_structure(addon)
        erros_009 = [p for p in problems if "ESTRUTURA-009" in p]
        assert erros_009 == [], "Imports absolutos nao devem gerar ESTRUTURA-009"

    def test_estrutura_009_mensagem_contem_modulo_e_arquivo(self, tmp_path):
        """A mensagem ESTRUTURA-009 indica qual arquivo e qual modulo estao ausentes."""
        code = "from .modulo_inexistente import algo\n"
        addon = self._criar_addon(tmp_path, {
            "__init__.py": (
                "import globalPluginHandler\nimport addonHandler\n"
                "addonHandler.initTranslation()\n"
                "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
                "    def terminate(self): pass\n"
            ),
            "helper.py": code,
        })
        problems = validate_addon_structure(addon)
        erros_009 = [p for p in problems if "ESTRUTURA-009" in p]
        assert any("modulo_inexistente" in e for e in erros_009)
        assert any("helper.py" in e for e in erros_009)


class TestSanitizeManifestCamposProibidos:
    """Testes de remocao de campos proibidos em _sanitize_manifest (v2.7.0)."""

    def test_sha256_removido(self):
        manifest = (
            "name = GmailSummarizer\n"
            "version = 1.1.0\n"
            "sha256 = 4f4e5c434a434b4d4f4e5c434a434b4d\n"
            "minimumNVDAVersion = 2026.1.1\n"
        )
        result = _sanitize_manifest(manifest)
        assert "sha256" not in result, "sha256 deve ser removido do manifest"
        assert "name = GmailSummarizer" in result
        assert "version = 1.1.0" in result

    def test_configspec_removido(self):
        manifest = (
            "name = MeuAddon\n"
            "configSpec = [gmailResumo]\nemail = string(default='')\n"
            "version = 1.0.0\n"
        )
        result = _sanitize_manifest(manifest)
        assert "configSpec" not in result
        assert "configspec" not in result.lower()
        assert "name = MeuAddon" in result

    def test_sha256_case_insensitive_removido(self):
        manifest = "name = X\nSHA256 = abc123\nversion = 1.0.0\n"
        result = _sanitize_manifest(manifest)
        assert "SHA256" not in result

    def test_campos_normais_preservados_com_proibidos_presentes(self):
        manifest = (
            "name = TestAddon\n"
            "summary = Um addon.\n"
            "version = 1.0.0\n"
            "sha256 = deadbeef\n"
            "minimumNVDAVersion = 2026.1.1\n"
        )
        result = _sanitize_manifest(manifest)
        assert "name = TestAddon" in result
        assert "summary" in result
        assert "version = 1.0.0" in result
        assert "sha256" not in result

    def test_modulo_stdlib_ignorado_sem_pip(self, tmp_path):
        """os, sys, threading etc. nao devem ser passados ao pip (v2.0.0)."""
        from nvdastudio.builder.addon_builder import bundle_addon_dependencies
        from unittest.mock import patch
        with patch("subprocess.run") as mock_run:
            result = bundle_addon_dependencies(
                str(tmp_path), ["os", "sys", "threading", "json"], "meuAddon"
            )
        mock_run.assert_not_called()
        assert result == []

    def test_modulo_local_do_addon_ignorado_sem_pip(self, tmp_path):
        """Arquivo .py ja presente no addon nao deve ser passado ao pip (v2.0.0)."""
        from nvdastudio.builder.addon_builder import bundle_addon_dependencies
        from unittest.mock import patch
        # Cria estrutura do addon com um modulo local
        plugin_dir = tmp_path / "globalPlugins" / "meuAddon"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "settings_panel.py").write_text("# modulo local\n")
        (plugin_dir / "transcribe_dialog.py").write_text("# modulo local\n")

        with patch("subprocess.run") as mock_run:
            result = bundle_addon_dependencies(
                str(tmp_path), ["settings_panel", "transcribe_dialog"], "meuAddon"
            )
        mock_run.assert_not_called()
        assert result == []

    def test_pacote_externo_real_passa_para_pip(self, tmp_path):
        """Pacotes reais externos (openai, Pillow) devem chegar ao pip (v2.0.0)."""
        from nvdastudio.builder.addon_builder import bundle_addon_dependencies
        from unittest.mock import patch, MagicMock
        ok = MagicMock()
        ok.returncode = 0
        mock_llm = MagicMock()
        mock_llm_resp = MagicMock()
        mock_llm_resp.content = '{"resolved": {"openai": "openai", "Pillow": "Pillow"}}'
        mock_llm.chat.return_value = mock_llm_resp
        with patch("nvdastudio.builder.addon_builder.create_llm_client", return_value=mock_llm), \
             patch("subprocess.run", return_value=ok) as mock_run:
            bundle_addon_dependencies(
                str(tmp_path), ["openai", "Pillow"], "meuAddon"
            )
        assert mock_run.call_count == 2

    def test_mistura_local_e_externo_so_externo_vai_ao_pip(self, tmp_path):
        """settings_panel (local) e openai (externo): so openai vai ao pip (v2.0.0)."""
        from nvdastudio.builder.addon_builder import bundle_addon_dependencies
        from unittest.mock import patch, MagicMock
        plugin_dir = tmp_path / "globalPlugins" / "meuAddon"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "settings_panel.py").write_text("# modulo local\n")

        ok = MagicMock()
        ok.returncode = 0
        mock_llm = MagicMock()
        mock_llm_resp = MagicMock()
        mock_llm_resp.content = '{"resolved": {"settings_panel": "settings_panel", "openai": "openai"}}'
        mock_llm.chat.return_value = mock_llm_resp
        with patch("nvdastudio.builder.addon_builder.create_llm_client", return_value=mock_llm), \
             patch("subprocess.run", return_value=ok) as mock_run:
            bundle_addon_dependencies(
                str(tmp_path), ["settings_panel", "openai"], "meuAddon"
            )
        assert mock_run.call_count == 1
        # O argumento passado ao pip deve ser openai, nao settings_panel
        call_args = mock_run.call_args[0][0]  # cmd list
        assert "openai" in call_args
        assert "settings_panel" not in call_args


class TestValidateAddonStructureNVDA022:
    """Testes de validate_addon_structure() -- NVDA-022 (imports 3rd party nivel modulo)."""

    def _criar_addon(self, tmp_path, arquivos: dict) -> str:
        import os
        addon = str(tmp_path / "MeuAddon")
        plugin_dir = os.path.join(addon, "globalPlugins", "MeuAddon")
        os.makedirs(plugin_dir, exist_ok=True)
        with open(os.path.join(addon, "manifest.ini"), "w", encoding="utf-8") as f:
            f.write(
                "name = MeuAddon\nsummary = Teste.\nversion = 1.0.0\n"
                "minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.1.1\n"
            )
        os.makedirs(os.path.join(addon, "doc"), exist_ok=True)
        for relpath, conteudo in arquivos.items():
            dest = os.path.join(plugin_dir, relpath)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w", encoding="utf-8") as f:
                f.write(conteudo)
        return addon

    def test_nvda022_import_nivel_modulo_detectado(self, tmp_path):
        """NVDA-022: from googleapiclient.discovery import build no topo detecta erro."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "from .gmail_service import GmailService\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        service = "from googleapiclient.discovery import build\n\nclass GmailService: pass\n"
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "gmail_service.py": service,
        })
        problems = validate_addon_structure(addon)
        erros_022 = [p for p in problems if "NVDA-022" in p]
        assert len(erros_022) >= 1, f"Esperava NVDA-022, obteve: {problems}"
        assert "googleapiclient" in erros_022[0]
        assert "gmail_service.py" in erros_022[0]

    def test_nvda022_lazy_import_dentro_metodo_sem_erro(self, tmp_path):
        """Imports 3rd party dentro de metodos (lazy) nao devem gerar NVDA-022."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "from .gmail_service import GmailService\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        service = (
            "import threading\n"
            "\nclass GmailService:\n"
            "    def _build(self):\n"
            "        from googleapiclient.discovery import build  # lazy\n"
            "        return build('gmail', 'v1')\n"
        )
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "gmail_service.py": service,
        })
        problems = validate_addon_structure(addon)
        erros_022 = [p for p in problems if "NVDA-022" in p]
        assert erros_022 == [], f"NVDA-022 falso positivo com lazy import: {erros_022}"

    def test_nvda022_stdlib_ignorado(self, tmp_path):
        """threading, os, sys, typing em nivel de modulo nao geram NVDA-022."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        service = (
            "import threading\nimport os\nimport sys\n"
            "from typing import List\n\nclass MeuService: pass\n"
        )
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "meu_service.py": service,
        })
        problems = validate_addon_structure(addon)
        erros_022 = [p for p in problems if "NVDA-022" in p]
        assert erros_022 == [], f"stdlib nao deve gerar NVDA-022: {erros_022}"

    def test_nvda022_init_py_excluido_da_verificacao(self, tmp_path):
        """__init__.py nao e verificado pela regra NVDA-022 (importa servicos legalmente)."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "from .gmail_service import GmailService\n"
            "import requests  # no __init__.py (excluido da NVDA-022)\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        service = "class GmailService: pass\n"
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "gmail_service.py": service,
        })
        problems = validate_addon_structure(addon)
        erros_022 = [p for p in problems if "NVDA-022" in p]
        assert erros_022 == [], "__init__.py nao deve gerar NVDA-022"

    def test_nvda022_mensagem_sugere_lazy_import(self, tmp_path):
        """A mensagem NVDA-022 explica como corrigir com lazy import."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        service = "import openai\nclass Sumarizador: pass\n"
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "sumarizador.py": service,
        })
        problems = validate_addon_structure(addon)
        erros_022 = [p for p in problems if "NVDA-022" in p]
        assert len(erros_022) >= 1
        msg = erros_022[0]
        assert "openai" in msg
        assert "sumarizador.py" in msg

    def test_nvda022_nvda_module_camelcase_nao_e_falso_positivo(self, tmp_path):
        """NVDA-022 nao deve disparar para addonHandler, globalPluginHandler (camelCase NVDA)."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        # ai_runner.py com import addonHandler em nivel de modulo — modulo NVDA nativo
        runner = (
            "import addonHandler\n"
            "import globalPluginHandler\n"
            "import scriptHandler\n"
            "class AIRunner: pass\n"
        )
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "ai_runner.py": runner,
        })
        problems = validate_addon_structure(addon)
        erros_022 = [p for p in problems if "NVDA-022" in p]
        assert erros_022 == [], (
            "Modulos NVDA camelCase (addonHandler, etc.) nao devem gerar NVDA-022: "
            + str(erros_022)
        )

    def test_nvda022_nvdahelper_nao_e_falso_positivo(self, tmp_path):
        """NVDA-022: nvdaHelper (extensao C interna do NVDA) nao deve gerar aviso."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        service = (
            "import nvdaHelper\n"
            "from nvdaHelper import nvdaState\n"
            "class NvdaService: pass\n"
        )
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "nvda_service.py": service,
        })
        problems = validate_addon_structure(addon)
        erros_022 = [p for p in problems if "NVDA-022" in p]
        assert erros_022 == [], (
            "nvdaHelper e modulo NVDA interno, nao deve gerar NVDA-022: "
            + str(erros_022)
        )

    def test_nvda022_webbrowser_stdlib_nao_e_falso_positivo(self, tmp_path):
        """NVDA-022: webbrowser (stdlib) em nivel de modulo nao gera aviso."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        service = (
            "import webbrowser\n"
            "import email\n"
            "import html\n"
            "import platform\n"
            "class BrowserService: pass\n"
        )
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "browser_service.py": service,
        })
        problems = validate_addon_structure(addon)
        erros_022 = [p for p in problems if "NVDA-022" in p]
        assert erros_022 == [], (
            "Modulos stdlib (webbrowser, email, html, platform) nao devem gerar NVDA-022: "
            + str(erros_022)
        )


class TestValidateAddonStructureNVDA023:
    """Testes de validate_addon_structure() -- NVDA-023 (type annotation com tipo lazy)."""

    def _criar_addon(self, tmp_path, arquivos: dict) -> str:
        import os
        addon = str(tmp_path / "MeuAddon")
        plugin_dir = os.path.join(addon, "globalPlugins", "MeuAddon")
        os.makedirs(plugin_dir, exist_ok=True)
        with open(os.path.join(addon, "manifest.ini"), "w", encoding="utf-8") as f:
            f.write(
                "name = MeuAddon\nsummary = Teste.\nversion = 1.0.0\n"
                "minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.1.1\n"
            )
        os.makedirs(os.path.join(addon, "doc"), exist_ok=True)
        for relpath, conteudo in arquivos.items():
            dest = os.path.join(plugin_dir, relpath)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w", encoding="utf-8") as f:
                f.write(conteudo)
        return addon

    def test_nvda023_bare_annotation_de_tipo_lazy_detectado(self, tmp_path):
        """NVDA-023: -> Credentials com Credentials apenas em import lazy gera erro."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "from .oauth import get_credentials\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        oauth = (
            "import os\n"
            "from typing import Optional\n"
            "\n"
            "def get_credentials() -> Credentials:\n"  # bare annotation — tipo nao importado a nivel de modulo
            "    from google.oauth2.credentials import Credentials  # lazy\n"
            "    return Credentials()\n"
        )
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "oauth.py": oauth,
        })
        problems = validate_addon_structure(addon)
        erros_023 = [p for p in problems if "NVDA-023" in p]
        assert len(erros_023) >= 1, f"Esperava NVDA-023, obteve: {problems}"
        assert "Credentials" in erros_023[0]
        assert "oauth.py" in erros_023[0]

    def test_nvda023_string_literal_annotation_sem_erro(self, tmp_path):
        """String literal -> 'Credentials' (forward reference) nao deve gerar NVDA-023."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "from .oauth import get_credentials\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        oauth = (
            "import os\n"
            "\n"
            "def get_credentials() -> 'Credentials':\n"  # string literal — correto (NVDA-023)
            "    from google.oauth2.credentials import Credentials  # lazy\n"
            "    return Credentials()\n"
        )
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "oauth.py": oauth,
        })
        problems = validate_addon_structure(addon)
        erros_023 = [p for p in problems if "NVDA-023" in p]
        assert erros_023 == [], f"String literal nao deve gerar NVDA-023: {erros_023}"

    def test_nvda023_tipo_importado_a_nivel_de_modulo_sem_erro(self, tmp_path):
        """Quando o tipo e importado a nivel de modulo, annotation direta e valida."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "from .service import transcrever\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        service = (
            "from typing import Optional\n"
            "\n"
            "def transcrever(texto: Optional[str]) -> str:\n"  # Optional importado no modulo
            "    return texto or ''\n"
        )
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "service.py": service,
        })
        problems = validate_addon_structure(addon)
        erros_023 = [p for p in problems if "NVDA-023" in p]
        assert erros_023 == [], f"Tipo no modulo nao deve gerar NVDA-023: {erros_023}"

    def test_nvda023_sem_annotation_de_retorno_sem_erro(self, tmp_path):
        """Funcao sem annotation de retorno nao deve gerar NVDA-023."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "from .oauth import get_credentials\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        oauth = (
            "import os\n"
            "\n"
            "def get_credentials():\n"  # sem annotation — igualmente valido
            "    from google.oauth2.credentials import Credentials  # lazy\n"
            "    return Credentials()\n"
        )
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "oauth.py": oauth,
        })
        problems = validate_addon_structure(addon)
        erros_023 = [p for p in problems if "NVDA-023" in p]
        assert erros_023 == [], f"Sem annotation nao deve gerar NVDA-023: {erros_023}"


class TestImportToPip:
    """Testes de _resolve_pip_names — resolucao semantica via LLM (v3.5.0)."""

    def test_resolve_sem_api_key_passthrough(self):
        """Quando LLM falha, todos os nomes sao retornados como estao (passthrough)."""
        from nvdastudio.builder.addon_builder import _resolve_pip_names
        from unittest.mock import patch
        names = ["googleapiclient", "bs4", "requests", "google_auth_oauthlib"]
        with patch("nvdastudio.builder.addon_builder.create_llm_client", side_effect=Exception("sem credencial")):
            result = _resolve_pip_names(names)
        for name in names:
            assert result[name] == name

    def test_resolve_com_llm_traduz_nomes(self):
        """Com api_key, LLM e chamado e retorna nomes pip corretos."""
        from nvdastudio.builder.addon_builder import _resolve_pip_names
        from unittest.mock import patch, MagicMock

        fake_resp = MagicMock()
        fake_resp.content = (
            '{"resolved": {"googleapiclient": "google-api-python-client",'
            ' "bs4": "beautifulsoup4"}}'
        )
        fake_client = MagicMock()
        fake_client.chat.return_value = fake_resp

        with patch("nvdastudio.builder.addon_builder.create_llm_client", return_value=fake_client):
            result = _resolve_pip_names(["googleapiclient", "bs4"])

        assert result["googleapiclient"] == "google-api-python-client"
        assert result["bs4"] == "beautifulsoup4"
        fake_client.chat.assert_called_once()

    def test_resolve_llm_envia_todos_nomes_juntos(self):
        """LLM recebe todos os nomes em uma unica chamada (nao um por um)."""
        from nvdastudio.builder.addon_builder import _resolve_pip_names
        from unittest.mock import patch, MagicMock

        fake_resp = MagicMock()
        fake_resp.content = '{"resolved": {}}'
        fake_client = MagicMock()
        fake_client.chat.return_value = fake_resp

        with patch("nvdastudio.builder.addon_builder.create_llm_client", return_value=fake_client):
            _resolve_pip_names(["a", "b", "c"])

        assert fake_client.chat.call_count == 1
        prompt_sent = fake_client.chat.call_args[0][0]
        assert '"a"' in prompt_sent
        assert '"b"' in prompt_sent
        assert '"c"' in prompt_sent

    def test_resolve_llm_falha_graceful(self):
        """Se LLM falhar, retorna passthrough sem exception."""
        from nvdastudio.builder.addon_builder import _resolve_pip_names
        from unittest.mock import patch

        with patch("nvdastudio.builder.addon_builder.create_llm_client", side_effect=Exception("rede")):
            result = _resolve_pip_names(["googleapiclient"])

        assert result["googleapiclient"] == "googleapiclient"

    def test_resolve_lista_vazia(self):
        """Lista vazia retorna dict vazio."""
        from nvdastudio.builder.addon_builder import _resolve_pip_names
        assert _resolve_pip_names([]) == {}

    def test_bundle_sempre_usa_llm_para_resolver_nomes(self, tmp_path):
        """bundle_addon_dependencies sempre usa create_llm_client para resolver nomes pip."""
        from nvdastudio.builder.addon_builder import bundle_addon_dependencies
        from unittest.mock import patch, MagicMock

        ok = MagicMock()
        ok.returncode = 0
        fake_resp = MagicMock()
        fake_resp.content = '{"resolved": {"requests": "requests"}}'
        fake_client = MagicMock()
        fake_client.chat.return_value = fake_resp
        with patch("subprocess.run", return_value=ok):
            with patch("nvdastudio.builder.addon_builder.create_llm_client", return_value=fake_client) as mock_llm:
                bundle_addon_dependencies(str(tmp_path), ["requests"], "meuAddon")
        mock_llm.assert_called_once()

    def test_bundle_com_api_key_chama_llm_e_usa_resultado(self, tmp_path):
        """bundle_addon_dependencies com api_key usa o nome pip resolvido pelo LLM."""
        from nvdastudio.builder.addon_builder import bundle_addon_dependencies
        from unittest.mock import patch, MagicMock

        ok = MagicMock()
        ok.returncode = 0

        fake_resp = MagicMock()
        fake_resp.content = '{"resolved": {"googleapiclient": "google-api-python-client"}}'
        fake_client = MagicMock()
        fake_client.chat.return_value = fake_resp

        with patch("subprocess.run", return_value=ok) as mock_run:
            with patch("nvdastudio.builder.addon_builder.create_llm_client", return_value=fake_client):
                bundle_addon_dependencies(
                    str(tmp_path), ["googleapiclient"], "meuAddon"
                )
        call_args = mock_run.call_args[0][0]
        assert "google-api-python-client" in call_args
        assert "googleapiclient" not in call_args

    def test_bundle_google_auth_oauthlib_submodulo_via_llm(self, tmp_path):
        """bundle normaliza 'google_auth_oauthlib.flow' -> root -> LLM retorna nome pip."""
        from nvdastudio.builder.addon_builder import bundle_addon_dependencies
        from unittest.mock import patch, MagicMock

        ok = MagicMock()
        ok.returncode = 0

        fake_resp = MagicMock()
        fake_resp.content = '{"resolved": {"google_auth_oauthlib": "google-auth-oauthlib"}}'
        fake_client = MagicMock()
        fake_client.chat.return_value = fake_resp

        with patch("subprocess.run", return_value=ok) as mock_run:
            with patch("nvdastudio.builder.addon_builder.create_llm_client", return_value=fake_client):
                bundle_addon_dependencies(
                    str(tmp_path), ["google_auth_oauthlib.flow"], "meuAddon",
                )
        call_args = mock_run.call_args[0][0]
        assert "google-auth-oauthlib" in call_args
        assert "flow" not in call_args


class TestValidateAddonStructureNVDA024:
    """NVDA-024: categoryClasses.append() sem guard causa painel duplicado."""

    def _criar_addon(self, tmp_path, files: dict) -> str:
        """Helper: cria estrutura minima de addon em tmp_path."""
        plugin_dir = tmp_path / "globalPlugins" / "meuAddon"
        plugin_dir.mkdir(parents=True)
        manifest = tmp_path / "manifest.ini"
        manifest.write_text(
            "[add-on]\naddonId=meuAddon\naddonSummary=Teste\naddonVersion=1.0.0\n"
            "addonAuthor=Teste\nminimumNVDAVersion=2023.1\nlastTestedNVDAVersion=2025.3\n"
        )
        for name, content in files.items():
            (plugin_dir / name).write_text(content)
        return str(tmp_path)

    def test_nvda024_append_sem_guard_detectado(self, tmp_path):
        """append() incondicional em categoryClasses deve gerar NVDA-024."""
        init = (
            "import globalPluginHandler, addonHandler, gui\n"
            "from gui.settingsDialogs import NVDASettingsDialog\n"
            "from .panel import MeuPanel\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def __init__(self, *args, **kwargs):\n"
            "        super().__init__(*args, **kwargs)\n"
            "        NVDASettingsDialog.categoryClasses.append(MeuPanel)\n"
            "    def terminate(self):\n"
            "        super().terminate()\n"
            "        if MeuPanel in NVDASettingsDialog.categoryClasses:\n"
            "            NVDASettingsDialog.categoryClasses.remove(MeuPanel)\n"
        )
        addon = self._criar_addon(tmp_path, {"__init__.py": init})
        problems = validate_addon_structure(addon)
        erros_024 = [p for p in problems if "NVDA-024" in p]
        assert len(erros_024) >= 1, f"Esperava NVDA-024 mas nao encontrou: {problems}"
        assert "MeuPanel" in erros_024[0]

    def test_nvda024_append_com_guard_sem_erro(self, tmp_path):
        """append() com guard 'if Panel not in' nao deve gerar NVDA-024."""
        init = (
            "import globalPluginHandler, addonHandler, gui\n"
            "from gui.settingsDialogs import NVDASettingsDialog\n"
            "from .panel import MeuPanel\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def __init__(self, *args, **kwargs):\n"
            "        super().__init__(*args, **kwargs)\n"
            "        if MeuPanel not in NVDASettingsDialog.categoryClasses:\n"
            "            NVDASettingsDialog.categoryClasses.append(MeuPanel)\n"
            "    def terminate(self):\n"
            "        super().terminate()\n"
            "        if MeuPanel in NVDASettingsDialog.categoryClasses:\n"
            "            NVDASettingsDialog.categoryClasses.remove(MeuPanel)\n"
        )
        addon = self._criar_addon(tmp_path, {"__init__.py": init})
        problems = validate_addon_structure(addon)
        erros_024 = [p for p in problems if "NVDA-024" in p]
        assert erros_024 == [], f"Guard correto nao deve gerar NVDA-024: {erros_024}"

    def test_nvda024_sem_settings_panel_sem_erro(self, tmp_path):
        """Addon sem settings panel nao deve gerar NVDA-024."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        addon = self._criar_addon(tmp_path, {"__init__.py": init})
        problems = validate_addon_structure(addon)
        erros_024 = [p for p in problems if "NVDA-024" in p]
        assert erros_024 == [], f"Sem panel nao deve gerar NVDA-024: {erros_024}"


class TestValidateAddonStructureNVDA025:
    """NVDA-025: config.conf com secao generica causa colisao entre addons."""

    def _criar_addon(self, tmp_path, py_files: dict, addon_id: str = "MeuAddonReal") -> str:
        """Helper: cria addon com manifest.ini contendo addonId especifico."""
        plugin_dir = tmp_path / "globalPlugins" / addon_id
        plugin_dir.mkdir(parents=True)
        manifest = tmp_path / "manifest.ini"
        manifest.write_text(
            f"[add-on]\naddonId={addon_id}\naddonSummary=Teste\naddonVersion=1.0.0\n"
            "addonAuthor=Teste\nminimumNVDAVersion=2023.1\nlastTestedNVDAVersion=2025.3\n"
        )
        for name, content in py_files.items():
            (plugin_dir / name).write_text(content)
        return str(tmp_path)

    def test_nvda025_placeholder_meuaddon_detectado(self, tmp_path):
        """config.conf['meuAddon'] deve gerar NVDA-025."""
        init = (
            "import globalPluginHandler, addonHandler, config\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        panel = (
            "import wx, config\n"
            "from gui.settingsDialogs import SettingsPanel\n"
            "class TestPanel(SettingsPanel):\n"
            "    title = 'Teste'\n"
            "    def makeSettings(self, sizer):\n"
            "        self._v = config.conf['meuAddon'].get('key', '')\n"
            "    def onSave(self):\n"
            "        config.conf['meuAddon']['key'] = ''\n"
        )
        addon = self._criar_addon(tmp_path, {"__init__.py": init, "panel.py": panel})
        problems = validate_addon_structure(addon)
        erros_025 = [p for p in problems if "NVDA-025" in p]
        assert len(erros_025) >= 1, f"Esperava NVDA-025 para placeholder 'meuAddon': {problems}"
        assert "meuAddon" in erros_025[0]

    def test_nvda025_placeholder_addonidreal_detectado(self, tmp_path):
        """config.conf['addonIdReal'] (nosso placeholder novo) deve gerar NVDA-025."""
        panel = (
            "import wx, config\n"
            "from gui.settingsDialogs import SettingsPanel\n"
            "class TestPanel(SettingsPanel):\n"
            "    title = 'Teste'\n"
            "    def makeSettings(self, sizer):\n"
            "        self._v = config.conf['addonIdReal'].get('key', '')\n"
            "    def onSave(self):\n"
            "        config.conf['addonIdReal']['key'] = ''\n"
        )
        addon = self._criar_addon(tmp_path, {"__init__.py": "import globalPluginHandler, addonHandler\naddonHandler.initTranslation()\nclass GlobalPlugin(globalPluginHandler.GlobalPlugin):\n    def terminate(self): pass\n", "panel.py": panel})
        problems = validate_addon_structure(addon)
        erros_025 = [p for p in problems if "NVDA-025" in p]
        assert len(erros_025) >= 1, f"Esperava NVDA-025 para placeholder 'addonIdReal': {problems}"

    def test_nvda025_secao_correta_sem_erro(self, tmp_path):
        """config.conf com o addonId correto nao deve gerar NVDA-025."""
        panel = (
            "import wx, config\n"
            "from gui.settingsDialogs import SettingsPanel\n"
            "class TestPanel(SettingsPanel):\n"
            "    title = 'Teste'\n"
            "    def makeSettings(self, sizer):\n"
            "        self._v = config.conf['MeuAddonReal'].get('key', '')\n"
            "    def onSave(self):\n"
            "        config.conf['MeuAddonReal']['key'] = ''\n"
        )
        addon = self._criar_addon(tmp_path, {
            "__init__.py": "import globalPluginHandler, addonHandler\naddonHandler.initTranslation()\nclass GlobalPlugin(globalPluginHandler.GlobalPlugin):\n    def terminate(self): pass\n",
            "panel.py": panel,
        }, addon_id="MeuAddonReal")
        problems = validate_addon_structure(addon)
        erros_025 = [p for p in problems if "NVDA-025" in p]
        assert erros_025 == [], f"addonId correto nao deve gerar NVDA-025: {erros_025}"

    def test_nvda025_secao_errada_detectada(self, tmp_path):
        """config.conf com secao diferente do addonId deve gerar NVDA-025."""
        panel = (
            "import wx, config\n"
            "from gui.settingsDialogs import SettingsPanel\n"
            "class TestPanel(SettingsPanel):\n"
            "    title = 'Teste'\n"
            "    def makeSettings(self, sizer):\n"
            "        self._v = config.conf['outroAddon'].get('key', '')\n"
            "    def onSave(self):\n"
            "        config.conf['outroAddon']['key'] = ''\n"
        )
        addon = self._criar_addon(tmp_path, {
            "__init__.py": "import globalPluginHandler, addonHandler\naddonHandler.initTranslation()\nclass GlobalPlugin(globalPluginHandler.GlobalPlugin):\n    def terminate(self): pass\n",
            "panel.py": panel,
        }, addon_id="MeuAddonReal")
        problems = validate_addon_structure(addon)
        erros_025 = [p for p in problems if "NVDA-025" in p]
        assert len(erros_025) >= 1, f"Secao 'outroAddon' != 'MeuAddonReal' deve gerar NVDA-025: {problems}"
        assert "outroAddon" in erros_025[0]
        assert "MeuAddonReal" in erros_025[0]




# ===========================================================================
# Plano aa1600dd (2026-05-10): testes de regressao das fixes
# ===========================================================================

class TestNvda047UrlVazio:
	"""Bug regressao: regex consumia newline e capturava version= da linha seguinte."""

	def test_url_vazio_reportado_com_mensagem_correta(self, tmp_path):
		addon = tmp_path / "addon"
		addon.mkdir()
		# Cria globalPlugins/x/__init__.py para nao disparar ESTRUTURA-004
		gp = addon / "globalPlugins" / "x"
		gp.mkdir(parents=True)
		(gp / "__init__.py").write_text(
			"import addonHandler\naddonHandler.initTranslation()\n"
			"import globalPluginHandler\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"  def terminate(self): pass\n",
			encoding="utf-8",
		)
		manifest = (
			"name = MeuAddon\n"
			"summary = teste\n"
			"description = d\n"
			"author = A\n"
			"url = \n"
			"version = 1.0.0\n"
			"minimumNVDAVersion = 2026.1.0\n"
			"lastTestedNVDAVersion = 2026.1.0\n"
		)
		(addon / "manifest.ini").write_text(manifest, encoding="utf-8")
		problems = validate_addon_structure(str(addon))
		nvda047 = [p for p in problems if p.startswith("NVDA-047")]
		assert len(nvda047) == 1, f"Esperado 1 NVDA-047, recebido: {nvda047}"
		# Mensagem antiga reportava 'version = 1.0.0' — agora reporta url vazio
		assert "vazio" in nvda047[0].lower()
		assert "version" not in nvda047[0]

	def test_url_http_sem_s_reportado_corretamente(self, tmp_path):
		addon = tmp_path / "addon"
		addon.mkdir()
		gp = addon / "globalPlugins" / "x"
		gp.mkdir(parents=True)
		(gp / "__init__.py").write_text(
			"import addonHandler\naddonHandler.initTranslation()\n"
			"import globalPluginHandler\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"  def terminate(self): pass\n",
			encoding="utf-8",
		)
		manifest = (
			"name = MeuAddon\n"
			"summary = teste\n"
			"description = d\n"
			"author = A\n"
			"url = http://example.com\n"
			"version = 1.0.0\n"
			"minimumNVDAVersion = 2026.1.0\n"
			"lastTestedNVDAVersion = 2026.1.0\n"
		)
		(addon / "manifest.ini").write_text(manifest, encoding="utf-8")
		problems = validate_addon_structure(str(addon))
		nvda047 = [p for p in problems if p.startswith("NVDA-047")]
		assert len(nvda047) == 1
		assert "http://example.com" in nvda047[0]
		assert "https" in nvda047[0].lower()

	def test_url_https_valido_nao_reporta(self, tmp_path):
		addon = tmp_path / "addon"
		addon.mkdir()
		gp = addon / "globalPlugins" / "x"
		gp.mkdir(parents=True)
		(gp / "__init__.py").write_text(
			"import addonHandler\naddonHandler.initTranslation()\n"
			"import globalPluginHandler\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"  def terminate(self): pass\n",
			encoding="utf-8",
		)
		manifest = (
			"name = MeuAddon\n"
			"summary = teste\n"
			"description = d\n"
			"author = A\n"
			"url = https://github.com/me/addon\n"
			"version = 1.0.0\n"
			"minimumNVDAVersion = 2026.1.0\n"
			"lastTestedNVDAVersion = 2026.1.0\n"
		)
		(addon / "manifest.ini").write_text(manifest, encoding="utf-8")
		problems = validate_addon_structure(str(addon))
		nvda047 = [p for p in problems if p.startswith("NVDA-047")]
		assert nvda047 == []


class TestPathTraversalComFronteiraDeDiretorio:
    # Bug real de auditoria: o guard antigo comparava dest_abs.startswith(addon_folder)
    # sem exigir fronteira de separador -- uma pasta irma cujo nome comeca com o
    # mesmo prefixo (ex: testAddonExtra vs testAddon) passava no startswith().
    # Fix: compara contra addon_folder + os.sep.

    def test_bloqueia_escrita_em_pasta_irma_com_nome_prefixado(self, tmp_path):
        """addon_name='testAddon' + filename com ../ tentando escrever em
        testAddonExtra (pasta irma cujo nome comeca com testAddon).
        """
        blocks = [
            {"filename": "manifest.ini", "code": "name = testAddon\n", "language": "ini"},
            {
                "filename": "../testAddonExtra/evil.py",
                "code": "# nao deveria ser escrito fora de addon_folder\n",
                "language": "python",
            },
        ]
        folder, saved = save_addon_files(
            blocks, str(tmp_path), "testAddon", use_timestamp=False
        )
        evil_path = os.path.join(str(tmp_path), "testAddonExtra", "evil.py")
        assert not os.path.exists(evil_path)
        for p in saved:
            assert p.startswith(folder + os.sep) or p == folder
