import re
from ._base import _run_sub_agent, narrate, _truncate_at_word
from ..utils.logger import get_logger, log_decision
from ..builder.nvda_context import get_docs_assembler

MODULE_VERSION = "1.7.0"
_logger = get_logger("assembler")

_SYSTEM = """Voce e o Assembler do NVDAStudio.
Receba os outputs de todos os steps anteriores e monte a resposta final organizada.

TEXTO PURO - sem markdown de cabecalho desnecessario, sem asteriscos soltos.

Sua saida DEVE conter, nesta ordem:
1. Resumo do que foi criado (2-3 linhas)
2. Cada arquivo gerado com seu bloco de codigo identificado com nome de arquivo:
   - ```python:globalPlugins/NomeAddon/__init__.py  (codigo principal)
   - ```ini:manifest.ini                            (manifesto)
   - ```html:doc/pt_BR/userGuide.html               (documentacao - OBRIGATORIA se gerada)
3. Se o addon tiver agentes: inclua agent_runner.py e agent_config.md como blocos separados
4. Instrucoes de instalacao passo a passo
5. Como testar o addon no NVDA

REGRAS CRITICAS:
- Use APENAS UMA pasta de plugin: globalPlugins/NomeUnico/__init__.py
  Se houver codigo de dois plugins diferentes, FUNDA em um unico __init__.py.
  Dois GlobalPlugin no mesmo addon causam conflito de atalhos no NVDA.
- Se o step de documentacao gerou um bloco html:doc/pt_BR/userGuide.html,
  voce DEVE incluir esse bloco na saida final. Nunca omita a documentacao.
- O campo docFileName no manifest.ini SEM bloco html correspondente e erro estrutural.

Use separadores claros entre secoes: === NOME DA SECAO ===
Nao omita nenhum arquivo gerado pelos outros steps.
Corrija inconsistencias entre os artefatos (ex: nome no manifest diferente do codigo)."""


# --------------------------------------------------------------------------
# Validacao 1: artefatos de addon com agente
# Pares (descricao, pattern_arquivo, pattern_conteudo)
# Se conteudo_pattern bate no output mas arquivo_pattern NAO bate -> aviso.
# --------------------------------------------------------------------------
_AGENT_ARTIFACT_CHECKS: list[tuple[str, str, str]] = [
	(
		"agent_runner.py",
		r"```\w*:.*agent_runner\.py",
		r"(AgentRunner|agent_runner|reset_session)",
	),
	(
		"agent_config.md",
		r"```\w*:.*agent_config\.md",
		r"(agent_config|AgentConfig|## Invariantes)",
	),
]


def _validate_agent_artifacts(output: str) -> list[str]:
	"""
	Verifica artefatos de addon com agente.
	Retorna lista de avisos. Lista vazia = sem problemas.
	Regra 9: analisa texto, nunca executa.
	"""
	warnings = []
	for nome_arquivo, pattern_arquivo, pattern_conteudo in _AGENT_ARTIFACT_CHECKS:
		if re.search(pattern_conteudo, output, re.IGNORECASE):
			if not re.search(pattern_arquivo, output, re.IGNORECASE):
				warnings.append(
					f"[AVISO-ASSEMBLY] '{nome_arquivo}' referenciado no output mas "
					f"bloco de codigo anotado ausente. Verificar se o arquivo foi gerado."
				)
	return warnings


# --------------------------------------------------------------------------
# Validacao 2: problemas estruturais do addon (B6, B7)
# --------------------------------------------------------------------------

# Pattern para capturar nome da pasta de plugin: globalPlugins/<Nome>/__init__.py
_PLUGIN_FOLDER_PATTERN = re.compile(
	r"```\w*:globalPlugins/(\w+)/__init__\.py",
	re.IGNORECASE,
)

# Pattern para detectar docFileName no manifest
_DOC_FILENAME_PATTERN = re.compile(r"docFileName\s*=\s*\S+", re.IGNORECASE)

# Pattern para detectar nome no manifest.ini: name = NomeAddon
_MANIFEST_NAME_PATTERN = re.compile(r"^name\s*=\s*(\S+)", re.IGNORECASE | re.MULTILINE)

# Pattern para detectar bloco html de documentacao
_DOC_BLOCK_PATTERN = re.compile(r"```html:doc/", re.IGNORECASE)


def _validate_structural_issues(output: str) -> list[str]:
	"""
	Detecta problemas estruturais no output do assembler (B6, B7).

	B6 — Duas pastas de plugin conflitantes:
		Encontra todos os blocos `python:globalPlugins/<Nome>/__init__.py`.
		Se houver mais de um nome de pasta unico, emite aviso de conflito.
		O NVDA carregaria dois GlobalPlugin simultaneamente — comportamento
		imprevisivel e conflito de atalhos para o usuario cego.

	B7 — docFileName sem bloco html:
		Se manifest.ini referencia docFileName mas nao ha bloco html:doc/,
		o NVDA exibe link de ajuda quebrado e o usuario nao tem documentacao.

	Retorna lista de avisos. Lista vazia = sem problemas estruturais.
	Regra 5: logica deterministica — nao semantica.
	Regra 9: analisa texto, nunca executa codigo.
	"""
	warnings = []

	# B6: verifica pastas de plugin duplicadas
	plugin_folders = _PLUGIN_FOLDER_PATTERN.findall(output)
	unique_folders = list(dict.fromkeys(f.lower() for f in plugin_folders))
	if len(unique_folders) > 1:
		nomes = ", ".join(set(plugin_folders))
		warnings.append(
			f"[AVISO-ESTRUTURA-B6] Duas pastas de plugin detectadas: {nomes}. "
			f"O NVDA carregaria dois GlobalPlugin simultaneamente causando conflito "
			f"de atalhos. Funda todo o codigo em uma unica pasta globalPlugins/NomeUnico/."
		)

	# B7: verifica docFileName sem bloco html
	if _DOC_FILENAME_PATTERN.search(output) and not _DOC_BLOCK_PATTERN.search(output):
		warnings.append(
			"[AVISO-ESTRUTURA-B7] manifest.ini referencia docFileName mas nenhum bloco "
			"html:doc/ foi encontrado no output. Inclua o bloco "
			"```html:doc/pt_BR/userGuide.html com a documentacao do addon."
		)

	# B8: consistencia cruzada nome manifest vs pasta globalPlugins
	manifest_name_match = _MANIFEST_NAME_PATTERN.search(output)
	if manifest_name_match and plugin_folders:
		manifest_name = manifest_name_match.group(1).strip().lower()
		# Compara sem diferenciar maiuscula/minuscula e sem espacos
		folder_names = [f.lower().replace(" ", "") for f in set(plugin_folders)]
		manifest_slug = manifest_name.replace(" ", "").replace("-", "").replace("_", "")
		matches = [
			f for f in folder_names
			if f.replace("-", "").replace("_", "") == manifest_slug
		]
		if not matches:
			warnings.append(
				f"[AVISO-ESTRUTURA-B8] Nome no manifest.ini ('{manifest_name_match.group(1)}')"
				f" nao corresponde a pasta globalPlugins ({', '.join(set(plugin_folders))}). "
				f"O NVDA usa o nome da pasta para registrar o addon — o addon instalara "
				f"mas nao carregara se os nomes forem diferentes."
			)

	return warnings


def run(prompt: str, model_id: str, reasoning_params: dict, cache_key: str | None = None) -> str:
	# Narracao "antes" removida (v1.6.0): o proprio modelo ja narra a intencao
	# via LiveNarrator no content, antes/entre as tool calls -- narrate() aqui
	# duplicava a mesma coisa. A saida final do assembler e extraida por
	# blocos com fence (extract_code_blocks()), entao e seguro narrar no
	# content: o texto solto da narracao nunca entra no artefato montado.
	output = _run_sub_agent(_SYSTEM, prompt, model_id, reasoning_params,
							extra_docs=get_docs_assembler(), cache_key=cache_key,
							live_narrate=True)

	# Validacao 1: artefatos de agente (v1.0.1)
	all_warnings = _validate_agent_artifacts(output)

	# Validacao 2: problemas estruturais (v1.1.0)
	all_warnings += _validate_structural_issues(output)

	if all_warnings:
		narrate(f"encontrei {len(all_warnings)} problema(s) na montagem: {_truncate_at_word(all_warnings[0], 100)}")
		aviso_bloco = (
			"=== AVISO DE MONTAGEM ===\n"
			+ "\n".join(all_warnings)
			+ "\n=== FIM DO AVISO ===\n\n"
		)
		log_decision(_logger, "assembly_avisos",
					 f"total={len(all_warnings)}: {'; '.join(all_warnings[:2])}")
		return aviso_bloco + output

	narrate("todos os arquivos do addon ficaram completos e consistentes")
	log_decision(_logger, "assembly_ok", "artefatos e estrutura validados")
	return output
