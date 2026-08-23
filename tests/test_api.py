"""FastAPI layer tests.

Hermetic by construction: rate limiting is disabled, persistence is
redirected to tmp dirs, and the pipeline runs on MockProvider (fast,
deterministic — the same provider the existing suite uses).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.deps
import api.routes_review
import api.routes_skills
import api.routes_ablation
import api.routes_lifecycle
from api.app import app
from src.agents.skill_distiller import SkillProposal
from src.lifecycle.store import LifecycleStore
from src.llm.mock_provider import MockProvider
from src.skills.curator import SkillCurator
from src.storage import HistoryStore, ProposalsStore
from src.ui import rate_limit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_sse(text: str) -> list[dict]:
    """Parse a full SSE response body into [{id, event, data}, ...]."""
    events = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        ev: dict = {}
        for line in block.strip().split("\n"):
            if line.startswith("id: "):
                ev["id"] = int(line[4:])
            elif line.startswith("event: "):
                ev["event"] = line[7:]
            elif line.startswith("data: "):
                ev["data"] = json.loads(line[6:])
        if "event" in ev:
            events.append(ev)
    return events


SAMPLE_PRD = """# 用户召回通知
## 背景
支付失败的订单在 30 分钟内未重试时，应向用户发送召回通知。
## 需求
1. 失败后第 5 分钟发送第一条推送。
2. 用户点击推送后回到支付页。
## 非目标
- 不做短信通道。
"""


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    # Quota off — tests exercise the pipeline, not the demo budget.
    monkeypatch.setattr(rate_limit, "DISABLED", True)
    # Force MockProvider regardless of .env (tests must never hit the network).
    monkeypatch.setattr(api.routes_review, "get_llm", lambda: MockProvider())
    monkeypatch.setattr(api.routes_skills, "get_llm", lambda: MockProvider())
    # Hermetic storage: history/proposals point at tmp dirs.
    monkeypatch.setattr(
        api.deps,
        "_history_store",
        HistoryStore(tmp_path / "history"),
    )
    monkeypatch.setattr(
        api.deps,
        "_proposals_store",
        ProposalsStore(
            tmp_path / "proposals",
            learned_dir=tmp_path / "learned",
            runtime_stats_path=tmp_path / "runtime_stats.yaml",
        ),
    )
    # Skill usage telemetry must not mutate the repo's runtime_stats.yaml.
    monkeypatch.setattr(
        api.deps,
        "_curator",
        SkillCurator(runtime_stats_path=tmp_path / "runtime_stats.yaml"),
    )
    # Lifecycle governance must not touch the repo's data/lifecycle db or
    # trigger the legacy migration — point it at an isolated empty store.
    lifecycle = LifecycleStore(tmp_path / "lifecycle" / "skills.db")
    monkeypatch.setattr(api.deps, "_lifecycle_store", lifecycle)
    monkeypatch.setattr(api.deps, "_migration_attempted", True)
    monkeypatch.setattr(api.routes_lifecycle, "get_llm", lambda: MockProvider())
    # Ablation reads/writes must also stay inside tmp (repo ships a real latest.json).
    monkeypatch.setattr(
        api.routes_ablation,
        "DEFAULT_OUTPUT_DIR",
        tmp_path / "ablation",
    )
    with TestClient(app) as c:
        yield c
    lifecycle.close()


def run_review(client: TestClient) -> tuple[str, list[dict]]:
    """POST a review and drain its SSE stream. Returns (run_id, events)."""
    resp = client.post("/api/reviews", json={"prd_text": SAMPLE_PRD})
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]
    stream = client.get(f"/api/reviews/{run_id}/stream")
    assert stream.status_code == 200, stream.text
    return run_id, parse_sse(stream.text)


# ---------------------------------------------------------------------------
# Basic endpoints
# ---------------------------------------------------------------------------


def test_health_and_meta(client):
    assert client.get("/api/health").json() == {"ok": True}
    meta = client.get("/api/meta").json()
    assert meta["provider"] in {"mock", "openai"}
    assert meta["model"] in {"MockProvider", "gpt-4o-mini"}


def test_golden_prds(client):
    prds = client.get("/api/golden-prds").json()
    assert len(prds) >= 1
    assert all("filename" in p and "content" in p for p in prds)


def test_review_requires_text(client):
    resp = client.post("/api/reviews", json={"prd_text": "   "})
    assert resp.status_code == 422


def test_review_accepts_language_override(client):
    """Forced language rides along the review request without breaking the run."""
    resp = client.post(
        "/api/reviews", json={"prd_text": SAMPLE_PRD, "language": "zh"}
    )
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    stream = client.get(f"/api/reviews/{run_id}/stream")
    events = parse_sse(stream.text)
    assert any(e["event"] == "done" for e in events)


def test_history_delete_roundtrip(client):
    run_id, events = run_review(client)
    history_id = next(
        e["data"]["history_run_id"]
        for e in events
        if e["event"] == "done" and e["data"].get("history_run_id")
    )
    assert client.get(f"/api/history/{history_id}").status_code == 200
    resp = client.delete(f"/api/history/{history_id}")
    assert resp.status_code == 200
    # Gone from both the detail endpoint and the listing.
    assert client.get(f"/api/history/{history_id}").status_code == 404
    listing = client.get("/api/history").json()
    assert all(r["run_id"] != history_id for r in listing)
    # Deleting again → 404.
    assert client.delete(f"/api/history/{history_id}").status_code == 404


def test_review_stream_event_order(client):
    run_id, events = run_review(client)
    types = [e["event"] for e in events]
    # Critic findings arrive before any supervisor output; verdict before done.
    assert "critiques" in types and "verdict" in types and "done" in types
    assert types.index("critiques") < types.index("thinking")
    assert types.index("verdict") < types.index("done")
    critiques = next(e["data"] for e in events if e["event"] == "critiques")
    assert isinstance(critiques["critiques"], list)
    verdict = next(e["data"] for e in events if e["event"] == "verdict")
    assert "executive_summary" in verdict["verdict"]
    # Final state is queryable after the stream closes.
    final = client.get(f"/api/reviews/{run_id}").json()
    assert final["finished"] is True
    assert final["verdict"]["executive_summary"]


def test_review_stream_replay_via_last_event_id(client):
    run_id, events = run_review(client)
    first_id = events[0]["id"]
    replay = client.get(
        f"/api/reviews/{run_id}/stream", headers={"Last-Event-ID": str(first_id)}
    )
    replayed = parse_sse(replay.text)
    assert [e["id"] for e in replayed] == [e["id"] for e in events[1:]]


def test_unknown_run_404(client):
    assert client.get("/api/reviews/nope/stream").status_code == 404
    assert client.get("/api/reviews/nope").status_code == 404


def test_discuss_round_cap(client):
    run_id, _ = run_review(client)
    messages = [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}] * 5
    resp = client.post(
        f"/api/reviews/{run_id}/discuss",
        json={"critique_uid": "does-not-matter", "messages": messages},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


def test_rate_limit_429(client, monkeypatch):
    monkeypatch.setattr(rate_limit, "DISABLED", False)
    monkeypatch.setattr(rate_limit, "GLOBAL_PER_DAY", 0)
    resp = client.post("/api/reviews", json={"prd_text": SAMPLE_PRD})
    assert resp.status_code == 429
    assert resp.json()["detail"]["reason"] == "global"


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------


def test_upload_markdown(client):
    resp = client.post(
        "/api/uploads", files={"file": ("prd.md", b"# Title\n\nsome content", "text/markdown")}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["chars"] > 0 and "Title" in body["text"]


def test_upload_unsupported_type(client):
    resp = client.post("/api/uploads", files={"file": ("virus.exe", b"MZ", "application/x-msdownload")})
    assert resp.status_code == 400


def test_upload_too_large(client):
    big = b"a" * (2 * 1024 * 1024 + 1)
    resp = client.post("/api/uploads", files={"file": ("big.txt", big, "text/plain")})
    assert resp.status_code == 413


# ---------------------------------------------------------------------------
# History + skills + proposals
# ---------------------------------------------------------------------------


def test_history_roundtrip(client, tmp_path):
    run_id, events = run_review(client)
    done = next(e["data"] for e in events if e["event"] == "done")
    history_id = done["history_run_id"]
    assert history_id
    listing = client.get("/api/history").json()
    assert any(r["run_id"] == history_id for r in listing)
    detail = client.get(f"/api/history/{history_id}").json()
    assert detail["run_id"] == history_id
    assert detail["supervisor_verdict"]["executive_summary"]
    assert client.get("/api/history/not-a-run").status_code == 404
    # The live run also reports its history id once finished.
    assert client.get(f"/api/reviews/{run_id}").json()["history_run_id"] == history_id


def test_skills_list_and_feedback(client):
    skills = client.get("/api/skills").json()
    assert isinstance(skills, list)
    if skills:
        name = skills[0]["name"]
        md = client.get(f"/api/skills/{name}/md").json()
        assert md["md"].strip()
        resp = client.post(f"/api/skills/{name}/feedback", json={"accepted": True})
        assert resp.status_code == 200 and resp.json()["accepted"] is True


def _seed_history_runs(history: HistoryStore, texts: list[str]) -> list[str]:
    """Persist N runs with distinct PRD texts; return their run_ids."""
    run_ids = []
    for i, text in enumerate(texts):
        record = history.save(
            {
                "prd_text": text,
                "critiques": [],
                "challenges": [],
                "final_report": {},
            },
            prd_filename=f"seed_prd_{i}.md",
        )
        assert record is not None
        run_ids.append(record.run_id)
    return run_ids


def test_proposal_approve_flow(client, tmp_path):
    history = api.deps.get_history_store()
    run_ids = _seed_history_runs(
        history,
        [
            "# PRD A\nusers pay via payment api integration for the flow screen\n",
            "# PRD B\nusers see a flow screen when the payment api fails\n",
            "# PRD C\nusers import data through the payment api on the flow screen\n",
        ],
    )

    proposal_md = (
        "---\n"
        "name: demo-skill\n"
        "description: Flag PRDs whose payment api usage leaves users without a flow screen.\n"
        'version: "1.0"\n'
        "created_by: distiller\n"
        "injected_into:\n  - engineering\n"
        "trigger_keywords: [users, payment, api, data]\n"
        "---\n\n"
        "# Skill: demo-skill\n\n"
        "## When to apply\nThe PRD mentions payment api usage.\n\n"
        "## Instruction\nCheck the user-facing flow screen.\n"
    )
    store = api.deps.get_proposals_store()
    store.save(
        SkillProposal(
            proposal_id="p_test_1",
            proposed_name="demo-skill",
            proposed_skill_md=proposal_md,
            injected_into=["engineering"],
            generalization_score=0.9,
            evidence=[{"run_id": rid, "critique_excerpt": "[P2] demo"} for rid in run_ids],
            pattern_frequency=3,
            created_at="2026-08-13T00:00:00Z",
        )
    )

    pending = client.get("/api/proposals").json()
    assert any(p["proposal_id"] == "p_test_1" for p in pending)

    # Approval is refused before any gate has run.
    resp = client.post("/api/proposals/p_test_1/approve")
    assert resp.status_code == 409
    assert "not run" in resp.json()["detail"]

    # Deterministic gates first.
    resp = client.post("/api/lifecycle/gates/p_test_1/run", json={})
    assert resp.status_code == 200, resp.text
    latest = resp.json()["latest"]
    assert set(latest) == {"spec", "evidence", "novelty"}
    assert latest["spec"]["passed"], latest["spec"]["detail"]
    assert latest["evidence"]["passed"], latest["evidence"]["detail"]
    assert latest["novelty"]["passed"], latest["novelty"]["detail"]

    # Still refused: the shadow gate hasn't run.
    resp = client.post("/api/proposals/p_test_1/approve")
    assert resp.status_code == 409
    assert "shadow" in resp.json()["detail"]

    # Full gate set including the counterfactual shadow evaluation. Under
    # MockProvider the OFF baseline is the current library and the ON arm
    # adds only the candidate — identical critique sets, so the policy
    # deterministically passes with a neutral (below-preference) note.
    resp = client.post("/api/lifecycle/gates/p_test_1/run", json={"include_shadow": True})
    assert resp.status_code == 200, resp.text
    latest = resp.json()["latest"]
    assert set(latest) == {"spec", "evidence", "novelty", "shadow"}
    assert latest["shadow"]["passed"], latest["shadow"]["detail"]

    resp = client.post("/api/proposals/p_test_1/approve")
    assert resp.status_code == 200, resp.text
    assert (tmp_path / "learned" / "demo-skill" / "SKILL.md").exists()
    assert client.get("/api/proposals").json() == []

    # Lifecycle records: lineage + active status + audit transitions.
    lineage = client.get("/api/lifecycle/lineage/demo-skill").json()
    assert lineage["versions"][0]["admission_actor"] == "pm:ui"
    assert lineage["versions"][0]["source_proposal_id"] == "p_test_1"
    transitions = [t["to_status"] for t in lineage["transitions"]]
    assert transitions == ["approved", "active"]
    statuses = {
        row["skill_name"]: row["status"]
        for row in client.get("/api/lifecycle/library").json()
    }
    assert statuses.get("demo-skill") == "active"


def test_proposal_reject_flow(client, tmp_path):
    store = ProposalsStore(tmp_path / "proposals", learned_dir=tmp_path / "learned")
    store.save(
        SkillProposal(
            proposal_id="p_test_2",
            proposed_name="reject-me",
            proposed_skill_md=(
                "---\nname: reject-me\ndescription: x\ninjected_into: [design]\n---\n\nbody"
            ),
            injected_into=["design"],
            generalization_score=0.5,
            pattern_frequency=1,
            created_at="2026-08-13T00:00:00Z",
        )
    )
    resp = client.post("/api/proposals/p_test_2/reject")
    assert resp.status_code == 200
    assert client.get("/api/proposals").json() == []
    assert client.post("/api/proposals/nope/approve").status_code == 404


def test_ablation_latest_missing(client):
    # Hermetic: no ablation report → null, not an error.
    assert client.get("/api/ablation").json() is None
    assert client.get("/api/ablation/status/unknown").status_code == 404
