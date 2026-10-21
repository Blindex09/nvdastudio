# Pendências do NVDAStudio

## Decisões do dono de 20/out/2026 que ainda não estão no código

As regras estão em `.claude/rules/projeto-nvdastudio.md`. Falta o código, cada item com teste de regressão (regra 12) e prova ao vivo (regra 15):

1. Guardar a chave de API no cofre de credenciais do Windows e não em `config.conf` do NVDA (`gui/settings_panel.py::get_api_key` e quem grava); migrar as chaves que já estão no arquivo e apagá-las de lá.
2. Garantir que a janela do assistente (`gui/studio_dialog.py`) nunca trave o NVDA nem o resto durante o trabalho (hoje há `ShowModal` e trabalho em threads; medir o que trava de verdade).
3. Linha de status com provedor e modelo no modo Studio, lida com as setas, nunca falada sozinha.
4. Tirar o teto de tokens por construção e as rodadas de correção calculadas (regra 8), já registrados como dívida.
5. Instalar no NVDA da pessoa segue a chave de aprovação; só a mensagem final falada sozinha.
6. Autonomia do agente (decisão do dono, 21/out/2026, a mesma do Agentic): conferir cada laço, repetição e correção do pipeline de IA deste projeto contra a ordem escrita em `.claude/rules/projeto-nvdastudio.md` (fato ao modelo, raciocínio sobe, o modelo muda de caminho, só por último a rede de segurança). Onde o código encerra ou dita a estratégia antes disso, corrigir com teste. No Agentic isto já foi feito para o laço de ferramentas (commit 45d529e).
