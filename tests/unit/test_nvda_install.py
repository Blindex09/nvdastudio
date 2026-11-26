"""package_open_in_nvda hands the package to NVDA's own installer and checks a fact."""

from pathlib import Path

import pytest

from nvdastudio_mcp.nvda_install import NvdaInstallError, open_in_nvda, slave_from_command

BS = chr(92)
PKG = Path("C:/x/Test-0.1.0.nvda-addon")
SLAVE = Path("C:/Program Files/NVDA/nvda_slave.exe")


def _open(**overrides):
    args = dict(
        platform="win32", wait_seconds=0, poll_seconds=0,
        find_slave_fn=lambda: SLAVE, pids_fn=lambda: [10], windows_fn=lambda pids: [],
        run_fn=lambda command: 0,
    )
    args.update(overrides)
    return open_in_nvda(PKG, **args)


def test_comando_registrado_com_e_sem_aspas():
    exe = "C:" + BS + "Program Files" + BS + "NVDA" + BS + "nvda_slave.exe"
    assert slave_from_command(chr(34) + exe + chr(34) + " addons_installAddonPackage " + chr(34) + "%1" + chr(34)) == exe
    plain = "C:" + BS + "NVDA" + BS + "nvda_slave.exe"
    assert slave_from_command(plain + " addons_installAddonPackage %1") == plain
    assert slave_from_command("lixo") is None


def test_fora_do_windows_e_erro():
    with pytest.raises(NvdaInstallError, match="Windows"):
        _open(platform="linux")


def test_nvda_nao_instalado_e_erro():
    with pytest.raises(NvdaInstallError, match="not installed"):
        _open(find_slave_fn=lambda: None)


def test_nvda_fechado_e_erro_e_nao_chama_o_instalador():
    calls = []
    with pytest.raises(NvdaInstallError, match="not running"):
        _open(pids_fn=lambda: [], run_fn=lambda command: calls.append(command) or 0)
    assert calls == []


def test_janela_nova_do_nvda_conta_como_dialogo_aberto():
    seen = iter([["NVDA"], ["NVDA", "Add-on Installation"]])
    result = _open(windows_fn=lambda pids: next(seen))
    assert result["dialog_detected"] is True and result["new_nvda_windows"] == ["Add-on Installation"]
    assert result["slave_exit_code"] == 0


def test_sem_janela_nova_nao_diz_que_abriu():
    result = _open(windows_fn=lambda pids: ["NVDA"])
    assert result["dialog_detected"] is False and result["new_nvda_windows"] == []
    assert "do not assume" in str(result["next_step"])


def test_o_instalador_recebe_o_caminho_do_pacote():
    calls = []
    _open(run_fn=lambda command: calls.append(command) or 0)
    assert calls == [[str(SLAVE), "addons_installAddonPackage", str(PKG)]]
