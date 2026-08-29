import configparser
import os
import re


_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MANIFEST_PATH = os.path.join(_ROOT, "manifest.ini")

PROJECT_BASELINE = (2026, 1, 1)
ABSOLUTE_MINIMUM = (2019, 3, 0)


def _parse_manifest() -> dict[str, str]:
    with open(MANIFEST_PATH, encoding="utf-8") as fh:
        content = fh.read()
    parser = configparser.ConfigParser()
    parser.read_string("[root]\n" + content)
    return dict(parser["root"])


def _version_tuple(version_str: str) -> tuple[int, int, int]:
    parts = [int(x) for x in version_str.strip().split(".")]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


class TestProjectManifestExiste:
    def test_manifest_ini_existe(self):
        assert os.path.isfile(MANIFEST_PATH)


class TestProjectManifestCamposObrigatorios:
    def setup_method(self):
        self.m = _parse_manifest()

    def test_name_presente(self):
        assert self.m.get("name", "").strip()

    def test_summary_presente(self):
        assert self.m.get("summary", "").strip()

    def test_version_presente(self):
        assert self.m.get("version", "").strip()

    def test_author_presente(self):
        assert self.m.get("author", "").strip()

    def test_minimumNVDAVersion_presente(self):
        assert "minimumnvdaversion" in self.m

    def test_lastTestedNVDAVersion_presente(self):
        assert "lasttestednvdaversion" in self.m

    def test_description_entre_aspas(self):
        with open(MANIFEST_PATH, encoding="utf-8") as fh:
            raw = fh.read()
        match = re.search(r"^description\s*=\s*(.+)$", raw, re.MULTILINE)
        assert match, "Campo description nao encontrado no manifest.ini"
        assert match.group(1).strip().startswith(('"', "'"))


class TestProjectManifestBaseline:
    def setup_method(self):
        self.m = _parse_manifest()
        self.minimum = _version_tuple(self.m["minimumnvdaversion"])
        self.last_tested = _version_tuple(self.m["lasttestednvdaversion"])

    def test_minimum_respeita_baseline_do_projeto(self):
        assert self.minimum >= PROJECT_BASELINE, (
            f"minimumNVDAVersion {self.minimum} abaixo do baseline {PROJECT_BASELINE}"
        )

    def test_last_tested_respeita_baseline_do_projeto(self):
        assert self.last_tested >= PROJECT_BASELINE, (
            f"lastTestedNVDAVersion {self.last_tested} abaixo do baseline {PROJECT_BASELINE}"
        )

    def test_minimum_nao_abaixo_do_limite_absoluto(self):
        assert self.minimum >= ABSOLUTE_MINIMUM

    def test_minimum_menor_ou_igual_last_tested(self):
        assert self.minimum <= self.last_tested

    def test_minimum_formato_valido(self):
        raw = self.m["minimumnvdaversion"].strip()
        assert re.match(r"^(0|\d{4})\.(\d)(?:\.(\d))?$", raw)

    def test_last_tested_formato_valido(self):
        raw = self.m["lasttestednvdaversion"].strip()
        assert re.match(r"^(0|\d{4})\.(\d)(?:\.(\d))?$", raw)
