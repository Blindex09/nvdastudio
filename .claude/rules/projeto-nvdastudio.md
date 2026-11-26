# NVDAStudio: notas de código

- `addon_builder.py`, `nvda_context.py` e `code_sandbox.py` usam TAB; código novo usa 4 espaços. Ao mexer neles, não reformate o arquivo todo;
  remova só o que ficou sem uso.
- `tests/support.py` monta pastas de addon a partir de blocos (`save_addon_files`); só os testes usam.
- Os testes de execução isolada rodam de verdade: o Docker sobe sozinho (a primeira chamada leva alguns segundos).
- Pendências: falta prova ao vivo com o NVDA real (instalar o pacote gerado e ver carregar); `fix_addon_structure` só funde pastas de plugin;
  o NVDA 2027.1 (master) passa para Python 3.14: a imagem e o empacotamento de dependências (cp313) precisarão acompanhar quando sair.
