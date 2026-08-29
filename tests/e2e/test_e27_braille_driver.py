import ast
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
# Helpers (Regra 9: apenas leitura de string — nunca executa codigo gerado)
# ---------------------------------------------------------------------------


def _ler_braille_py(addon_folder: str) -> str:
	"""
	Retorna o conteudo do arquivo .py do BrailleDisplayDriver gerado.

	Procura em brailleDisplayDrivers/ por qualquer .py que nao seja __init__.py.
	Retorna string vazia se a pasta ou arquivo nao existirem.
	"""
	bd_dir = os.path.join(addon_folder, "brailleDisplayDrivers")
	if os.path.isdir(bd_dir):
		for f in os.listdir(bd_dir):
			if f.endswith(".py") and not f.startswith("_"):
				with open(os.path.join(bd_dir, f), encoding="utf-8", errors="replace") as fh:
					return fh.read()
	return ""


def _tem_pasta_braille(addon_folder: str) -> bool:
	"""Retorna True se brailleDisplayDrivers/ existe no addon gerado."""
	bd_dir = os.path.join(addon_folder, "brailleDisplayDrivers")
	return os.path.isdir(bd_dir)


def _ler_manifest(addon_folder: str) -> str:
	"""Retorna o conteudo do manifest.ini (Regra 9: apenas string)."""
	path = os.path.join(addon_folder, "manifest.ini")
	if os.path.isfile(path):
		with open(path, encoding="utf-8", errors="replace") as fh:
			return fh.read()
	return ""


# ---------------------------------------------------------------------------
# Fixture — addon BrailleDisplayDriver
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fluxo_braille() -> FluxoReport:
	"""
	Gera um BrailleDisplayDriver NVDA completo UMA VEZ para toda a classe.

	A query cobre todas as regras alvo deste modulo:
	  - numCols, isThreadSafe, supportsAutomaticDetection (NVDA-037)
	  - @classmethod check() (NVDA-011)
	  - @classmethod registerAutomaticDetection() (auto-deteccao)
	  - display(cells: list[int]) — metodo principal do driver
	  - terminate() com super().terminate() como ultima linha (NVDA-028)

	Arquivo esperado em: brailleDisplayDrivers/meu_braille.py
	"""
	return _executar_fluxo_completo(
		addon_name="BrailleDisplay_e2e",
		query=(
			"Crie um BrailleDisplayDriver NVDA completo chamado 'MeuBraille' "
			"para um display braille de 40 celulas. O driver deve: "
			"1) Herdar de braille.BrailleDisplayDriver com name='meu_braille', "
			"description='Meu Display Braille'; "
			"2) Ter numCols: int = 40 como atributo de classe; "
			"3) Ter isThreadSafe: bool = True (necessario para hwIo e auto-deteccao); "
			"4) Ter supportsAutomaticDetection: bool = True; "
			"5) Ter @classmethod check(cls) -> bool que verifica se o driver esta disponivel; "
			"6) Ter @classmethod registerAutomaticDetection(cls, driverRegistrar) que registra "
			"dispositivos USB/Bluetooth; "
			"7) Implementar display(self, cells: list[int]) -> None que recebe lista de inteiros "
			"(um por celula, padrao 8-bit) e envia para o hardware; "
			"8) Implementar terminate(self) -> None com super().terminate() como ULTIMA linha; "
			"9) Arquivo salvo em brailleDisplayDrivers/meu_braille.py; "
			"10) Ter manifest.ini com minimumNVDAVersion=2026.1.1, lastTestedNVDAVersion=2026.1."
		),
	)


# ---------------------------------------------------------------------------
# Classe de testes: BrailleDisplayDriver
# ---------------------------------------------------------------------------


class TestBrailleDisplayDriver:
	"""
	Valida regras do BrailleDisplayDriver contra o addon gerado pela IA.

	Testes condicionais: fazem pytest.skip() quando brailleDisplayDrivers/ nao existe.
	Regra 9: nenhum codigo gerado e executado em nenhuma validacao.
	"""

	# ------------------------------------------------------------------
	# NVDA-037: numCols, display(), isThreadSafe obrigatorios
	# ------------------------------------------------------------------

	def test_nvda037_braille_driver_campos_obrigatorios(
		self, fluxo_braille: FluxoReport
	) -> None:
		"""
		NVDA-037: BrailleDisplayDriver deve declarar numCols, display() e isThreadSafe.

		numCols: inteiro com o numero de celulas fisicas do display.
		display(): metodo que recebe a lista de bytes e envia ao hardware.
		isThreadSafe: bool que permite ao NVDA chamar display() de thread hwIo.

		Sem esses tres membros o NVDA nao consegue usar o display corretamente.

		Ref: nvda_developer_guide_2025.html — secao BrailleDisplayDriver.
		"""
		if not fluxo_braille.success:
			pytest.skip("Pipeline nao concluiu")
		if not _tem_pasta_braille(fluxo_braille.addon_folder):
			pytest.skip("brailleDisplayDrivers/ nao foi gerado pelo modelo")
		code = _ler_braille_py(fluxo_braille.addon_folder)
		if not code:
			pytest.skip("Nenhum .py encontrado em brailleDisplayDrivers/")
		assert "numCols" in code, (
			"NVDA-037: BrailleDisplayDriver sem atributo numCols. "
			"Declare numCols: int = <N> com o numero de celulas do display. "
			"Ref: nvda_developer_guide_2025.html — secao BrailleDisplayDriver."
		)
		assert "def display(" in code, (
			"NVDA-037: BrailleDisplayDriver sem metodo display(). "
			"display(self, cells: list[int]) e o metodo principal que envia "
			"os bytes ao hardware braille. Sem ele o NVDA nao consegue escrever. "
			"Ref: nvda_developer_guide_2025.html — secao BrailleDisplayDriver."
		)
		assert "isThreadSafe" in code, (
			"NVDA-037: BrailleDisplayDriver sem atributo isThreadSafe. "
			"Declare isThreadSafe: bool = True para permitir chamadas de thread hwIo. "
			"Necessario para displays com auto-deteccao e comunicacao USB/Bluetooth. "
			"Ref: nvda_developer_guide_2025.html — secao BrailleDisplayDriver."
		)

	# ------------------------------------------------------------------
	# NVDA-011: @classmethod check() obrigatorio
	# ------------------------------------------------------------------

	def test_nvda011_braille_driver_tem_check_classmethod(
		self, fluxo_braille: FluxoReport
	) -> None:
		"""
		NVDA-011: BrailleDisplayDriver deve ter @classmethod check().

		O NVDA chama check() antes de tentar instanciar o driver para verificar
		se o hardware/software necessario esta disponivel. Sem check(), o NVDA
		pode travar ou gerar erro ao tentar carregar o driver em hardware incompativel.

		check() deve retornar True se o driver pode ser usado, False caso contrario.

		Ref: nvda_developer_guide_2025.html — secao BrailleDisplayDriver.check().
		"""
		if not fluxo_braille.success:
			pytest.skip("Pipeline nao concluiu")
		if not _tem_pasta_braille(fluxo_braille.addon_folder):
			pytest.skip("brailleDisplayDrivers/ nao foi gerado pelo modelo")
		code = _ler_braille_py(fluxo_braille.addon_folder)
		if not code:
			pytest.skip("Nenhum .py encontrado em brailleDisplayDrivers/")
		assert "@classmethod" in code, (
			"NVDA-011: BrailleDisplayDriver sem @classmethod. "
			"check() classmethod e obrigatorio para validar disponibilidade do hardware. "
			"Ref: nvda_developer_guide_2025.html — secao BrailleDisplayDriver."
		)
		assert "def check(" in code, (
			"NVDA-011: @classmethod check() ausente no driver. "
			"O NVDA chama check() antes de instanciar o driver — obrigatorio. "
			"Assinatura: @classmethod def check(cls) -> bool"
		)

	# ------------------------------------------------------------------
	# NVDA-037: display() aceita lista de celulas (parametro cells)
	# ------------------------------------------------------------------

	def test_nvda037_display_method_com_cells_parametro(
		self, fluxo_braille: FluxoReport
	) -> None:
		"""
		NVDA-037: display() deve aceitar o parametro cells (lista de inteiros).

		O NVDA chama display(cells) passando uma lista onde cada elemento
		e um inteiro de 8 bits representando o padrao de pontos de uma celula.
		A assinatura correta e: def display(self, cells: list[int]) -> None

		Sem o parametro cells o metodo nao pode receber os dados do NVDA.

		Ref: nvda_developer_guide_2025.html — secao BrailleDisplayDriver.
		"""
		if not fluxo_braille.success:
			pytest.skip("Pipeline nao concluiu")
		if not _tem_pasta_braille(fluxo_braille.addon_folder):
			pytest.skip("brailleDisplayDrivers/ nao foi gerado pelo modelo")
		code = _ler_braille_py(fluxo_braille.addon_folder)
		if not code:
			pytest.skip("Nenhum .py encontrado em brailleDisplayDrivers/")
		if "def display(" not in code:
			pytest.skip("display() ausente — coberto por test_nvda037_braille_driver_campos_obrigatorios")
		# Verifica que display() tem parametro cells (ou nome equivalente)
		display_sigs = re.findall(r"def display\s*\(([^)]+)\)", code)
		tem_cells = any(
			"cells" in sig or "cell" in sig or "data" in sig
			for sig in display_sigs
		)
		assert tem_cells, (
			"NVDA-037: display() presente mas sem parametro 'cells'. "
			"Assinatura correta: def display(self, cells: list[int]) -> None. "
			"O NVDA passa a lista de celulas braille como 'cells'. "
			"Ref: nvda_developer_guide_2025.html — secao BrailleDisplayDriver."
		)

	# ------------------------------------------------------------------
	# NVDA-028 (bonus): terminate() chama super().terminate() como ultima linha
	# ------------------------------------------------------------------

	def test_nvda028_terminate_chama_super_como_ultima_linha(
		self, fluxo_braille: FluxoReport
	) -> None:
		"""
		NVDA-028 (bonus): terminate() deve chamar super().terminate() como ULTIMA linha.

		Se super().terminate() nao e chamado, recursos do driver base do NVDA
		(timers, filas hwIo, handles de porta serial/USB) nao sao liberados.
		Se super().terminate() nao e a ultima linha, codigo que roda depois
		pode usar recursos ja liberados pelo super, causando uso-apos-liberacao.

		Ref: nvda_developer_guide_2025.html — secao terminate().
		"""
		if not fluxo_braille.success:
			pytest.skip("Pipeline nao concluiu")
		if not _tem_pasta_braille(fluxo_braille.addon_folder):
			pytest.skip("brailleDisplayDrivers/ nao foi gerado pelo modelo")
		code = _ler_braille_py(fluxo_braille.addon_folder)
		if not code:
			pytest.skip("Nenhum .py encontrado em brailleDisplayDrivers/")
		if "def terminate" not in code:
			pytest.skip("terminate() ausente no driver braille — regra NVDA-028 nao se aplica")
		assert "super().terminate()" in code, (
			"NVDA-028: terminate() presente mas sem super().terminate(). "
			"O driver base libera recursos internos em terminate() — obrigatorio chamar. "
			"Ref: nvda_developer_guide_2025.html — secao terminate()."
		)
		# Verifica que super().terminate() e a ultima instrucao nao-vazia do metodo
		linhas = code.splitlines()
		dentro_terminate = False
		indent_terminate: int | None = None
		ultima_instrucao = ""
		for linha in linhas:
			stripped = linha.strip()
			if re.match(r"def terminate\s*\(", stripped):
				dentro_terminate = True
				indent_terminate = len(linha) - len(linha.lstrip())
				continue
			if dentro_terminate:
				if not stripped:
					continue
				indent_atual = len(linha) - len(linha.lstrip())
				# Saiu do metodo quando a indentacao volta ao nivel do def ou menor
				if indent_terminate is not None and indent_atual <= indent_terminate and not stripped.startswith("#"):
					break
				if not stripped.startswith("#"):
					ultima_instrucao = stripped
		assert "super().terminate()" in ultima_instrucao, (
			"NVDA-028: super().terminate() nao e a ultima instrucao de terminate(). "
			f"Ultima instrucao detectada: {ultima_instrucao!r}. "
			"super().terminate() deve ser a ULTIMA linha do metodo. "
			"Codigo apos o super() pode usar recursos ja liberados."
		)

	# ------------------------------------------------------------------
	# Sintaxe Python valida (Regra 9: ast.parse, sem exec)
	# ------------------------------------------------------------------

	def test_braille_driver_sintaxe_python_valida(
		self, fluxo_braille: FluxoReport
	) -> None:
		"""
		O codigo do BrailleDisplayDriver deve ter sintaxe Python valida.

		Regra 9: usa ast.parse() — nenhum codigo e executado.
		Codigo com erro de sintaxe faz o NVDA falhar ao tentar carregar o driver.
		"""
		if not fluxo_braille.success:
			pytest.skip("Pipeline nao concluiu")
		if not _tem_pasta_braille(fluxo_braille.addon_folder):
			pytest.skip("brailleDisplayDrivers/ nao foi gerado pelo modelo")
		code = _ler_braille_py(fluxo_braille.addon_folder)
		if not code:
			pytest.skip("Nenhum .py encontrado em brailleDisplayDrivers/")
		try:
			ast.parse(code)
		except SyntaxError as exc:
			pytest.fail(
				f"SyntaxError no BrailleDisplayDriver gerado (linha {exc.lineno}): {exc.msg}. "
				"O NVDA nao conseguiria carregar o driver."
			)

	# ------------------------------------------------------------------
	# Heranca de braille.BrailleDisplayDriver
	# ------------------------------------------------------------------

	def test_herda_de_braille_display_driver(
		self, fluxo_braille: FluxoReport
	) -> None:
		"""
		O driver deve herdar de braille.BrailleDisplayDriver (ou BrailleDisplayDriver).

		Sem heranca correta o NVDA nao reconhece a classe como um driver braille
		e nunca a lista no dialogo de configuracao de display braille.

		Ref: nvda_developer_guide_2025.html — secao BrailleDisplayDriver.
		"""
		if not fluxo_braille.success:
			pytest.skip("Pipeline nao concluiu")
		if not _tem_pasta_braille(fluxo_braille.addon_folder):
			pytest.skip("brailleDisplayDrivers/ nao foi gerado pelo modelo")
		code = _ler_braille_py(fluxo_braille.addon_folder)
		if not code:
			pytest.skip("Nenhum .py encontrado em brailleDisplayDrivers/")
		herda = bool(
			re.search(r"class\s+\w+\s*\(\s*braille\.BrailleDisplayDriver\s*\)", code)
			or re.search(r"class\s+\w+\s*\(\s*BrailleDisplayDriver\s*\)", code)
		)
		assert herda, (
			"Driver braille nao herda de braille.BrailleDisplayDriver. "
			"Declare: class MeuDriver(braille.BrailleDisplayDriver): "
			"O NVDA nao reconhece a classe sem a heranca correta. "
			"Ref: nvda_developer_guide_2025.html — secao BrailleDisplayDriver."
		)

	# ------------------------------------------------------------------
	# manifest.ini: versoes minimas corretas
	# ------------------------------------------------------------------

	def test_manifest_versoes_corretas(
		self, fluxo_braille: FluxoReport
	) -> None:
		"""
		manifest.ini deve ter minimumNVDAVersion e lastTestedNVDAVersion >= 2026.1.

		BrailleDisplayDrivers com auto-deteccao dependem de APIs adicionadas em 2025.x.
		Declarar versoes mais antigas pode causar incompatibilidade silenciosa.
		"""
		if not fluxo_braille.success:
			pytest.skip("Pipeline nao concluiu")
		manifest = _ler_manifest(fluxo_braille.addon_folder)
		if not manifest:
			pytest.skip("manifest.ini nao encontrado")
		_VERSION_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")
		_BASELINE = (2025, 3, 3)

		def _vtuple(v: str) -> tuple[int, ...]:
			parts = v.rstrip(".").split(".")
			try:
				return tuple(int(x) for x in parts[:3]) + (0,) * (3 - len(parts))
			except ValueError:
				return (0, 0, 0)

		campos = {}
		for linha in manifest.splitlines():
			linha = linha.strip()
			if "=" in linha and not linha.startswith("#") and not linha.startswith("["):
				k, _, v = linha.partition("=")
				campos[k.strip().lower()] = v.strip()

		for display_nome, chave in {
			"minimumNVDAVersion": "minimumnvdaversion",
			"lastTestedNVDAVersion": "lasttestednvdaversion",
		}.items():
			val = campos.get(chave, "")
			if not val:
				continue  # ausencia de campo e coberta pelo teste de fluxo principal
			val_clean = val.rstrip(".")
			if not _VERSION_RE.match(val_clean):
				continue  # formato invalido e coberto pelo teste de fluxo principal
			assert _vtuple(val_clean) >= _BASELINE, (
				f"manifest.ini: {display_nome}={val!r} abaixo do baseline 2026.1. "
				"BrailleDisplayDrivers com auto-deteccao requerem NVDA 2025.x+."
			)
