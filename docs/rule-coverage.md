# Cobertura de Regras e Agentes NVDAStudio

Atualizado em: 2026-08-03

## Objetivo

O NVDAStudio deve criar addons NVDA desde casos simples ate casos complexos:
global plugins, app modules, synth drivers, braille display drivers, tabelas
braille, dicionarios de fala, gestures por locale, settings panels, integrações
com APIs externas e addons com dependencias empacotadas.

Para isso, as regras precisam estar sincronizadas entre gerador, auditor,
critico, builder, testes e documentacao. O arquivo
`addon/globalPlugins/nvdastudio/rule_registry.py` e o contrato central dessa
cobertura.

## Cruzamento com Community Access

O Community Access declara:

- um agente NVDA Addon Specialist para `globalPlugins`, `appModules`,
  `synthDrivers`, `brailleDisplayDrivers`, empacotamento e Add-on Store;
- um agente wxPython Specialist com regras `WX-A11Y-001..014`;
- politica "No Source, No Claim";
- padrao coordenador-trabalhador com agentes especialistas e allowlist.

O NVDAStudio usa isso como baseline, mas expande a cobertura:

- `NVDA-001..063`, exceto `NVDA-041`, que e alias historico de `NVDA-034` (62 regras ativas);
- `WX-A11Y-001..014`;
- `DTK-A11Y` (12 regras);
- `ARCH-001..009`;
- `NVDA-UX-001..003`.

Total: 100 regras ativas (62 NVDA + 14 WX-A11Y + 12 DTK-A11Y + 9 ARCH + 3 NVDA-UX),
conferido contra `rule_registry.RULE_REGISTRY` em 2026-09-03. Os numeros
anteriores deste bloco (84 ativas, 60 NVDA, 7 ARCH, sem DTK-A11Y) estavam
defasados: nao acompanharam NVDA-062, NVDA-063, as 2 ARCH novas nem a
familia DTK-A11Y inteira.

`NVDA-063` (2026-09-03) e a primeira regra do catalogo que confronta DOIS
arquivos: todas as outras olham um arquivo por vez, e por isso nenhuma via
o defeito de costura que passou por todos os portoes na rodada
AssistenteEscrita -- chamador e definicao discordando entre modulos do
mesmo addon.

**Nota de governanca (2026-08-03, achado de auditoria nao resolvido):**
`ARCH-003` e `ARCH-006` tem topicos DIFERENTES em `core/planner.py` (menu
entry point pra multiplas funcionalidades / menu pra addon com dialog) vs
`ai/critic.py` + `builder/nvda_context.py` (AppModule vs GlobalPlugin /
extension points sem register/unregister). Sao 2 pares de regras
genuinamente distintas colidindo na mesma numeracao -- `rule_registry.py`
segue o consenso dos 2 arquivos (critic+nvda_context); os topicos de
`planner.py` continuam ativos no proprio prompt dele, sem entrada correta
no registry central. Requer decisao: renumerar os topicos de `planner.py`
(ex: ARCH-008/ARCH-009) ou fundir com os existentes.

## Ciclo de vida obrigatório de cada regra

Cada regra ativa no registro deve ter:

- `source`: fonte humana ou tecnica;
- `owner_agents`: agentes que precisam conhecer a regra;
- `required_surfaces`: prompts, validadores, testes e documentacao esperados;
- `callbacks`: ciclo de resposta da regra.

Callbacks padrao:

- `prompt_gate`: a regra entra no contexto do agente antes da geracao;
- `static_audit`: a regra pode ser reportada na auditoria estatica;
- `quality_critic`: o critic pode reprovar ou pedir correcao;
- `targeted_fix`: o orchestrator consegue transformar a falha em instrucao de retry;
- `checkpoint_report`: a falha pode aparecer no checkpoint para o usuario.

## Regras de governanca

- Nao criar regra nova apenas em comentario, prompt ou teste isolado.
- Toda regra nova deve entrar no `RULE_REGISTRY`.
- Se uma regra for renumerada, manter alias deprecated com `alias_for`.
- O critic, o accessibility auditor e o code generator recebem o mesmo texto
  central via `RULE_REGISTRY_PROMPT_TEXT`.
- Addons com dependencias externas devem passar por estrategia explicita:
  PyPI name real, bundle em `lib/`, lazy import quando apropriado, validacao de
  arquitetura para `.dll` e `.pyd`, e fallback claro quando a dependencia faltar.
- Prompts ambiguos devem passar pelo clarifier antes de assumir tipo de addon,
  credenciais, API externa, driver ou comportamento invasivo.

## Como validar

Rodar:

```powershell
python -m pytest tests\unit\test_rule_registry_contract.py -q
```

Esse teste garante que:

- todas as regras ativas do projeto aparecem no registro;
- `NVDA-041` nao volta como regra ativa duplicada;
- gerador, auditor e critic recebem o mesmo contrato;
- as fontes do Community Access continuam documentadas.
