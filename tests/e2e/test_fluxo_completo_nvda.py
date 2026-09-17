import ast
import json
import os
import re
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pytest

# 2026-08-16: importado direto de project_policy.py (fonte unica de
# verdade) em vez de hardcoded duplicado -- copia hardcoded ja tinha
# ficado presa em "2026.1.1" enquanto o baseline real subiu pra 2026.2.0
# (mesma classe de drift documentada em orchestrator/nvda_context.py).
from nvdastudio.utils.project_policy import PROJECT_MIN_NVDA as _PROJECT_MIN_NVDA

# Carrega .env se existir (permite rodar via Bash sem exportar a key manualmente)
try:
    from dotenv import load_dotenv
    _REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    load_dotenv(dotenv_path=os.path.join(_REPO_ROOT, ".env"), override=False)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Chave e skip
# ---------------------------------------------------------------------------

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
    reason=("Ollama Cloud token nao disponivel" if not HAS_OLLAMA else "OpenCode Go token nao disponivel (necessario pro Critic, ver critic.py 3.19.0)"),
)

# ---------------------------------------------------------------------------
# Caminhos de referencia (docs NVDA)
# ---------------------------------------------------------------------------

# 2026-08-16: achado de auditoria -- apontava pra c:\docs_nvda, caminho
# absoluto que so existia manualmente numa maquina especifica (ver
# nvda_context.py 3.31.0). Os docs reais agora vem bundlados junto do
# pacote do addon (nvda_docs_cache/) -- aponta pra la. _NVDA_MANIFEST_TPL/
# _NVDA_DEVGUIDE nao tem arquivo bundlado equivalente (nao fazem parte do
# clone de nvaccess/nvda, so o AddonTemplate/dev guide) -- mantidos como
# referencia documental, nenhum teste neste arquivo os le de fato.
_NVDA_DOCS = (
	Path(__file__).resolve().parent.parent.parent
	/ "addon" / "globalPlugins" / "nvdastudio" / "nvda_docs_cache"
)
_NVDA_MANIFEST_TPL = _NVDA_DOCS / "AddonTemplate-master" / "manifest.ini.tpl"
_NVDA_GPHANDLER = _NVDA_DOCS / "nvda" / "source" / "globalPluginHandler.py"
_NVDA_DEVGUIDE = _NVDA_DOCS / "nvda_developer_guide_2025.html"


# Campos obrigatorios do manifest.ini — derivados do AddonTemplate oficial
# Chaves em lowercase porque _parse_manifest_fields normaliza com .lower()
_MANIFEST_REQUIRED_FIELDS = [
    "name",
    "summary",
    "author",
    "version",
    "minimumnvdaversion",
    "lasttestednvdaversion",
]

# Formatos de versao validos: MAJOR.MINOR ou MAJOR.MINOR.PATCH
_VERSION_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")

# Atalhos que conflitam com o NVDA core (NVDA-009)
# Fonte: nvda_developer_guide_2025.html — secao "Script Gestures"
_CONFLICTING_CORE_GESTURES = {
    "kb:nvda+t",   # leitura de titulo — core NVDA
    "kb:nvda+b",   # leitura da barra de status
    "kb:nvda+e",   # leitor de texto de edicao
    "kb:nvda+n",   # menu NVDA
    "kb:nvda+q",   # sair do NVDA
    "kb:nvda+f1",  # ajuda de teclado
    "kb:nvda+s",   # modo de fala
}

# ---------------------------------------------------------------------------
# Output dir
# ---------------------------------------------------------------------------

_E2E_OUTPUT_DIR = os.path.join(
    os.path.expanduser("~"), "Documents", "NVDAStudio", "addons_gerados", "e2e_nvda_fluxo"
)
_REPORT_DIR = os.path.join(os.path.dirname(__file__), "relatorios")


# ---------------------------------------------------------------------------
# Dataclasses de rastreamento
# ---------------------------------------------------------------------------

@dataclass
class StepTrace:
    step_id: str
    step_type: str
    model_used: str
    approved: bool
    score: int
    retries_used: int
    tokens_used: int
    issues: list[str] = field(default_factory=list)
    output_preview: str = ""


@dataclass
class FluxoReport:
    """Relatorio estruturado do fluxo completo."""
    addon_name: str
    query: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    plan_id: str = ""
    complexity: str = ""
    duration_seconds: float = 0.0
    total_tokens: int = 0
    total_retries: int = 0
    replan_count: int = 0
    success: bool = False
    error: str = ""

    events: list[tuple[str, str]] = field(default_factory=list)
    steps: list[StepTrace] = field(default_factory=list)

    addon_folder: str = ""
    files_saved: list[str] = field(default_factory=list)
    nvda_addon_path: str = ""
    zip_names: list[str] = field(default_factory=list)

    struct_problems: list[str] = field(default_factory=list)
    has_init_py: bool = False
    has_manifest: bool = False
    has_doc: bool = False

    blocks_collected: list[dict] = field(default_factory=list)

    @property
    def event_types(self) -> list[str]:
        return [e[0] for e in self.events]

    @property
    def approved_steps(self) -> list[StepTrace]:
        return [s for s in self.steps if s.approved]

    @property
    def failed_steps(self) -> list[StepTrace]:
        return [s for s in self.steps if not s.approved]

    @property
    def avg_score(self) -> float:
        if not self.steps:
            return 0.0
        return sum(s.score for s in self.steps) / len(self.steps)

    @property
    def models_used(self) -> set[str]:
        return {s.model_used for s in self.steps if s.model_used}

    def _safe(self, text: str) -> str:
        _TRANS = str.maketrans({
            '\u2011': '-', '\u2013': '-', '\u2014': '-',
            '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',
            '\u2026': '...',
        })
        return text.translate(_TRANS).encode('cp1252', errors='replace').decode('cp1252')

    def print_report(self) -> None:
        sep = "=" * 72
        print(f"\n{sep}")
        print(f"FLUXO COMPLETO NVDA — {self.addon_name}")
        print(f"  Query:       {self.query[:80]}")
        print(f"  Timestamp:   {self.timestamp}")
        print(f"  Duracao:     {self.duration_seconds:.1f}s")
        print(f"  Sucesso:     {self.success}")
        if self.error:
            print(f"  ERRO:        {self.error}")

        print("\n--- PIPELINE ---")
        print(f"  Plano ID:    {self.plan_id}")
        print(f"  Complexidade:{self.complexity}")
        print(f"  Steps total: {len(self.steps)}")
        print(f"  Aprovados:   {len(self.approved_steps)}/{len(self.steps)}")
        print(f"  Retries:     {self.total_retries}")
        print(f"  Replans:     {self.replan_count}")
        print(f"  Tokens:      {self.total_tokens:,}")
        print(f"  Score medio: {self.avg_score:.1f}")

        print("\n--- STEPS ---")
        for st in self.steps:
            status = "OK" if st.approved else "FALHOU"
            print(f"  [{status}] {st.step_id:5s} {st.step_type:20s} "
                  f"score={st.score:3d} retries={st.retries_used} "
                  f"tokens={st.tokens_used:,} modelo={st.model_used}")
            for issue in st.issues[:2]:
                print(f"         >> {self._safe(issue)[:82]}")

        print("\n--- EVENTOS ---")
        for ev, det in self.events:
            print(f"  [{ev:15s}] {self._safe(det)[:88]}")

        print("\n--- ARTEFATOS ---")
        print(f"  Pasta:    {self.addon_folder}")
        for f in self.files_saved:
            rel = os.path.relpath(f, self.addon_folder) if self.addon_folder else f
            sz = os.path.getsize(f) if os.path.isfile(f) else 0
            print(f"    {rel}  ({sz:,} bytes)")
        print(f"  .nvda-addon: {self.nvda_addon_path}")
        if self.zip_names:
            print(f"  ZIP ({len(self.zip_names)} entradas):")
            for n in self.zip_names[:10]:
                print(f"    {n}")

        print("\n--- VALIDACAO ESTRUTURAL ---")
        print(f"  __init__.py: {'OK' if self.has_init_py else 'AUSENTE'}")
        print(f"  manifest.ini:{'OK' if self.has_manifest else 'AUSENTE'}")
        print(f"  doc/:        {'OK' if self.has_doc else 'AUSENTE'}")
        if self.struct_problems:
            for p in self.struct_problems:
                print(f"  [PROBLEMA] {p}")
        else:
            print("  Sem problemas estruturais")
        print(sep)

    def save_json(self) -> str:
        os.makedirs(_REPORT_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(_REPORT_DIR, f"fluxo_nvda_{self.addon_name}_{ts}.json")
        data = {
            "addon_name": self.addon_name,
            "query": self.query[:200],
            "timestamp": self.timestamp,
            "plan_id": self.plan_id,
            "duration_seconds": round(self.duration_seconds, 2),
            "total_tokens": self.total_tokens,
            "total_retries": self.total_retries,
            "replan_count": self.replan_count,
            "success": self.success,
            "error": self.error,
            "avg_score": round(self.avg_score, 1),
            "steps": [
                {
                    "step_id": s.step_id,
                    "step_type": s.step_type,
                    "model_used": s.model_used,
                    "approved": s.approved,
                    "score": s.score,
                    "retries_used": s.retries_used,
                    "tokens_used": s.tokens_used,
                    "issues": s.issues[:3],
                }
                for s in self.steps
            ],
            "events": [(e, d[:100]) for e, d in self.events],
            "files_saved": [os.path.basename(f) for f in self.files_saved],
            "zip_names": self.zip_names,
            "struct_problems": self.struct_problems,
            "has_init_py": self.has_init_py,
            "has_manifest": self.has_manifest,
            "has_doc": self.has_doc,
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        print(f"[RELATORIO] Salvo em: {path}")
        return path


# ---------------------------------------------------------------------------
# Motor E2E (fluxo sincrono com captura total)
# ---------------------------------------------------------------------------

def _executar_fluxo_completo(
    addon_name: str,
    query: str,
    output_dir: str = _E2E_OUTPUT_DIR,
) -> FluxoReport:
    """
    Executa o fluxo inteiro do app e retorna FluxoReport detalhado.

    Fluxo real:
      usuario (query) -> Orchestrator -> Planner -> Steps paralelos
      -> Critic por step -> retry/escalacao -> Replan se necessario
      -> assembly -> AddonBuilder (Fix A) -> save_addon_files
      -> package_addon (.nvda-addon) -> validate_addon_structure

    Regra 9: codigo gerado nunca executado.
    """
    from nvdastudio.core.orchestrator import Orchestrator, OrchestrationResult
    from nvdastudio.builder.addon_builder import (
        extract_code_blocks,
        save_addon_files,
        package_addon,
        validate_addon_structure,
    )

    report = FluxoReport(addon_name=addon_name, query=query)
    orch_results: list[OrchestrationResult] = []
    t0 = time.time()

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(_REPORT_DIR, exist_ok=True)

    orch = Orchestrator()
    orch.initialize()
    orch.set_callbacks(
        on_progress=lambda ev, det: report.events.append((ev, det)),
        on_complete=lambda r: orch_results.append(r),
    )

    # Executa sincrono (sem thread) para capturar tudo
    try:
        orch._run_until_complete(query)
    except Exception as exc:
        report.error = f"Pipeline excecao: {exc}"
        report.duration_seconds = time.time() - t0
        report.print_report()
        return report

    report.duration_seconds = time.time() - t0

    if not orch_results:
        report.error = "on_complete nao foi chamado pelo pipeline"
        report.print_report()
        return report

    result = orch_results[0]
    report.success = result.success
    report.plan_id = result.plan_id
    report.total_tokens = getattr(result, "total_tokens", 0)
    report.total_retries = result.total_retries
    report.replan_count = getattr(result, "replan_count", 0)
    report.error = result.error or ""

    # Captura steps
    for sr in result.step_results:
        report.steps.append(StepTrace(
            step_id=sr.step_id,
            step_type=sr.step_type,
            model_used=sr.model_used,
            approved=sr.approved,
            score=sr.score,
            retries_used=sr.retries_used,
            tokens_used=getattr(sr, "tokens_used", 0),
            issues=list(sr.issues),
            output_preview=sr.output[:300] if sr.output else "",
        ))

    # Captura complexidade
    for ev, det in report.events:
        if ev == "PLANO_CRIADO":
            report.complexity = det
            break

    if not result.success:
        report.print_report()
        report.save_json()
        return report

    # --- Fix A: coleta TODOS os blocos de steps aprovados ---
    _PRIO = ["code_generation", "manifest_builder", "documentation",
             "agent_runner", "agent_template", "assembly"]

    def _prio(sr) -> int:
        try:
            return _PRIO.index(sr.step_type)
        except ValueError:
            return len(_PRIO)

    sorted_steps = sorted(
        [sr for sr in result.step_results if sr.approved and sr.output],
        key=_prio,
    )
    seen_fnames: set[str] = set()
    all_blocks: list[dict] = []
    for sr in sorted_steps:
        for blk in extract_code_blocks(sr.output):
            fname = blk.get("filename", "").strip()
            if fname and fname not in seen_fnames:
                seen_fnames.add(fname)
                all_blocks.append(blk)
            elif not fname:
                all_blocks.append(blk)

    # Fallback: assembly_output
    if not all_blocks and getattr(result, "assembly_output", ""):
        all_blocks = extract_code_blocks(result.assembly_output)
    if not all_blocks and result.final_output:
        all_blocks = extract_code_blocks(result.final_output)

    report.blocks_collected = all_blocks

    if not all_blocks:
        report.error = "Nenhum bloco de codigo extraido dos steps aprovados"
        report.print_report()
        report.save_json()
        return report

    # Salva no disco
    try:
        addon_folder, saved_paths = save_addon_files(all_blocks, output_dir, addon_name)
        report.addon_folder = addon_folder
        report.files_saved = saved_paths
    except Exception as exc:
        report.error = f"save_addon_files falhou: {exc}"
        report.print_report()
        report.save_json()
        return report

    # Empacota .nvda-addon
    try:
        nvda_addon_path = package_addon(addon_folder)
        report.nvda_addon_path = nvda_addon_path
        if os.path.isfile(nvda_addon_path):
            with zipfile.ZipFile(nvda_addon_path, "r") as zf:
                report.zip_names = zf.namelist()
    except Exception as exc:
        report.error = f"package_addon falhou: {exc}"

    # Validacao estrutural
    problems = validate_addon_structure(addon_folder)
    report.struct_problems = problems

    # Popula flags rapidas
    # Achado real de auditoria (2026-08-09, test_e36 GeminiMultimodal):
    # checar so o basename casava com QUALQUER __init__.py, inclusive de um
    # SUBPACOTE de feature (ex: globalPlugins/Addon/audio/__init__.py) --
    # reportava has_init_py=True mesmo sem o __init__.py RAIZ (com a classe
    # GlobalPlugin de verdade) nunca ter sido gerado. Exige exatamente 2
    # niveis relativos a addon_folder (globalPlugins/<NomeAddon>/__init__.py).
    report.has_init_py = any(
        os.path.relpath(f, addon_folder).replace("\\", "/").startswith("globalPlugins/")
        and os.path.basename(f) == "__init__.py"
        and os.path.relpath(f, addon_folder).replace("\\", "/").count("/") == 2
        for f in saved_paths
    )
    report.has_manifest = any(
        os.path.basename(f).lower() == "manifest.ini" for f in saved_paths
    )
    report.has_doc = any("doc" in f.lower() and f.endswith(".html") for f in saved_paths)

    report.print_report()
    report.save_json()
    return report


# ---------------------------------------------------------------------------
# Helpers de validacao
# ---------------------------------------------------------------------------

def _ler_init_py(addon_folder: str) -> str:
    """Retorna o conteudo do __init__.py principal (Regra 9: apenas string)."""
    gp = os.path.join(addon_folder, "globalPlugins")
    if not os.path.isdir(gp):
        return ""
    for subdir in os.listdir(gp):
        init = os.path.join(gp, subdir, "__init__.py")
        if os.path.isfile(init):
            with open(init, encoding="utf-8", errors="replace") as fh:
                return fh.read()
    return ""


def _ler_manifest(addon_folder: str) -> str:
    """Retorna o conteudo do manifest.ini (Regra 9: apenas string)."""
    path = os.path.join(addon_folder, "manifest.ini")
    if os.path.isfile(path):
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    return ""


def _parse_manifest_fields(content: str) -> dict[str, str]:
    """Extrai pares key=value do manifest.ini sem configparser (mais tolerante)."""
    fields: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            fields[key.strip().lower()] = value.strip()
    return fields


def _gestures_em_codigo(code: str) -> list[str]:
    """
    Busca padroes de gesture no codigo Python (sem executar — Regra 9).
    Retorna lista de gestures encontrados como string.
    """
    # Busca: gesture="kb:NVDA+X" no decorador @script
    return re.findall(r'gesture\s*=\s*["\']([^"\']+)["\']', code, re.IGNORECASE)


# ---------------------------------------------------------------------------
# FIXTURE
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def fluxo_report():
    """
    Executa o fluxo completo UMA VEZ para toda a classe.
    Todos os testes da classe consomem o mesmo FluxoReport.
    Economiza tokens e tempo de API.
    """
    report = _executar_fluxo_completo(
        addon_name="FluxoNVDA_e2e",
        query=(
            "Crie um GlobalPlugin NVDA chamado 'AnunciadorStatus' que anuncia "
            "o status da bateria ao pressionar NVDA+shift+B. "
            "O plugin deve: "
            "1) Ter classe GlobalPlugin com @script decorator; "
            "2) Chamar addonHandler.initTranslation() no topo; "
            "3) Implementar terminate() que chama super().terminate(); "
            "4) Retornar informacao via ui.message(); "
            "5) Ter manifest.ini com version=1.0.0, minimumNVDAVersion=2026.1.1, "
            "lastTestedNVDAVersion=2026.1.1, docFileName=userGuide.html; "
            "6) Ter documentacao em doc/pt_BR/userGuide.html e doc/en/userGuide.html."
        ),
    )
    return report


# ---------------------------------------------------------------------------
# Classe de testes: fluxo completo
# ---------------------------------------------------------------------------

@skip_unless_ollama
class TestFluxoCompletoNVDA:
    """
    5.1.0: skip_unless_ollama era definido neste arquivo mas nunca aplicado
    -- fluxo_report (fixture de modulo) rodava o pipeline completo (LLM
    real) incondicionalmente e ficava pendurado sem as chaves configuradas,
    em vez de skip limpo. Ver test_e20_regras_qualidade_codigo.py 5.1.0 para
    o achado completo. Mesmo padrao ja usado em test_e35/e36/e37/e38.

    Valida o fluxo inteiro do app — desde o pedido do usuario ate o .nvda-addon gerado —
    contra a documentacao oficial do NVDA em c:\\docs_nvda.

    Todos os testes compartilham o mesmo FluxoReport (fixture de modulo).
    Regra 9: nenhum codigo e executado em nenhuma validacao.
    """

    # ------------------------------------------------------------------
    # 1. Fluxo de execucao
    # ------------------------------------------------------------------

    def test_pipeline_concluiu_com_sucesso(self, fluxo_report: FluxoReport):
        """Pipeline deve terminar com success=True."""
        assert fluxo_report.success, (
            f"Pipeline falhou. Erro: {fluxo_report.error}"
        )

    def test_eventos_de_progresso_emitidos(self, fluxo_report: FluxoReport):
        """
        O fluxo deve emitir eventos de progresso na sequencia correta.
        Valida que o usuario do NVDA receberia feedback audio durante toda a criacao.
        """
        evs = fluxo_report.event_types
        assert "PLANEJANDO" in evs, "Evento PLANEJANDO nao foi emitido"
        assert "PLANO_CRIADO" in evs, "Evento PLANO_CRIADO nao foi emitido"
        assert "EXECUTANDO" in evs, "Evento EXECUTANDO nao foi emitido"
        assert "CONCLUIDO" in evs, "Evento CONCLUIDO nao foi emitido"

    def test_planner_gerou_steps_minimos(self, fluxo_report: FluxoReport):
        """
        O plano deve ter pelo menos: manifest_builder, code_generation, assembly.
        Esses 3 sao o minimo para um addon NVDA valido.
        """
        if not fluxo_report.success:
            pytest.skip("Pipeline nao concluiu")
        step_types = {s.step_type for s in fluxo_report.steps}
        assert "manifest_builder" in step_types, "Plano sem manifest_builder"
        assert "code_generation" in step_types, "Plano sem code_generation"
        assert "assembly" in step_types, "Plano sem assembly"

    def test_todos_steps_criticos_aprovados(self, fluxo_report: FluxoReport):
        """
        Steps criticos (code_generation, manifest_builder) devem ser APROVADOS.
        Steps nao-criticos (accessibility_audit, documentation) podem falhar sem
        travar o pipeline.
        """
        if not fluxo_report.success:
            pytest.skip("Pipeline nao concluiu")
        criticos = [s for s in fluxo_report.steps
                    if s.step_type in {"code_generation", "manifest_builder"}]
        falhos = [s for s in criticos if not s.approved]
        assert not falhos, (
            f"Steps criticos falharam: "
            f"{[(s.step_type, s.score, s.issues[:1]) for s in falhos]}"
        )

    def test_durecao_dentro_de_limite_razoavel(self, fluxo_report: FluxoReport):
        """Pipeline nao deve demorar mais de 10 minutos para um addon simples."""
        assert fluxo_report.duration_seconds < 600, (
            f"Pipeline demorou {fluxo_report.duration_seconds:.0f}s — acima de 600s"
        )

    def test_tokens_foram_contados(self, fluxo_report: FluxoReport):
        """total_tokens deve ser > 0 (API foi chamada de verdade)."""
        if not fluxo_report.success:
            pytest.skip("Pipeline nao concluiu")
        assert fluxo_report.total_tokens > 0, "Nenhum token registrado — API nao chamada?"

    # ------------------------------------------------------------------
    # 2. Artefatos no disco
    # ------------------------------------------------------------------

    def test_addon_folder_criado(self, fluxo_report: FluxoReport):
        """A pasta do addon deve existir no disco."""
        if not fluxo_report.success:
            pytest.skip("Pipeline nao concluiu")
        assert fluxo_report.addon_folder, "addon_folder nao definido"
        assert os.path.isdir(fluxo_report.addon_folder), (
            f"Pasta do addon nao existe: {fluxo_report.addon_folder}"
        )

    def test_init_py_salvo_no_disco(self, fluxo_report: FluxoReport):
        """globalPlugins/<nome>/__init__.py deve existir no disco."""
        if not fluxo_report.success:
            pytest.skip("Pipeline nao concluiu")
        assert fluxo_report.has_init_py, (
            f"__init__.py nao foi salvo. "
            f"Arquivos: {[os.path.basename(f) for f in fluxo_report.files_saved]}"
        )

    def test_manifest_ini_salvo_no_disco(self, fluxo_report: FluxoReport):
        """manifest.ini deve existir na raiz da pasta do addon."""
        if not fluxo_report.success:
            pytest.skip("Pipeline nao concluiu")
        assert fluxo_report.has_manifest, (
            f"manifest.ini nao foi salvo. "
            f"Arquivos: {[os.path.basename(f) for f in fluxo_report.files_saved]}"
        )

    def test_documentacao_html_gerada(self, fluxo_report: FluxoReport):
        """Pelo menos um arquivo userGuide.html deve ter sido salvo."""
        if not fluxo_report.success:
            pytest.skip("Pipeline nao concluiu")
        # Verifica nos blocos coletados (mesmo que nao tenha sido salvo ainda)
        doc_blocks = [
            b for b in fluxo_report.blocks_collected
            if b.get("language") == "html"
        ]
        doc_files = [f for f in fluxo_report.files_saved if f.endswith(".html")]
        assert doc_blocks or doc_files, (
            "Nenhum arquivo de documentacao HTML foi gerado. "
            f"Blocos coletados: {[b.get('filename') for b in fluxo_report.blocks_collected]}"
        )

    def test_nvda_addon_empacotado(self, fluxo_report: FluxoReport):
        """O .nvda-addon deve ter sido gerado e ser um ZIP valido."""
        if not fluxo_report.success:
            pytest.skip("Pipeline nao concluiu")
        assert fluxo_report.nvda_addon_path, ".nvda-addon nao foi gerado"
        assert os.path.isfile(fluxo_report.nvda_addon_path), (
            f".nvda-addon nao existe no disco: {fluxo_report.nvda_addon_path}"
        )
        assert zipfile.is_zipfile(fluxo_report.nvda_addon_path), (
            ".nvda-addon deve ser um ZIP valido (NVDA nao consegue instalar)"
        )

    # ------------------------------------------------------------------
    # 3. Estrutura do pacote ZIP — conforme NVDA addon loader
    # Ref: c:\docs_nvda\nvda\source\addonHandler\__init__.py
    # ------------------------------------------------------------------

    def test_zip_tem_manifest_na_raiz(self, fluxo_report: FluxoReport):
        """
        manifest.ini deve estar na RAIZ do ZIP (nao em subpasta).
        Ref: addonHandler/__init__.py — le manifest.ini da raiz do zip.
        """
        if not fluxo_report.success or not fluxo_report.zip_names:
            pytest.skip("ZIP nao disponivel")
        assert "manifest.ini" in fluxo_report.zip_names, (
            f"manifest.ini nao esta na raiz do ZIP. "
            f"Entradas: {fluxo_report.zip_names[:10]}"
        )

    def test_zip_tem_globalplugins_com_init_py(self, fluxo_report: FluxoReport):
        """
        ZIP deve conter globalPlugins/<nome>/__init__.py.
        Ref: globalPluginHandler.py — importa modulos de globalPlugins.<nome>.
        """
        if not fluxo_report.success or not fluxo_report.zip_names:
            pytest.skip("ZIP nao disponivel")
        init_py_entries = [
            n for n in fluxo_report.zip_names
            if n.startswith("globalPlugins/") and n.endswith("__init__.py")
        ]
        assert init_py_entries, (
            f"Nenhum globalPlugins/.../__init__.py no ZIP. "
            f"Entradas: {fluxo_report.zip_names}"
        )

    def test_zip_uma_unica_pasta_de_plugin(self, fluxo_report: FluxoReport):
        """
        ESTRUTURA-007: deve haver apenas UMA subpasta em globalPlugins/ com __init__.py.
        NVDA carregaria todas — duas causam conflito de atalhos.
        Fix _deduplicate_blocks() deve ter resolvido isso.
        """
        if not fluxo_report.success or not fluxo_report.zip_names:
            pytest.skip("ZIP nao disponivel")
        plugin_dirs = set()
        for entry in fluxo_report.zip_names:
            m = re.match(r"^globalPlugins/([^/]+)/__init__\.py$", entry)
            if m:
                plugin_dirs.add(m.group(1))
        assert len(plugin_dirs) <= 1, (
            f"ESTRUTURA-007 ainda presente: multiplas pastas de plugin no ZIP: {plugin_dirs}. "
            f"NVDA carregaria dois GlobalPlugins simultaneamente."
        )

    def test_zip_sem_prefix_de_pasta_raiz(self, fluxo_report: FluxoReport):
        """
        Entradas do ZIP NAO devem comecar com o nome do addon como prefixo de pasta.
        Ex: correto = 'manifest.ini'; errado = 'MeuAddon/manifest.ini'
        Ref: addonHandler/__init__.py — le entradas relativas.
        """
        if not fluxo_report.success or not fluxo_report.zip_names:
            pytest.skip("ZIP nao disponivel")
        nome_lower = fluxo_report.addon_name.lower().replace("_e2e", "").replace("_", "")
        prefixadas = [
            n for n in fluxo_report.zip_names
            if n.lower().split("/")[0].replace("_", "") == nome_lower
               and "/" in n
        ]
        assert not prefixadas, (
            f"ZIP tem entradas com prefixo de pasta: {prefixadas[:3]}. "
            f"NVDA nao conseguiria importar o plugin."
        )

    # ------------------------------------------------------------------
    # 4. manifest.ini — contra AddonTemplate oficial
    # Ref: c:\docs_nvda\AddonTemplate-master\manifest.ini.tpl
    # ------------------------------------------------------------------

    def test_manifest_campos_obrigatorios(self, fluxo_report: FluxoReport):
        """
        manifest.ini deve ter todos os campos obrigatorios do AddonTemplate oficial.
        Ref: c:\\docs_nvda\\AddonTemplate-master\\manifest.ini.tpl
        """
        if not fluxo_report.success or not fluxo_report.has_manifest:
            pytest.skip("manifest.ini nao disponivel")
        content = _ler_manifest(fluxo_report.addon_folder)
        fields = _parse_manifest_fields(content)
        ausentes = [f for f in _MANIFEST_REQUIRED_FIELDS if f not in fields]
        assert not ausentes, (
            f"Campos ausentes no manifest.ini: {ausentes}. "
            f"Campos presentes: {list(fields.keys())}. "
            f"Ref: c:\\docs_nvda\\AddonTemplate-master\\manifest.ini.tpl"
        )

    def test_manifest_sem_secao_addon(self, fluxo_report: FluxoReport):
        """
        manifest.ini NAO pode ter secao [add-on] ou [addon].
        Ref: addonHandler/__init__.py usa ConfigObj sem secao — arquivo plano.
        """
        if not fluxo_report.success or not fluxo_report.has_manifest:
            pytest.skip("manifest.ini nao disponivel")
        content = _ler_manifest(fluxo_report.addon_folder)
        assert "[add-on]" not in content.lower(), (
            "manifest.ini tem '[add-on]' — NVDA usa ConfigObj sem secao, rejeitaria o addon."
        )
        assert "[addon]" not in content.lower().replace(" ", ""), (
            "manifest.ini tem secao [addon] — invalido para o loader do NVDA."
        )

    def test_manifest_versao_formato_correto(self, fluxo_report: FluxoReport):
        """
        version deve ser MAJOR.MINOR.PATCH (ex: 1.0.0).
        minimumNVDAVersion e lastTestedNVDAVersion devem ser MAJOR.MINOR.PATCH >= 2026.1.
        Ref: addonAPIVersion.py: versao e representada como tupla de 3 inteiros.
        """
        if not fluxo_report.success or not fluxo_report.has_manifest:
            pytest.skip("manifest.ini nao disponivel")
        content = _ler_manifest(fluxo_report.addon_folder)
        fields = _parse_manifest_fields(content)

        # Mapa: nome de exibicao -> chave lowercase (como _parse_manifest_fields retorna)
        _version_campos = {
            "version": "version",
            "minimumNVDAVersion": "minimumnvdaversion",
            "lastTestedNVDAVersion": "lasttestednvdaversion",
        }
        for display_nome, chave in _version_campos.items():
            val = fields.get(chave, "")
            # Remove ponto final acidental (bug comum da IA)
            val_clean = val.rstrip(".")
            assert _VERSION_RE.match(val_clean), (
                f"manifest.ini: {display_nome}={val!r} nao segue formato MAJOR.MINOR.PATCH. "
                f"Ex valido: 1.0.0 | 2026.1"
            )

        # Versoes do NVDA devem respeitar o baseline do projeto
        def _vtuple(v: str):
            parts = v.rstrip(".").split(".")
            try:
                return tuple(int(x) for x in parts[:3]) + (0,) * (3 - len(parts))
            except ValueError:
                return (0, 0, 0)

        baseline = _vtuple(_PROJECT_MIN_NVDA)
        for display_nome, chave in {
            "minimumNVDAVersion": "minimumnvdaversion",
            "lastTestedNVDAVersion": "lasttestednvdaversion",
        }.items():
            val = fields.get(chave, "0.0.0").rstrip(".")
            assert _vtuple(val) >= baseline, (
                f"manifest.ini: {display_nome}={val!r} abaixo do baseline {_PROJECT_MIN_NVDA}. "
                f"NVDAStudio nao mantem compatibilidade com versoes antigas."
            )

    def test_manifest_doc_file_name(self, fluxo_report: FluxoReport):
        """
        docFileName deve ser 'userGuide.html' (padrao do AddonTemplate).
        Ref: AddonTemplate-master/manifest.ini.tpl
        """
        if not fluxo_report.success or not fluxo_report.has_manifest:
            pytest.skip("manifest.ini nao disponivel")
        content = _ler_manifest(fluxo_report.addon_folder)
        fields = _parse_manifest_fields(content)
        doc_fname = fields.get("docfilename", "")
        if doc_fname:
            assert "guide" in doc_fname.lower() or doc_fname.endswith(".html"), (
                f"docFileName={doc_fname!r} nao e um nome plausivel de guia do usuario. "
                f"Padrao AddonTemplate: userGuide.html"
            )

    # ------------------------------------------------------------------
    # 5. Codigo Python — conforme globalPluginHandler.py do NVDA
    # Ref: c:\docs_nvda\nvda\source\globalPluginHandler.py
    # ------------------------------------------------------------------

    def test_codigo_tem_classe_globalplugin(self, fluxo_report: FluxoReport):
        """
        O __init__.py deve conter 'class GlobalPlugin'.
        Ref: globalPluginHandler.py — carrega GlobalPlugin de cada modulo.
        """
        if not fluxo_report.success or not fluxo_report.has_init_py:
            pytest.skip("__init__.py nao disponivel")
        code = _ler_init_py(fluxo_report.addon_folder)
        assert "class GlobalPlugin" in code, (
            "Classe GlobalPlugin ausente no __init__.py. "
            "Ref: c:\\docs_nvda\\nvda\\source\\globalPluginHandler.py — "
            "NVDA importa GlobalPlugin de cada modulo em globalPlugins/."
        )

    def test_codigo_herda_globalpluginhandler(self, fluxo_report: FluxoReport):
        """
        GlobalPlugin deve herdar de globalPluginHandler.GlobalPlugin.
        Ref: globalPluginHandler.py: class GlobalPlugin(baseObject.ScriptableObject)
        """
        if not fluxo_report.success or not fluxo_report.has_init_py:
            pytest.skip("__init__.py nao disponivel")
        code = _ler_init_py(fluxo_report.addon_folder)
        herda = (
            "globalPluginHandler.GlobalPlugin" in code
            or "GlobalPlugin(globalPluginHandler.GlobalPlugin)" in code
        )
        assert herda, (
            "GlobalPlugin nao herda de globalPluginHandler.GlobalPlugin. "
            "Ref: globalPluginHandler.py linha 68: class GlobalPlugin(baseObject.ScriptableObject)"
        )

    def test_codigo_tem_inittranslation(self, fluxo_report: FluxoReport):
        """
        addonHandler.initTranslation() deve ser chamado no nivel do modulo.
        NVDA-003: sem isso, strings _() retornam untranslated em outros idiomas.
        """
        if not fluxo_report.success or not fluxo_report.has_init_py:
            pytest.skip("__init__.py nao disponivel")
        code = _ler_init_py(fluxo_report.addon_folder)
        assert "initTranslation" in code, (
            "addonHandler.initTranslation() ausente — strings nao serao traduzidas. "
            "NVDA-003: obrigatorio em todo GlobalPlugin."
        )

    def test_codigo_tem_terminate(self, fluxo_report: FluxoReport):
        """
        GlobalPlugin deve implementar terminate().
        Ref: globalPluginHandler.py: plugin.terminate() chamado ao desligar NVDA.
        NVDA-004: sem terminate(), recursos (timers, threads) ficam ativos.
        """
        if not fluxo_report.success or not fluxo_report.has_init_py:
            pytest.skip("__init__.py nao disponivel")
        code = _ler_init_py(fluxo_report.addon_folder)
        assert "def terminate" in code, (
            "terminate() ausente no GlobalPlugin. "
            "Ref: globalPluginHandler.py — NVDA chama terminate() ao desinstalar/recarregar. "
            "NVDA-004: obrigatorio para cleanup de recursos."
        )

    def test_codigo_usa_script_decorator_para_scripts_nomeados(self, fluxo_report: FluxoReport):
        """
        Todo script_* nomeado deve ter @script decorator.

        __gestures em si NAO e mais banido (achado real do teste E2E de
        2026-08-04 + doc oficial do NVDA: developerGuide.html descreve
        __gestures como "an alternative method that still works", nao
        proibida — e o padrao legitimo de "camada" de comandos combina
        __gestures + @script no mesmo addon). O que continua obrigatorio
        e que scripts nomeados individualmente (def script_X) tenham
        @script decorator com description, para aparecerem no Input Help.
        """
        if not fluxo_report.success or not fluxo_report.has_init_py:
            pytest.skip("__init__.py nao disponivel")
        code = _ler_init_py(fluxo_report.addon_folder)
        # Pelo menos um @script deve estar presente se ha script_
        tem_script_func = bool(re.search(r"def script_\w+", code))
        tem_decorator = "@script" in code
        if tem_script_func:
            assert tem_decorator, (
                "Funcoes script_* presentes mas @script decorator ausente. "
                "Ref: nvda_developer_guide_2025.html — todas as scripts devem usar @script."
            )

    def test_codigo_sintaxe_python_valida(self, fluxo_report: FluxoReport):
        """
        O codigo Python gerado deve ter sintaxe valida (Regra 9: ast.parse, sem exec).
        Codigo com erro de sintaxe causa falha ao importar o plugin no NVDA.
        """
        if not fluxo_report.success or not fluxo_report.has_init_py:
            pytest.skip("__init__.py nao disponivel")
        code = _ler_init_py(fluxo_report.addon_folder)
        try:
            ast.parse(code)
        except SyntaxError as exc:
            pytest.fail(
                f"SyntaxError no __init__.py gerado (linha {exc.lineno}): {exc.msg}. "
                f"NVDA nao conseguiria importar o plugin."
            )

    def test_codigo_nao_tem_exec_eval(self, fluxo_report: FluxoReport):
        """
        Regra 9 aplicada ao output: o codigo gerado em si nao deve ter exec() ou eval()
        chamados em nivel de modulo (execucao automatica de string arbitraria).
        """
        if not fluxo_report.success or not fluxo_report.has_init_py:
            pytest.skip("__init__.py nao disponivel")
        code = _ler_init_py(fluxo_report.addon_folder)
        # Busca textual simples — nao executa
        exec_patterns = re.findall(r"\bexec\s*\(", code)
        eval_patterns = re.findall(r"\beval\s*\(", code)
        assert not exec_patterns, "exec() encontrado no codigo gerado — risco de seguranca"
        assert not eval_patterns, "eval() encontrado no codigo gerado — risco de seguranca"

    def test_codigo_atalho_nao_conflita_com_core(self, fluxo_report: FluxoReport):
        """
        NVDA-009: atalhos usados nao devem conflitar com o NVDA core.
        Ref: nvda_developer_guide_2025.html — gestos reservados.
        """
        if not fluxo_report.success or not fluxo_report.has_init_py:
            pytest.skip("__init__.py nao disponivel")
        code = _ler_init_py(fluxo_report.addon_folder)
        gestures = _gestures_em_codigo(code)
        conflitos = [g for g in gestures if g.lower() in _CONFLICTING_CORE_GESTURES]
        assert not conflitos, (
            f"NVDA-009: atalho(s) que conflitam com o NVDA core: {conflitos}. "
            f"Use modificador extra (ex: NVDA+shift+X) para evitar conflito. "
            f"Ref: nvda_developer_guide_2025.html"
        )

    # ------------------------------------------------------------------
    # 6. Validacao estrutural integrada
    # ------------------------------------------------------------------

    def test_validate_addon_structure_sem_problemas_criticos(self, fluxo_report: FluxoReport):
        """
        validate_addon_structure() nao deve reportar problemas criticos (ESTRUTURA-0XX).
        ESTRUTURA-007 (multiplas pastas) deve ter sido corrigido pelo _deduplicate_blocks.
        """
        if not fluxo_report.success:
            pytest.skip("Pipeline nao concluiu")
        criticos = [p for p in fluxo_report.struct_problems
                    if p.startswith("ESTRUTURA-") and not p.startswith("ESTRUTURA-006")]
        assert not criticos, (
            f"Problemas estruturais criticos encontrados: {criticos}"
        )

    def test_sem_arquivos_pyd_no_addon(self, fluxo_report: FluxoReport):
        """
        Addon simples nao deve conter arquivos .pyd (binarios compilados).
        NVDA-017: binarios .pyd exigem validacao de arquitetura (x64 vs ARM).
        """
        if not fluxo_report.success or not fluxo_report.addon_folder:
            pytest.skip("addon_folder nao disponivel")
        pyd_files = []
        for _root, _dirs, files in os.walk(fluxo_report.addon_folder):
            for f in files:
                if f.lower().endswith(".pyd"):
                    pyd_files.append(f)
        assert not pyd_files, (
            f"NVDA-017: arquivos .pyd no addon: {pyd_files}. "
            f"Addons simples devem ser Python puro."
        )

    # ------------------------------------------------------------------
    # 7. Regras adicionais da skill nvda-addon-dev
    # ------------------------------------------------------------------

    def test_codigo_chama_super_init(self, fluxo_report: FluxoReport):
        """
        R5: o __init__ do GlobalPlugin deve chamar super().__init__(*args, **kwargs).
        Sem isso, a cadeia MRO do NVDA nao e inicializada corretamente.
        """
        if not fluxo_report.success or not fluxo_report.has_init_py:
            pytest.skip("__init__.py nao disponivel")
        code = _ler_init_py(fluxo_report.addon_folder)
        assert "super().__init__" in code, (
            "R5: GlobalPlugin.__init__ deve chamar super().__init__(*args, **kwargs). "
            "Sem isso a cadeia MRO do NVDA nao e inicializada corretamente."
        )

    def test_script_decorator_tem_description(self, fluxo_report: FluxoReport):
        """
        R8: @script deve sempre ter o kwarg description=.
        O NVDA usa description para expor o comando na caixa de dialogo de gestos.
        """
        if not fluxo_report.success or not fluxo_report.has_init_py:
            pytest.skip("__init__.py nao disponivel")
        code = _ler_init_py(fluxo_report.addon_folder)
        if "@script" not in code:
            return  # sem @script, nada a verificar
        decoradores = re.findall(r'@script\([^)]*\)', code)
        sem_desc = [d for d in decoradores if "description" not in d]
        assert not sem_desc, (
            f"R8: @script sem description= encontrado(s): {sem_desc}. "
            "O NVDA usa description para expor o comando na caixa de dialogo de gestos."
        )

    def test_strings_traduzidas_tem_comentario_translators(self, fluxo_report: FluxoReport):
        """
        R13: cada _() deve ter # Translators: na linha imediatamente anterior.
        Sem o comentario, as ferramentas de traducao do NVDA nao extraem a string.
        """
        if not fluxo_report.success or not fluxo_report.has_init_py:
            pytest.skip("__init__.py nao disponivel")
        code = _ler_init_py(fluxo_report.addon_folder)
        if '_("' not in code and "_(' " not in code:
            return  # sem strings traduzíveis, ok
        linhas = code.splitlines()
        violacoes: list[str] = []
        for i, linha in enumerate(linhas):
            if '_("' in linha and not linha.strip().startswith("#"):
                linha_anterior = linhas[i - 1].strip() if i > 0 else ""
                if not linha_anterior.startswith("# Translators:"):
                    violacoes.append(
                        f"Linha {i + 1}: _() sem '# Translators:' antes: {linha.strip()[:80]}"
                    )
        assert not violacoes, (
            "R13: strings _() sem comentario # Translators: na linha anterior:\n"
            + "\n".join(violacoes)
        )

    def test_codigo_nao_usa_time_sleep(self, fluxo_report: FluxoReport):
        """
        R16: codigo nao deve usar time.sleep() — bloqueia a thread principal do NVDA
        e congela toda a interface de acessibilidade durante o sleep.
        """
        if not fluxo_report.success or not fluxo_report.has_init_py:
            pytest.skip("__init__.py nao disponivel")
        code = _ler_init_py(fluxo_report.addon_folder)
        assert "time.sleep(" not in code, (
            "R16: codigo usa time.sleep() que bloqueia a thread principal do NVDA. "
            "Use wx.CallLater ou threading.Timer para delays assincronos."
        )

    def test_codigo_usa_tabs_para_indentacao(self, fluxo_report: FluxoReport):
        """
        R17: codigo NVDA deve usar TABs para indentacao, nao espacos.
        O NVDA e historicamente indentado com TABs; misturar causa IndentationError.
        """
        if not fluxo_report.success or not fluxo_report.has_init_py:
            pytest.skip("__init__.py nao disponivel")
        code = _ler_init_py(fluxo_report.addon_folder)
        linhas_com_conteudo = [
            line for line in code.splitlines() if line and not line.startswith("#")
        ]
        linhas_indentadas = [line for line in linhas_com_conteudo if line and line[0] in (" ", "\t")]
        linhas_com_espacos = [line for line in linhas_indentadas if line.startswith("    ")]
        assert not linhas_com_espacos, (
            f"R17: {len(linhas_com_espacos)} linha(s) indentadas com espacos em vez de TABs. "
            "O NVDA usa TABs — misturar causa IndentationError ao importar o plugin."
        )

    def test_manifest_url_e_https(self, fluxo_report: FluxoReport):
        """
        R22: url no manifest.ini deve comecar com https://.
        URLs http:// sao inseguras e podem ser bloqueadas pelo repositorio do NVDA.
        """
        if not fluxo_report.success or not fluxo_report.has_manifest:
            pytest.skip("manifest.ini nao disponivel")
        content = _ler_manifest(fluxo_report.addon_folder)
        fields = _parse_manifest_fields(content)
        url_val = fields.get("url", "").strip()
        if not url_val:
            return  # campo url ausente e opcional — outro teste cobre campos obrigatorios
        assert url_val.startswith("https://"), (
            f"R22: manifest.ini url deve comecar com https://, encontrado: {url_val!r}. "
            "URLs http:// sao inseguras e rejeitadas pelo repositorio oficial do NVDA."
        )

    def test_imports_terceiros_com_try_except(self, fluxo_report: FluxoReport):
        """
        R19: imports de bibliotecas de terceiros NAO devem aparecer no nivel de modulo.
        Devem ser lazy (dentro de funcao ou bloco try/except) para nao travar o NVDA
        se a biblioteca nao estiver instalada.
        """
        if not fluxo_report.success or not fluxo_report.has_init_py:
            pytest.skip("__init__.py nao disponivel")
        code = _ler_init_py(fluxo_report.addon_folder)
        # Bibliotecas comuns que NAO fazem parte do NVDA nem da stdlib
        THIRD_PARTY = [
            "requests", "ollama", "pydantic",
            "tinydb", "httpx", "aiohttp", "boto3", "paramiko",
        ]
        violacoes: list[str] = []
        for lib in THIRD_PARTY:
            padrao = rf"^import {lib}\b|^from {lib}\b"
            if re.search(padrao, code, re.MULTILINE):
                violacoes.append(lib)
        assert not violacoes, (
            f"R19: import(s) de 3rd party no nivel de modulo: {violacoes}. "
            "Use imports lazy (dentro de funcao ou try/except) para nao travar o NVDA "
            "se a biblioteca nao estiver instalada no ambiente do usuario."
        )
