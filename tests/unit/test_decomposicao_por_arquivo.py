"""
Decomposicao por ARQUIVO, nao por feature.

MEDIDO EM EXECUCAO REAL (E2E test_e36, 3 rodadas em 2026-08-29):

    code_generation que FALHOU:  ret=3  tok=419.277
    code_generation que FALHOU:  ret=3  tok=419.007
    code_generation que FALHOU:  ret=3  tok=414.085
    code_generation que PASSOU:  ret=3  tok=127.784

Mesmas 3 tentativas, um terco do custo. A diferenca nao era o modelo nem o
loop de retry -- era quantos ARQUIVOS o step tentava produzir de uma vez. Os
caros eram reprovados por entrega parcial, com o Critic dizendo literalmente
"nao foi gerado o arquivo solicitado gemini_service.py".

O guarda de tamanho ja existia, mas media o COMPRIMENTO DA DESCRICAO -- proxy
fraco: uma descricao curta pode pedir 6 arquivos. E o prompt de replanejamento
pedia explicitamente "um step por feature/subpacote", que e exatamente o que
produzia os steps de 419 mil tokens.
"""

import inspect

from nvdastudio.core.planner import (
	MODULE_VERSION,
	_MAX_FILES_POR_CODE_STEP,
	ExecutionStep,
	Planner,
	oversized_code_generation_steps,
)

assert MODULE_VERSION == "2.35.0"


def _step(step_id: str, alvos: list[str], descricao: str = "gerar", tipo: str = "code_generation"):
	return ExecutionStep(step_id, tipo, descricao, "alto", target_files=list(alvos))


class TestGuardaPorNumeroDeArquivos:
	def test_um_arquivo_passa(self):
		assert oversized_code_generation_steps([_step("a", ["globalPlugins/X/__init__.py"])]) == []

	def test_dois_arquivos_passam(self):
		"""2 e deliberado, nao 1: um servico e o __init__.py do seu subpacote
		saem naturalmente juntos, e forcar 1 por step criaria steps triviais
		(um __init__.py vazio nao merece uma rodada de LLM)."""
		assert oversized_code_generation_steps([_step("a", ["x/s.py", "x/__init__.py"])]) == []

	def test_tres_ou_mais_e_reprovado(self):
		grande = _step("cg_feature", ["s.py", "d.py", "p.py", "t.py"])
		assert oversized_code_generation_steps([grande]) == ["cg_feature"]

	def test_descricao_longa_continua_valendo_como_rede(self):
		"""O criterio antigo nao foi removido -- virou complemento."""
		assert oversized_code_generation_steps([_step("a", ["s.py"], "x" * 2000)]) == ["a"]

	def test_step_sem_arquivo_alvo_nao_e_reprovado(self):
		"""web_research, design_review e afins nao escrevem arquivo."""
		assert oversized_code_generation_steps([_step("a", [])]) == []

	def test_so_avalia_code_generation(self):
		outro = _step("doc", ["a.py", "b.py", "c.py", "d.py"], tipo="documentation")
		assert oversized_code_generation_steps([outro]) == []

	def test_teto_e_dois(self):
		assert _MAX_FILES_POR_CODE_STEP == 2


class TestCampoNoStep:
	def test_target_files_normalizado_como_o_layout(self):
		"""Mesma normalizacao de forma de expected_files -- separador do
		Windows, barra inicial, duplicata. Sem reparo de ponto de entrada:
		um step individual nao precisa declarar o __init__.py do addon."""
		step = ExecutionStep(
			"a", "code_generation", "x", "alto",
			target_files=["globalPlugins\\X\\s.py", "/globalPlugins/X/s.py"],
		)
		assert step.target_files == ["globalPlugins/X/s.py"]

	def test_default_vazio(self):
		assert ExecutionStep("a", "web_research", "x", "alto").target_files == []


class TestPromptDoReplanejamento:
	"""O prompt pedia 'um step por feature/subpacote' -- a causa do problema."""

	def test_pede_divisao_por_arquivo(self):
		src = inspect.getsource(Planner.create_plan)
		assert "Divida por ARQUIVO" in src
		assert "no maximo 2 arquivos" in src

	def test_nao_pede_mais_um_step_por_feature(self):
		src = inspect.getsource(Planner.create_plan)
		assert "um step por feature/subpacote" not in src

	def test_justifica_com_o_dado_medido(self):
		"""Instrucao com motivo concreto pesa mais que ordem seca -- e o mesmo
		principio aplicado aos principios de engenharia desta sessao."""
		src = inspect.getsource(Planner.create_plan)
		assert "3x mais" in src or "entrega parcial" in src


class TestEscopoNoPromptDoStep:
	"""O gerador precisa saber quais arquivos ESTE step produz."""

	def test_orchestrator_injeta_os_arquivos_alvo(self):
		from nvdastudio.core.orchestrator import Orchestrator

		src = inspect.getsource(Orchestrator._build_step_prompt)
		assert "target_files" in src
		assert "ARQUIVOS DESTE STEP" in src

	def test_so_injeta_em_step_que_escreve_arquivo(self):
		from nvdastudio.core.orchestrator import Orchestrator

		src = inspect.getsource(Orchestrator._build_step_prompt)
		i = src.find("ARQUIVOS DESTE STEP")
		trecho = src[max(0, i - 300):i]
		assert "code_generation" in trecho and "agent_runner" in trecho


class TestGuardaNaoConfiaNoPlanner:
	"""
	ACHADO AO VIVO (E2E 2026-08-30, quarta rodada): o criterio por
	`target_files` NUNCA disparou em execucao real. Os unicos registros de
	"Subtarefas grandes detectadas" nos logs eram `cg_grande` -- fixture de
	teste unitario. O planner simplesmente nao preencheu o campo.

	`target_files` e declarado OBRIGATORIO no schema. Mas "obrigatorio no
	schema" nao e o mesmo que "preenchido": o guarda contava zero arquivos e
	deixava passar um step que na pratica produzia seis. Confiar que a IA
	preencheu um campo e o mesmo erro de confiar que ela seguiu uma regra --
	precisa de verificacao.

	A verificacao adicionada e ARITMETICA, nao adivinhacao: se o layout declara
	mais .py do que os steps conseguem cobrir no teto, entao por contagem
	simples algum step produz mais que o permitido. Nao inferimos QUAL arquivo
	vai em QUAL step -- isso continua sendo decisao semantica do planner.
	"""

	_LAYOUT_8 = [f"globalPlugins/X/f{i}.py" for i in range(8)] + [
		"manifest.ini",
		"doc/en/userGuide.html",
	]

	def test_caso_real_tres_steps_sem_declarar_layout_de_oito(self):
		"""Reproduz a rodada 4: 3 code_generation, nenhum declarou, layout com
		8 arquivos .py. Capacidade maxima = 3 x 2 = 6 < 8."""
		steps = [_step("a", []), _step("b", []), _step("c", [])]
		assert sorted(oversized_code_generation_steps(steps, self._LAYOUT_8)) == ["a", "b", "c"]

	def test_layout_que_cabe_nao_e_marcado(self):
		"""4 steps x 2 arquivos = 8 = exatamente o layout. Cabe."""
		steps = [_step(f"c{i}", ["a.py", "b.py"]) for i in range(4)]
		assert oversized_code_generation_steps(steps, self._LAYOUT_8) == []

	def test_so_marca_quem_se_omitiu(self):
		"""Um step que declarou 2 arquivos esta dentro do contrato e nao deve
		ser penalizado porque OUTRO step do plano se omitiu."""
		steps = [_step("bom", ["a.py", "b.py"]), _step("omisso", [])]
		assert oversized_code_generation_steps(steps, self._LAYOUT_8) == ["omisso"]

	def test_layout_pequeno_sem_declaracao_nao_e_marcado(self):
		"""Addon de 1 arquivo nao precisa declarar nada -- marcar seria falso
		positivo em todo addon simples, que hoje converge a 100%."""
		steps = [_step("a", [])]
		layout = ["globalPlugins/X/__init__.py", "manifest.ini"]
		assert oversized_code_generation_steps(steps, layout) == []

	def test_sem_layout_mantem_o_comportamento_anterior(self):
		"""Chamada sem o parametro (planos antigos, testes existentes) nao pode
		mudar de comportamento."""
		assert oversized_code_generation_steps([_step("a", [])]) == []

	def test_manifest_e_doc_nao_contam_como_arquivo_de_codigo(self):
		"""code_generation nao produz manifest.ini nem userGuide.html -- inclui-los
		na contagem inflaria o layout e geraria replanejamento desnecessario."""
		steps = [_step("a", [])]
		layout = ["globalPlugins/X/__init__.py", "manifest.ini", "doc/en/userGuide.html"]
		assert oversized_code_generation_steps(steps, layout) == []

	def test_sem_step_de_codigo_nao_levanta(self):
		"""Divisao por zero seria o jeito mais bobo de derrubar o planejamento."""
		assert oversized_code_generation_steps([], self._LAYOUT_8) == []
