# NVDAStudio — instruções operacionais para agentes

Este arquivo é lido automaticamente no início de qualquer sessão de agente
neste repositório. Não é material de estudo — são regras de processo.

## Antes de declarar qualquer implementação concluída

**Não é opcional.** Antes de dizer "pronto" pra qualquer mudança de código
neste projeto, consulte e aplique o que for cabível dos 3 documentos abaixo.
Eles não são referência passiva — são checklist operacional.

1. **`docs/metodologia-verificacao-arquitetura.md`** — pirâmide de
   verificação (Static Analysis → Unit → Component → Architecture Fitness
   Functions → Contract → Integration → Non-Functional → E2E → Regression →
   Quality Gate → Observability). Pra TODA mudança de código:
   - Rodar `ruff check` no(s) arquivo(s) tocado(s) — sempre.
   - Rodar `mypy` se o projeto for Python — este é.
   - Rodar os testes unitários/integração relevantes ao módulo tocado, não
     só assumir que compila.
   - Se a mudança envolve a "costura" entre 2+ módulos (um passa dado pro
     outro, um chama o outro, um documenta um contrato que o outro deveria
     respeitar): ler os dois lados antes de considerar concluído — é onde
     mora a classe de bug mais cara de descobrir tarde (o exemplo concreto
     está registrado no fim do próprio documento).
   - Todo bug real corrigido ganha teste de regressão, sempre, sem exceção.
   - Nunca subir pro degrau mais caro (E2E real, custa API de verdade) sem
     esgotar os degraus baratos antes — E2E confirma, não descobre.

2. **`docs/conceitos-ia-para-desenvolvimento-de-software.md`** — engenharia
   de sistemas com IA (Harness Engineering, roteamento determinístico,
   decomposição, Agent Evals, trajetória, custo, loop detection,
   checkpoints, graceful degradation). Aplicável sempre que a mudança tocar
   o pipeline de agentes (Planner/Critic/Orchestrator/sub-agentes): a
   decisão de CONTEÚDO é da IA, a decisão de ROTEAMENTO é determinística
   (nunca inverter isso); ao decompor uma tarefa grande em partes, garantir
   que quem AVALIA o resultado também sabe que existem partes (não só quem
   gera).

3. **`docs/conceitos-ia-seguranca-confiabilidade.md`** — segurança e
   confiabilidade de agente (sandboxing, permission boundaries, blast
   radius, adversarial evals, recovery/resilience). Aplicável sempre que a
   mudança tocar execução de código gerado, ferramentas expostas a um
   sub-agente, ou conteúdo vindo de fora (busca web, input do usuário).

## Regra geral de conclusão

Uma implementação só está "concluída" quando: lint limpo, testes relevantes
passando (incluindo os novos de regressão do bug corrigido), e — quando a
mudança tocar a costura entre módulos — confirmação de que o que um lado
promete é literalmente o que o outro consome. "Parece certo" não é
suficiente; "os degraus baratos da pirâmide confirmam" é.

Isso não substitui julgamento — para mudanças triviais e isoladas, aplicar
o bom senso sobre qual subconjunto do checklist é proporcional. O objetivo é
processo real de engenharia, não burocracia por burocracia.
