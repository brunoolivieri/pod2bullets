"""Test Web UI HTML rendering, podcast filtering, non-blinking status, LLM summarization, and dual logs."""

from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from pod2bullets.config import settings
from pod2bullets.db.connection import get_db_connection, init_db
from pod2bullets.db.repository import Repository
from pod2bullets.logging_config import get_active_log_paths, is_suppressed_polling_line
from pod2bullets.models import EpisodeStatus
from pod2bullets.system_status import activity_tracker
from pod2bullets.web.app import create_app
from pod2bullets.worker.queue import BackgroundWorker


def test_web_ui_pages_and_new_features(tmp_path: Path, sample_mp3: Path):
    db_file = tmp_path / "ui_test.sqlite"
    settings.db_path = db_file
    settings.logs_dir = tmp_path / "logs"
    init_db(db_file)

    conn = get_db_connection(db_file)
    repo = Repository(conn)
    repo.create_list("Tecnologia", "tecnologia")
    feed1 = repo.create_feed("Podcast Tech", "pod-tech", "http://example.com/rss")
    feed2 = repo.create_feed("Podcast Ciência", "pod-ciencia", "http://example.com/rss2")
    ep1 = repo.upsert_episode(
        feed_id=feed1.id,
        guid="ep-1",
        title="Episódio Interface Tech",
        slug="episodio-interface-tech",
        audio_url="http://example.com/audio1.mp3",
    )
    repo.upsert_episode(
        feed_id=feed2.id,
        guid="ep-2",
        title="Episódio Exclusivo Ciência",
        slug="episodio-exclusivo-ciencia",
        audio_url="http://example.com/audio2.mp3",
    )

    # Create a completed transcript for ep1 so we can test full reading, .txt export, and LLM summary
    tx_file = tmp_path / "ep1_transcript.txt"
    tx_file.write_text(
        "Conteúdo completo da transcrição sobre inteligência artificial.", encoding="utf-8"
    )
    repo.record_transcript(
        episode_id=ep1.id,
        model_id="whisper-large-v3-turbo",
        engine_name="faster-whisper",
        plain_text_path=str(tx_file),
        char_count=62,
        word_count=8,
        duration_proc_seconds=4.2,
    )
    repo.update_episode_status(ep1.id, EpisodeStatus.COMPLETED)
    conn.close()

    app = create_app()
    client = TestClient(app)

    # 1. Main index page without feed_id: must NOT show all episodes mixed together
    #    and must NOT contain the blinking "Processando requisição..." indicator (Item 2)
    res = client.get("/")
    assert res.status_code == 200
    assert "pod2bullets" in res.text
    assert "Processando requisição" not in res.text
    assert "Selecione um Podcast no Menu à Esquerda" in res.text
    assert "Episódio Interface Tech" not in res.text

    # 2. Selecting a specific podcast lists ONLY its episodes with "Ler na Íntegra", "Exportar .TXT", "Reprocessar"
    res_feed1 = client.get(f"/?feed_id={feed1.id}")
    assert res_feed1.status_code == 200
    assert "Episódio Interface Tech" in res_feed1.text
    assert "Ler na Íntegra" in res_feed1.text
    assert "Exportar .TXT" in res_feed1.text
    assert "Reprocessar" in res_feed1.text
    assert "Episódio Exclusivo Ciência" not in res_feed1.text

    # 3. System status badge: returns EMPTY when idle (no visual feedback blinking on simple online check, Item 1)
    res_idle = client.get("/system/status")
    assert res_idle.status_code == 200
    assert res_idle.text == ""

    activity_tracker.start("test_task", "Transcrevendo episódio teste")
    try:
        res_busy = client.get("/system/status")
        assert res_busy.status_code == 200
        assert "⏳" in res_busy.text
        assert "Sistema Ocupado" in res_busy.text
        assert "Transcrevendo episódio teste" in res_busy.text
    finally:
        activity_tracker.finish("test_task")

    # 4. LLM Settings & Summarization across providers (ChatGPT, Claude, Gemini, DeepSeek, Qwen) (Item 7)
    assert client.get("/llm/settings").status_code == 200
    res_cfg = client.post(
        "/llm/config",
        data={
            "provider": "deepseek",
            "prompt": "Resuma em 3 bullets objetivos:",
            "model_name": "deepseek-chat",
            "api_key": "sk-test-1234567890",
        },
    )
    assert res_cfg.status_code == 200

    def mock_llm_transport(req: httpx.Request):
        url = str(req.url)
        if "anthropic.com" in url:
            return httpx.Response(
                200, json={"content": [{"type": "text", "text": "• Resumo Claude"}]}
            )
        if "googleapis.com" in url:
            return httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": "• Resumo Gemini"}]}}]},
            )
        # OpenAI / DeepSeek / Qwen compatible format
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "• Resumo OpenAI/DeepSeek/Qwen"}}]},
        )

    with patch(
        "httpx.Client", return_value=httpx.Client(transport=httpx.MockTransport(mock_llm_transport))
    ):
        for prov in ("chatgpt", "claude", "gemini", "deepseek", "qwen"):
            res_sum = client.post(
                f"/llm/summarize/{ep1.id}",
                data={
                    "provider": prov,
                    "prompt": f"Prompt customizado para {prov}",
                    "api_key": f"key-{prov}-123456789",
                },
            )
            assert res_sum.status_code == 200
            data = res_sum.json()
            assert data["provider"] == prov
            assert "Resumo" in data["summary_text"]

    # Download summary as .txt
    res_dl_sum = client.get("/llm/summaries/1/download")
    assert res_dl_sum.status_code == 200
    assert "attachment" in res_dl_sum.headers["content-disposition"]

    # 4b. Local Transcription + Choosing LLM Model in the same action + Version Fallback (Newest -> Fallback)
    settings.podcasts_dir = tmp_path / "podcasts"
    settings.tmp_dir = tmp_path / "tmp"
    client.post(
        "/llm/provider/claude",
        data={"model_name": "claude-sonnet-4-0", "api_key": "sk-ant-testkey12345"},
    )
    # Verify deprecated 'claude-sonnet-4-0' was auto-upgraded to newest 'claude-sonnet-4-6'
    cfg_json = client.get("/llm/config").json()
    assert cfg_json["providers"]["claude"]["model"] == "claude-sonnet-4-6"

    client.post("/llm/prompt", data={"prompt": "Resuma a transcrição local em tópicos:"})

    res_local_plus_llm = client.post(
        "/episodes/2/download",
        data={"model_id": "fake-engine", "llm_provider": "claude"},
    )
    assert res_local_plus_llm.status_code == 200
    assert res_local_plus_llm.json()["model_id"] == "fake-engine"
    assert res_local_plus_llm.json()["llm_provider"] == "claude"
    assert client.get("/llm/config").json()["last_direct_provider"] == "claude"

    claude_call_count = [0]

    def mock_audio_dl_and_claude_fallback(req: httpx.Request):
        import json

        url = str(req.url)
        if url.endswith(".mp3"):
            mp3_bytes = sample_mp3.read_bytes()
            return httpx.Response(
                200, content=mp3_bytes, headers={"content-length": str(len(mp3_bytes))}
            )
        if url.endswith("/v1/models"):
            return httpx.Response(
                200,
                json={"data": [{"id": "claude-sonnet-4-6-live"}]},
            )
        if "anthropic.com/v1/messages" in url:
            claude_call_count[0] += 1
            body = json.loads(req.content.decode("utf-8"))
            # Simulate 404 on first attempt, then success on fallback attempt #2
            if claude_call_count[0] == 1:
                return httpx.Response(
                    404,
                    json={
                        "error": {"type": "not_found_error", "message": f"model: {body['model']}"}
                    },
                )
            return httpx.Response(
                200,
                json={
                    "content": [
                        {
                            "type": "text",
                            "text": f"• Resumo da Transcrição Local via {body['model']}",
                        }
                    ]
                },
            )
        return httpx.Response(404)

    worker = BackgroundWorker(db_path=db_file)
    with patch(
        "httpx.Client",
        return_value=httpx.Client(transport=httpx.MockTransport(mock_audio_dl_and_claude_fallback)),
    ):
        assert worker.process_next_job() is True

    # Verify both local transcript and automatic LLM summary exist on /view/2, and fallback model succeeded on attempt #2
    assert claude_call_count[0] == 2
    res_view2 = client.get("/view/2")
    assert res_view2.status_code == 200
    assert "Resumo da Transcrição Local via claude-sonnet-4-6-live" in res_view2.text
    assert client.delete("/llm/provider/claude/key").status_code == 200

    # 5. Dual logs (YYYY-MM-DD-HH-MM-APP.log and transcricao.log), Log Viewer & Polling suppression (Items 8-12)
    paths = get_active_log_paths()
    assert paths["app"].name.endswith("-APP.log")
    assert paths["transcricao"].name.endswith("-transcricao.log")
    assert paths["app"].exists()
    assert paths["transcricao"].exists()

    assert client.get("/logs/viewer").status_code == 200
    tail_app = client.get("/logs/tail?log_type=app").json()
    assert tail_app["filename"].endswith("-APP.log")
    tail_tx = client.get("/logs/tail?log_type=transcricao").json()
    assert tail_tx["filename"].endswith("-transcricao.log")

    # Verify Item 12 polling log suppression
    assert is_suppressed_polling_line(
        'INFO:     127.0.0.1:37130 - "GET /episodes/card/1 HTTP/1.1" 200 OK'
    )
    assert is_suppressed_polling_line(
        "[2026-11-04 11:43:12] INFO     pod2bullets.web: [HTTP] GET /episodes/card/1 -> 200 (13.2ms)"
    )
    assert is_suppressed_polling_line(
        "[2026-11-04 11:43:12] INFO     pod2bullets.web: [HTTP] GET /queue/panel -> 200 (5.0ms)"
    )
    assert not is_suppressed_polling_line(
        "[2026-11-04 11:43:12] INFO     pod2bullets.web: [HTTP] GET /?feed_id=1 -> 200 (15.0ms)"
    )


def test_queue_visualization_and_cancellation(tmp_path: Path):
    db_file = tmp_path / "queue_test.sqlite"
    settings.db_path = db_file
    init_db(db_file)

    conn = get_db_connection(db_file)
    db_repo = Repository(conn)
    feed = db_repo.create_feed("Podcast Fila", "pod-fila", "http://example.com/rss")
    ep1 = db_repo.upsert_episode(
        feed_id=feed.id,
        guid="q-ep-1",
        title="Episódio Fila 1",
        slug="episodio-fila-1",
        audio_url="http://example.com/q1.mp3",
    )
    ep2 = db_repo.upsert_episode(
        feed_id=feed.id,
        guid="q-ep-2",
        title="Episódio Fila 2",
        slug="episodio-fila-2",
        audio_url="http://example.com/q2.mp3",
    )

    app = create_app()
    with patch.object(BackgroundWorker, "start"), patch.object(BackgroundWorker, "stop"):
        with TestClient(app) as client:
            # Enqueue 2 jobs
            client.post(f"/episodes/{ep1.id}/download", data={"model_id": "fake-model"})
            client.post(f"/episodes/{ep2.id}/download", data={"model_id": "fake-model"})

            # Check queue visualization endpoints
            resp_manage = client.get("/queue/manage")
            assert resp_manage.status_code == 200
            assert "Fila de Processamento" in resp_manage.text
            assert ep1.title in resp_manage.text
            assert ep2.title in resp_manage.text

            resp_json = client.get("/queue/")
            assert resp_json.status_code == 200
            jobs_data = resp_json.json()["jobs"]
            active_jobs = [j for j in jobs_data if j["status"] in ("pending", "running")]
            assert len(active_jobs) == 2

            # Cancel first job individually
            first_job_id = active_jobs[0]["id"]
            cancel_resp = client.post(f"/queue/{first_job_id}/cancel")
            assert cancel_resp.status_code == 200
            assert db_repo.is_job_cancelled(first_job_id)

            # Cancel remaining active jobs
            cancel_all_resp = client.post("/queue/cancel-all")
            assert cancel_all_resp.status_code == 200
            assert db_repo.get_episode(ep1.id).status.value == "available"
            assert db_repo.get_episode(ep2.id).status.value == "available"

            # Clear finished/cancelled jobs history
            clear_resp = client.post("/queue/clear-history")
            assert clear_resp.status_code == 200
            assert len(db_repo.list_queue_jobs()) == 0

    conn.close()
