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
    assert "Reprocessar Só Texto (LLM)" in res_view2.text
    assert "Reprocessar Tudo (Desde o MP3)" in res_view2.text

    # 4c. Reprocess ONLY the existing local text via LLM (without downloading MP3 again)
    mp3_requested = [False]

    def mock_reprocess_text_only(req: httpx.Request):
        if str(req.url).endswith(".mp3"):
            mp3_requested[0] = True
            return httpx.Response(500)
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "• Novo Resumo Reprocessado Só do Texto"}]},
        )

    res_reproc_llm = client.post("/episodes/2/reprocess-llm", data={"llm_provider": "claude"})
    assert res_reproc_llm.status_code == 200
    assert res_reproc_llm.json()["mode"] == "text_only_llm"

    with patch(
        "httpx.Client",
        return_value=httpx.Client(transport=httpx.MockTransport(mock_reprocess_text_only)),
    ):
        assert worker.process_next_job() is True

    assert mp3_requested[0] is False
    res_view2_after = client.get("/view/2")
    assert "Novo Resumo Reprocessado Só do Texto" in res_view2_after.text
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


def test_summaries_browser_and_multi_llm_coexistence(tmp_path: Path):
    db_file = tmp_path / "summaries_ui_test.sqlite"
    settings.db_path = db_file
    settings.logs_dir = tmp_path / "logs"
    init_db(db_file)

    conn = get_db_connection(db_file)
    repo = Repository(conn)
    repo.create_list("Geral", "geral")
    feed = repo.create_feed("Podcast Multi LLM", "pod-multi-llm", "http://example.com/rss")
    ep = repo.upsert_episode(
        feed_id=feed.id,
        guid="ep-multi",
        title="Episódio Multi Resumo",
        slug="episodio-multi-resumo",
        audio_url="http://example.com/multi.mp3",
    )
    repo.update_episode_status(ep.id, EpisodeStatus.COMPLETED)

    # Base transcript
    tx_file = tmp_path / "ep_multi_transcript.txt"
    tx_file.write_text("Transcrição completa gerada por Whisper.", encoding="utf-8")
    tx = repo.record_transcript(
        episode_id=ep.id,
        model_id="whisper-large-v3-turbo",
        engine_name="faster-whisper",
        plain_text_path=str(tx_file),
        char_count=len(tx_file.read_text()),
        word_count=5,
        duration_proc_seconds=12.5,
    )

    # Summary 1: Gemini
    sum1_file = tmp_path / "ep_multi_summary_gemini.txt"
    sum1_file.write_text("• Ponto 1 do Gemini\n• Ponto 2 do Gemini", encoding="utf-8")
    s1 = repo.record_summary(
        episode_id=ep.id,
        transcript_id=tx.id,
        provider="gemini",
        model_name="gemini-2.5-flash",
        prompt_used="Resuma os principais pontos com marcadores...",
        summary_text=sum1_file.read_text(encoding="utf-8"),
        summary_path=str(sum1_file),
        duration_proc_seconds=3.2,
    )

    # Summary 2: Claude (coexisting with Gemini for the same episode)
    sum2_file = tmp_path / "ep_multi_summary_claude.txt"
    sum2_file.write_text(
        "• Análise detalhada pelo Claude\n• Segundo bullet do Claude", encoding="utf-8"
    )
    s2 = repo.record_summary(
        episode_id=ep.id,
        transcript_id=tx.id,
        provider="claude",
        model_name="claude-sonnet-4-6",
        prompt_used="Faça uma síntese analítica dos argumentos...",
        summary_text=sum2_file.read_text(encoding="utf-8"),
        summary_path=str(sum2_file),
        duration_proc_seconds=4.8,
    )

    # Verify both summaries exist in DB
    summaries = repo.list_episode_summaries(ep.id)
    assert len(summaries) == 2
    assert {s.provider for s in summaries} == {"gemini", "claude"}

    app = create_app()
    with patch.object(BackgroundWorker, "start"), patch.object(BackgroundWorker, "stop"):
        with TestClient(app) as client:
            # 1. Main navigation /summaries
            resp = client.get("/summaries")
            assert resp.status_code == 200
            assert "Navegador de Resumos" in resp.text
            assert "gemini-2.5-flash" in resp.text
            assert "claude-sonnet-4-6" in resp.text
            assert "whisper-large-v3-turbo" in resp.text
            assert "Episódio Multi Resumo" in resp.text

            # 2. HTMX filter by provider
            resp_gemini = client.get("/summaries/cards?provider=gemini")
            assert resp_gemini.status_code == 200
            assert "gemini-2.5-flash" in resp_gemini.text
            assert "claude-sonnet-4-6" not in resp_gemini.text

            resp_claude = client.get("/summaries/cards?provider=claude")
            assert resp_claude.status_code == 200
            assert "claude-sonnet-4-6" in resp_claude.text
            assert "gemini-2.5-flash" not in resp_claude.text

            # 3. Filter by feed_id
            resp_feed = client.get(f"/summaries/cards?feed_id={feed.id}")
            assert resp_feed.status_code == 200
            assert "gemini-2.5-flash" in resp_feed.text
            assert "claude-sonnet-4-6" in resp_feed.text

            # Filter with non-existent feed
            resp_empty = client.get("/summaries/cards?feed_id=99999")
            assert resp_empty.status_code == 200
            assert "Nenhum resumo encontrado" in resp_empty.text

            # 4. Episode card on index shows both summaries
            resp_index = client.get(f"/?feed_id={feed.id}")
            assert resp_index.status_code == 200
            assert "📑 Resumo (gemini)" in resp_index.text
            assert "📑 Resumo (claude)" in resp_index.text

            # Card partial endpoint also shows both summaries
            resp_card = client.get(f"/episodes/card/{ep.id}")
            assert resp_card.status_code == 200
            assert "📑 Resumo (gemini)" in resp_card.text
            assert "📑 Resumo (claude)" in resp_card.text

            # 5. View episode page shows both summaries
            resp_view = client.get(f"/view/{ep.id}")
            assert resp_view.status_code == 200
            assert f"summary-{s1.id}" in resp_view.text
            assert f"summary-{s2.id}" in resp_view.text
            assert "gemini-2.5-flash" in resp_view.text
            assert "claude-sonnet-4-6" in resp_view.text

            # 6. Delete one summary (s1 - Gemini)
            del_resp = client.post(f"/summaries/{s1.id}/delete")
            assert del_resp.status_code == 200
            assert not sum1_file.exists()  # Disk file deleted
            assert sum2_file.exists()  # Claude disk file preserved

            # DB check: only s2 remains
            remaining = repo.list_episode_summaries(ep.id)
            assert len(remaining) == 1
            assert remaining[0].id == s2.id

            # Central page now only has s2
            resp_after_del = client.get("/summaries")
            assert resp_after_del.status_code == 200
            assert "claude-sonnet-4-6" in resp_after_del.text
            assert "gemini-2.5-flash" not in resp_after_del.text

    conn.close()
