# NVDAStudio

NVDAStudio é um addon para o leitor de telas NVDA que cria, corrige, testa e empacota outros addons por meio de uma IA agêntica conversacional.

## Como funciona

O usuário conversa em linguagem natural. Quando o pedido estiver ambíguo, a IA faz perguntas antes de alterar arquivos. Durante a execução, ela informa o que está fazendo, usa ferramentas reais, aceita interrupção e novas instruções e continua a partir do estado atual.

Há um único fluxo de criação e correção:

1. A IA interpreta o pedido e decide se precisa esclarecer algo.
2. No provedor Studio, o roteador seleciona provedor e modelo conforme a tarefa; nos provedores manuais, seleciona somente o modelo.
3. O agente trabalha em uma pasta confinada, lê e edita arquivos, roda testes e corrige falhas.
4. Gates objetivos verificam sintaxe, estrutura NVDA, acessibilidade, execução isolada e integridade.
5. Se o usuário pediu empacotamento, o addon é gerado no formato `.nvda-addon` e validado antes da entrega.

O provedor `Studio`, com o modelo `Alto`, compara os provedores já configurados por capacidade, complexidade, contexto, qualidade, custo, velocidade e confiabilidade observada. Se uma rota falhar, preserva os arquivos e tenta outra rota compatível. A preferência de privacidade limita a execução a um único provedor para não replicar contexto entre serviços.

Factory usa também o roteamento automático nativo do Droid. Ollama, OpenAI, Gemini, Anthropic, xAI e OpenCode Go usam o mesmo contrato agêntico e as mesmas ferramentas do projeto.

## Princípio híbrido

A IA decide:

- intenção e necessidade de perguntas;
- arquitetura e estratégia de implementação;
- quais arquivos alterar;
- uso e sequência de ferramentas;
- diagnóstico e correção;
- se o pedido inclui empacotamento.

Código determinístico decide somente fronteiras objetivas:

- permissões e confirmação de ações sensíveis;
- confinamento de caminhos e prevenção de traversal;
- cancelamento, timeout e isolamento;
- sintaxe e contratos verificáveis do NVDA/wxPython;
- integridade do pacote instalável.

Não há roteamento semântico por palavras-chave, pipeline staged, plano obrigatório por fases, editores paralelos, subagentes fixos ou lógica antiga mantida por compatibilidade.

## Configuração

No painel de configurações do NVDAStudio, escolha o provedor e informe a credencial correspondente quando necessária. `Studio + Alto` permite seleção automática entre provedores e modelos. Nos demais provedores, `Alto` escolhe apenas um modelo daquele serviço; um modelo concreto selecionado manualmente é respeitado.

Studio não possui chave própria: usa somente provedores que já tenham credencial configurada, além da Factory quando o Droid estiver instalado e autenticado. A decisão e o resultado de cada tentativa ficam registrados nos logs.

O baseline do projeto é NVDA `2026.1.1+`. Addons novos devem usar:

- `minimumNVDAVersion = 2026.1.1`
- `lastTestedNVDAVersion = 2026.2.0`

## Desenvolvimento

O contrato central da arquitetura está em [AI_MODULE_SPEC.md](C:/nvdastudio/addon/globalPlugins/NVDAStudio/AI_MODULE_SPEC.md). As regras operacionais estão em [CLAUDE.md](C:/nvdastudio/CLAUDE.md), fonte única para qualquer agente; não manter cópias.

Verificação mínima para qualquer alteração:

```powershell
python -m ruff check addon/globalPlugins/NVDAStudio tests build.py --exclude addon/globalPlugins/NVDAStudio/lib --exclude addon/globalPlugins/NVDAStudio/nvda_docs_cache
python -m mypy addon/globalPlugins/NVDAStudio
python -m pytest -q tests/unit tests/integration
python build.py
```

Bibliotecas vendorizadas em `addon/globalPlugins/NVDAStudio/lib/` e o cache de fonte do NVDA em `nvda_docs_cache/` não são código próprio e ficam fora do lint/mypy.

## Regras de manutenção

- Não manter código, arquivos, shims ou documentação sem consumidor real.
- Não duplicar registries, ferramentas, endpoints ou caminhos de execução.
- Não substituir compreensão semântica da IA por regex ou listas de palavras.
- Todo bug real corrigido recebe teste de regressão.
- Saída de IA não é executada diretamente no processo do NVDA.
- Logs devem redigir segredos e permanecer úteis para diagnóstico.
- A interface deve ser operável por teclado, anunciar progresso e usar linguagem natural.
- Compilar uma atualização não exige incrementar a versão do addon por si só.

## Estrutura

```text
addon/globalPlugins/NVDAStudio/
  ai/           clientes, registry e roteamento de modelos
  builder/      agente, ferramentas, workspace, validação e pacote
  core/         orquestração e tipos de resultado
  gui/          diálogo conversacional e configurações
  memory/       contexto efêmero da sessão
  sub_agents/   validador AST objetivo consumido pelo gate
  tool_system/  aprovação de ações sensíveis
  tools/        gateway local por execução
  utils/        logging, políticas, timeouts e segurança
```

Histórico de mudanças deve ser consultado no controle de versão. Este README documenta apenas o comportamento atual.
