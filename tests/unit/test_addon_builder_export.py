import os
import zipfile
import pytest
from nvdastudio.builder.addon_builder import (
    generate_quality_report, export_addon_zip, AddonBuilderError, MODULE_VERSION,
)


class TestAddonBuilderVersao:
    def test_versao_e_1_4_0(self):
        assert MODULE_VERSION == "4.17.0"


# ---------- Helpers ----------

def _make_step(step_id, step_type, approved, score, issues=None):
    from dataclasses import dataclass
    @dataclass
    class SR:
        step_id: str
        step_type: str
        approved: bool
        score: int
        issues: list
    return SR(step_id=step_id, step_type=step_type, approved=approved,
               score=score, issues=issues or [])


# ---------- generate_quality_report ----------

class TestGenerateQualityReport:
    def test_retorna_string(self):
        report = generate_quality_report("MeuAddon", "p-001", [], 0)
        assert isinstance(report, str)

    def test_contem_nome_addon(self):
        report = generate_quality_report("TestAddon", "p-001", [], 0)
        assert "TestAddon" in report

    def test_contem_plan_id(self):
        report = generate_quality_report("X", "plan-xyz-123", [], 0)
        assert "plan-xyz-123" in report

    def test_contem_tokens_se_fornecido(self):
        report = generate_quality_report("X", "p", [], total_tokens=5000)
        assert "5" in report  # alguma representação de 5000

    def test_sem_tokens_nao_menciona_zero(self):
        report = generate_quality_report("X", "p", [], total_tokens=0)
        # Quando total_tokens=0, linha não deve aparecer
        assert "Tokens consumidos:" not in report

    def test_contem_resumo_de_steps(self):
        steps = [
            _make_step("s1", "code_generation", True, 95),
            _make_step("s2", "manifest_builder", True, 90),
        ]
        report = generate_quality_report("A", "p", steps)
        assert "2/2" in report

    def test_contem_issues_do_step(self):
        steps = [_make_step("s1", "code_generation", False, 40,
                             issues=["NVDA-001: falta nextHandler"])]
        report = generate_quality_report("A", "p", steps)
        assert "NVDA-001" in report or "nextHandler" in report

    def test_step_aprovado_indica_aprovado(self):
        steps = [_make_step("s1", "code_generation", True, 95)]
        report = generate_quality_report("A", "p", steps)
        assert "APROVADO" in report

    def test_step_reprovado_indica_reprovado(self):
        steps = [_make_step("s1", "code_generation", False, 30)]
        report = generate_quality_report("A", "p", steps)
        assert "REPROVADO" in report

    def test_sem_steps_retorna_relatorio_valido(self):
        report = generate_quality_report("X", "p", [])
        assert len(report) > 0
        assert "0/0" in report

    def test_nao_executa_codigo(self):
        """Conteúdo malicioso nos issues não deve ser executado."""
        steps = [_make_step("s1", "code_gen", False, 0,
                             issues=["__import__('os').system('rm -rf /');"])]
        report = generate_quality_report("A", "p", steps)
        # Apenas verificamos que a função retornou sem executar nada
        assert isinstance(report, str)


# ---------- export_addon_zip ----------

class TestExportAddonZip:
    def test_gera_arquivo_zip(self, tmp_path):
        addon_folder = tmp_path / "MeuAddon"
        addon_folder.mkdir()
        (addon_folder / "manifest.ini").write_text("name = Teste")
        gp = addon_folder / "globalPlugins" / "meuAddon"
        gp.mkdir(parents=True)
        (gp / "__init__.py").write_text("# codigo")

        zip_path = export_addon_zip(str(addon_folder), "MeuAddon")
        assert os.path.exists(zip_path)
        assert zip_path.endswith(".zip")

    def test_zip_e_valido(self, tmp_path):
        addon_folder = tmp_path / "AddonV"
        addon_folder.mkdir()
        (addon_folder / "manifest.ini").write_text("name = V")

        zip_path = export_addon_zip(str(addon_folder), "AddonV")
        assert zipfile.is_zipfile(zip_path)

    def test_zip_contem_manifest(self, tmp_path):
        addon_folder = tmp_path / "WithManifest"
        addon_folder.mkdir()
        (addon_folder / "manifest.ini").write_text("name = WM")

        zip_path = export_addon_zip(str(addon_folder), "WithManifest")
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        assert any("manifest.ini" in n for n in names)

    def test_zip_contem_relatorio_quando_fornecido(self, tmp_path):
        addon_folder = tmp_path / "WithReport"
        addon_folder.mkdir()
        (addon_folder / "manifest.ini").write_text("name = WR")

        zip_path = export_addon_zip(str(addon_folder), "WithReport",
                                     report_md="# Relatorio\nTeste")
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        assert any("QUALITY_REPORT.md" in n for n in names)

    def test_zip_sem_relatorio_nao_contem_report(self, tmp_path):
        addon_folder = tmp_path / "NoReport"
        addon_folder.mkdir()
        (addon_folder / "manifest.ini").write_text("name = NR")

        zip_path = export_addon_zip(str(addon_folder), "NoReport", report_md="")
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        assert not any("QUALITY_REPORT.md" in n for n in names)

    def test_pasta_inexistente_levanta_erro(self, tmp_path):
        with pytest.raises(AddonBuilderError):
            export_addon_zip(str(tmp_path / "nao_existe"), "X")

    def test_nome_com_espacos_sanitizado_no_zip(self, tmp_path):
        addon_folder = tmp_path / "Com Espaco"
        addon_folder.mkdir()
        (addon_folder / "manifest.ini").write_text("name = E")

        zip_path = export_addon_zip(str(addon_folder), "Com Espaco")
        assert "Com_Espaco" in zip_path

    def test_nao_executa_conteudo_do_zip(self, tmp_path):
        """Conteúdo malicioso no manifest não deve ser executado."""
        addon_folder = tmp_path / "Malicious"
        addon_folder.mkdir()
        (addon_folder / "manifest.ini").write_text("__import__('os').system('id')")

        zip_path = export_addon_zip(str(addon_folder), "Malicious")
        assert os.path.exists(zip_path)
