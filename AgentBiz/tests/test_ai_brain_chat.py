# -*- coding: utf-8 -*-
"""Tests del camino de llamada LLM de ask_nvidia_sync (chat de la oficina).

Cubre los dos bugs reales del feed:
- guard len(response) > 10 rechazaba respuestas cortas legitimas ("FUNCIONA")
- curl -s sin --show-error ni exit code enmascaraba timeouts como "Sin respuesta"
"""
import json
import subprocess


def _resp_stdout(content=None, reasoning=None, finish="stop"):
    msg = {"role": "assistant"}
    if content is not None:
        msg["content"] = content
    if reasoning is not None:
        msg["reasoning_content"] = reasoning
    return json.dumps({
        "choices": [{"finish_reason": finish, "message": msg}],
        "usage": {"completion_tokens": 5},
    })


def _run(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=["curl"], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


def _ask(monkeypatch, results, **kwargs):
    import agents.ai_brain as ab
    calls = {"n": 0, "paths": []}

    def fake_run(cmd, **kw):
        calls["paths"].append([a for a in cmd if a.startswith("-d@")])
        i = min(calls["n"], len(results) - 1)
        calls["n"] += 1
        return results[i]

    monkeypatch.setattr(ab.subprocess, "run", fake_run)
    out = ab.ask_nvidia_sync(kwargs.pop("prompt", "hola"),
                             system="sys", agent_id=None, **kwargs)
    return out, calls


def test_respuesta_corta_legitima_no_es_error(monkeypatch):
    # "FUNCIONA" (8 chars) es una respuesta valida; el guard viejo la rechazaba
    out, _ = _ask(monkeypatch, [_run(stdout=_resp_stdout(content="FUNCIONA"))])
    assert out == "FUNCIONA"


def test_respuesta_vacia_reintenta_y_reporta_claro(monkeypatch):
    # content vacio -> reintento unico y si persiste, mensaje claro (no "muy corta")
    out, calls = _ask(monkeypatch, [
        _run(stdout=_resp_stdout(content="")),
        _run(stdout=_resp_stdout(content="")),
    ])
    assert calls["n"] == 2, "debe reintentar ante contenido vacio"
    assert "vacia" in out.lower()


def test_respuesta_vacia_luego_ok_devuelve_ok(monkeypatch):
    out, calls = _ask(monkeypatch, [
        _run(stdout=_resp_stdout(content="")),
        _run(stdout=_resp_stdout(content="La respuesta completa del modelo.")),
    ])
    assert calls["n"] == 2
    assert out == "La respuesta completa del modelo."


def test_timeout_reporta_codigo_y_reintenta(monkeypatch):
    # rc=28 = curl timeout; el guard viejo decia "Error: Sin respuesta"
    out, calls = _ask(monkeypatch, [
        _run(stdout="", stderr="", returncode=28),
        _run(stdout="", stderr="", returncode=28),
    ])
    assert calls["n"] == 2, "debe reintentar ante timeout"
    assert "timeout" in out.lower()


def test_timeout_luego_ok_devuelve_ok(monkeypatch):
    out, calls = _ask(monkeypatch, [
        _run(stdout="", stderr="", returncode=28),
        _run(stdout=_resp_stdout(content="Recuperado tras timeout.")),
    ])
    assert calls["n"] == 2
    assert out == "Recuperado tras timeout."


def test_archivo_temporal_distinto_por_llamada(monkeypatch):
    # dos llamadas concurrentes no deben pisar el mismo nvidia_request.json
    import agents.ai_brain as ab
    seen = []

    def fake_run(cmd, **kw):
        seen.append([a for a in cmd if a.startswith("-d@")][0])
        return _run(stdout=_resp_stdout(content="ok unica"))

    monkeypatch.setattr(ab.subprocess, "run", fake_run)
    ab.ask_nvidia_sync("a", agent_id=None)
    ab.ask_nvidia_sync("b", agent_id=None)
    assert len(set(seen)) == 2, "cada llamada debe usar un archivo temporal propio"


def test_error_de_api_no_reintenta(monkeypatch):
    # un error de la API (no de transporte) no gana nada con reintento
    out, calls = _ask(monkeypatch, [
        _run(stdout=json.dumps({"error": {"message": "Invalid token"}})),
    ])
    assert calls["n"] == 1
    assert "Invalid token" in out
