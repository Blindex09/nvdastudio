# Design: Cobertura E2E Completa — NVDAStudio

**Data:** 2026-04-17
**Autor:** olive (via NVDAStudio session)
**Status:** Aprovado

---

## Contexto

Após auditoria completa do projeto, foram identificados três grupos de gaps de cobertura:

1. **Regras semânticas sem validador** — existem no system prompt mas não são detectadas deterministicamente pelo `addon_builder.py`
2. **Fluxos internos do Orchestrator** — replan, clarification, context compression sem E2E
3. **ESTRUTURA-000** — único gap menor nas regras determinísticas já existentes

---

## Decisões de Design

### Novos validadores: funções `_check_*()` em `addon_builder.py`

Funções auxiliares chamadas por `validate_addon_structure()`. Padrão consistente com `_detect_pyd_architecture`, `_is_known_module`. Arquivo único, sem nova dependência.

### Testes E2E dos validadores (E14–E19): sem API, determinísticos

Padrão idêntico a E1–E13: fixture Python inline → `save_addon_files` → `validate_addon_structure` → assert fail + pass + message quality.

### Testes E2E do Orchestrator (E20–E22): API real + `@requires_groq`

Padrão `test_full_pipeline.py`. Timeout e escalação: monkeypatch de `_STEP_TIMEOUT_SECONDS` e modelo inválido para disparar paths deterministicamente com infraestrutura real.

---

## Escopo de Implementação

### 1. Validadores novos em `addon_builder.py`

| Função | Regra | Técnica |
|---|---|---|
| `_check_nvda001_next_handler()` | NVDA-001 | AST: `event_*` sem `nextHandler` no corpo |
| `_check_nvda008_script_description()` | NVDA-008 | AST: `@script` sem kwarg `description` |
| `_check_nvda009_atalho_conflito()` | NVDA-009 | Regex: atalhos reservados NVDA core |
| `_check_nvda019_translators()` | NVDA-019 | Texto linha-a-linha: `_()` sem `# Translators:` |
| `_check_nvda021_indentacao()` | NVDA-021 | Texto: linhas com espaços em vez de TABs |
| `_check_wx_a11y_critical()` | WX-A11Y-001/002/003 | AST: widgets sem SetName, Panel sem AcceleratorTable, EVT_LEFT_DOWN sem teclado |

### 2. Testes E2E — validadores (E14–E19)

| Arquivo | Regra | Cenários |
|---|---|---|
| `test_e14_nvda001_next_handler.py` | NVDA-001 | fail: `event_*` sem nextHandler; pass: com nextHandler; falso positivo: método normal |
| `test_e15_nvda008_script_desc.py` | NVDA-008 | fail: `@script` sem description; pass: com description; edge: gesture sem description |
| `test_e16_nvda009_atalho.py` | NVDA-009 | fail: `nvda+n`, `nvda+q` (reservados); pass: `nvda+shift+o`; lista completa de core keys |
| `test_e17_nvda019_translators.py` | NVDA-019 | fail: `_()` sem comment; pass: com `# Translators:`; falso positivo: hardcoded sem `_()` |
| `test_e18_nvda021_tabs.py` | NVDA-021 | fail: indentação espaços; pass: TABs; falso positivo: comentário com espaços |
| `test_e19_wx_a11y_criticos.py` | WX-A11Y-001/002/003 | fail + pass para cada uma das 3 regras críticas |

### 3. Teste unitário ESTRUTURA-000

`tests/unit/test_estrutura000.py`: `validate_addon_structure("/inexistente")` retorna `["ESTRUTURA-000: ..."]`.

### 4. Testes E2E — Orchestrator (E20–E22)

| Arquivo | Fluxo | Validações |
|---|---|---|
| `test_e20_orchestrator_replan.py` | Replan + degradação sistêmica | `replan_count >= 1`; evento `REPLANEJANDO` emitido; evento `AVISO` degradação |
| `test_e21_orchestrator_clarif.py` | Mid-pipeline clarification | step `user_clarification` gerado; evento `AGUARDANDO_USUARIO`; pipeline conclui com callback |
| `test_e22_orchestrator_context.py` | Context compression + assembly output | output > 3000 chars → resumo estruturado; `assembly_output` não-vazio; `completed_message` não-vazio |

---

## Atalhos NVDA Core reservados (NVDA-009)

```python
_NVDA_CORE_GESTURES = {
    "nvda+n", "nvda+q", "nvda+f2", "nvda+f3", "nvda+f4",
    "nvda+shift+f4", "nvda+ctrl+f", "nvda+f5", "nvda+f6",
    "nvda+f7", "nvda+f8", "nvda+f9", "nvda+f10", "nvda+f11",
    "nvda+f12", "nvda+shift+f12", "nvda+1", "nvda+2",
    "nvda+3", "nvda+4", "nvda+5", "nvda+6", "nvda+7",
    "nvda+8", "nvda+9", "nvda+0", "nvda+a", "nvda+b",
    "nvda+ctrl+b", "nvda+c", "nvda+d", "nvda+e",
    "nvda+shift+e", "nvda+f", "nvda+ctrl+f", "nvda+g",
    "nvda+h", "nvda+shift+h", "nvda+i", "nvda+j",
    "nvda+k", "nvda+shift+k", "nvda+l", "nvda+m",
    "nvda+shift+m", "nvda+shift+s", "nvda+t",
    "nvda+shift+t", "nvda+u", "nvda+shift+u",
    "nvda+v", "nvda+w", "nvda+x", "nvda+y", "nvda+z",
}
```

---

## Critérios de Sucesso

- Todos os 22 validadores determinísticos têm E2E (21 existentes + ESTRUTURA-000)
- Todas as 6 novas regras têm fail path + pass path + message quality
- Todos os 3 fluxos do Orchestrator têm E2E com API real
- `pytest tests/e2e/ -v` passa (com GROQ_API_KEY) sem regressões
- `pytest tests/unit/test_estrutura000.py` passa sem API
