# Engenharia, Arquitetura e Verification & Validation de Software

> Documento de referência pessoal (Felipe), com base em práticas atuais de
> engenharia de software sobre como verificar sistemas de ponta a ponta. Guarda os conceitos
> pra reuso em qualquer projeto futuro, não só no NVDAStudio.
> Criado em 2026-08-09, motivado por um achado real neste projeto (ver exemplo
> concreto no final).

> **Nota de escopo (2026-08-09, rodada 2)**: a pirâmide original abaixo é
> forte como metodologia de VERIFICAÇÃO (o código faz o que devia?), mas não
> cobre sozinha arquitetura de software (o SISTEMA continua saudável
> conforme cresce?). A seção "Arquitetura como código verificável" (mais
> abaixo) fecha esse lado — pirâmide de testes + fitness functions
> arquiteturais juntas.

## A ordem certa (do mais barato pro mais caro)

```
Static Analysis
  -> Unit Tests
  -> Component/Module Tests
  -> Architecture Fitness Functions
  -> Contract Tests
  -> Integration Tests
  -> Behavioral Evals
  -> Non-Functional Tests (performance/security/resilience)
  -> E2E Real
  -> Regression Testing
  -> Quality Gate
  -> Observability-driven Root Cause Analysis
```

A heurística geral: **priorize o degrau de baixo antes de gastar no degrau
alto.** Cada degrau tende a ser mais caro (tempo, dinheiro, API real) e mais
lento de rodar que o anterior — gastar num degrau alto pra achar um bug que
um degrau baixo já teria achado de graça é desperdício.

**Isso é heurística de custo, não lei rígida de sequência.** Engenharia
moderna não exige uma ordem universal obrigatória: testes de camadas
diferentes costumam rodar em PARALELO no CI (não em fila estrita), e certos
riscos justificam investir cedo em E2E, segurança ou performance mesmo antes
de esgotar os degraus baratos — por exemplo, uma mudança que toca
autenticação ou dado sensível pode justificar um teste de segurança
antecipado, independente de onde ela está na pirâmide. A ordem aqui é um
guia de PRIORIZAÇÃO DE CUSTO, pra evitar o erro mais comum (descobrir via
E2E caro algo que um teste barato já pegaria) — não uma sequência que
precisa ser seguida à risca em todo cenário.

### 1. Static Analysis
Lint, type-check, análise de AST. Não executa nada — só lê o código. Custo:
quase zero, roda em segundos — deveria rodar depois de TODA edição de código,
sem exceção.
- **Lint** (`ruff` em Python, `eslint` em TS/JS, etc.) — sempre, em qualquer
  linguagem.
- **Type-check** (`mypy` em Python, `tsc --noEmit` em TS) — **`mypy` só se o
  projeto for Python**; em outra linguagem, usar o type-checker nativo dela
  (não existe equivalente universal).
- `ast.parse()` (ou o parser da linguagem) pra sintaxe pura, quando nem lint
  completo é possível ainda.

### 2. Unit Tests
Testa uma função/classe isolada, sem dependências externas. A maior parte da
suite deveria estar aqui — são os mais baratos e rápidos de rodar em loop.

### 3. Component/Module Tests
Testa um módulo inteiro (várias funções/classes juntas) ainda isolado do resto
do sistema. Verifica que o módulo se comporta certo *sozinho*.

### 4. Integration Tests
Testa múltiplos módulos juntos, geralmente com dependências externas (API,
banco, LLM) mockadas. Verifica que os módulos conseguem *conversar* — mas não
necessariamente que o que um promete é o que o outro espera.

### 5. Contract Tests
**O degrau que mais falta em projetos reais.** Verifica explicitamente que a
"promessa" de um módulo (um campo, um parâmetro, um callback, uma regra
documentada) é exatamente o que o módulo consumidor espera e usa — não só que
a chamada não quebra. É aqui que se pega bug do tipo "módulo A grava o campo
`step_issues`, módulo B lê `issues`" ou "função X documenta o parâmetro Y como
alias de Z, mas nada popula Y de verdade".

**Como caçar esse tipo de bug sem gastar em teste real**: pegar cada
"costura" entre dois módulos (uma função que outro módulo chama, um campo que
outro módulo lê, uma regra que um prompt/registry declara e outro deveria
aplicar) e perguntar: *o que um lado promete é literalmente o que o outro lado
consome, com o mesmo nome/formato/timing?* Ler os dois lados junto, não cada um
isolado.

### 6. Behavioral Evals
Testa se o sistema *decide certo* dado um comportamento plausível — diferente
de Integration Tests (só verifica se os dados fluem) e diferente de E2E Real
(gasta API de verdade). Usa respostas de modelo mockadas mas **realistas**
(não só um mock genérico) pra verificar se a lógica de decisão (aprovação,
roteamento, retry) reage do jeito certo a cenários reais sem pagar por eles.

### 7. E2E Real
Sistema completo, ponta a ponta, com chamadas reais (API paga, rede, etc).
O degrau mais caro e mais lento — deve ser usado pra **confirmar**, não pra
**descobrir**. Se um bug só aparece aqui e nunca antes, é sinal de que um
degrau mais barato deveria ter pego, e vale investir em fechar essa lacuna.

### 8. Regression Testing
Todo bug real encontrado (em qualquer degrau) ganha um teste automatizado que
prova que ele não volta. Disciplina simples: **bug → teste de regressão**,
sempre, sem exceção.

### 9. Observability-driven Root Cause Analysis
Quando algo falha em produção (ou num teste real caro), usar dados observáveis
(logs estruturados, métricas, trajetória de decisão) pra localizar a causa
raiz rápido, em vez de re-executar tentativa-e-erro. Conceitos ligados:
- **Failure Localization**: identificar EXATAMENTE qual módulo/linha causou a
  falha, não só "o pipeline falhou".
- **Dependency tracing**: seguir a cadeia de dependências entre módulos pra
  achar onde o dado real diverge do esperado.

## Arquitetura como código verificável

A pirâmide acima responde "o código funciona?". As seções abaixo respondem
uma pergunta diferente: **"a arquitetura continua saudável conforme o
sistema cresce?"** — sem isso, um projeto pode ter 100% dos testes passando
e ainda assim estar acumulando degradação estrutural silenciosa.

### Architectural Fitness Functions — o conceito central desta seção

Transformar regras arquiteturais em **verificações automáticas**, incorporadas
ao mesmo pipeline dos testes — não só documentadas em texto que ninguém
relê. Exemplos de regra que vira checagem de verdade:

```
- modulo de dominio nao pode depender de UI
- nao pode haver dependencia circular entre modulos
- todo modulo publico declara MODULE_VERSION
- nenhum segredo/API key hardcoded no codigo
- cobertura de teste no codigo critico >= limite definido
- latencia de um step <= limite definido
- toda chamada de rede tem timeout explicito
```

É a mesma disciplina, aplicada em outra camada, da seção "Contract Tests"
(verificar a costura ENTRE dois módulos) — fitness functions verificam a
costura entre o código INTEIRO e as regras que ele deveria sempre respeitar,
continuamente, não só numa auditoria manual ocasional.

**Architecture Conformance Testing**: rodar essas fitness functions de
verdade a cada mudança, confirmando que a implementação real ainda respeita
a arquitetura definida — não só na hora que foi desenhada.

**Architecture / Dependency Tests**: testes específicos para os LIMITES
entre camadas/módulos (ex: "o módulo `ai/` nunca importa `gui/`") — a versão
testável de um diagrama de arquitetura que, sem isso, só existe como
intenção.

**Technical Debt / Architectural Drift Detection**: detectar automaticamente
quando mudanças recentes começam a se afastar da arquitetura pretendida —
antes que vire um problema grande o suficiente pra exigir um resgate manual.

### Evolutionary Architecture e Continuous Architecture / Architecture as Code

Arquitetura não é algo desenhado uma vez e congelado — é continuamente
EVOLUÍDA através de mudanças pequenas + feedback real (dos testes, das
fitness functions, do uso real). **Continuous Architecture** / **Architecture
as Code** é a prática de aproximar essa evolução do pipeline automatizado —
a arquitetura vive em verificações executáveis, não só em documentação que
desatualiza.

### Architecture Decision Records (ADRs)

Registrar cada decisão arquitetural relevante junto com o **porquê** — não
só "usamos X", mas "escolhemos X em vez de Y porque Z". O padrão de
changelog já usado em cada módulo deste projeto (ver `AI_MODULE_SPEC.md` e
o cabeçalho de cada arquivo, sempre com "achado real"/"motivado por") já É,
na prática, uma forma de ADR — vale reconhecer isso formalmente ao decidir
arquitetura em qualquer novo projeto.

### Quality Attributes / "-ilities"

As propriedades não-funcionais que definem se um sistema é bom, além de
"funciona": **reliability**, **scalability**, **maintainability**,
**testability**, **security**, **accessibility**, **performance**,
**resilience**, **observability**. Cada uma merece verificação própria, não
só ser citada como intenção — as próximas subsecções cobrem como testar
várias delas na prática.

### Resilience Testing / Fault Injection e Chaos Engineering

**Resilience Testing**: testar deliberadamente timeout, indisponibilidade,
falha parcial de dependência, comportamento de retry, circuit breaker — o
sistema DEGRADA bem quando uma peça falha, ou quebra em cascata? **Chaos
Engineering** é a forma mais radical disso: provocar falhas controladas de
propósito (mesmo em produção, com salvaguardas) pra confirmar resiliência
real, não só teórica.

### Performance / Load / Stress / Soak Testing

Família de teste quase ausente da pirâmide original, e importante pra
qualquer sistema que vá crescer: **Load Testing** (comportamento sob carga
esperada), **Stress Testing** (além do limite esperado, até quebrar —
descobrir ONDE quebra), **Soak Testing** (carga sustentada por muito tempo —
pega vazamento de memória/recurso que só aparece com o tempo).

### Security Testing — SAST / DAST / SCA

Camada própria de segurança de código (distinta do eixo de segurança de
AGENTE já coberto em `conceitos-ia-seguranca-confiabilidade.md`): **SAST**
(Static Application Security Testing — analisa o código sem executar, tipo
lint focado em vulnerabilidade), **DAST** (Dynamic — testa a aplicação
RODANDO, de fora, como um atacante faria), **SCA** (Software Composition
Analysis — audita dependências de terceiros atrás de CVEs conhecidas).

**Ferramenta concreta pra Python (SAST): `bandit`.** Rodar `bandit -r
<pasta>` custa segundos, zero API, e pega uma classe de problema que nenhum
outro degrau da pirâmide cobre: exceção silenciosamente engolida
(`try/except: pass`), uso de `subprocess`/`urllib` sem cuidado, gerador
pseudo-aleatório inseguro usado em contexto sensível. Achado real (2026-08-09):
17 ocorrências de `try/except: pass` sem NENHUM log — nenhuma delas era
comportamento errado (fallbacks legítimos), mas todas violavam a regra de
"nunca engolir exceção silenciosamente", porque debugar uma falha nesses
pontos no futuro seria impossível sem log nenhum. SCA já tinha ferramenta
concreta neste projeto antes disso (`pip-audit`, via pre-commit).

### Dead Code Detection

Ferramenta concreta pra Python: `vulture`. Acha função/variável/atributo
que parece nunca ser referenciado em lugar nenhum do código. Ruído alto em
confiança baixa (60%) — muito do que aparece é callback de framework (GUI
chamado pelo próprio wx, nunca por código do projeto) ou campo de dataclass
— mas achou candidatos reais de limpeza que vale triar manualmente. Mesma
categoria do achado real desta sessão de `memory_loop.py` (493 linhas nunca
importadas por ninguém) — esse tipo de módulo morto que ninguém percebe até
alguém rodar a ferramenta certa.

### Mutation Testing

Altera o código deliberadamente (introduz um bug de propósito — inverte uma
condição, muda um operador) e verifica se a suíte de testes REALMENTE
detecta esse defeito. Responde uma pergunta que cobertura de linha sozinha
não responde: "meus testes têm asserções fortes o bastante, ou só
'executam' o código sem checar nada de verdade?"

### Property-Based Testing

Em vez de escrever exemplos manuais um por um, gerar automaticamente MUITOS
inputs (incluindo casos extremos que um humano não pensaria) e verificar uma
PROPRIEDADE/invariante que deve sempre valer, não um valor exato esperado.
Este projeto já usa isso (`hypothesis`, ver `test_ast_validator_hypothesis.py`)
— vale reconhecer o nome formal da técnica ao aplicá-la em outros projetos.

### Consumer-Driven Contract Testing

Evolução mais específica de "Contract Tests" (seção 5 da pirâmide) quando
existem CONSUMIDORES e PROVEDORES bem definidos (ex: um frontend consumindo
uma API, um serviço consumindo outro): o consumidor declara o contrato que
espera, e esse contrato vira o teste que o provedor precisa continuar
satisfazendo — inverte quem "dita" o contrato, do provedor pro consumidor
real.

### Maintainability / Internal Quality como métrica contínua

Manutenibilidade não é "ter o código funcionando" — é uma propriedade que
precisa ser MEDIDA continuamente, não só assumida. Sinais concretos e
verificáveis: tamanho/complexidade de função (funções gigantes são difíceis
de entender e testar), duplicação de código, acoplamento entre módulos
(quantos outros módulos um módulo específico afeta se mudar), e a própria
cobertura de teste do código crítico. Tratar isso como métrica que pode
DEGRADAR com o tempo (não um estado permanente uma vez alcançado) é o que
liga esta seção de volta à Architectural Fitness Functions — a manutenibilidade
também pode virar uma checagem automatizada, não só opinião de quem revisa.

### Configuration Drift Detection e Dependency / Protocol Compliance

**Configuration Drift Detection**: detectar quando a configuração REAL de um
ambiente (variáveis, versões, flags) diverge silenciosamente da configuração
esperada/documentada — o mesmo princípio de "Architectural Drift Detection"
(já coberto acima), aplicado a configuração em vez de estrutura de código.

**Dependency Compliance**: verificar que as dependências de terceiros
usadas continuam dentro do esperado — versão compatível, licença aceitável,
sem vulnerabilidade conhecida (isso já é parcialmente SCA, ver seção acima,
mas Dependency Compliance é mais amplo: inclui licenciamento e política de
atualização, não só CVE).

**Protocol Compliance**: quando um sistema implementa um protocolo/contrato
formal externo (uma API pública, um formato de arquivo padronizado, um
protocolo de comunicação entre serviços), verificar que a implementação
respeita a ESPECIFICAÇÃO do protocolo, não só os testes que o próprio time
escreveu — evita o caso de "meus testes passam, mas não sigo o protocolo
de verdade".

### Evidence-Based Completion

Uma implementação está "concluída" quando existe EVIDÊNCIA verificável
(lint limpo, testes passando, fitness functions ok), não quando "parece
certo" ou "deveria funcionar". Esse é o princípio que fecha o documento
inteiro: cada degrau da pirâmide existe pra gerar evidência concreta antes
do próximo degrau (mais caro) ser necessário — "Quality Gate" (seção 19) é
a forma operacional desse princípio, um portão que só abre com evidência
real, não com confiança subjetiva.

### O pipeline com arquitetura incorporada

```
Codigo mudou
  -> Static Analysis
  -> Unit Tests
  -> Architecture Fitness Functions
  -> Component Tests
  -> Contract Tests
  -> Integration Tests
  -> Non-Functional Tests (performance/security/resilience)
  -> E2E Real
  -> Regression Testing
  -> Quality Gate
  -> Deploy
  -> Observability-driven Root Cause Analysis
```

A diferença de fundo: o sistema deixa de ser verificado só por "o software
funciona?" e passa a ser verificado também por "**a arquitetura continua
saudável?**" — a mesma lógica de "achar o defeito no estágio mais barato
possível" (o princípio central deste documento inteiro) agora se aplica
também à saúde estrutural do projeto, não só ao comportamento do código.

## Exemplo do tipo de bug que este documento existe pra evitar

Um pipeline de múltiplos estágios, onde um estágio final AVALIA a saída dos
estágios anteriores, tinha um estágio de avaliação que nunca recebia o
OBJETIVO de cada tarefa individual — só via o resultado produzido, sem saber
o que aquele resultado especificamente deveria conter. Um módulo prometia
(via nome de parâmetro e docstring) passar contexto suficiente pro avaliador
julgar, mas na prática só passava a saída de etapas anteriores — nunca o
objetivo da etapa atual. Resultado: rejeições sistemáticas de saídas
corretas, custando uma quantidade significativa de chamadas caras de API
antes do problema ser diagnosticado.

Isso é um bug de **Contract Test** clássico. Uma auditoria de integração
(múltiplos agentes de leitura, focados exatamente nesse padrão "promessa vs.
realidade", sem nenhuma chamada de LLM externa) achou esse bug e vários
outros do mesmo tipo em minutos, com custo zero de API — o mesmo bug só
tinha aparecido antes via um teste E2E real caro. Essa é a lição central
deste documento: **o degrau 5 (Contract Tests) deveria ter pego isso antes
do degrau 7 (E2E Real) precisar gastar dinheiro pra achar.**

---

## v1 fechada (2026-08-09)

Este documento está fechado como v1. Não é uma lista de buzzwords pra
crescer indefinidamente a cada termo novo que aparecer — cobre a espinha
dorsal de Verification & Validation (Static → Unit → Component →
Architecture Fitness Functions → Contract → Integration → Non-Functional →
E2E → Regression → Quality Gate → Observability) mais o eixo de arquitetura
como código verificável. Evolução futura deveria vir de problema real
encontrado na prática, não de "achei mais um conceito pra adicionar" — o
mesmo princípio que o documento já defende pra código (bug real → teste de
regressão) vale pra ele mesmo.
