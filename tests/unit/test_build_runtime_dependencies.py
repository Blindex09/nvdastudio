"""Regressao para dependencias necessarias ao runtime do NVDAStudio.

O NVDA nao fornece tinydb nem httpx. Se lib/ nao for versionada e empacotada
inteira, o addon instalado degrada para "biblioteca HTTP interna nao esta
disponivel" (todos os clientes de provedor) ou perde a memoria persistente --
e nenhum teste de dev pega isso, porque o site-packages do desenvolvedor
mascara a falta.
"""

import os
import subprocess
import sys
import zipfile

import pytest

import build as build_module

_LIB_DIR = os.path.join(build_module.ADDON_DIR, "globalPlugins", "nvdastudio", "lib")

_ARQUIVOS_OBRIGATORIOS = (
	"globalPlugins/nvdastudio/lib/tinydb/__init__.py",
	"globalPlugins/nvdastudio/lib/httpx/__init__.py",
	"globalPlugins/nvdastudio/lib/httpcore/__init__.py",
	"globalPlugins/nvdastudio/lib/h11/__init__.py",
	"globalPlugins/nvdastudio/lib/anyio/__init__.py",
	"globalPlugins/nvdastudio/lib/idna/__init__.py",
	"globalPlugins/nvdastudio/lib/typing_extensions.py",
	# Sem o bundle de CAs o httpx nao abre TLS -- e nao e .py, entao um filtro
	# de extensao descuidado em build.py o deixaria de fora.
	"globalPlugins/nvdastudio/lib/certifi/cacert.pem",
)


@pytest.fixture(scope="module")
def nomes_no_pacote(tmp_path_factory):
	dist = tmp_path_factory.mktemp("dist")
	original = build_module.DIST_DIR
	build_module.DIST_DIR = str(dist)
	try:
		artifact = build_module.build()
	finally:
		build_module.DIST_DIR = original
	with zipfile.ZipFile(artifact) as archive:
		return set(archive.namelist())


@pytest.mark.parametrize("arquivo", _ARQUIVOS_OBRIGATORIOS)
def test_pacote_final_inclui_dependencia_vendorizada(nomes_no_pacote, arquivo):
	assert arquivo in nomes_no_pacote


def test_pacote_final_traz_licencas_das_dependencias(nomes_no_pacote):
	licencas = {n for n in nomes_no_pacote if n.startswith("globalPlugins/nvdastudio/licenses/")}
	for pacote in ("tinydb", "httpx", "httpcore", "h11", "anyio", "certifi", "idna"):
		assert any(f"/{pacote}-" in n for n in licencas), f"licenca de {pacote} ausente"


def test_lib_nao_contem_extensao_compilada():
	"""Binario em lib/ fica preso a versao de Python/ABI do NVDA e quebra em
	silencio na proxima atualizacao do NVDA -- so puro Python entra."""
	for root, _, files in os.walk(_LIB_DIR):
		for f in files:
			assert not f.lower().endswith((".pyd", ".dll", ".so")), os.path.join(root, f)


def test_httpx_e_tinydb_importam_so_com_stdlib_e_lib():
	"""Reproduz a condicao do NVDA: nenhum site-packages, so stdlib + lib/.

	-I ignora env/usuario, -S nao carrega site-packages. Se alguma dependencia
	transitiva estiver faltando em lib/, o import falha aqui em vez de so
	dentro do NVDA do usuario.
	"""
	script = (
		"import sys; sys.path.insert(0, sys.argv[1]); "
		"import httpx, tinydb, certifi; "
		"httpx.Client(timeout=1).close(); "
		"assert httpx.__file__.startswith(sys.argv[1]), httpx.__file__; "
		"print('ok')"
	)
	proc = subprocess.run(
		[sys.executable, "-I", "-S", "-c", script, _LIB_DIR],
		capture_output=True, text=True, timeout=60,
	)
	assert proc.returncode == 0, proc.stderr
	assert proc.stdout.strip() == "ok"
