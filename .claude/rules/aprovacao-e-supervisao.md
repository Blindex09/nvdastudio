---
paths:
  - "addon/globalPlugins/nvdastudio/tool_system/**"
  - "addon/globalPlugins/nvdastudio/gui/**"
---

# Aprovação e supervisão humana (regras 7 e 16)

> Texto integral das regras 7 e 16, mais as decisões do dono de 17/out/2026 (no fim). A divergência antiga com a regra permanente de harness sobre ferramentas irreversíveis está resolvida: a chave de aprovação da pessoa vale para tudo.

### 7. Aprovação: ligada ou desligada, nunca bloqueio

- Com a aprovação desligada, o agente faz tudo sem perguntar. Com ela ligada, faz com pedido de aprovação. Nunca uma
  recusa seca. Vale para o sistema inteiro e para todas as interfaces.
- Ações irreversíveis ou de alto impacto (apagar, sobrescrever, enviar, publicar, gastar) seguem a configuração de
  aprovação.
- A confirmação mostra tudo o que vai mudar, inclusive o que seria desligado. Nunca desligar uma capacidade que ninguém
  pediu.
- A segurança existe, mas sem travas desnecessárias: o sistema é seguro e ao mesmo tempo livre.
- A pasta de trabalho acompanha a chave de aprovação (decisão do dono, 20/out/2026): com a aprovação desligada o agente é livre de
  verdade e mexe onde a pessoa pedir, inclusive fora da pasta; com ela ligada, o que fica fora da pasta pede aprovação mostrando o
  caminho exato. O que nunca depende da chave: a honestidade da plataforma e nunca gravar segredo em conversa ou registro.

### 16. Supervisão humana calibrada

- Intervenção humana onde o risco é maior (ações irreversíveis, escopo ampliado, ambiguidade material) e fora do
  caminho no resto. Supervisão constante em ação de baixo risco é tão errado quanto autonomia total em ação de alto
  risco.

## Decisões do dono de 17/out/2026

- Com a aprovação desligada pela pessoa, o agente segue tudo sem pedir aprovação, inclusive em ação irreversível. Ligada, pede. A aprovação é
  uma chave da pessoa; não existe ferramenta que a configuração não consiga soltar.
- Com a aprovação ligada, a aprovação vale para os argumentos exatos que foram mostrados: se os argumentos mudam depois do sim, a decisão
  anterior não vale e uma nova é pedida.
- Com a aprovação ligada, instalar software desconhecido (pacote, programa, servidor MCP, skill de terceiros) sempre pede aprovação, por risco de
  cadeia de suprimento. Com ela desligada, segue.
- Decisão de 20/out/2026: com a aprovação desligada, o agente apaga, move e altera onde a pessoa pedir, também fora da pasta de trabalho. Com ela ligada, ação fora da pasta pede aprovação com o caminho exato. Um pedido de aprovação que a IA de governança levanta sobre algo que a pessoa acabou de pedir continua sendo perguntado quando a aprovação está ligada (a pergunta mostra tudo o que vai mudar).
- Confirmado pelo dono em 20/out/2026: com a aprovação ligada, ação fora da pasta de trabalho pede aprovação; só com a aprovação desligada ela não pede. Vale nos dois chats do Agentic e nos outros dois projetos.
- Cópia de segurança do que fica fora da pasta de trabalho (decisão do dono, 20/out/2026): é feita sempre, com a aprovação ligada ou desligada, em silêncio; não pede e não avisa. Serve para o pedido de desfazer.
