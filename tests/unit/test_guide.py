from nvdastudio_mcp import guide


def test_guia_tem_topicos_e_pula_a_persona_antiga():
    titles = [t["topico"] for t in guide.list_topics()]
    assert len(titles) >= 10
    assert not any("FORMATO" in t for t in titles)


def test_busca_por_trecho_do_titulo_sem_diferenciar_caixa():
    found = guide.read_topic("manifest")
    assert found and "minimumNVDAVersion" in found[0].text


def test_busca_vazia_ou_inexistente_nao_devolve_nada():
    assert guide.read_topic("") == []
    assert guide.read_topic("zzz-nao-existe") == []


def test_o_guia_nao_manda_o_modelo_responder_sem_markdown():
    for section in guide.SECTIONS:
        assert "NUNCA use markdown" not in section.text
