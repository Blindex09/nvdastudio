"""Regressao: o assembly era sempre o sacrificado quando o orcamento acabava.

Duas rodadas complexas de 2026-09-02, duas falhas identicas no mesmo lugar:

  ResumoGemini      estourou por 2%  (853.455 / 836.850)   -> asm nao rodou
  AssistenteEscrita estourou por 5%  (1.272.721/1.209.750) -> asm1 nao rodou

Nas DUAS todo o codigo do addon ja estava gerado e aprovado, e foi descartado
por falta de empacotamento. Steps que nao produzem arquivo gastaram o saldo
que faltava para a entrega.

Padrao aplicado (pesquisa 2026-09-02): "token reserve" / "budget backstop" --
nunca comecar uma etapa que nao se pode pagar para terminar. O teto efetivo de
quem NAO entrega e o teto menos a reserva; so a entrega enxerga o teto inteiro.
Quando o saldo entra na reserva, o pipeline nao para: descarta o que nao
entrega e segue direto para a entrega.
"""
import pytest

from nvdastudio.utils.iteration_budget import (
    IterationBudget, _RESERVA_DE_ENTREGA,
)
from nvdastudio.core.orchestrator import (
    Orchestrator, _NON_BLOCKING_STEP_TYPES, _STEP_TYPES_DE_ENTREGA,
)
from nvdastudio.core.planner import ExecutionStep


def _step(step_id, step_type):
    return ExecutionStep(
        step_id=step_id, step_type=step_type, description="d", model_id="m",
    )


class TestReservaNoOrcamento:
    @pytest.fixture
    def budget(self):
        b = IterationBudget()
        b.reset()
        b._limits.max_tokens = 1_000_000
        return b

    def test_com_saldo_folgado_todos_seguem(self, budget):
        budget._state.tokens_used = 100_000
        assert budget.can_continue()[0]
        assert budget.can_continue(para_entrega=True)[0]

    def test_dentro_da_reserva_so_a_entrega_segue(self, budget):
        """O caso exato das duas rodadas: saldo suficiente para empacotar,
        gasto por steps que nao empacotam."""
        budget._state.tokens_used = 1_000_000 - _RESERVA_DE_ENTREGA + 1
        assert not budget.can_continue()[0], "step comum nao pode entrar na reserva"
        assert budget.can_continue(para_entrega=True)[0], "a entrega TEM que caber"

    def test_teto_real_estourado_para_todos(self, budget):
        budget._state.tokens_used = 1_000_001
        assert not budget.can_continue()[0]
        assert not budget.can_continue(para_entrega=True)[0]

    def test_motivo_explica_que_e_reserva_nao_estouro(self, budget):
        """Relatorio que mente sobre a causa manda investigar o lugar errado."""
        budget._state.tokens_used = 1_000_000 - _RESERVA_DE_ENTREGA + 1
        motivo = budget.can_continue()[1]
        assert "reserva" in motivo.lower()

    def test_reserva_cobre_o_custo_medido_do_assembly(self):
        """Assembly aprovado custou 30.558 e 43.109 nas duas rodadas. A reserva
        precisa cobrir o pior caso com folga para retentativa e Critic."""
        assert _RESERVA_DE_ENTREGA >= 43_109 * 2


class TestDescarteEmFavorDaEntrega:
    def _orch(self):
        return Orchestrator.__new__(Orchestrator)

    def test_descarta_consultivos_e_segue_para_a_entrega(self, monkeypatch):
        import nvdastudio.core.orchestrator as mod

        chamadas = {"n": 0}

        class _Budget:
            def can_continue(self, para_entrega=False):
                chamadas["n"] += 1
                return (True, "") if para_entrega else (False, "reserva")

        monkeypatch.setattr(mod, "iteration_budget", _Budget())
        remaining = [
            _step("aa1", "accessibility_audit"),
            _step("er1", "engineering_review"),
            _step("asm1", "assembly"),
        ]
        falhos: set = set()
        ok, _ = self._orch()._saldo_permite_seguir(remaining, falhos)

        assert ok, "com saldo de reserva e um assembly pendente, tem que seguir"
        assert [s.step_id for s in remaining] == ["asm1"]
        assert falhos == {"aa1", "er1"}, (
            "os descartados precisam entrar em failed_step_ids -- "
            "_deps_partially_ready() exige isso para liberar o assembly"
        )

    def test_sem_entrega_pendente_para_de_verdade(self, monkeypatch):
        import nvdastudio.core.orchestrator as mod

        class _Budget:
            def can_continue(self, para_entrega=False):
                return (True, "") if para_entrega else (False, "reserva")

        monkeypatch.setattr(mod, "iteration_budget", _Budget())
        remaining = [_step("aa1", "accessibility_audit")]
        ok, motivo = self._orch()._saldo_permite_seguir(remaining, set())
        assert not ok and motivo == "reserva"

    def test_teto_real_estourado_nao_salva_nem_a_entrega(self, monkeypatch):
        import nvdastudio.core.orchestrator as mod

        class _Budget:
            def can_continue(self, para_entrega=False):
                return False, "estourou"

        monkeypatch.setattr(mod, "iteration_budget", _Budget())
        remaining = [_step("asm1", "assembly")]
        ok, _ = self._orch()._saldo_permite_seguir(remaining, set())
        assert not ok

    def test_saldo_normal_nao_descarta_nada(self, monkeypatch):
        import nvdastudio.core.orchestrator as mod

        class _Budget:
            def can_continue(self, para_entrega=False):
                return True, ""

        monkeypatch.setattr(mod, "iteration_budget", _Budget())
        remaining = [_step("aa1", "accessibility_audit"), _step("asm1", "assembly")]
        falhos: set = set()
        ok, _ = self._orch()._saldo_permite_seguir(remaining, falhos)
        assert ok and len(remaining) == 2 and not falhos


class TestCoerenciaEntreAsDuasListas:
    def test_consultivos_do_planner_nao_bloqueiam_no_orchestrator(self):
        """Bug introduzido em ef8a97b: engineering_review era CONSULTIVO no
        planner (assembly nao depende dele) e BLOQUEANTE aqui. Duas listas
        descrevendo o mesmo conceito e discordando -- Regra 5."""
        from nvdastudio.core.planner import _STEPS_CONSULTIVOS

        divergentes = _STEPS_CONSULTIVOS - _NON_BLOCKING_STEP_TYPES
        assert not divergentes, (
            f"step consultivo no planner mas bloqueante no orchestrator: {divergentes}"
        )

    def test_entrega_nunca_e_nao_bloqueante(self):
        """Se a entrega fosse nao-bloqueante, falhar nela sairia de mansinho."""
        assert not (_STEP_TYPES_DE_ENTREGA & _NON_BLOCKING_STEP_TYPES)


class TestFallbacksDeterministicos:
    def test_manifest_minimo_nao_tem_a_secao_proibida(self):
        """A rede de seguranca gerava exatamente o que manifest_builder.py,
        nvda_validator.py e critic.py chamam de erro grave. So aparecia no
        caminho de excecao, por isso passou despercebido."""
        from nvdastudio.builder.addon_builder import _generate_minimal_manifest

        assert "[add-on]" not in _generate_minimal_manifest("MeuAddon")

    def test_manifest_minimo_comeca_por_name(self):
        from nvdastudio.builder.addon_builder import _generate_minimal_manifest

        assert _generate_minimal_manifest("MeuAddon").startswith("name = MeuAddon")

    def test_documentation_nao_bloqueia_porque_existe_rede(self):
        """O afrouxamento so vale ENQUANTO a rede existir.

        Se alguem remover _generate_minimal_user_guide sem devolver
        documentation para os bloqueantes, o addon passa a sair sem ajuda
        nenhuma no NVDA -- silenciosamente. Este teste amarra as duas pontas.
        """
        from nvdastudio.builder import addon_builder

        assert "documentation" in _NON_BLOCKING_STEP_TYPES
        assert hasattr(addon_builder, "_generate_minimal_user_guide"), (
            "documentation so pode ser nao-bloqueante enquanto houver guia minimo"
        )

    def test_guia_minimo_e_html_valido(self):
        from nvdastudio.builder.addon_builder import _generate_minimal_user_guide

        guia = _generate_minimal_user_guide("MeuAddon")
        assert "<html" in guia and "</html>" in guia and "MeuAddon" in guia

    def test_guia_minimo_escapa_o_nome(self):
        """O nome vem do pedido do usuario -- nao entra cru no HTML."""
        from nvdastudio.builder.addon_builder import _generate_minimal_user_guide

        guia = _generate_minimal_user_guide("<script>alert(1)</script>")
        assert "<script>" not in guia and "&lt;script&gt;" in guia

    def test_guia_minimo_nao_e_injetado_quando_ja_existe_html(self, tmp_path):
        """A rede nao pode sobrescrever a documentacao real."""
        from nvdastudio.builder.addon_builder import save_addon_files

        blocos = [
            {"language": "ini", "filename": "manifest.ini",
             "code": "name = A\nsummary = s\nauthor = a\nversion = 1.0.0\n"},
            {"language": "python", "filename": "globalPlugins/A/__init__.py",
             "code": "import globalPluginHandler\n"},
            {"language": "html", "filename": "doc/pt_BR/userGuide.html",
             "code": "<html><body>guia de verdade</body></html>"},
        ]
        pasta, _ = save_addon_files(blocos, str(tmp_path), "A", use_timestamp=False)
        import pathlib as _p
        real = (_p.Path(pasta) / "doc" / "pt_BR" / "userGuide.html").read_text(encoding="utf-8")
        assert "guia de verdade" in real
