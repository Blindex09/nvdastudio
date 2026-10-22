---
paths:
  - "features/**"
  - "scripts/**"
  - "tests/**"
---

# O agente se cuida sozinho (regra 20)

> Regra obrigatória, sem exceção, igual nos três projetos. Decisão do dono, 21/out/2026, repetida muitas vezes. Pesquisa em `docs/autonomia.md` do Agentic (Hermes, Anthropic sobre agentes de longa duração, recuperação de laços).

### 20. O agente se cuida sozinho

O agente é livre quanto à estratégia, se ajusta, se corrige e aprende com os erros e com os acertos. O que isso exige, sempre:

- Quem checa, vê os problemas, acha a causa e corrige o caminho é o agente, na própria execução. Quem desenvolve constrói o mecanismo e prova que ele funciona; não faz à mão o que o agente deve fazer sozinho. Diante de qualquer falha a pergunta é "que mecanismo faltou para o agente ter achado e corrigido isto sozinho?", e esse mecanismo é o que se constrói. O conserto à mão só vale como passo para provar o mecanismo, e a entrega diz o que o agente já faz sozinho e o que ainda falta.
- Diante de um laço ou de um erro, nesta ordem: (1) o harness diz ao modelo só o fato, sem dizer o que fazer; (2) o raciocínio sobe e o roteador leva a chamada para outro modelo, só enquanto estiver travado; (3) o agente recomeça uma vez por etapa com o contexto reorganizado; (4) só então a rede de segurança da regra 8, muito rara, encerra com entrega parcial que diz onde parou e o que foi tentado. Progresso é trabalho de verdade (criar, editar, verificar), nunca só atividade.
- Chamada ao modelo: conexão viva e lenta espera; conexão morta (nenhum dado por muito tempo, medido pelo silêncio entre pedaços, nunca pelo tempo da tarefa) é descartada e refeita em outro modelo do mesmo provedor, com uma frase calma à pessoa.
- Aprende com os erros e com os acertos, em silêncio, durante a tarefa e ao fim, e mantém as próprias habilidades em ordem.
- O roteador escolhe entre todos os modelos do provedor por evidência (taxa de sucesso, latência, custo, o que cada um oferece), nunca por lista de nomes, e experimenta os que ainda não têm evidência. O thinking e as demais capacidades de cada modelo são decididos pelo roteador, pela tarefa e pelo que o modelo oferece; a escolha da pessoa, quando existe, vale.
- Hoje só o Ollama funciona, e a prova ao vivo roda no Auto do Ollama; o que é de outro provedor fica pronto, testado em unidade, e é provado quando o crédito voltar.
- Nenhum relógio corta uma tarefa que avança: o único tempo aqui mede a conexão, nunca a tarefa.
- O código do produto muda por quem desenvolve; o agente corrige a execução (caminho, estratégia, resultado, aprendizado), não o código dele.
