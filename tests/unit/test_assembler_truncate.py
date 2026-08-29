import inspect

import nvdastudio.sub_agents.assembler as assembler_mod


class TestAssemblerUsaTruncateAtWordNoWarning:
    def test_narracao_de_warning_usa_truncate_at_word_nao_slice_bruto(self):
        src = inspect.getsource(assembler_mod.run)
        assert "_truncate_at_word(all_warnings[0], 100)" in src
        assert "all_warnings[0][:100]" not in src
