"""
Todo consumidor de saida estruturada sobrevive ao provedor cair.

`get_structured_output_model()` forca OpenCode Go, o unico com json_schema
estrito e prompt caching confirmados ao vivo. Quando essa conta para de
atender, um disjuntor (model_registry 1.19.0) faz as chamadas SEGUINTES caírem
no provedor ativo -- degradadas, mas vivas.

O buraco: quem resolve o modelo UMA vez e nao reconsulta depois da falha morre
na propria chamada que disparou o disjuntor. Foi o caso do Planner, e custou
TRES execucoes seguidas mortas em 1,5 a 5 segundos, com zero steps.

Ha duas formas validas de sobreviver, e este teste aceita as duas:

1. usar `llm_factory.call_with_structured_output()`, que reconsulta o modelo a
   cada item da cadeia;
2. chamar direto, mas RECONSULTAR `get_structured_output_model()` no tratamento
   da falha -- e o que o Critic ja fazia (`get_critic_fallback_model()`) e o que
   o Planner passou a fazer.

Consumidor novo que nao faca nem uma coisa nem outra quebra aqui, em vez de
quebrar numa execucao real de 45 minutos.
"""

import pathlib

_RAIZ = pathlib.Path(__file__).resolve().parents[2] / "addon" / "globalPlugins" / "nvdastudio"


def _consumidores() -> list[pathlib.Path]:
	achados = []
	for p in _RAIZ.rglob("*.py"):
		if "nvda_docs_cache" in str(p) or p.name in ("model_registry.py", "llm_factory.py"):
			continue
		if "get_structured_output_model" in p.read_text(encoding="utf-8", errors="ignore"):
			achados.append(p)
	return achados


def test_existem_consumidores_para_verificar():
	"""Precondicao: se ninguem mais usar o helper, este teste vira decoracao."""
	assert _consumidores(), "nenhum consumidor encontrado -- o teste perdeu o alvo"


def test_todo_consumidor_sobrevive_a_queda_do_provedor():
	frageis = []
	for p in _consumidores():
		texto = p.read_text(encoding="utf-8", errors="ignore")
		usa_cadeia = "call_with_structured_output" in texto
		# reconsulta no tratamento da falha: ha um `except` e, depois dele, uma
		# nova resolucao do modelo
		reconsulta = False
		for marcador in ("except LLMClientError", "except Exception"):
			i = texto.find(marcador)
			while i != -1:
				if "get_structured_output_model" in texto[i:i + 3000] or \
				   "get_critic_fallback_model" in texto[i:i + 3000]:
					reconsulta = True
					break
				i = texto.find(marcador, i + 1)
			if reconsulta:
				break
		if not (usa_cadeia or reconsulta):
			frageis.append(str(p.relative_to(_RAIZ)))

	assert not frageis, (
		"consumidores que morrem na propria chamada que derruba o provedor:\n  "
		+ "\n  ".join(sorted(frageis))
		+ "\n\nUse llm_factory.call_with_structured_output() (reconsulta a cada "
		"item da cadeia) ou reconsulte get_structured_output_model() no "
		"tratamento da falha, como o Critic e o Planner fazem."
	)
