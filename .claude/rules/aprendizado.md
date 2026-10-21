---
paths:
  - "addon/globalPlugins/nvdastudio/memory/**"
  - "addon/globalPlugins/nvdastudio/builder/**"
---

# Aprendizado sempre (regra 10)

> Texto integral, sem mudança.

### 10. Aprendizado sempre

- O sistema aprende com os erros, as correções, os falsos positivos e as atualizações, para melhorar qualidade,
  performance e precisão, sem a pessoa precisar pedir.
- O aprendizado vale na hora, sem fila de aprovação. Aprendizado sobre o mesmo assunto atualiza a habilidade existente,
  nunca cria duplicata. Habilidades seguem o formato aberto SKILL.md.
- Uma remoção da lista de achados não é automaticamente aprendida como falso positivo: pode ser só um item fora do
  escopo. O julgamento continua sendo da IA.
- As habilidades são aplicadas sozinhas pelo classificador quando a tarefa pede.
- O sistema aprende o que as APIs reais esperam testando de verdade no sandbox, para que o próximo software já nasça
  funcionando.
- Conhecimento que muda no mundo (como acessibilidade) se atualiza sozinho a partir de fontes confiáveis.

## Decisão do dono de 17/out/2026

- O aprendizado que vem de conteúdo não confiável (web, arquivo de terceiros, resultado de ferramenta, MCP, outro agente) também vale na hora,
  sem fila, mas é guardado com a origem marcada e a confiança reduzida, e nunca vira instrução. Isso protege
  contra envenenamento de memória sem tirar a liberdade de aprender.

## Decisão do dono de 20/out/2026

- O aprendizado é silencioso: não avisa na conversa e não há tela de memória para a pessoa ver ou apagar. A origem e a confiança reduzida do que
  veio de fora continuam gravadas por dentro (no registro técnico), para proteger contra envenenamento de memória. Isto troca a parte "visível e
  editável" da decisão de 17/out/2026.

## Decisões do dono de 20/out/2026 sobre o que a pessoa vê do aprendizado

- Não existe tela nem painel de memória em nenhum dos três projetos (o diálogo "Adicionar memória" do Agentic e o painel de memória do Qaaccessibility saem). A pessoa pede por conversa ("lembre disso", "esqueça aquilo"); o que o sistema aprende sozinho continua gravado por dentro, com a origem. Isto troca o que foi dito antes no mesmo dia.
- Habilidade vinda da internet segue a chave de aprovação: com a aprovação ligada, fica aguardando a decisão da pessoa; desligada, entra sozinha, sem fila e sem aviso.
