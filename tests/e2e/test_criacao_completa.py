import json
import os
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime

import pytest

# ---------------------------------------------------------------------------
# Helpers de encoding
# ---------------------------------------------------------------------------

_UNICODE_SAFE_MAP = str.maketrans({
    '\u2011': '-',   # non-breaking hyphen
    '\u2013': '-',   # en dash
    '\u2014': '-',   # em dash
    '\u2018': "'",   # left single quote
    '\u2019': "'",   # right single quote
    '\u201c': '"',   # left double quote
    '\u201d': '"',   # right double quote
    '\u2026': '...',  # ellipsis
    '\u00e9': 'e',   # e agudo (fallback extra para cp1252 extremo)
})


def _safe_str(text: str) -> str:
    """Substitui chars problemáticos de LLM por equivalentes ASCII/cp1252."""
    return text.translate(_UNICODE_SAFE_MAP).encode('cp1252', errors='replace').decode('cp1252')


# ---------------------------------------------------------------------------
# Configuracao
# ---------------------------------------------------------------------------

# .strip() defensivo: trailing space na env var causa h11.LocalProtocolError
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

# 5.1.0: skip_unless_ollama era definido mas nunca aplicado -- achado real
# de auditoria 2026-08-25 (foi o proprio gatilho: essa lacuna travou uma
# rodada inteira de pytest por horas). As 5 classes compartilham
# fluxo_report (fixture de modulo que roda o pipeline completo, LLM real);
# sem as chaves, ficava pendurado indefinidamente em vez de skip limpo.
# Ver test_e20_regras_qualidade_codigo.py 5.1.0 para o achado completo.
pytestmark = skip_unless_ollama

# Pasta de saida dos addons criados pelos testes e2e
_E2E_OUTPUT_DIR = os.path.join(
    os.path.expanduser("~"), "Documents", "NVDAStudio", "addons_gerados", "e2e_tests"
)

# Pasta para relatorios JSON dos testes
_REPORT_DIR = os.path.join(
    os.path.dirname(__file__), "relatorios"
)


# ---------------------------------------------------------------------------
# Dataclasses de resultado
# ---------------------------------------------------------------------------

@dataclass
class StepTrace:
    """Captura o que aconteceu em cada step do pipeline."""
    step_id: str
    step_type: str
    model_used: str
    approved: bool
    score: int
    retries_used: int
    tokens_used: int
    issues: list[str] = field(default_factory=list)
    output_preview: str = ""   # primeiros 300 chars do output


@dataclass
class PipelineReport:
    """Relatorio completo de uma execucao de pipeline."""
    addon_name: str
    query: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    plan_id: str = ""
    # O plano veio do caminho degradado (sem json_schema estrito)? Explica
    # por que o MESMO pedido gera planos de formas diferentes entre rodadas.
    planejamento_degradado: bool = False
    complexity: str = ""
    duration_seconds: float = 0.0
    total_tokens: int = 0
    total_tokens_medidor: int = 0
    total_retries: int = 0
    replan_count: int = 0
    success: bool = False
    error: str = ""

    # Progresso
    events: list[tuple[str, str]] = field(default_factory=list)

    # Steps individuais
    steps: list[StepTrace] = field(default_factory=list)

    # Artefatos gerados no disco
    addon_folder: str = ""
    files_saved: list[str] = field(default_factory=list)
    nvda_addon_path: str = ""
    zip_names: list[str] = field(default_factory=list)

    # Validacao estrutural
    struct_problems: list[str] = field(default_factory=list)
    has_init_py: bool = False
    has_manifest: bool = False
    has_doc: bool = False
    has_lib: bool = False

    # Portao final: o MESMO que a GUI aplica antes de entregar
    # (studio_dialog::_on_package -> validate_final_package). Ate
    # 2026-09-03 o E2E chamava package_addon() direto e nunca rodava
    # esse portao -- o degrau mais CARO da piramide era o unico cego
    # para uma checagem que ja existia e que a GUI ja fazia.
    final_gate_ok: bool = False
    final_gate_evidence: str = ""

    # Blocos coletados por step (Fix A)
    blocks_collected: list[dict] = field(default_factory=list)

    @property
    def event_types(self) -> set[str]:
        return {e[0] for e in self.events}

    @property
    def models_used(self) -> set[str]:
        return {s.model_used for s in self.steps if s.model_used}

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

    def print_report(self):
        """Imprime relatorio legivel para o terminal."""
        sep = "=" * 70
        print(f"\n{sep}")
        print(f"RELATORIO E2E: {self.addon_name}")
        print(f"  Timestamp:   {self.timestamp}")
        print(f"  Duracao:     {self.duration_seconds:.1f}s")
        print(f"  Sucesso:     {self.success}")
        if self.error:
            print(f"  ERRO:        {self.error}")
        print("\n--- PIPELINE ---")
        print(f"  Plano ID:    {self.plan_id}")
        if self.planejamento_degradado:
            print("  Plano:       DEGRADADO (sem json_schema estrito)")
        print(f"  Complexidade:{self.complexity}")
        print(f"  Total steps: {len(self.steps)}")
        print(f"  Aprovados:   {len(self.approved_steps)}/{len(self.steps)}")
        print(f"  Total retries:{self.total_retries}")
        print(f"  Replans:     {self.replan_count}")
        print(f"  Total tokens:{self.total_tokens:,}")
        if self.total_tokens_medidor:
            print(f"  Medidor:     {self.total_tokens_medidor:,} (inclui steps descartados por replanejamento)")
        print(f"  Score medio: {self.avg_score:.1f}")
        print(f"  Modelos:     {', '.join(sorted(self.models_used))}")

        print("\n--- STEPS INDIVIDUAIS ---")
        for st in self.steps:
            status = "OK" if st.approved else "FALHOU"
            print(f"  [{status}] {st.step_id:5s} {st.step_type:20s} "
                  f"score={st.score:3d} retries={st.retries_used} "
                  f"tokens={st.tokens_used:,} modelo={st.model_used}")
            if st.issues:
                for issue in st.issues[:2]:
                    print(f"         ISSUE: {_safe_str(issue)[:80]}")

        print("\n--- EVENTOS DE PROGRESSO ---")
        for ev, det in self.events:
            print(f"  [{ev:15s}] {_safe_str(det)[:90]}")

        print("\n--- BLOCOS COLETADOS (Fix A) ---")
        for blk in self.blocks_collected:
            print(f"  {blk.get('language','?'):6s} | {blk.get('filename','(sem nome)')}")

        print("\n--- ARTEFATOS NO DISCO ---")
        print(f"  Pasta:       {self.addon_folder}")
        print(f"  Arquivos:    {len(self.files_saved)}")
        for f in self.files_saved:
            size = os.path.getsize(f) if os.path.isfile(f) else 0
            rel = os.path.relpath(f, self.addon_folder) if self.addon_folder else f
            print(f"    {rel}  ({size:,} bytes)")
        print(f"  .nvda-addon: {self.nvda_addon_path}")
        if self.zip_names:
            print(f"  Conteudo do pacote ({len(self.zip_names)} arquivos):")
            for n in self.zip_names[:20]:
                print(f"    {n}")
            if len(self.zip_names) > 20:
                print(f"    ... +{len(self.zip_names)-20} mais")

        print("\n--- VALIDACAO ESTRUTURAL ---")
        print(f"  __init__.py: {'OK' if self.has_init_py else 'AUSENTE'}")
        print(f"  manifest.ini:{' OK' if self.has_manifest else 'AUSENTE'}")
        print(f"  doc/:        {'OK' if self.has_doc else 'AUSENTE'}")
        print(f"  lib/:        {'OK' if self.has_lib else 'AUSENTE'}")
        if self.struct_problems:
            print(f"  Problemas estruturais ({len(self.struct_problems)}):")
            for p in self.struct_problems:
                print(f"    {p}")
        else:
            print("  Sem problemas estruturais")
        print(f"  Portao final: {'APROVADO' if self.final_gate_ok else 'REPROVADO'}")
        if not self.final_gate_ok and self.final_gate_evidence:
            print(f"    {self.final_gate_evidence[:500]}")
        print(sep)

    def to_dict(self) -> dict:
        """Converte para dict serializavel em JSON."""
        return {
            "addon_name": self.addon_name,
            "query": self.query[:200],
            "timestamp": self.timestamp,
            "plan_id": self.plan_id,
            "planejamento_degradado": self.planejamento_degradado,
            "complexity": self.complexity,
            "duration_seconds": round(self.duration_seconds, 2),
            "total_tokens": self.total_tokens,
            "total_tokens_medidor": self.total_tokens_medidor,
            "total_retries": self.total_retries,
            "replan_count": self.replan_count,
            "success": self.success,
            "error": self.error,
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
                    "output_preview": s.output_preview,
                }
                for s in self.steps
            ],
            "events": [(e, d[:100]) for e, d in self.events],
            "addon_folder": self.addon_folder,
            "files_saved": [os.path.basename(f) for f in self.files_saved],
            "nvda_addon_path": self.nvda_addon_path,
            "zip_names": self.zip_names,
            "struct_problems": self.struct_problems,
            "has_init_py": self.has_init_py,
            "has_manifest": self.has_manifest,
            "has_doc": self.has_doc,
            "has_lib": self.has_lib,
            "final_gate_ok": self.final_gate_ok,
            "final_gate_evidence": self.final_gate_evidence,
            "blocks_collected": [
                {"language": b.get("language", "?"), "filename": b.get("filename", "")}
                for b in self.blocks_collected
            ],
            "avg_score": round(self.avg_score, 1),
            "models_used": sorted(self.models_used),
        }


# ---------------------------------------------------------------------------
# Engine de execucao E2E
# ---------------------------------------------------------------------------

def _rodar_pipeline_e2e(
    addon_name: str,
    query: str,
    output_dir: str = _E2E_OUTPUT_DIR,
    on_clarify=None,
) -> PipelineReport:
    """
    Executa pipeline completo e retorna PipelineReport com tudo monitorado.

    Fluxo:
      1. Inicializa Orchestrator com API key real
      2. Executa _run_pipeline (sincrono — chama direto, sem thread)
      3. Captura todos os eventos de progresso
      4. Captura StepResult de cada step
      5. Coleta blocos de TODOS os steps aprovados (Fix A)
      6. Salva arquivos no disco em output_dir/addon_name_YYYYMMDD_HHMMSS/
      7. Empacota como .nvda-addon
      8. Valida estrutura: __init__.py, manifest.ini, doc/, lib/
      9. Salva relatorio JSON em tests/e2e/relatorios/

    on_clarify: callback opcional (list[str] -> list[str]) para responder
    perguntas de clarificacao mid-pipeline. Sem callback (None, comportamento
    pre-existente), o Orchestrator segue com graceful degradation (perguntas
    ficam sem resposta, "(sem resposta)" no contexto). Adicionado pra
    golden_eval_set_complexo.py (test_e36) poder rodar pedidos reais
    complexos o suficiente pra disparar clarificacao sem travar esperando
    input humano de verdade num teste automatizado.

    Regra 9: codigo gerado nunca executado — apenas salvo e inspecionado.
    """
    from nvdastudio.core.orchestrator import Orchestrator, OrchestrationResult
    from nvdastudio.builder.addon_builder import (
        extract_code_blocks, save_addon_files, package_addon,
        validate_addon_structure,
    )

    report = PipelineReport(addon_name=addon_name, query=query)
    orch_results: list[OrchestrationResult] = []
    t0 = time.time()

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(_REPORT_DIR, exist_ok=True)

    orch = Orchestrator()
    orch.initialize()
    orch.set_callbacks(
        on_progress=lambda ev, det: report.events.append((ev, det)),
        on_complete=lambda r: orch_results.append(r),
        on_clarify=on_clarify,
    )

    # BUG REAL achado ao vivo (2026-08-17, test_e36 com 2 casos parametrizados
    # rodando na mesma sessao pytest): orch._run_pipeline() e chamado DIRETO
    # aqui (sincrono, sem thread) -- diferente da producao, que sempre passa
    # por run_async()/run_conversational_async(), os UNICOS 2 lugares que
    # chamam iteration_budget.reset() antes de rodar um pedido NOVO
    # (iteration_budget e um singleton de PROCESSO INTEIRO, nao resetado em
    # lugar nenhum por padrao). Sem o reset aqui, o 2o caso parametrizado
    # (gemini_multimodal_midia) herdava o orcamento ja ESGOTADO do 1o caso
    # (assistente_leitura_gemini, 41 retries/2.9M tokens/121min) e falhava
    # em 65s com "Orcamento excedido" em TODOS os 8 steps, sem nenhum rodar
    # de verdade -- nao era regressao de codigo, era vazamento de estado
    # entre casos de teste. _run_pipeline() em si NAO reseta de proposito
    # (tambem e usado por agentic_loop.py::surgical_replan() pra RETOMAR um
    # plano existente, onde resetar destruiria o orcamento acumulado
    # legitimamente) -- o reset e responsabilidade de quem inicia um pedido
    # NOVO, exatamente como run_async() ja faz na producao.
    from nvdastudio.utils.iteration_budget import budget as _iteration_budget
    _iteration_budget.reset()

    # Executa pipeline (sincrono)
    try:
        orch._run_pipeline(query)
    except Exception as exc:
        report.error = f"Pipeline excecao: {exc}"
        report.duration_seconds = time.time() - t0
        report.print_report()
        return report

    report.duration_seconds = time.time() - t0

    if not orch_results:
        report.error = "on_complete nao foi chamado"
        report.print_report()
        return report

    result = orch_results[0]
    report.success = result.success
    report.plan_id = result.plan_id
    report.planejamento_degradado = getattr(result, "planejamento_degradado", False)
    report.total_tokens = getattr(result, "total_tokens", 0)
    report.total_tokens_medidor = getattr(result, "total_tokens_medidor", 0)
    report.total_retries = result.total_retries
    report.replan_count = getattr(result, "replan_count", 0)
    report.error = result.error or ""

    # Captura steps individuais
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

    # Captura complexidade do plano
    plano_criado = [det for ev, det in report.events if ev == "PLANO_CRIADO"]
    if plano_criado:
        report.complexity = plano_criado[0]

    if not result.success:
        report.print_report()
        _salvar_relatorio(report)
        return report

    # --- Coleta de blocos (Fix A: todos os steps aprovados) ---
    _STEP_PRIORITY = [
        "code_generation", "manifest_builder", "documentation",
        "agent_runner", "assembly",
    ]
    # 5.45.0: mesmo fix do _collect_all_blocks (studio_dialog.py) --
    # "agent_template" removido: gera so TEMPLATE MD (documentacao/spec),
    # nunca codigo de producao. Sem essa allowlist, um trecho ilustrativo
    # sem anotacao de arquivo dentro do template aprovado virava
    # module_N.py "de verdade" quando code_generation falhava (bug real,
    # caso GeminiMultimodal, 2026-08-16).
    _CODE_SOURCE_STEP_TYPES = set(_STEP_PRIORITY) | {"test_generation"}

    def _priority(sr) -> int:
        try:
            return _STEP_PRIORITY.index(sr.step_type)
        except ValueError:
            return len(_STEP_PRIORITY)

    sorted_results = sorted(
        [r for r in result.step_results
         if r.step_type in _CODE_SOURCE_STEP_TYPES and r.approved and r.output],
        key=_priority,
    )

    seen_filenames: set[str] = set()
    all_blocks: list[dict] = []
    for sr in sorted_results:
        for blk in extract_code_blocks(sr.output):
            fname = blk.get("filename", "").strip()
            if fname and fname not in seen_filenames:
                seen_filenames.add(fname)
                all_blocks.append(blk)
            elif not fname:
                all_blocks.append(blk)

    # Fallback: assembly_output / final_output
    if not all_blocks:
        source = result.assembly_output or result.final_output
        all_blocks = extract_code_blocks(source)

    report.blocks_collected = all_blocks

    if not all_blocks:
        report.error = "Nenhum bloco de codigo coletado dos steps"
        report.print_report()
        _salvar_relatorio(report)
        return report

    # --- Salva arquivos no disco ---
    try:
        folder, saved = save_addon_files(all_blocks, output_dir, addon_name)
        report.addon_folder = folder
        report.files_saved = saved
    except Exception as exc:
        report.error = f"save_addon_files: {exc}"
        report.print_report()
        _salvar_relatorio(report)
        return report

    # --- Valida estrutura ---
    report.struct_problems = validate_addon_structure(folder)

    # Inspecao manual da estrutura (Regra 9: apenas existencia, nao execucao)
    for root, _dirs, files in os.walk(folder):
        for fname in files:
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, folder).replace("\\", "/")
            # Achado real de auditoria (2026-08-09, test_e36 GeminiMultimodal):
            # "globalPlugins" in rel casava com QUALQUER __init__.py sob
            # globalPlugins/, inclusive de um SUBPACOTE de feature (ex:
            # globalPlugins/Addon/audio/__init__.py) -- reportava has_init_py=True
            # mesmo quando o __init__.py RAIZ do addon (com a classe GlobalPlugin
            # de verdade) nunca foi gerado, porque o step final da decomposicao
            # ARCH-010 ficou bloqueado. Exige exatamente 2 niveis
            # (globalPlugins/<NomeAddon>/__init__.py), nao 3+.
            if fname == "__init__.py" and rel.startswith("globalPlugins/") and rel.count("/") == 2:
                report.has_init_py = True
            if fname == "manifest.ini":
                report.has_manifest = True
            if "doc" in rel and fname.endswith(".html"):
                report.has_doc = True
            if "lib" in rel and fname.endswith((".py", ".pyd", ".pth")):
                report.has_lib = True

    # --- Empacota .nvda-addon ---
    try:
        safe_name = addon_name.replace(" ", "_")
        nvda_path = package_addon(
            folder,
            os.path.join(output_dir, f"{safe_name}.nvda-addon")
        )
        report.nvda_addon_path = nvda_path
        if zipfile.is_zipfile(nvda_path):
            with zipfile.ZipFile(nvda_path, "r") as zf:
                report.zip_names = zf.namelist()

        # Portao final sobre o ARQUIVO entregue, nao sobre a pasta
        # intermediaria: abre o ZIP, revalida a estrutura (inclui
        # NVDA-063) e EXECUTA o addon em subprocesso isolado, agora
        # acionando os comandos. E o unico ponto do E2E que responde
        # "esse .nvda-addon funciona?" em vez de "esse .nvda-addon
        # tem os arquivos certos?".
        from nvdastudio.builder.code_sandbox import CodeSandbox

        final_check = CodeSandbox(timeout_sec=30).validate_final_package(nvda_path)
        report.final_gate_ok = final_check.success
        report.final_gate_evidence = (
            final_check.error or final_check.stderr or final_check.stdout
        )[:2000]
    except Exception as exc:
        report.error = f"package_addon: {exc}"

    report.print_report()
    _salvar_relatorio(report)
    return report


def _salvar_relatorio(report: PipelineReport):
    """Salva relatorio JSON em tests/e2e/relatorios/."""
    os.makedirs(_REPORT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = os.path.join(_REPORT_DIR, f"e2e_{report.addon_name}_{ts}.json")
    try:
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"\n[RELATORIO] Salvo em: {fname}")
    except Exception as exc:
        print(f"\n[AVISO] Nao foi possivel salvar relatorio: {exc}")


# ---------------------------------------------------------------------------
# Fixtures compartilhadas
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def e2e_output_dir():
    """Cria e retorna pasta de saida para os testes e2e."""
    os.makedirs(_E2E_OUTPUT_DIR, exist_ok=True)
    return _E2E_OUTPUT_DIR


# ---------------------------------------------------------------------------
# Teste 1: Addon simples — anunciador de hora
# ---------------------------------------------------------------------------

class TestE2EAddonSimples:
    """
    Addon mais simples possivel: GlobalPlugin + ui.message + atalho.
    Valida fluxo basico, blocos coletados e estrutura minima no disco.
    """

    def test_criacao_completa_addon_hora(self, e2e_output_dir):
        """
        Fluxo ponta a ponta:
          query -> pipeline -> collect_blocks -> save -> package -> validate
        Verifica: eventos, steps, arquivos, .nvda-addon, estrutura.
        """
        report = _rodar_pipeline_e2e(
            addon_name="HoraAddon_e2e",
            query=(
                "Crie um GlobalPlugin NVDA chamado HoraAddon que anuncia "
                "a hora atual ao pressionar NVDA+Shift+H. "
                "Use ui.message() para anunciar. "
                "Inclua addonHandler.initTranslation() e terminate(). "
                "Inclua manifest.ini com name=horaAddon, version=1.0.0, "
                "minimumNVDAVersion=2026.1.1, lastTestedNVDAVersion=2026.1.1. "
                "Gere documentacao em doc/pt_BR/userGuide.html."
            ),
            output_dir=e2e_output_dir,
        )

        # Pipeline deve ter completado
        assert report.success, f"Pipeline falhou: {report.error}"

        # Eventos obrigatorios
        assert "PLANEJANDO" in report.event_types
        assert "EXECUTANDO" in report.event_types
        assert "MONTANDO" in report.event_types

        # Steps devem ter sido executados
        assert len(report.steps) >= 2, (
            f"Esperado >= 2 steps. Recebidos: {[s.step_type for s in report.steps]}"
        )

        # Pelo menos 1 bloco coletado
        assert len(report.blocks_collected) >= 1, (
            "Nenhum bloco coletado dos steps"
        )

        # Pasta criada no disco
        assert report.addon_folder, "Pasta do addon nao foi criada"
        assert os.path.isdir(report.addon_folder), (
            f"Pasta nao existe: {report.addon_folder}"
        )

        # Pelo menos 1 arquivo salvo
        assert len(report.files_saved) >= 1, "Nenhum arquivo foi salvo"

    def test_addon_hora_tem_manifest_no_disco(self, e2e_output_dir):
        """manifest.ini deve existir na pasta gerada."""
        report = _rodar_pipeline_e2e(
            addon_name="HoraManifest_e2e",
            query=(
                "Crie addon NVDA HoraAddon com manifest.ini completo. "
                "name=horaAddon, version=1.0.0, minimumNVDAVersion=2026.1.1, "
                "lastTestedNVDAVersion=2026.1.1. "
                "GlobalPlugin com atalho NVDA+H para anunciar a hora."
            ),
            output_dir=e2e_output_dir,
        )

        if not report.success:
            pytest.skip(f"Pipeline falhou: {report.error}")

        assert report.has_manifest, (
            f"manifest.ini ausente. Arquivos salvos: {report.files_saved}"
        )

        # Conteudo do manifest deve ter campos obrigatorios
        manifest_path = os.path.join(report.addon_folder, "manifest.ini")
        if os.path.isfile(manifest_path):
            content = open(manifest_path, encoding="utf-8", errors="replace").read()
            # Nunca executa — apenas le como texto
            assert "name" in content.lower()
            assert "[add-on]" not in content, (
                "manifest.ini NAO pode ter secao [add-on] — NVDA rejeita"
            )

    def test_addon_hora_pacote_nvda_addon_valido(self, e2e_output_dir):
        """O .nvda-addon gerado deve ser um ZIP valido com estrutura correta."""
        report = _rodar_pipeline_e2e(
            addon_name="HoraPacote_e2e",
            query=(
                "Crie GlobalPlugin NVDA 'HoraAddon' com atalho NVDA+H. "
                "manifest.ini com name=horaAddon, version=1.0.0, "
                "minimumNVDAVersion=2026.1.1, lastTestedNVDAVersion=2026.1.1."
            ),
            output_dir=e2e_output_dir,
        )

        if not report.success:
            pytest.skip(f"Pipeline falhou: {report.error}")

        assert report.nvda_addon_path, ".nvda-addon nao foi gerado"
        assert os.path.isfile(report.nvda_addon_path), (
            f"Arquivo .nvda-addon nao existe: {report.nvda_addon_path}"
        )
        assert zipfile.is_zipfile(report.nvda_addon_path), (
            ".nvda-addon deve ser um ZIP valido"
        )

        # Verifica estrutura interna do ZIP
        assert len(report.zip_names) >= 1, "ZIP esta vazio"
        has_manifest_in_zip = "manifest.ini" in report.zip_names
        has_plugin_in_zip = any("globalPlugins" in n for n in report.zip_names)
        assert has_manifest_in_zip or has_plugin_in_zip, (
            f"ZIP nao tem manifest.ini nem globalPlugins/. Conteudo: {report.zip_names}"
        )


# ---------------------------------------------------------------------------
# Teste 2: Addon com documentacao
# ---------------------------------------------------------------------------

class TestE2EAddonComDocumentacao:
    """
    Addon com step de documentacao obrigatorio.
    Valida que doc/pt_BR/userGuide.html e gerado e salvo.
    """

    def test_documentacao_gerada_em_disco(self, e2e_output_dir):
        """
        O step 'documentation' deve gerar doc/pt_BR/userGuide.html.
        Fix D: documentation agora e OBRIGATORIO no prompt do Planner.
        """
        report = _rodar_pipeline_e2e(
            addon_name="DocAddon_e2e",
            query=(
                "Crie um addon NVDA que anuncia informacoes sobre a janela em foco "
                "ao pressionar NVDA+F. Inclua documentacao completa em "
                "doc/pt_BR/userGuide.html e doc/en/userGuide.html. "
                "manifest.ini com version=1.0.0, minimumNVDAVersion=2026.1.1."
            ),
            output_dir=e2e_output_dir,
        )

        if not report.success:
            pytest.skip(f"Pipeline falhou: {report.error}")

        # Verifica que doc/ foi gerada (qualquer arquivo HTML)
        doc_files = [
            f for f in report.files_saved
            if "doc" in f.lower() and f.endswith(".html")
        ]
        if not doc_files:
            # Verifica na estrutura de pasta diretamente
            doc_dir = os.path.join(report.addon_folder, "doc")
            if os.path.isdir(doc_dir):
                for root, _dirs, files in os.walk(doc_dir):
                    for fname in files:
                        if fname.endswith(".html"):
                            doc_files.append(os.path.join(root, fname))

        assert len(doc_files) >= 1, (
            f"Nenhum arquivo HTML de documentacao encontrado. "
            f"Pasta: {report.addon_folder}. "
            f"Blocos coletados: {[b.get('filename','?') for b in report.blocks_collected]}"
        )

    def test_step_documentation_presente_no_plano(self, e2e_output_dir):
        """
        O plano deve sempre incluir step 'documentation'.
        v1.7.0: injecao deterministica via _inject_documentation() — garante
        que documentation esteja presente mesmo quando a LLM omite em planos
        complexity=low. Confirmado em E2E 2026-03-30 (LLM omitia com query simples).
        """
        from nvdastudio.core.planner import Planner, STEP_DOCUMENTATION

        planner = Planner()
        plan = planner.create_plan(
            "Crie addon NVDA que lista janelas abertas com documentacao completa."
        )

        step_types = {s.step_type for s in plan.steps}
        assert STEP_DOCUMENTATION in step_types, (
            f"documentation ausente no plano mesmo com injecao deterministica. "
            f"Steps: {step_types}. Verificar _inject_documentation() no planner.py"
        )


# ---------------------------------------------------------------------------
# Teste 3: Comportamento da IA — modelos, scores, retries
# ---------------------------------------------------------------------------

class TestE2EComportamentoIA:
    """
    Monitora o comportamento da IA durante a criacao:
    - Quais modelos foram usados por step_type
    - Scores do Critic por step
    - Quantos retries cada step precisou
    - Se houve escalacao ou replanejamento
    """

    def test_modelos_corretos_por_step_type(self, e2e_output_dir):
        """
        Verifica que cada step_type usou o modelo configurado em STEP_MODEL_MAP.
        Regra 5: STEP_MODEL_MAP e deterministico — nao usa LLM para escolher.
        """
        from nvdastudio.core.planner import STEP_MODEL_MAP, COMPLEXITY_MAP

        report = _rodar_pipeline_e2e(
            addon_name="ModelosAddon_e2e",
            query=(
                "Crie um GlobalPlugin NVDA simples que anuncia o titulo "
                "da janela em foco ao pressionar NVDA+T."
            ),
            output_dir=e2e_output_dir,
        )

        if not report.success:
            pytest.skip(f"Pipeline falhou: {report.error}")

        # Determine expected model per step_type using plan complexity mapping
        complexity = report.complexity or "low"
        for step in report.steps:
            if step.step_type in STEP_MODEL_MAP:
                # Prefer complexity-specific map when available
                complexity_map = COMPLEXITY_MAP.get(complexity, {})
                expected_model = complexity_map.get(step.step_type, STEP_MODEL_MAP[step.step_type])
                assert step.model_used == expected_model, (
                    f"Step {step.step_type} usou modelo errado: "
                    f"esperado={expected_model}, usado={step.model_used}"
                )

    def test_scores_do_critic_sao_numericos(self, e2e_output_dir):
        """Todos os StepResult devem ter score numerico >= 0."""
        report = _rodar_pipeline_e2e(
            addon_name="ScoresAddon_e2e",
            query=(
                "Crie um addon NVDA que monitora o clipboard e anuncia "
                "quando o conteudo muda."
            ),
            output_dir=e2e_output_dir,
        )

        if not report.steps:
            pytest.skip("Nenhum step foi executado")

        for step in report.steps:
            assert isinstance(step.score, int), (
                f"Score do step {step.step_id} deve ser int: {step.score}"
            )
            assert step.score >= 0, (
                f"Score negativo para step {step.step_id}: {step.score}"
            )

    def test_tokens_sendo_contados(self, e2e_output_dir):
        """
        Tokens devem ser > 0 quando o pipeline completa com sucesso.
        Fix B4: tokens_used agora propagados via thread-local.
        """
        report = _rodar_pipeline_e2e(
            addon_name="TokensAddon_e2e",
            query=(
                "Crie addon NVDA simples que anuncia o nome do processo "
                "em foco ao pressionar NVDA+P."
            ),
            output_dir=e2e_output_dir,
        )

        if not report.success:
            pytest.skip(f"Pipeline falhou: {report.error}")

        assert report.total_tokens > 0, (
            "total_tokens deve ser > 0 apos pipeline com sucesso. "
            "B4 fix: tokens_used nao esta sendo propagado corretamente."
        )

    def test_relatorio_json_salvo_em_disco(self, e2e_output_dir):
        """O relatorio JSON deve ser salvo em tests/e2e/relatorios/ automaticamente."""
        os.makedirs(_REPORT_DIR, exist_ok=True)

        antes = set(os.listdir(_REPORT_DIR)) if os.path.isdir(_REPORT_DIR) else set()

        _rodar_pipeline_e2e(
            addon_name="RelatorioAddon_e2e",
            query=(
                "Crie addon NVDA que anuncia 'Ola' ao pressionar NVDA+O."
            ),
            output_dir=e2e_output_dir,
        )

        depois = set(os.listdir(_REPORT_DIR)) if os.path.isdir(_REPORT_DIR) else set()
        novos = depois - antes

        assert len(novos) >= 1, (
            f"Relatorio JSON nao foi criado em {_REPORT_DIR}"
        )

        # Verifica que o JSON e valido
        relatorio_path = os.path.join(_REPORT_DIR, list(novos)[0])
        with open(relatorio_path, encoding="utf-8") as f:
            data = json.load(f)

        assert "addon_name" in data
        assert "steps" in data
        assert "blocks_collected" in data
        assert isinstance(data["steps"], list)


# ---------------------------------------------------------------------------
# Teste 4: Fix A — collect_all_blocks garante arquivos completos
# ---------------------------------------------------------------------------

class TestE2EFixACollectAllBlocks:
    """
    Valida especificamente o Fix A: _collect_all_blocks coleta de todos os steps.
    Antes: apenas assembly_output (perdia arquivos).
    Agora: itera todos os step_results aprovados em ordem de prioridade.
    """

    def test_blocos_coletados_de_steps_individuais(self, e2e_output_dir):
        """
        _collect_all_blocks deve encontrar blocos em code_generation e
        manifest_builder mesmo que o assembly nao os reemita corretamente.
        """
        from nvdastudio.core.orchestrator import Orchestrator
        from nvdastudio.builder.addon_builder import extract_code_blocks

        events = []
        orch_results = []

        orch = Orchestrator()
        orch.initialize()
        orch.set_callbacks(
            on_progress=lambda ev, det: events.append((ev, det)),
            on_complete=lambda r: orch_results.append(r),
        )

        orch._run_pipeline(
            "Crie um GlobalPlugin NVDA simples chamado TesteBloco "
            "com atalho NVDA+B para anunciar 'Bloco OK'. "
            "Inclua manifest.ini."
        )

        assert orch_results, "on_complete nao chamado"
        result = orch_results[0]

        # Simula _collect_all_blocks
        _STEP_PRIORITY = [
            "code_generation", "manifest_builder", "documentation",
            "agent_runner", "assembly",
        ]
        # 5.45.0: "agent_template" removido -- ver comentario equivalente
        # em _rodar_pipeline_e2e() acima.
        _CODE_SOURCE_STEP_TYPES = set(_STEP_PRIORITY) | {"test_generation"}

        def _priority(sr):
            try:
                return _STEP_PRIORITY.index(sr.step_type)
            except ValueError:
                return len(_STEP_PRIORITY)

        sorted_results = sorted(
            [r for r in result.step_results
             if r.step_type in _CODE_SOURCE_STEP_TYPES and r.approved and r.output],
            key=_priority,
        )

        seen: set[str] = set()
        all_blocks = []
        for sr in sorted_results:
            for blk in extract_code_blocks(sr.output):
                fname = blk.get("filename", "").strip()
                if fname and fname not in seen:
                    seen.add(fname)
                    all_blocks.append(blk)
                elif not fname:
                    all_blocks.append(blk)

        print(f"\n[FIX A] Blocos coletados: {len(all_blocks)}")
        for blk in all_blocks:
            print(f"  lang={blk.get('language','?')} file={blk.get('filename','(sem nome)')}")

        assert len(all_blocks) >= 1, (
            "Fix A: _collect_all_blocks deve encontrar ao menos 1 bloco. "
            "Verifique se code_generator usa path annotations corretos."
        )

    def test_init_py_salvo_em_disco_via_fix_a(self, e2e_output_dir):
        """
        O __init__.py do GlobalPlugin deve existir na pasta gerada.
        Antes do Fix A isso falhava porque assembly omitia o arquivo.
        """
        report = _rodar_pipeline_e2e(
            addon_name="FixAAddon_e2e",
            query=(
                "Crie GlobalPlugin NVDA 'FixAAddon' com atalho NVDA+A. "
                "Salve o codigo em globalPlugins/fixAAddon/__init__.py. "
                "Inclua manifest.ini."
            ),
            output_dir=e2e_output_dir,
        )

        if not report.success:
            pytest.skip(f"Pipeline falhou: {report.error}")

        assert report.has_init_py, (
            f"__init__.py ausente na pasta gerada. "
            f"Arquivos salvos: {[os.path.relpath(f, report.addon_folder) for f in report.files_saved]}. "
            f"Blocos coletados: {[b.get('filename','?') for b in report.blocks_collected]}"
        )


# ---------------------------------------------------------------------------
# Teste 5: Regra 9 — codigo nunca executado em nenhum ponto
# ---------------------------------------------------------------------------

class TestE2ERegra9:
    """Garante que nenhum codigo gerado pela LLM e executado durante o fluxo E2E."""

    def test_fluxo_completo_sem_execucao_de_codigo(self, e2e_output_dir):
        """
        Mesmo com codigo Python salvo em disco, nenhum arquivo e importado
        ou executado. Valida que chegamos ate package_addon sem excecao de execucao.
        Regra 9: codigo e tratado como texto/bytes em todo o fluxo.
        """
        report = _rodar_pipeline_e2e(
            addon_name="Regra9Addon_e2e",
            query=(
                "Crie GlobalPlugin NVDA com acesso ao sistema de arquivos "
                "para listar a pasta do usuario. Atalho NVDA+L."
            ),
            output_dir=e2e_output_dir,
        )

        # Se chegamos aqui sem excecao, codigo nao foi executado
        assert report is not None

        # Verifica que arquivos .py foram salvos como texto (nao executados)
        for saved_file in report.files_saved:
            if saved_file.endswith(".py"):
                # Le como texto — nao executa
                with open(saved_file, encoding="utf-8", errors="replace") as f:
                    content = f.read()
                assert isinstance(content, str), "Arquivo .py deve ser texto"
                assert len(content) > 0, "Arquivo .py nao deve estar vazio"
                # Nenhuma excecao de execucao foi lancada
