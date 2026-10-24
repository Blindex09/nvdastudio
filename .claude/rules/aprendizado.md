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

## Aprende com os erros e com os acertos (decisão do dono, 21/out/2026)

O aprendizado vale também no meio da tarefa, e não só ao fim: uma cópia do agente revisa em segundo plano o que foi feito quando uma etapa termina (um fato, nunca um relógio) e guarda a lição em silêncio; a lição final da execução substitui a do meio. Com a pessoa ociosa e só quando o conjunto de habilidades aprendidas mudou, um curador junta as que dizem a mesma coisa, sem apagar nada. Quando o agente sai sozinho de uma repetição, o que se repetiu e quantas vezes recomeçou chega ao julgamento da lição como fato, e a lição é do modelo.

## O que se aproveita do Hermes no aprendizado (decisão do dono, 22/out/2026)

- A orientação que a pessoa dá no meio da tarefa para corrigir ou redirecionar o trabalho é o sinal mais forte do que guardar. Ela fica registrada durante toda a execução (não se apaga ao ser aplicada) e é mostrada ao modelo que decide a lição, como fato; é ele quem julga, pelo significado, o que vale guardar.
- Atualizar uma habilidade já guardada é feito a partir do texto atual dela, inteiro (ler antes de escrever): o modelo que junta o aprendizado novo recebe o que a habilidade já sabe. Se a junção não puder ser feita, o aprendizado novo é acrescentado depois do texto atual e nada que a habilidade sabia se perde.
- Não se guarda como regra: falha do ambiente (programa ou pacote não instalado, caminho que mudou, credencial não configurada), afirmação negativa sobre uma ferramenta ("a ferramenta X não funciona") nem erro passageiro que passou em outra tentativa (a lição é o jeito de tentar de novo). Medido ao vivo em 22/out/2026 com cinco casos em tentativas repetidas: a instrução atual da lição já respeita isto (24 a 25 de 25), então o texto não mudou; o que foi acrescentado são fatos para o juiz, não regras.

## A falha da regressão ao vivo vira lição que o próprio agente guarda (decisão do dono, 22/out/2026)

- Quando um passo da regressão ao vivo falha, os fatos da falha (o que o roteiro confere, as últimas linhas que ele imprimiu, o que o verificador de invariantes achou) vão para o mesmo juiz de lições que avalia toda execução terminada. É o modelo que decide, pelo significado, se há algo a guardar; uma falha nunca vira habilidade, no máximo uma nota do que não repetir. O que fica é guardado em silêncio, na memória do Assistente Geral, com a origem. Falha de ambiente, de provedor ou do próprio roteiro não é lição (o juiz decide). O código do produto continua sendo corrigido por quem desenvolve; a lição é do agente.
- Uma nota do que falhou não vive mais que o dia em que o mesmo jeito funcionou (decisão do dono, 22/out/2026): quando uma execução bem-sucedida é julgada, pelo significado, como o mesmo assunto de uma nota de falha, o sucesso aposenta a nota, que fica só como histórico, e a lição nova diz em que condição o jeito antigo falhou. Assunto diferente não aposenta nada: cada lição vale para o seu "quando usar".
