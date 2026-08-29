"""
Ciclo de vida do addon GERADO: versionamento semantico e changelog util.

MOTIVO DE EXISTIR (auditoria 2026-08-29): o pipeline tratava cada entrega como
se fosse a primeira. O prompt de manifest_builder trazia `version = 1.0.0` como
exemplo e nada mais -- nenhuma orientacao sobre o que fazer quando o NVDAStudio
MODIFICA um addon que ja existe, que e metade do proposito do projeto ("cria,
revisa, documenta, empacota e itera outros addons"). Na pratica isso produzia
duas falhas reais:

  1. Versao que nao anda. O NVDA compara versoes para decidir se um addon e
     uma atualizacao. Reentregar um addon modificado ainda como 1.0.0 faz o
     usuario cego instalar por cima sem nenhum sinal de que algo mudou -- e,
     dependendo do fluxo de instalacao, sem a atualizacao acontecer.
  2. Changelog decorativo. "Initial release with full feature set" na segunda
     entrega e pior que campo vazio: o usuario nao tem outra forma de saber o
     que mudou, porque nao ha tela para ele ler.

DIVISAO DETERMINISTICO/SEMANTICO (README Regra 7): a IA decide o CONTEUDO --
que tipo de mudanca foi feita e o que escrever no changelog. O codigo aqui
decide a INTEGRIDADE -- que a versao entregue e estritamente maior que a
anterior. Monotonicidade de versao e regra tecnica verificavel, nunca
julgamento; deixa-la para o modelo seria inverter a regra.
"""

import re

MODULE_VERSION = "1.0.0"

# Formato emitido por builder/addon_loader.py::AddonContext.to_prompt_context().
# COSTURA: se aquele cabecalho mudar, esta regex para de achar a versao anterior
# e o bump silenciosamente vira no-op -- por isso existe teste de regressao
# ligando os dois lados (tests/unit/test_addon_versioning.py).
_PREVIOUS_VERSION_RE = re.compile(
	r"=== ADDON EXISTENTE:\s*.+?\s+v(\d+)\.(\d+)\.(\d+)\s*===",
)

_MANIFEST_VERSION_RE = re.compile(r"^(\s*version\s*=\s*)(.+?)\s*$", re.MULTILINE)

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

# Changelog que nao informa nada. Nao e blacklist semantica (proibida pela
# Regra 7) -- e checagem de FORMA sobre um campo que o projeto exige preencher,
# do mesmo tipo que "campo nao pode ter quebra de linha".
_CHANGELOG_VAZIO = frozenset({
	"", "-", "n/a", "na", "none", "nenhum", "nenhuma",
	"initial release", "primeira versao", "primeira versão",
	"versao inicial", "versão inicial", "release inicial",
	"sem alteracoes", "sem alterações", "atualizacoes diversas",
	"atualizações diversas", "melhorias gerais", "correcoes gerais",
	"correções gerais", "varias melhorias", "várias melhorias",
	"bug fixes", "melhorias e correcoes", "melhorias e correções",
})


def parse_semver(version: str) -> tuple[int, int, int] | None:
	"""Converte 'X.Y.Z' em tupla comparavel. None se nao for semver puro."""
	m = _SEMVER_RE.match(version.strip())
	if not m:
		return None
	return int(m.group(1)), int(m.group(2)), int(m.group(3))


def extract_previous_version(prompt: str) -> str | None:
	"""
	Le a versao do addon existente no bloco de contexto do addon_loader.

	None quando o pedido e de um addon NOVO (nao ha bloco "ADDON EXISTENTE"),
	que e o caso em que nenhum bump se aplica.
	"""
	m = _PREVIOUS_VERSION_RE.search(prompt)
	if not m:
		return None
	return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"


def next_version(previous: str, change_kind: str = "feature") -> str:
	"""
	Proxima versao semantica a partir da anterior.

	change_kind: "breaking" incrementa MAJOR, "feature" MINOR, "fix" PATCH.
	Qualquer outro valor e tratado como "feature" -- nunca levanta, porque
	este caminho roda dentro do pipeline e uma excecao aqui derrubaria uma
	entrega que, no pior caso, so precisa de um numero conservador.

	Versao anterior nao-semver cai em "1.0.0": e o menor valor seguro que
	ainda e maior que os formatos livres comuns (ex: "0.9", "beta").
	"""
	parsed = parse_semver(previous)
	if parsed is None:
		return "1.0.0"
	major, minor, patch = parsed
	if change_kind == "breaking":
		return f"{major + 1}.0.0"
	if change_kind == "fix":
		return f"{major}.{minor}.{patch + 1}"
	return f"{major}.{minor + 1}.0"


def enforce_version_bump(manifest_text: str, previous: str | None) -> tuple[str, str | None]:
	"""
	Garante que a versao do manifest seja estritamente maior que `previous`.

	Retorna (manifest_corrigido, aviso). `aviso` e None quando nada precisou
	mudar -- o caso normal quando o modelo ja versionou certo.

	Corrige em vez de rejeitar de proposito: reprovar o step inteiro por um
	numero de versao gastaria uma rodada de LLM para consertar algo que o
	codigo resolve sem ambiguidade. Rejeitar fica reservado para o que exige
	julgamento.
	"""
	if previous is None:
		return manifest_text, None

	m = _MANIFEST_VERSION_RE.search(manifest_text)
	if not m:
		return manifest_text, None

	atual = m.group(2).strip()
	anterior_t = parse_semver(previous)
	atual_t = parse_semver(atual)

	if anterior_t is None:
		return manifest_text, None
	if atual_t is not None and atual_t > anterior_t:
		return manifest_text, None

	corrigida = next_version(previous, "feature")
	corrigido = _MANIFEST_VERSION_RE.sub(
		lambda mm: f"{mm.group(1)}{corrigida}", manifest_text, count=1,
	)
	aviso = (
		f"versao do manifest ({atual or 'ausente'}) nao era maior que a versao "
		f"anterior do addon ({previous}); corrigida para {corrigida}"
	)
	return corrigido, aviso


def changelog_is_uninformative(manifest_text: str) -> bool:
	"""
	True quando o changelog e um placeholder que nao informa nada ao usuario.

	Usado como AVISO para o proximo retry, nunca para bloquear a entrega: um
	changelog fraco degrada a experiencia, mas nao quebra o addon -- e derrubar
	uma entrega funcional por causa disso seria desproporcional.
	"""
	m = re.search(r"^\s*changelog\s*=\s*(.*)$", manifest_text, re.MULTILINE)
	if not m:
		return True
	texto = m.group(1).strip().strip(".").lower()
	return texto in _CHANGELOG_VAZIO


# ---------------------------------------------------------------------------
# Orientacao para o manifest_builder. Fica aqui, junto das funcoes
# deterministicas que a fiscalizam, para que prompt e verificacao nao possam
# divergir sem alguem ver as duas coisas no mesmo arquivo.
# ---------------------------------------------------------------------------
ADDON_LIFECYCLE_PROMPT_TEXT = """## Versionamento e changelog (ciclo de vida do addon)

Um addon nao e entregue uma vez -- ele evolui. O usuario cego nao tem tela
para conferir o que mudou: o numero de versao e o changelog sao a unica forma
dele saber que recebeu algo diferente.

Addon NOVO (nao ha bloco "ADDON EXISTENTE" no pedido):
  version = 1.0.0
  changelog = descreva o que o addon FAZ, em uma frase concreta.

Addon EXISTENTE sendo modificado (o pedido traz "ADDON EXISTENTE: <nome> vX.Y.Z"):
  A nova versao deve ser SEMPRE maior que a anterior. Escolha o incremento
  pela natureza real da mudanca:
    - PATCH (X.Y.Z+1): corrigiu comportamento errado, sem mudar o que o addon
      oferece.
    - MINOR (X.Y+1.0): adicionou funcionalidade, atalho ou opcao de
      configuracao, mantendo o que ja existia funcionando.
    - MAJOR (X+1.0.0): removeu ou renomeou algo que o usuario ja usava --
      atalho, opcao salva, comando. Quebra o habito dele; sinalize.

  changelog = diga o que MUDOU NESTA VERSAO, do ponto de vista de quem usa o
  addon, em uma unica linha. Nomeie a funcionalidade ou o atalho afetado.
  Escreva o que o usuario vai perceber, nao o que voce editou no codigo.

  Errado: "Melhorias gerais e correcoes." / "Refatoracao do modulo principal."
  Certo:  "Novo atalho NVDA+shift+t anuncia o tempo restante da faixa atual."
  Certo:  "Corrige a fala travando quando a API demora mais de 10 segundos."

Nunca reutilize o changelog da versao anterior, e nunca escreva "versao
inicial" numa versao que nao e a primeira."""
