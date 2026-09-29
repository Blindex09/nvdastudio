"""extract_json_object: achado ao vivo (2026-09-29, teste real via Ollama
Cloud, modo Alto) -- json.loads cru em resp.content falhava com "Expecting
value: line 1 column 1" mesmo com uma resposta REAL e completa do modelo,
porque o Ollama Cloud (ai/ollama_client.py ja documenta isso) nao garante
structured output estrito: a resposta as vezes vem cercada de crases de
markdown ou com prosa antes/depois do objeto JSON. JsonFieldStreamer.feed
extraiu o campo "message" corretamente da MESMA resposta que json.loads()
rejeitava -- confirmando que o conteudo era real, so nao comecava com '{'.
"""
import json

import pytest

from nvdastudio.utils.json_stream import extract_json_object


def test_json_puro_sem_modificacao():
	assert extract_json_object('{"action": "run_pipeline"}') == {"action": "run_pipeline"}


def test_json_cercado_por_crases_de_markdown():
	texto = '```json\n{"action": "run_pipeline", "message": "oi"}\n```'
	assert extract_json_object(texto) == {"action": "run_pipeline", "message": "oi"}


def test_prosa_antes_do_json_achado_ao_vivo():
	"""Reproduz exatamente o caso real: o modelo narra em portugues antes do
	objeto JSON que carrega a decisao estruturada."""
	texto = (
		"Vou continuar a correcao do GeminiTranscriber, adicionando os "
		'comentarios que faltam.\n\n{"action": "run_pipeline", '
		'"message": "Vou continuar a correcao.", "task_specification": "corrigir X"}'
	)
	data = extract_json_object(texto)
	assert data["action"] == "run_pipeline"
	assert data["task_specification"] == "corrigir X"


def test_prosa_depois_do_json_extra_data():
	texto = '{"action": "run_pipeline"} Espero que ajude!'
	assert extract_json_object(texto) == {"action": "run_pipeline"}


def test_json_aninhado_com_prosa_nas_duas_pontas():
	texto = 'Claro! {"a": {"b": 1}, "c": [1, 2]} Isso resolve.'
	assert extract_json_object(texto) == {"a": {"b": 1}, "c": [1, 2]}


def test_texto_vazio_levanta_json_decode_error():
	with pytest.raises(json.JSONDecodeError):
		extract_json_object("")


def test_texto_sem_nenhum_objeto_levanta_json_decode_error():
	with pytest.raises(json.JSONDecodeError):
		extract_json_object("isso nao tem json nenhum")
