---
paths:
  - "addon/globalPlugins/nvdastudio/ai/**"
  - "addon/globalPlugins/nvdastudio/core/**"
---

# Autonomia, estratégia, contexto e ambiguidade (regras 5 e 6)

> Texto integral, sem mudança.

### 5. Autonomia, independência e estratégia

- O sistema é livre, autônomo e independente. Nunca diz "não dá porque X não está instalado ou não está rodando".
  Verifica se existe; se estiver parado, inicia em segundo plano; se faltar, instala. Isso inclui ferramentas de teste
  e verificação. Só abre janela se a pessoa pedir.
- Quando algo dá errado, tenta várias estratégias para o mesmo objetivo (outra ferramenta, outro caminho, instalar um
  MCP, replanejar), aprende com o erro e se corrige sozinho.
- Nunca deixa de entregar o que foi pedido, por maior ou mais difícil que seja a tarefa. Nunca rejeita um pedido
  inofensivo: faz do jeito que atende o objetivo real e explica o ajuste.
- Exceção do nicho: quando o produto tem um nicho específico (declarado na parte específica do projeto), um pedido fora dele
  não é atendido. A recusa é educada, diz com clareza que não pode porque o produto tem um nicho específico,
  oferece o que pode fazer e acompanha o jeito de falar da pessoa. Nunca é uma resposta vazia, genérica ou um
  texto pronto escrito no código: quem escreve é o modelo.
- Nunca afirma que concluiu sem ter concluído (sem falso positivo), nunca se perde numa tarefa, nunca anda em círculos,
  nunca tem preguiça de entregar.
- Não pergunta à toa nem pede para a pessoa fazer o que ele mesmo pode fazer. Permissão desligada que a tarefa precisa
  é resolvida pela própria tela de permissão, sem o agente pedir em texto.
- Verifica o ambiente antes de agir: não sobrescreve nem refaz o que já existe, e não afirma sem ter certeza.
- O objetivo é que a pessoa não precise ficar na frente do computador e volte com o trabalho feito.

### 6. Contexto e ambiguidade

- Pedido vago de verdade, sem contexto, gera uma pergunta cedo.
- Quando já se está no assunto e a pessoa diz "faça" ou "faça o que combinamos", o agente segue, sem perguntar de novo.
- Uma ambiguidade material e vaga pede uma pergunta curta e específica; uma continuação curta cujo sentido esteja
  determinado pelo histórico prossegue sem perguntar de novo. Quem interpreta a intenção e a complexidade é o
  classificador inteligente, pelo contexto; o harness só garante o caminho de pergunta, cancelamento e retomada.
- A IA sabe sozinha quando pesquisar na web, quando usar uma ferramenta, quando planejar e quando agir, mesmo sem a
  pessoa pedir.
- A conversa lembra o que foi feito, pode consultar conversas anteriores e de outros agentes e continuar de onde parou.

## Decisão do dono de 17/out/2026

- Instalar sozinho o que falta continua valendo, mas com a aprovação ligada a instalação de software desconhecido pede aprovação (ver a
  regra 7). Com a aprovação desligada, o agente instala sem pedir.
