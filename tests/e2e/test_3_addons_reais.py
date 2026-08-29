import os
import zipfile
import tempfile
import time
from dataclasses import dataclass, field
import pytest

# Carrega .env da raiz do repositorio se existir. Caminho derivado do proprio
# arquivo (nao hardcoded em c:\nvdastudio) para que a suite rode em qualquer
# checkout/CI; python-dotenv e opcional para nao quebrar a COLETA do pytest
# quando ausente -- os testes deste modulo ja sao skipados sem as chaves.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=os.path.join(_REPO_ROOT, ".env"), override=False)
except ImportError:
    pass

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

pytestmark = skip_unless_ollama


@dataclass
class AddonResult:
    """Resultado completo de um fluxo de criacao de addon."""
    addon_name: str
    query: str
    pipeline_events: list = field(default_factory=list)
    final_output: str = ""
    zip_path: str = ""
    zip_names: list = field(default_factory=list)
    duration_seconds: float = 0.0
    errors: list = field(default_factory=list)

    @property
    def has_manifest(self) -> bool:
        return "manifest.ini" in self.zip_names

    @property
    def has_global_plugin(self) -> bool:
        return any("globalPlugins" in n for n in self.zip_names)

    @property
    def manifest_sem_secao(self) -> bool:
        return "[add-on]" not in self.final_output

    @property
    def event_types(self) -> set:
        return {e[0] for e in self.pipeline_events}

    def print_summary(self):
        print(f"\n{'='*60}")
        print(f"ADDON: {self.addon_name} ({self.duration_seconds:.1f}s)")
        print(f"  Eventos: {len(self.pipeline_events)}")
        print(f"  Tipos:   {sorted(self.event_types)}")
        print(f"  ZIP:     {self.zip_path}")
        print(f"  Arquivos no ZIP: {len(self.zip_names)}")
        for n in self.zip_names:
            print(f"    {n}")
        if self.errors:
            print(f"  ERROS: {self.errors}")
        print(f"{'='*60}")



def _rodar_pipeline(addon_name: str, query: str, tmpdir: str) -> AddonResult:
    """
    Executa o pipeline completo para um addon e retorna AddonResult.
    Nao executa o codigo gerado (Regra 9).
    """
    from nvdastudio.core.orchestrator import Orchestrator
    from nvdastudio.builder.addon_builder import (
        extract_code_blocks, save_addon_files, package_addon
    )

    result = AddonResult(addon_name=addon_name, query=query)
    orch_results = []
    t0 = time.time()

    orch = Orchestrator()
    orch.initialize()
    orch.set_callbacks(
        on_progress=lambda ev, det: result.pipeline_events.append((ev, det)),
        on_complete=lambda r: orch_results.append(r),
    )

    try:
        orch._run_pipeline(query)
    except Exception as e:
        result.errors.append(f"Pipeline: {e}")
        result.duration_seconds = time.time() - t0
        return result

    result.duration_seconds = time.time() - t0

    if not orch_results:
        result.errors.append("on_complete nao chamado")
        return result

    orch_result = orch_results[0]
    result.final_output = orch_result.final_output or ""

    # Extrair blocos, salvar e empacotar — nunca executar (Regra 9)
    blocks = extract_code_blocks(result.final_output)
    if not blocks:
        result.errors.append("Nenhum bloco de codigo extraido do output")
        return result

    try:
        folder, _ = save_addon_files(blocks, tmpdir, addon_name)
        zip_path = package_addon(folder)
        result.zip_path = zip_path
        with zipfile.ZipFile(zip_path) as zf:
            result.zip_names = zf.namelist()
    except Exception as e:
        result.errors.append(f"Empacotamento: {e}")

    return result



# ---------------------------------------------------------------------------
# ADDON 1: AnunciadorClipboard
# Proposito: anunciar conteudo do clipboard via NVDA+Shift+C
# Tipo: GlobalPlugin simples — sem agente interno
# ---------------------------------------------------------------------------

class TestAddon1AnunciadorClipboard:
    """
    Addon 1: GlobalPlugin que anuncia o clipboard.
    Fluxo: pipeline simples, sem design_review (complexity=medium).
    """

    def test_pipeline_completo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            r = _rodar_pipeline(
                addon_name="AnunciadorClipboard",
                query=(
                    "Crie um GlobalPlugin NVDA chamado AnunciadorClipboard. "
                    "Atalho NVDA+Shift+C. Usa win32clipboard ou ctypes para ler o clipboard. "
                    "Anuncia o conteudo via ui.message(). "
                    "Se o clipboard estiver vazio, anuncia 'Clipboard vazio'. "
                    "Inclua addonHandler.initTranslation(), terminate() e try/except."
                ),
                tmpdir=tmpdir,
            )
            r.print_summary()

            assert not r.errors, f"Erros no pipeline: {r.errors}"
            assert r.final_output, "Output final vazio"
            assert len(r.final_output) > 100, "Output muito curto"

    def test_output_contem_estrutura_nvda(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            r = _rodar_pipeline(
                addon_name="AnunciadorClipboard",
                query=(
                    "Crie um GlobalPlugin NVDA chamado AnunciadorClipboard. "
                    "Atalho NVDA+Shift+C. Le o clipboard e anuncia o conteudo via ui.message()."
                ),
                tmpdir=tmpdir,
            )
            out = r.final_output.lower()
            assert "globalplugin" in out or "globalPluginHandler" in r.final_output
            assert "import" in out

    def test_zip_estrutura_correta(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            r = _rodar_pipeline(
                addon_name="AnunciadorClipboard",
                query=(
                    "Crie um GlobalPlugin NVDA chamado AnunciadorClipboard. "
                    "Atalho NVDA+Shift+C. Anuncia o clipboard via ui.message(). "
                    "Inclua manifest.ini com name=anunciadorClipboard, version=1.0.0, "
                    "minimumNVDAVersion=2026.1.1, lastTestedNVDAVersion=2026.1.1."
                ),
                tmpdir=tmpdir,
            )
            if r.errors:
                pytest.skip(f"Pipeline falhou: {r.errors}")

            assert r.zip_path, "ZIP nao foi gerado"
            assert zipfile.is_zipfile(r.zip_path), "ZIP invalido"

            # Estrutura exigida pelo NVDA
            assert r.has_manifest, f"manifest.ini ausente. ZIP: {r.zip_names}"
            assert r.has_global_plugin, f"globalPlugins/ ausente. ZIP: {r.zip_names}"

            # manifest.ini sem [add-on] (causa de erro de instalacao)
            with zipfile.ZipFile(r.zip_path) as zf:
                if "manifest.ini" in zf.namelist():
                    content = zf.read("manifest.ini").decode("utf-8", errors="replace")
                    assert "[add-on]" not in content, (
                        "manifest.ini NAO pode ter secao [add-on] — NVDA rejeita"
                    )

    def test_eventos_pipeline_emitidos(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            r = _rodar_pipeline(
                addon_name="AnunciadorClipboard",
                query="Crie um GlobalPlugin NVDA que anuncia o clipboard ao pressionar NVDA+Shift+C",
                tmpdir=tmpdir,
            )
            assert "PLANEJANDO" in r.event_types, f"Evento PLANEJANDO ausente. Eventos: {r.event_types}"
            concluido_ou_erro = "CONCLUIDO" in r.event_types or "ERRO" in r.event_types
            assert concluido_ou_erro, f"Nem CONCLUIDO nem ERRO emitidos. Eventos: {r.event_types}"



# ---------------------------------------------------------------------------
# ADDON 2: AuditorFoco
# Proposito: anuncia classe e nome do objeto com foco a cada mudanca
# Tipo: GlobalPlugin com event_gainFocus — uso de eventos NVDA
# ---------------------------------------------------------------------------

class TestAddon2AuditorFoco:
    """
    Addon 2: GlobalPlugin que usa event_gainFocus para monitorar foco.
    Testa que o pipeline gera codigo com eventos NVDA corretamente.
    """

    def test_pipeline_completo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            r = _rodar_pipeline(
                addon_name="AuditorFoco",
                query=(
                    "Crie um GlobalPlugin NVDA chamado AuditorFoco. "
                    "Implemente o metodo event_gainFocus(self, obj, nextHandler). "
                    "Quando o foco mudar, anuncia: nome do controle + classe da janela. "
                    "Usa api.getFocusObject() para obter o objeto. "
                    "Chama nextHandler() para nao quebrar a cadeia de eventos. "
                    "Inclua addonHandler.initTranslation() e terminate()."
                ),
                tmpdir=tmpdir,
            )
            r.print_summary()
            assert not r.errors, f"Erros: {r.errors}"
            assert r.final_output, "Output vazio"

    def test_output_tem_event_gain_focus(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            r = _rodar_pipeline(
                addon_name="AuditorFoco",
                query=(
                    "Crie um GlobalPlugin NVDA com event_gainFocus que anuncia "
                    "o nome e classe do objeto focado. Chama nextHandler()."
                ),
                tmpdir=tmpdir,
            )
            out = r.final_output
            has_event = "event_gainFocus" in out or "gainFocus" in out.lower()
            has_next = "nextHandler" in out
            assert has_event, "event_gainFocus ausente no output"
            assert has_next, "nextHandler() ausente — viola NVDA-001"

    def test_zip_valido_e_instalavel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            r = _rodar_pipeline(
                addon_name="AuditorFoco",
                query=(
                    "Crie um GlobalPlugin NVDA chamado AuditorFoco que monitora "
                    "mudancas de foco com event_gainFocus e anuncia o nome do controle. "
                    "Inclua manifest.ini com name=auditorFoco, version=1.0.0, "
                    "minimumNVDAVersion=2026.1.1, lastTestedNVDAVersion=2026.1.1."
                ),
                tmpdir=tmpdir,
            )
            if r.errors:
                pytest.skip(f"Pipeline falhou: {r.errors}")

            assert r.zip_path, "ZIP nao gerado"
            assert zipfile.is_zipfile(r.zip_path)

            # Valida que manifest.ini esta na raiz do ZIP (nao em subpasta)
            assert "manifest.ini" in r.zip_names, (
                f"manifest.ini ausente na raiz do ZIP. Conteudo: {r.zip_names}"
            )

            # Valida que lastTestedNVDAVersion >= 2025.1 no manifest
            with zipfile.ZipFile(r.zip_path) as zf:
                if "manifest.ini" in zf.namelist():
                    content = zf.read("manifest.ini").decode("utf-8", errors="replace")
                    has_last_tested = "lastTestedNVDAVersion" in content
                    if has_last_tested:
                        # Extrai valor e verifica que e >= 2025.1
                        for line in content.splitlines():
                            if "lastTestedNVDAVersion" in line:
                                val = line.split("=")[-1].strip()
                                year = int(val.split(".")[0]) if val and val[0].isdigit() else 0
                                assert year >= 2025, (
                                    f"lastTestedNVDAVersion={val} muito antigo — "
                                    f"NVDA 2025.x rejeita (BACK_COMPAT_TO=2025.1)"
                                )

    def test_eventos_incluem_steps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            r = _rodar_pipeline(
                addon_name="AuditorFoco",
                query=(
                    "Crie um GlobalPlugin NVDA com event_gainFocus que anuncia "
                    "o nome do controle focado."
                ),
                tmpdir=tmpdir,
            )
            step_events = {"EXECUTANDO", "AVALIANDO", "APROVADO"}
            encontrados = step_events & r.event_types
            assert encontrados, (
                f"Nenhum evento de step encontrado. Eventos: {r.event_types}"
            )

