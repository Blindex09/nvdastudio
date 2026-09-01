"""
Funcao de fitness arquitetural: o schema do Planner e `_build_steps` sao dois
lados da MESMA costura, e ja se desencontraram duas vezes nesta sessao.

1. 2026-09-01: `target_files` e `nvda_topics` estavam nas `properties` mas fora
   do `required`. Com `additionalProperties: False`, campo fora do required e
   opcional -- e o modelo simplesmente omitia os dois. Duas otimizacoes ficaram
   inertes; medido em 486 prompts logados, o marcador [NVDA-TOPICS:...] nunca
   apareceu.
2. Logo depois: com o schema ja corrigido, `_build_steps` continuava sem LER
   `nvda_topics` do plano. O campo existia no dataclass, era exigido do modelo e
   consumido pelo orchestrator -- e era jogado fora no meio do caminho.

Os dois bugs sao o mesmo padrao: a peca certa existe e esta desligada de quem
decide. Um teste que le os dois lados custa milissegundos; descobrir isso numa
rodada E2E custou horas e milhoes de tokens.
"""

import ast
import inspect

from nvdastudio.core.planner import MODULE_VERSION, Planner

# Properties que ficam FORA do required de proposito, com o motivo. Qualquer
# outra ausencia e o bug de 2026-09-01 se repetindo.
_OPCIONAIS_JUSTIFICADAS = {
	"reasoning_effort": (
		"tipo ['string','null'] e a propria descricao manda omitir quando null; "
		"o default por tipo de step ja cobre o caso omitido"
	),
}

# Campos exigidos do modelo que _build_steps nao copia com raw.get() -- cada um
# com o motivo. Vazio hoje; existe para que uma excecao futura precise ser
# escrita e justificada, em vez de passar despercebida.
_NAO_CONSUMIDOS_JUSTIFICADOS: dict[str, str] = {}


def test_versao():
	assert MODULE_VERSION == "2.38.0"


def _schema_do_step() -> dict:
	"""Le o _PLAN_SCHEMA de dentro de _call_planner_llm.

	O schema e uma literal dict local ao metodo -- nao da para importar. Ler a
	AST e mais chato que importar, mas e a unica forma de olhar o lado do schema
	sem duplicar a definicao aqui (Regra 5: zero duplicacao).
	"""
	src = inspect.getsource(Planner._call_planner_llm)
	arvore = ast.parse(src.lstrip().replace("\n\t", "\n"))
	for no in ast.walk(arvore):
		if not isinstance(no, ast.Dict):
			continue
		chaves = [k.value for k in no.keys if isinstance(k, ast.Constant)]
		if "step_id" in chaves and "step_type" in chaves:
			return {"properties": chaves}
	raise AssertionError("bloco de properties do step nao encontrado no schema")


def _required_do_step() -> set[str]:
	src = inspect.getsource(Planner._call_planner_llm)
	# A lista de required do step e a que contem "msg_escalating"; a do plano
	# contem "addon_name". Delimitar pelo conteudo, nao por posicao no arquivo:
	# duas correcoes anteriores quebraram por usar janela de texto fixa.
	arvore = ast.parse(src.lstrip().replace("\n\t", "\n"))
	for no in ast.walk(arvore):
		if not isinstance(no, ast.List):
			continue
		itens = [e.value for e in no.elts if isinstance(e, ast.Constant)]
		if "msg_escalating" in itens and "step_id" in itens:
			return set(itens)
	raise AssertionError("lista required do step nao encontrada")


def test_toda_property_do_step_esta_em_required():
	"""Property fora do required com additionalProperties=False e opcional --
	e o modelo omite o que e opcional."""
	props = set(_schema_do_step()["properties"])
	required = _required_do_step()
	faltando = props - required - set(_OPCIONAIS_JUSTIFICADAS)
	assert not faltando, (
		f"properties fora do required: {sorted(faltando)} -- o modelo vai "
		"omitir esses campos e quem depender deles fica inerte"
	)


def test_todo_campo_exigido_do_modelo_e_lido_por_build_steps():
	"""O outro lado da costura: exigir no schema nao e o mesmo que consumir."""
	src = inspect.getsource(Planner._build_steps)
	required = _required_do_step()
	nao_lidos = sorted(
		campo for campo in required
		if f'raw.get("{campo}"' not in src
		and campo not in _NAO_CONSUMIDOS_JUSTIFICADOS
	)
	assert not nao_lidos, (
		f"_build_steps nao le {nao_lidos} do plano -- o schema obriga o modelo "
		"a produzir esses campos e eles sao descartados no caminho"
	)


def test_justificativas_nao_viram_deposito():
	"""Cada excecao precisa continuar sendo verdade, com motivo escrito."""
	props = set(_schema_do_step()["properties"])
	for campo, motivo in _OPCIONAIS_JUSTIFICADAS.items():
		assert campo in props, f"{campo} saiu do schema -- tire a justificativa"
		assert len(motivo) > 20, f"{campo}: justificativa vaga demais"
	for campo, motivo in _NAO_CONSUMIDOS_JUSTIFICADOS.items():
		assert campo in _required_do_step(), (
			f"{campo} nao e mais exigido no schema -- tire a justificativa"
		)
		assert len(motivo) > 20, f"{campo}: justificativa vaga demais"


def test_nvda_topics_chega_ao_step():
	"""O bug concreto: schema exigia, orchestrator consumia, _build_steps
	descartava. Escopo de contexto por topico ficou inerte."""
	steps = Planner()._build_steps([{
		"step_id": "cg1", "step_type": "code_generation", "model_id": "x",
		"nvda_topics": ["scripts", "gui"],
	}])
	assert steps[0].nvda_topics == ["scripts", "gui"]


def test_topico_invalido_cai_para_contexto_completo():
	"""Topico inventado e ignorado la na frente; se TODOS forem invalidos o step
	receberia so o grupo core -- contexto minimo, em silencio. Lista vazia
	significa documentacao completa: mais cara, e a direcao segura de errar."""
	steps = Planner()._build_steps([{
		"step_id": "cg1", "step_type": "code_generation", "model_id": "x",
		"nvda_topics": ["nao_existe", "tambem_nao"],
	}])
	assert steps[0].nvda_topics == []


def test_design_review_nao_retenta():
	"""58 execucoes reais: as 30 aprovacoes vieram TODAS na primeira tentativa;
	das 18 que retentaram, zero foram aprovadas -- 3,7M tokens sem uma unica
	conversao, num step cujo output e usado mesmo reprovado."""
	steps = Planner()._build_steps([
		{"step_id": "dr0", "step_type": "design_review", "model_id": "x"},
		{"step_id": "cg1", "step_type": "code_generation", "model_id": "x"},
	])
	assert steps[0].max_retries == 1
	assert steps[1].max_retries == 3, "o teto e so do design_review"


def test_ponto_de_entrada_tem_piso_de_contexto():
	"""Cortar contexto NVDA de ~90k para ~23k derrubou as notas de 52.0 para
	15.7 e 32.7 para 9.1 em E2E real. O arquivo que o NVDA carrega registra
	gestos e/ou menu por definicao -- nao pode ficar sem esse contexto."""
	steps = Planner()._build_steps([{
		"step_id": "cg_core", "step_type": "code_generation", "model_id": "x",
		"nvda_topics": ["config"],
		"target_files": ["globalPlugins/A/__init__.py"],
	}])
	assert set(steps[0].nvda_topics) == {"config", "scripts", "gui"}


def test_piso_nao_atinge_modulo_auxiliar():
	"""Um cliente HTTP puro nao precisa de gui nem scripts -- o piso e do ponto
	de entrada, nao de todo code_generation."""
	steps = Planner()._build_steps([{
		"step_id": "cg_api", "step_type": "code_generation", "model_id": "x",
		"nvda_topics": ["config"],
		"target_files": ["globalPlugins/A/api/cliente.py"],
	}])
	assert steps[0].nvda_topics == ["config"]


def test_piso_nao_transforma_ausencia_em_escassez():
	"""Lista vazia significa 'documentacao completa'. Aplicar o piso aqui
	trocaria o contexto completo por dois topicos -- o oposto do objetivo."""
	steps = Planner()._build_steps([{
		"step_id": "cg_core", "step_type": "code_generation", "model_id": "x",
		"nvda_topics": [],
		"target_files": ["globalPlugins/A/__init__.py"],
	}])
	assert steps[0].nvda_topics == []


def test_appmodule_solto_tambem_recebe_o_piso():
	steps = Planner()._build_steps([{
		"step_id": "cg_app", "step_type": "code_generation", "model_id": "x",
		"nvda_topics": ["appmodule"],
		"target_files": ["appModules/notepad.py"],
	}])
	assert {"scripts", "gui", "appmodule"} == set(steps[0].nvda_topics)
