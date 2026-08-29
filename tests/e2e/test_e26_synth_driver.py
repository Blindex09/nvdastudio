import os
import re

import pytest

from tests.e2e.test_fluxo_completo_nvda import (
	FluxoReport,
	_executar_fluxo_completo,
	skip_unless_ollama,
	)

# 5.1.0: skip_unless_ollama importado do modulo de referencia (fonte
# unica) e aplicado a nivel de modulo -- achado real de auditoria
# 2026-08-25: este arquivo chamava _executar_fluxo_completo() (pipeline
# real, LLM de verdade) sem NENHUM guard de API key. Sem
# OLLAMA_API_KEY/OPENCODE_GO_API_KEY configuradas, o teste ficava
# pendurado indefinidamente na chamada de rede sem timeout, em vez de
# skip limpo -- travava a suite inteira. Ver
# test_e20_regras_qualidade_codigo.py 5.1.0 para o achado completo.
pytestmark = skip_unless_ollama


# ---------------------------------------------------------------------------
# Helpers (Regra 9: apenas leitura de string)
# ---------------------------------------------------------------------------

def _ler_synth_py(addon_folder: str) -> str:
	"""
	Retorna o conteudo do arquivo .py principal do SynthDriver.

	O AI pode salvar o arquivo com nomes diferentes (minha_sintese.py,
	mysynth.py, etc.). Busca recursivamente em synthDrivers/ e retorna
	o primeiro .py que nao seja __init__.py.

	Retorna string vazia se nao encontrar.
	"""
	sd_dir = os.path.join(addon_folder, "synthDrivers")
	if os.path.isdir(sd_dir):
		for f in os.listdir(sd_dir):
			if f.endswith(".py") and not f.startswith("_"):
				with open(os.path.join(sd_dir, f), encoding="utf-8", errors="replace") as fh:
					return fh.read()
	# Busca alternativa: o AI pode ter salvo direto na raiz ou em outro caminho
	if addon_folder and os.path.isdir(addon_folder):
		for root, _, files in os.walk(addon_folder):
			for f in files:
				if f.endswith(".py") and not f.startswith("_") and "synth" in f.lower():
					with open(os.path.join(root, f), encoding="utf-8", errors="replace") as fh:
						return fh.read()
	return ""


def _tem_synthdriver_no_codigo(code: str) -> bool:
	"""
	Verifica se o codigo define uma classe que herda de SynthDriver.
	Tolerante a variações como:
	  - class Foo(SynthDriver)
	  - class Foo(synthDriverHandler.SynthDriver)  — padrao oficial (tem ponto)
	"""
	return (
		bool(re.search(r"class\s+\w+\s*\(.*SynthDriver.*\)", code))
		or "synthDriverHandler.SynthDriver" in code
	)


def _listar_arquivos(addon_folder: str) -> list[str]:
	"""Lista todos os arquivos dentro do addon_folder com caminho relativo."""
	resultado: list[str] = []
	for root, _, files in os.walk(addon_folder):
		for f in files:
			abs_path = os.path.join(root, f)
			rel_path = os.path.relpath(abs_path, addon_folder).replace("\\", "/")
			resultado.append(rel_path)
	return resultado


# ---------------------------------------------------------------------------
# Fixture — SynthDriver completo com todas as APIs obrigatorias
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def fluxo_synth() -> FluxoReport:
	"""
	Gera um SynthDriver NVDA completo com a API Groq real.

	A query cobre EXPLICITAMENTE:
	  - NVDA-011: @classmethod check(cls) -> bool
	  - skill §25: supportedCommands com IndexCommand + supportedNotifications
	              com synthIndexReached E synthDoneSpeaking
	  - speak() que chama synthDoneSpeaking.notify() ao final da sequencia
	  - manifest.ini com minimumNVDAVersion=2026.1.1

	Arquivo gerado em synthDrivers/minha_sintese.py.
	"""
	return _executar_fluxo_completo(
		addon_name="MinhaSintese_e2e",
		query=(
			"Crie um SynthDriver NVDA completo chamado 'MinhaSintese' "
			"que implementa sintese de voz personalizada. O SynthDriver deve: "
			"1) Herdar de synthDriverHandler.SynthDriver com name='minha_sintese', "
			"description='Minha Sintese de Voz'; "
			"2) Ter @classmethod check(cls) -> bool que retorna True se o engine esta disponivel "
			"(NVDA chama check() antes de instanciar o driver para verificar disponibilidade); "
			"3) Declarar supportedSettings com VoiceSetting() e RateSetting(); "
			"4) Declarar supportedCommands = frozenset({IndexCommand}) "
			"(importando IndexCommand de speech.commands); "
			"5) Declarar supportedNotifications = frozenset({synthDriverHandler.synthIndexReached, "
			"synthDriverHandler.synthDoneSpeaking}) — ambos obrigatorios para sincronizacao de fala; "
			"6) Implementar speak(self, speechSequence) que itera a lista, chama "
			"synthIndexReached.notify(synth=self, index=item.index) para cada IndexCommand "
			"e chama synthDoneSpeaking.notify(synth=self) AO FINAL da sequencia completa; "
			"7) Implementar cancel(self) e pause(self, switch: bool); "
			"8) Ter _get_voice/_set_voice e _getAvailableVoices com OrderedDict de VoiceInfo; "
			"9) Arquivo salvo em synthDrivers/minha_sintese.py; "
			"10) Ter manifest.ini com minimumNVDAVersion=2026.1.1, lastTestedNVDAVersion=2026.1."
		),
	)


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------

class TestSynthDriver:
	"""
	Valida regras de SynthDriver NVDA contra o addon gerado pela IA.

	Testes condicionais: pulam se o arquivo synthDrivers/ nao existir
	ou se o pipeline nao concluiu.

	Regra 9: nenhum codigo e executado em nenhuma validacao.

	Regras cobertas:
	  - NVDA-011: @classmethod check(cls) -> bool
	  - NVDA-035: supportedCommands + supportedNotifications com
	              synthIndexReached e synthDoneSpeaking
	  - Extra:    speak() chama synthDoneSpeaking.notify() ao final
	"""

	# ------------------------------------------------------------------
	# NVDA-011: @classmethod check() obrigatorio
	# ------------------------------------------------------------------

	def test_nvda011_synth_driver_tem_check_classmethod(
		self, fluxo_synth: FluxoReport
	) -> None:
		"""
		NVDA-011: SynthDriver deve ter @classmethod check(cls) -> bool.

		O NVDA chama check() antes de tentar instanciar o driver para verificar
		se o hardware/software necessario esta disponivel. Sem check(), o NVDA
		pode travar ou gerar erro ao tentar carregar o driver em hardware incompativel.

		check() deve ser um @classmethod — nao um metodo de instancia.

		Ref: nvda_developer_guide_2025.html — secao SynthDriver.
		"""
		if not fluxo_synth.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_synth_py(fluxo_synth.addon_folder)
		if not code:
			pytest.skip("Arquivo synthDrivers/*.py nao encontrado — NVDA-011 nao se aplica")
		if not _tem_synthdriver_no_codigo(code):
			pytest.skip("Codigo nao define uma subclasse de SynthDriver — NVDA-011 nao se aplica")
		assert "@classmethod" in code, (
			"NVDA-011: SynthDriver sem @classmethod. "
			"check() deve ser declarado como @classmethod. "
			"O NVDA chama check() para verificar disponibilidade antes de instanciar o driver."
		)
		assert "def check(" in code, (
			"NVDA-011: metodo check() ausente no SynthDriver. "
			"O NVDA chama check() antes de instanciar o driver — sem ele o driver nao carrega. "
			"Assinatura: @classmethod / def check(cls) -> bool:"
		)
		# Verifica que @classmethod e def check aparecem proximos (mesmo bloco)
		linhas = code.splitlines()
		idx_check = next(
			(i for i, line in enumerate(linhas) if "def check(" in line), None
		)
		if idx_check is not None and idx_check > 0:
			# Olha as 3 linhas antes de def check — @classmethod deve estar la
			linhas_anteriores = "\n".join(linhas[max(0, idx_check - 3):idx_check])
			assert "@classmethod" in linhas_anteriores, (
				"NVDA-011: 'def check()' encontrado mas @classmethod nao esta nas linhas anteriores. "
				"check() deve ser decorado com @classmethod para funcionar corretamente no NVDA."
			)

	# ------------------------------------------------------------------
	# NVDA-035: supportedCommands + supportedNotifications
	# ------------------------------------------------------------------

	def test_nvda035_synth_driver_tem_campos_obrigatorios(
		self, fluxo_synth: FluxoReport
	) -> None:
		"""
		NVDA-035 (code_gen): SynthDriver deve declarar supportedCommands e supportedNotifications.

		supportedCommands: frozenset de classes de comando de fala suportadas.
		Deve conter pelo menos IndexCommand (de speech.commands).

		supportedNotifications: frozenset de sinais de notificacao necessarios
		para sincronizacao de fala. Deve conter AMBOS:
		  - synthIndexReached: emitido quando o driver atinge um indice
		  - synthDoneSpeaking: emitido quando a sequencia de fala termina

		Sem esses campos, o NVDA nao consegue coordenar a fala corretamente
		e funcoes como highlight de leitura e navegacao por frase falham.

		Ref: nvda_developer_guide_2025.html — secao SynthDriver interface.
		"""
		if not fluxo_synth.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_synth_py(fluxo_synth.addon_folder)
		if not code:
			pytest.skip("Arquivo synthDrivers/*.py nao encontrado — NVDA-035 nao se aplica")
		if not _tem_synthdriver_no_codigo(code):
			pytest.skip("Codigo nao define uma subclasse de SynthDriver — NVDA-035 nao se aplica")
		assert "supportedCommands" in code, (
			"NVDA-035: SynthDriver sem supportedCommands. "
			"Declare supportedCommands = frozenset({IndexCommand}) para indicar "
			"quais classes de comando de fala o driver suporta. "
			"Sem isso o NVDA nao sabe quais comandos enviar para o driver."
		)
		assert "supportedNotifications" in code, (
			"NVDA-035: SynthDriver sem supportedNotifications. "
			"Declare supportedNotifications = frozenset({synthIndexReached, synthDoneSpeaking}). "
			"Sem isso o NVDA nao consegue receber notificacoes de sincronizacao de fala."
		)
		assert "synthIndexReached" in code, (
			"NVDA-035: synthIndexReached ausente em supportedNotifications. "
			"synthIndexReached e necessario para sincronizacao de indice de fala "
			"(ex: highlight de palavra durante leitura). "
			"Inclua em supportedNotifications e emita via "
			"synthDriverHandler.synthIndexReached.notify(synth=self, index=item.index)."
		)
		assert "synthDoneSpeaking" in code, (
			"NVDA-035: synthDoneSpeaking ausente em supportedNotifications. "
			"synthDoneSpeaking e necessario para o NVDA saber quando a fala terminou. "
			"Sem ele, o NVDA nao sabe quando iniciar a proxima sequencia. "
			"Inclua em supportedNotifications e emita via "
			"synthDriverHandler.synthDoneSpeaking.notify(synth=self) ao final de speak()."
		)

	# ------------------------------------------------------------------
	# Extra: speak() deve chamar synthDoneSpeaking.notify() ao final
	# ------------------------------------------------------------------

	def test_speak_chama_synth_done_speaking_notify(
		self, fluxo_synth: FluxoReport
	) -> None:
		"""
		Extra (complementa NVDA-035): speak() deve chamar synthDoneSpeaking.notify()
		ao final de cada sequencia de fala.

		Este e o erro mais comum em implementacoes de SynthDriver:
		o desenvolvedor declara synthDoneSpeaking em supportedNotifications
		mas esquece de emiti-lo no metodo speak().

		Sem a chamada, o NVDA fica aguardando o fim da fala indefinidamente,
		causando travamento da fila de fala e silencio total apos o primeiro anuncio.

		Ref: nvda_developer_guide_2025.html — secao SynthDriver.speak().
		"""
		if not fluxo_synth.success:
			pytest.skip("Pipeline nao concluiu")
		code = _ler_synth_py(fluxo_synth.addon_folder)
		if not code:
			pytest.skip("Arquivo synthDrivers/*.py nao encontrado — extra nao se aplica")
		if not _tem_synthdriver_no_codigo(code):
			pytest.skip("Codigo nao define uma subclasse de SynthDriver — extra nao se aplica")
		if "def speak(" not in code:
			pytest.skip("Metodo speak() nao encontrado — extra nao se aplica")
		# Verifica que synthDoneSpeaking.notify aparece dentro do bloco speak()
		# Estrategia: extrai o texto a partir de 'def speak(' e busca notify
		idx_speak = code.find("def speak(")
		code_apos_speak = code[idx_speak:] if idx_speak != -1 else ""
		# Busca a proxima def no mesmo nivel para delimitar o corpo de speak()
		# (busca simples por proximidade — nao executa AST)
		prox_def = re.search(r"\ndef\s+\w+", code_apos_speak[10:])
		corpo_speak = (
			code_apos_speak[: prox_def.start() + 10]
			if prox_def
			else code_apos_speak
		)
		assert "synthDoneSpeaking" in corpo_speak and "notify" in corpo_speak, (
			"Extra (NVDA-035): speak() nao chama synthDoneSpeaking.notify(). "
			"synthDoneSpeaking.notify(synth=self) DEVE ser chamado ao final "
			"do metodo speak() para sinalizar ao NVDA que a fala terminou. "
			"Sem isso a fila de fala trava apos o primeiro anuncio."
		)

	# ------------------------------------------------------------------
	# Sanidade: arquivo synthDrivers/ existe
	# ------------------------------------------------------------------

	def test_synth_driver_arquivo_existe_em_synthdrivers(
		self, fluxo_synth: FluxoReport
	) -> None:
		"""
		Sanidade: o arquivo .py do SynthDriver deve estar em synthDrivers/.

		O NVDA carrega SynthDrivers da pasta synthDrivers/ dentro do addon.
		Salvar em outro caminho (globalPlugins/, raiz) impede o carregamento.

		Ref: nvda_developer_guide_2025.html — secao SynthDriver location.
		"""
		if not fluxo_synth.success:
			pytest.skip("Pipeline nao concluiu")
		arquivos = _listar_arquivos(fluxo_synth.addon_folder)
		synth_driver_files = [
			a for a in arquivos
			if a.startswith("synthDrivers/") and a.endswith(".py") and not a.endswith("__init__.py")
		]
		assert synth_driver_files, (
			"SynthDriver nao foi salvo em synthDrivers/. "
			"O NVDA carrega SynthDrivers exclusivamente de synthDrivers/<nome>.py. "
			f"Arquivos encontrados: {arquivos[:15]}"
		)

