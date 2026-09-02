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

assert MODULE_VERSION == "2.43.0"


def _step(step_id: str, alvos: list[str], descricao: str = "gerar", tipo: str = "code_generation"):
	return ExecutionStep(step_id, tipo, descricao, "alto", target_files=list(alvos))


def _step_completo(sid: str, alvos: list[str], dep: list[str]):
	"""Step de code_generation com alvos e dependencias, para os casos do
	injetor de core."""
	from nvdastudio.core.planner import STEP_CODE_GENERATION, ExecutionStep

	return ExecutionStep(
		sid, STEP_CODE_GENERATION, "x", "alto",
		depends_on=list(dep), target_files=list(alvos),
	)


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


class TestCamposNovosSaoObrigatoriosNoSchema:
	"""
	ACHADO CARO (2026-09-01): duas correcoes ficaram INERTES em producao porque
	os campos que elas dependiam estavam declarados nas `properties` do schema e
	FORA do `required`.

	Com `additionalProperties: False`, campo fora do required e OPCIONAL -- e o
	modelo simplesmente omitia os dois. Medido nos 486 prompts registrados de
	duas rodadas E2E reais:

	  - o marcador [NVDA-TOPICS:...] NUNCA apareceu em nenhum prompt;
	  - o guarda de decomposicao contava zero arquivos e nunca disparava;
	  - o custo por tentativa ficou IDENTICO antes e depois da correcao
	    (103.031 -> 103.055 tokens nos steps caros).

	Declarar no schema nao e o mesmo que ser preenchido. E a mesma classe dos
	outros defeitos desta sessao -- mecanismo que existe e ninguem alimenta --
	so que desta vez fui eu quem introduziu, duas vezes seguidas, depois de ja
	ter diagnosticado o padrao.

	Este teste existe para nao haver uma terceira.
	"""

	def _required_do_step(self) -> list[str]:
		import inspect
		import re

		from nvdastudio.core import planner

		src = inspect.getsource(planner)
		i = src.find("_PLAN_SCHEMA =")
		assert i != -1, "_PLAN_SCHEMA nao encontrado"
		bloco = src[i:]
		j = bloco.find('"required": ["step_id"')
		assert j != -1, "required do sub-schema de step nao encontrado"
		trecho = bloco[j:bloco.index("]", j)]
		return re.findall(r'"(\w+)"', trecho)[1:]  # descarta a chave "required"

	def test_target_files_e_obrigatorio(self):
		assert "target_files" in self._required_do_step(), (
			"target_files fora do required -- o modelo vai omitir e o guarda de "
			"decomposicao volta a contar zero arquivos"
		)

	def test_nvda_topics_e_obrigatorio(self):
		assert "nvda_topics" in self._required_do_step(), (
			"nvda_topics fora do required -- o modelo vai omitir e todo step "
			"volta a receber os 90 mil tokens de contexto completo"
		)

	def test_todo_campo_declarado_nas_properties_esta_no_required(self):
		"""
		A regra geral, para nao depender de lembrar campo a campo: com
		`additionalProperties: False`, um campo opcional no schema de step e um
		campo que o modelo nao preenche. Se algum dia houver um genuinamente
		opcional, ele entra na excecao COM o motivo.
		"""
		import inspect
		import re

		from nvdastudio.core import planner

		_OPCIONAIS_ACEITOS = {
			# reasoning_effort e legitimamente omitivel: a propria descricao diz
			# "Omita se null", e o orchestrator trata ausencia como sem thinking.
			"reasoning_effort",
		}

		src = inspect.getsource(planner)
		i = src.find("_PLAN_SCHEMA =")
		bloco = src[i:]
		ini = bloco.find('"step_id":')
		fim = bloco.find('"required": ["step_id"')
		props = set(re.findall(r'^\s*"(\w+)":\s*\{"type"', bloco[ini:fim], re.MULTILINE))

		faltando = props - set(self._required_do_step()) - _OPCIONAIS_ACEITOS
		assert not faltando, (
			f"Campo(s) do step nas properties e fora do required: {sorted(faltando)}. "
			"Com additionalProperties=False o modelo omite -- foi assim que "
			"target_files e nvda_topics ficaram inertes em producao."
		)


class TestInjetorDoCoreVerificaOAlvo:
	"""
	O SETIMO caso do padrao "mecanismo existe e verifica a coisa errada"
	(2026-09-01).

	`_inject_core_step()` existe desde 2026-08-17, com docstring detalhada, para
	garantir que algum step gere `globalPlugins/<addon>/__init__.py` -- o unico
	arquivo que o NVDA carrega num pacote de addon.

	Medido nos logs de 22 planejamentos reais: ele NUNCA injetou. Em TODOS os
	casos registrou "Step core ja presente no plano. Sem injecao." E os addons
	sairam sem `__init__.py` assim mesmo, sendo recusados pelo portao de
	carregabilidade.

	Causa: a deteccao era puramente ESTRUTURAL -- bastava um step depender de
	todos os irmaos. Um step que o modelo chamou de `cg_leitura_core`, que
	integra as features mas gera `leitura/servico.py`, satisfazia a condicao sem
	produzir o ponto de entrada. Integrar features e produzir o arquivo que o
	NVDA carrega sao coisas diferentes; a checagem so via a primeira.

	Com `target_files` declarado (2.33.0), da para verificar o que importa.
	"""

	def _cg(self, sid, alvos=None, dep=None):
		return _step_completo(sid, alvos or [], dep or [])

	def test_caso_real_da_rodada_5_injeta_o_core(self):
		"""Reproducao literal: 3 steps, um integra os outros, nenhum gera o
		__init__.py. Antes: nao injetava. O addon saia sem ponto de entrada."""
		steps = [
			self._cg("cg_settings", ["globalPlugins/A/settings_panel.py"]),
			self._cg("cg_historico", ["globalPlugins/A/historico/storage.py"]),
			self._cg("cg_leitura_core", ["globalPlugins/A/leitura/servico.py"],
					 ["cg_settings", "cg_historico"]),
		]
		resultado = Planner()._inject_core_step(steps, "crie um addon")
		assert any(s.step_id == "cg_core_inj" for s in resultado), (
			"sem este step o addon nao tem __init__.py e o NVDA nao carrega nada"
		)

	def test_nao_injeta_quando_alguem_ja_declara_o_ponto_de_entrada(self):
		"""Falso positivo aqui criaria DOIS steps gerando o mesmo arquivo."""
		steps = [
			self._cg("cg_core", ["globalPlugins/A/__init__.py"], ["cg_x"]),
			self._cg("cg_x", ["globalPlugins/A/servico.py"]),
		]
		resultado = Planner()._inject_core_step(steps, "q")
		assert not any(s.step_id == "cg_core_inj" for s in resultado)

	def test_appmodule_solto_conta_como_ponto_de_entrada(self):
		"""appModules/<exe>.py e carregavel por si so -- exigir __init__.py ali
		injetaria um step para um arquivo que o addon nao usa."""
		steps = [
			self._cg("cg_app", ["appModules/notepad.py"], ["cg_y"]),
			self._cg("cg_y", ["appModules/util.py"]),
		]
		resultado = Planner()._inject_core_step(steps, "q")
		assert not any(s.step_id == "cg_core_inj" for s in resultado)

	def test_sem_target_files_mantem_a_checagem_estrutural(self):
		"""Planos antigos, e testes existentes, nao podem mudar de
		comportamento: sem alvo declarado, a estrutura e tudo que existe."""
		steps = [self._cg("a", dep=["b"]), self._cg("b")]
		resultado = Planner()._inject_core_step(steps, "q")
		assert not any(s.step_id == "cg_core_inj" for s in resultado)

	def test_step_unico_nunca_recebe_injecao(self):
		"""Com 1 code_generation nao ha decomposicao -- ele ja e o core."""
		steps = [self._cg("unico", ["globalPlugins/A/servico.py"])]
		resultado = Planner()._inject_core_step(steps, "q")
		assert len(resultado) == 1

	def test_step_injetado_declara_o_arquivo_certo(self):
		steps = [
			self._cg("cg_a", ["globalPlugins/A/a.py"]),
			self._cg("cg_b", ["globalPlugins/A/b.py"], ["cg_a"]),
		]
		core = next(
			s for s in Planner()._inject_core_step(steps, "q")
			if s.step_id == "cg_core_inj"
		)
		assert "__init__.py" in core.expected_output
		assert set(core.depends_on) == {"cg_a", "cg_b"}, (
			"o core precisa depender de TODOS -- ele importa e orquestra os modulos"
		)

	def test_core_injetado_declara_contexto_nvda(self):
		"""Sem nvda_topics o step cai no fallback "documentacao completa"
		(~90k tokens medidos) -- e este e o step que menos pode morrer por
		estouro de orcamento."""
		from nvdastudio.core.planner import STEP_CODE_GENERATION, ExecutionStep

		steps = [
			ExecutionStep("cg_a", STEP_CODE_GENERATION, "x", "alto",
						  target_files=["globalPlugins/A/a.py"],
						  nvda_topics=["config"]),
			ExecutionStep("cg_b", STEP_CODE_GENERATION, "x", "alto",
						  depends_on=["cg_a"],
						  target_files=["globalPlugins/A/b.py"],
						  nvda_topics=["speech"]),
		]
		core = next(
			s for s in Planner()._inject_core_step(steps, "q")
			if s.step_id == "cg_core_inj"
		)
		topicos = set(core.nvda_topics)
		assert {"scripts", "gui"} <= topicos, (
			"todo ponto de entrada declara gestos e menu"
		)
		assert {"config", "speech"} <= topicos, (
			"o core importa os modulos dos irmaos -- precisa do contexto deles"
		)

	def test_core_injetado_usa_o_pacote_real_dos_irmaos(self):
		"""Deixar o placeholder `<addon>` na descricao poe duas instrucoes
		conflitantes no mesmo prompt: o bloco de layout do plano diz o caminho
		verdadeiro e manda usar EXATAMENTE aquele. O pacote ja esta declarado
		pelos irmaos -- nao ha nada para adivinhar."""
		from nvdastudio.core.planner import STEP_CODE_GENERATION, ExecutionStep

		steps = [
			ExecutionStep("cg_a", STEP_CODE_GENERATION, "x", "alto",
						  target_files=["globalPlugins/AssistenteLeitura/leitura/servico.py"]),
			ExecutionStep("cg_b", STEP_CODE_GENERATION, "x", "alto",
						  depends_on=["cg_a"],
						  target_files=["globalPlugins/AssistenteLeitura/settings_panel.py"]),
		]
		core = next(
			s for s in Planner()._inject_core_step(steps, "q")
			if s.step_id == "cg_core_inj"
		)
		esperado = "globalPlugins/AssistenteLeitura/__init__.py"
		assert core.expected_output == esperado
		assert core.target_files == [esperado]
		assert "<addon>" not in core.description
		assert esperado in core.description

	def test_sem_pacote_declarado_mantem_o_placeholder(self):
		"""Sem nenhum caminho de pacote nos irmaos nao ha o que resolver.
		Inventar um a partir do nome do addon criaria um SEGUNDO pacote em
		globalPlugins/ -- pior que o problema original."""
		from nvdastudio.core.planner import STEP_CODE_GENERATION, ExecutionStep

		steps = [
			ExecutionStep("cg_a", STEP_CODE_GENERATION, "x", "alto",
						  target_files=["appModules/notepad_helper/util.py"]),
			ExecutionStep("cg_b", STEP_CODE_GENERATION, "x", "alto",
						  depends_on=["cg_a"],
						  target_files=["appModules/notepad_helper/outro.py"]),
		]
		core = next(
			s for s in Planner()._inject_core_step(steps, "q")
			if s.step_id == "cg_core_inj"
		)
		assert core.expected_output == "appModules/notepad_helper/__init__.py"
