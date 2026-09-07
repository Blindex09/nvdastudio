"""Costura do MOTOR agentico (lacuna #3 da re-auditoria pos-demolicao).

O driver (agentic_driver.py) falava direto com o droid: montava a linha de
comando com as flags do droid, localizava o binario do droid e parseava o
envelope JSON do droid. Tres acoplamentos ao mesmo CLI espalhados no meio da
logica de loop/gate.

Esta costura isola os tres atras de uma abstracao (`AgenticBackend`): localizar
o CLI, montar o comando, ler os tokens da saida. Um segundo motor (Claude Code,
Codex Cli) passa a ser uma CLASSE NOVA que implementa o protocolo -- nao uma
reescrita do driver.

ANTI-LEGADO, de proposito: existe SO o `DroidBackend`, porque o droid e o unico
CLI agentico instalado nesta maquina. A abstracao NAO carrega um backend
especulativo (Codex/Claude Code) que ninguem exercita -- isso seria exatamente o
codigo morto que a lacuna #2 passou horas removendo. A prova de que o motor e
plugavel e a COSTURA (o driver depende do protocolo, e um backend fake nos testes
roda o loop inteiro), nao um segundo backend vazio no repositorio.
"""
import os
from typing import Protocol, runtime_checkable

from ..ai.factory_client import _achar_droid
from ..utils.logger import get_logger

MODULE_VERSION = "1.0.0"
_logger = get_logger("agentic_backends")


@runtime_checkable
class AgenticBackend(Protocol):
	"""Um motor agentico de CLI: sabe se localizar, montar seu comando de execucao
	num workdir e ler o custo em tokens da propria saida. O driver depende SO
	disto -- nunca das flags de um CLI especifico."""

	name: str

	def find(self) -> str:
		"""Caminho do executavel; levanta FactoryClientError se ausente."""
		...

	def build_command(
		self, cli: str, *, workdir: str, system_prompt_path: str,
		prompt_path: str, model_id: str, autonomy: str,
	) -> list[str]:
		"""Linha de comando que roda o agente no workdir, com o system prompt e o
		prompt do usuario em arquivo, no nivel de autonomia pedido."""
		...

	def parse_tokens(self, stdout: str) -> int:
		"""Tokens NOVOS (input+output+criacao de cache) somados da saida do CLI."""
		...


def parse_droid_tokens(stdout: str) -> int:
	"""Soma tokens NOVOS (input + output + criacao de cache) do envelope JSON do
	`droid exec -o json`. A leitura de cache (cache_read_input_tokens) fica de
	fora -- e fracao do preco; somar a peso cheio penalizaria o mecanismo que
	barateia. Mesma conta que ai/factory_client.py::_ler_envelope. Robusto: pega
	a ULTIMA linha que parseia como JSON com `usage` (o droid pode logar antes)."""
	import json
	total = 0
	for linha in reversed((stdout or "").splitlines()):
		linha = linha.strip()
		if not linha.startswith("{"):
			continue
		try:
			env = json.loads(linha)
		except (json.JSONDecodeError, ValueError):
			continue
		uso = env.get("usage") if isinstance(env, dict) else None
		if isinstance(uso, dict):
			total = (
				int(uso.get("input_tokens") or 0)
				+ int(uso.get("output_tokens") or 0)
				+ int(uso.get("cache_creation_input_tokens") or 0)
			)
			break
	return total


class DroidBackend:
	"""O motor da Factory (droid). Unico CLI agentico instalado -- ver docstring
	do modulo sobre por que nao ha um segundo backend real aqui."""

	name = "droid"

	def find(self) -> str:
		return _achar_droid()

	def build_command(
		self, cli: str, *, workdir: str, system_prompt_path: str,
		prompt_path: str, model_id: str, autonomy: str,
	) -> list[str]:
		return [
			cli, "exec",
			"-o", "json",  # envelope com usage -- captura tokens (comparacao de custo)
			"--auto", autonomy,
			"--cwd", workdir,
			"-m", model_id,
			"--append-system-prompt-file", system_prompt_path,
			"-f", prompt_path,
		]

	def parse_tokens(self, stdout: str) -> int:
		return parse_droid_tokens(stdout)


_BACKENDS: dict[str, type] = {"droid": DroidBackend}


def available_backends() -> tuple[str, ...]:
	"""Nomes dos backends registrados (hoje so 'droid')."""
	return tuple(sorted(_BACKENDS))


def get_backend(name: str | None = None) -> AgenticBackend:
	"""Backend agentico escolhido. Fonte da escolha, em ordem: argumento
	explicito, env NVDASTUDIO_AGENTIC_BACKEND, default 'droid'. Nome desconhecido
	degrada para droid com aviso (nunca derruba a build por um nome errado)."""
	escolha = (name or os.getenv("NVDASTUDIO_AGENTIC_BACKEND") or "droid").strip().lower()
	cls = _BACKENDS.get(escolha)
	if cls is None:
		_logger.warning(
			"[AGENTIC] backend %r desconhecido (disponiveis: %s) -- usando droid.",
			escolha, available_backends(),
		)
		cls = DroidBackend
	return cls()
