# NVDAStudio: notas de código

- `addon_builder.py`, `nvda_context.py` e `code_sandbox.py` usam TAB; código novo usa 4 espaços. Ao mexer neles, não reformate o arquivo todo;
  remova só o que ficou sem uso.
- `tests/support.py` monta pastas de addon a partir de blocos (`save_addon_files`); só os testes usam.
- Pendências: a execução isolada depende de Docker (20 testes pulam sem ele); falta prova ao vivo com o NVDA real (instalar o pacote gerado
  e ver carregar); `fix_addon_structure` só funde pastas de plugin.
