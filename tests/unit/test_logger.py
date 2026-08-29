import logging
import os
import time



from nvdastudio.utils import logger as logger_module
from nvdastudio.utils.logger import get_logger, log_llm_call, log_llm_response, log_decision


class TestLoggerEncoding:
    """Invariante: toda saida de log e compativel com cp1252."""

    def test_get_logger_retorna_logger_python(self):
        logger = get_logger("test_encoding")
        assert isinstance(logger, logging.Logger)

    def test_nome_logger_prefixado(self):
        logger = get_logger("meu_modulo")
        assert logger.name.startswith("nvdastudio.")

    def test_logger_idempotente(self):
        """Mesmo nome retorna mesmo logger sem duplicar handlers."""
        logger1 = get_logger("idempotente")
        handler_count = len(logger1.handlers)
        logger2 = get_logger("idempotente")
        assert len(logger2.handlers) == handler_count

    def test_logger_grava_no_projeto_e_no_appdata(self):
        logger = get_logger("dual_file_handler")
        files = [
            getattr(handler, "baseFilename", "")
            for handler in logger.handlers
            if isinstance(handler, logging.FileHandler)
        ]

        assert any(path.startswith(logger_module._PROJECT_LOG_DIR) for path in files)
        assert any(path.startswith(logger_module._NVDA_LOG_DIR) for path in files)

    def test_log_llm_call_nao_levanta_excecao(self):
        logger = get_logger("llm_call_test")
        log_llm_call(logger, "prompt_v1.0.0", "Crie um addon de teste")

    def test_log_llm_response_nao_levanta_excecao(self):
        logger = get_logger("llm_resp_test")
        log_llm_response(logger, "prompt_v1.0.0", "Resposta da IA aqui")

    def test_log_decision_nao_levanta_excecao(self):
        logger = get_logger("decision_test")
        log_decision(logger, "modelo_selecionado", "kimi-k2.6")

    def test_mensagem_com_caracteres_especiais_nao_quebra(self):
        """Caracteres fora do cp1252 devem ser substituidos, nao quebrar."""
        logger = get_logger("encoding_test")
        mensagem_com_emoji = "Testando \u2705 emoji fora do cp1252"
        # Nao deve levantar UnicodeEncodeError
        log_decision(logger, "teste", mensagem_com_emoji)

    def test_log_nao_contem_emoji_em_nivel_info(self, caplog):
        """Regra 11: mensagens de log nao devem conter emojis."""
        logger = get_logger("no_emoji")
        emojis = ["\u2705", "\u274c", "\u26a0", "\U0001f4e6", "\U0001f916"]
        with caplog.at_level(logging.INFO, logger="nvdastudio.no_emoji"):
            log_decision(logger, "evento_ok", "detalhe sem emoji")
        for record in caplog.records:
            for emoji in emojis:
                assert emoji not in record.getMessage(), (
                    f"Emoji encontrado em mensagem de log: {record.getMessage()}"
                )


class TestLogLLMCallFormat:
    """Testa formato de log de chamadas LLM."""

    def test_log_llm_call_inclui_prompt_version(self, caplog):
        logger = get_logger("llm_fmt")
        with caplog.at_level(logging.DEBUG, logger="nvdastudio.llm_fmt"):
            log_llm_call(logger, "v1.2.3", "mensagem de teste")
        assert any("v1.2.3" in r.getMessage() for r in caplog.records)

    def test_log_llm_call_limita_preview_a_500_chars(self, caplog):
        logger = get_logger("llm_limit")
        texto_longo = "x" * 2000
        with caplog.at_level(logging.DEBUG, logger="nvdastudio.llm_limit"):
            log_llm_call(logger, "v1.0.0", texto_longo)
        # Preview truncado — mensagem nao deve ter 2000 chars do texto
        for record in caplog.records:
            assert len(record.getMessage()) < 2000


class TestProjectRootDetection:
    """Regressao: log de projeto nao pode vazar para dentro de %APPDATA%/nvda/addons/
    quando o modulo roda a partir do addon instalado (nao do checkout de dev).
    """

    def test_checkout_de_dev_real_e_detectado(self):
        """A suite roda a partir do checkout de dev real: manifest.ini e build.py
        devem estar em _PROJECT_ROOT e _IS_DEV_CHECKOUT deve ser True."""
        assert os.path.isfile(os.path.join(logger_module._PROJECT_ROOT, "manifest.ini"))
        assert os.path.isfile(os.path.join(logger_module._PROJECT_ROOT, "build.py"))
        assert logger_module._IS_DEV_CHECKOUT is True

    def test_layout_instalado_nao_e_detectado_como_dev(self, tmp_path):
        """Simula o layout instalado (addons/nvdastudio/globalPlugins/nvdastudio/utils/,
        sem a pasta 'addon/' extra): manifest.ini fica um nivel abaixo de onde o
        calculo de 4 niveis acima aponta, e build.py nao existe no pacote distribuido.
        """
        installed_addons_dir = tmp_path / "addons"
        addon_pkg_dir = installed_addons_dir / "nvdastudio"
        addon_pkg_dir.mkdir(parents=True)
        (addon_pkg_dir / "manifest.ini").write_text("name = nvdastudio\n")

        module_dir = addon_pkg_dir / "globalPlugins" / "nvdastudio" / "utils"
        module_dir.mkdir(parents=True)

        computed_root = os.path.abspath(os.path.join(str(module_dir), "..", "..", "..", ".."))
        assert computed_root == str(installed_addons_dir)

        is_dev = os.path.isfile(os.path.join(computed_root, "manifest.ini")) and os.path.isfile(
            os.path.join(computed_root, "build.py")
        )
        assert is_dev is False

    def test_get_logger_nao_cria_log_de_projeto_quando_nao_e_dev_checkout(self, tmp_path, monkeypatch):
        """Com _IS_DEV_CHECKOUT=False, get_logger nao deve escrever nem criar
        _PROJECT_LOG_DIR (reproduz o bug do addons/logs/ se regredir)."""
        fake_project_log_dir = tmp_path / "logs_fantasma"
        fake_nvda_log_dir = tmp_path / "nvda_mirror"

        monkeypatch.setattr(logger_module, "_IS_DEV_CHECKOUT", False)
        monkeypatch.setattr(logger_module, "_PROJECT_LOG_DIR", str(fake_project_log_dir))
        monkeypatch.setattr(logger_module, "_NVDA_LOG_DIR", str(fake_nvda_log_dir))

        logger = get_logger("simulacao_instalado")

        files = [
            getattr(handler, "baseFilename", "")
            for handler in logger.handlers
            if isinstance(handler, logging.FileHandler)
        ]

        assert not any(path.startswith(str(fake_project_log_dir)) for path in files)
        assert any(path.startswith(str(fake_nvda_log_dir)) for path in files)
        assert not fake_project_log_dir.exists()


class TestRedactSecrets:
    """v1.2.0: previews de LLM nao devem gravar chaves de API cruas em disco."""

    def test_redige_chave_estilo_openai(self):
        from nvdastudio.utils.logger import _redact_secrets

        texto = "minha chave e sk-abcdefghijklmnopqrstuvwxyz1234567890"
        assert "sk-abcdefghijklmnopqrstuvwxyz1234567890" not in _redact_secrets(texto)
        assert "[REDACTED]" in _redact_secrets(texto)

    def test_redige_chave_estilo_anthropic(self):
        from nvdastudio.utils.logger import _redact_secrets

        texto = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890"
        assert "abcdefghijklmnopqrstuvwxyz1234567890" not in _redact_secrets(texto)

    def test_redige_chave_estilo_google(self):
        from nvdastudio.utils.logger import _redact_secrets

        texto = "AIzaSyAbCdEfGhIjKlMnOpQrStUvWxYz1234567"
        assert "[REDACTED]" in _redact_secrets(texto)

    def test_redige_bearer_token(self):
        from nvdastudio.utils.logger import _redact_secrets

        texto = "Authorization: Bearer abcdefghij1234567890klmnop"
        assert "[REDACTED]" in _redact_secrets(texto)

    def test_texto_sem_chave_permanece_intacto(self):
        from nvdastudio.utils.logger import _redact_secrets

        texto = "Crie um addon NVDA que anuncia a hora atual."
        assert _redact_secrets(texto) == texto

    def test_log_llm_call_redige_chave_no_preview(self, caplog):
        logger = get_logger("redact_call")
        prompt_com_chave = "Use esta chave: sk-abcdefghijklmnopqrstuvwxyz1234567890 no header"
        with caplog.at_level(logging.DEBUG, logger="nvdastudio.redact_call"):
            log_llm_call(logger, "v1.0.0", prompt_com_chave)
        for record in caplog.records:
            assert "sk-abcdefghijklmnopqrstuvwxyz1234567890" not in record.getMessage()

    def test_log_llm_response_redige_chave_no_preview(self, caplog):
        logger = get_logger("redact_resp")
        resposta_com_chave = "aqui esta: AIzaSyAbCdEfGhIjKlMnOpQrStUvWxYz1234567"
        with caplog.at_level(logging.DEBUG, logger="nvdastudio.redact_resp"):
            log_llm_response(logger, "v1.0.0", resposta_com_chave)
        for record in caplog.records:
            assert "AIzaSyAbCdEfGhIjKlMnOpQrStUvWxYz1234567" not in record.getMessage()


class TestPruneOldLogs:
    """v1.2.0: arquivos nvdastudio_*.log com mais de 30 dias devem ser removidos."""

    def test_arquivo_antigo_e_removido(self, tmp_path):
        from nvdastudio.utils.logger import _prune_old_logs

        antigo = tmp_path / "nvdastudio_2020-01-01.log"
        antigo.write_text("log antigo")
        antigo_mtime = time.time() - (40 * 86400)
        os.utime(antigo, (antigo_mtime, antigo_mtime))

        _prune_old_logs(str(tmp_path), retention_days=30)

        assert not antigo.exists()

    def test_arquivo_recente_e_mantido(self, tmp_path):
        from nvdastudio.utils.logger import _prune_old_logs

        recente = tmp_path / "nvdastudio_2026-08-03.log"
        recente.write_text("log recente")

        _prune_old_logs(str(tmp_path), retention_days=30)

        assert recente.exists()

    def test_arquivo_nao_correspondente_ao_padrao_e_ignorado(self, tmp_path):
        from nvdastudio.utils.logger import _prune_old_logs

        outro = tmp_path / "outro_arquivo.txt"
        outro.write_text("nao e log do nvdastudio")
        outro_mtime = time.time() - (100 * 86400)
        os.utime(outro, (outro_mtime, outro_mtime))

        _prune_old_logs(str(tmp_path), retention_days=30)

        assert outro.exists()

    def test_diretorio_inexistente_nao_levanta_excecao(self, tmp_path):
        from nvdastudio.utils.logger import _prune_old_logs

        _prune_old_logs(str(tmp_path / "nao_existe"), retention_days=30)


class TestLoggerVersao:
    def test_versao_1_2_0(self):
        from nvdastudio.utils.logger import MODULE_VERSION

        assert MODULE_VERSION == "1.2.0"
