"""Regressao: a entrega nao pode ficar atras de um step que so JULGA.

Rodada real de 2026-09-02 05:20 (ResumoGemini, addon complexo minimo):
os tres code_generation aprovados (95/95/92), manifest 95, doc 95 -- o addon
inteiro pronto e aprovado. O accessibility_audit rodou ANTES do assembly,
consumiu 176.041 tokens (21% do orcamento), o teto estourou por 2%
(853.455/836.850) e a UNICA etapa que nao rodou foi o assembly.

O addon estava pronto e foi descartado por uma auditoria que nao entrega nada.
"""
from nvdastudio.core.planner import (
	ExecutionStep, Planner, _desatrelar_assembly_de_consultivos,
	STEP_ASSEMBLY, STEP_ACCESSIBILITY_AUDIT, STEP_CODE_GENERATION,
	STEP_ENGINEERING_REVIEW,
)


def _step(sid, stype, deps=()):
	return ExecutionStep(
		step_id=sid, step_type=stype, description="d", model_id="m",
		depends_on=list(deps), context_from_steps=list(deps),
	)


class TestDesatrelarAssembly:
	def test_assembly_nao_espera_auditoria(self):
		steps = [
			_step("cg1", STEP_CODE_GENERATION),
			_step("audit1", STEP_ACCESSIBILITY_AUDIT, ["cg1"]),
			_step("asm", STEP_ASSEMBLY, ["cg1", "audit1"]),
		]
		asm = _desatrelar_assembly_de_consultivos(steps)[2]
		assert asm.depends_on == ["cg1"]
		assert "audit1" not in asm.context_from_steps

	def test_solta_todos_os_tipos_consultivos(self):
		steps = [
			_step("cg1", STEP_CODE_GENERATION),
			_step("er1", STEP_ENGINEERING_REVIEW, ["cg1"]),
			_step("audit1", STEP_ACCESSIBILITY_AUDIT, ["cg1"]),
			_step("asm", STEP_ASSEMBLY, ["cg1", "er1", "audit1"]),
		]
		assert _desatrelar_assembly_de_consultivos(steps)[3].depends_on == ["cg1"]

	def test_assembly_so_com_consultivos_fica_como_esta(self):
		"""Sem esta guarda o assembly ficaria PRONTO na primeira volta do
		orchestrator -- antes de qualquer codigo existir -- e empacotaria o
		vazio. Melhor esperar do que entregar um zip sem addon dentro."""
		steps = [
			_step("audit1", STEP_ACCESSIBILITY_AUDIT),
			_step("asm", STEP_ASSEMBLY, ["audit1"]),
		]
		assert _desatrelar_assembly_de_consultivos(steps)[1].depends_on == ["audit1"]

	def test_nao_mexe_em_quem_nao_e_assembly(self):
		steps = [
			_step("cg1", STEP_CODE_GENERATION),
			_step("audit1", STEP_ACCESSIBILITY_AUDIT, ["cg1"]),
			_step("doc1", "documentation", ["cg1", "audit1"]),
		]
		assert _desatrelar_assembly_de_consultivos(steps)[2].depends_on == ["cg1", "audit1"]

	def test_idempotente(self):
		steps = [
			_step("cg1", STEP_CODE_GENERATION),
			_step("audit1", STEP_ACCESSIBILITY_AUDIT, ["cg1"]),
			_step("asm", STEP_ASSEMBLY, ["cg1", "audit1"]),
		]
		uma = _desatrelar_assembly_de_consultivos(steps)[2].depends_on
		assert _desatrelar_assembly_de_consultivos(steps)[2].depends_on == uma


class TestAssemblyInjetado:
	def test_injetado_nao_depende_de_consultivo(self):
		"""O outro lado da costura: quando o assembly e NOSSO (injetado),
		ele ja nasce sem a dependencia consultiva."""
		planner = Planner.__new__(Planner)
		steps = [
			_step("cg1", STEP_CODE_GENERATION),
			_step("audit1", STEP_ACCESSIBILITY_AUDIT, ["cg1"]),
		]
		resultado = planner._inject_assembly(steps, "medium")
		asm = [s for s in resultado if s.step_type == STEP_ASSEMBLY]
		assert len(asm) == 1, "o assembly tem que ter sido injetado"
		assert asm[0].depends_on == ["cg1"]

	def test_injetado_com_so_consultivos_nao_fica_sem_dependencia(self):
		planner = Planner.__new__(Planner)
		resultado = planner._inject_assembly([_step("audit1", STEP_ACCESSIBILITY_AUDIT)], "medium")
		asm = [s for s in resultado if s.step_type == STEP_ASSEMBLY][0]
		assert asm.depends_on == ["audit1"]
