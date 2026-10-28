"""Workflow binding and SQLite/API contract tests."""

from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest
from PIL import Image

from studio.api import config, store
from studio.api.models import Plan, Shot
from studio.api.render import (
    bind_workflow,
    load_workflow,
    prepare_reference,
    reference_dimensions,
    size_for,
)


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "lumen-test.sqlite3")
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path / "media")
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    config.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    store.init_db()
    return tmp_path


def _plan(pack: int = 5) -> Plan:
    return Plan(
        mode="ecommerce",
        route="ecommerce",
        title="测试项目",
        summary="测试摘要",
        reasoning="测试理由",
        style_lock="Campaign Style Lock: test.",
        aspect="4:5",
        shots=[
            Shot(
                index=index,
                title=f"画面 {index}",
                purpose="测试用途",
                prompt=(
                    "A clean product photograph on a neutral background, soft studio "
                    "light, no text, no watermark."
                ),
                negative="text, watermark",
                aspect="4:5",
            )
            for index in range(1, pack + 1)
        ],
        skill="ecom-details-image",
        skill_version="main",
    )


def test_text_to_image_workflow_binds_real_values() -> None:
    graph = bind_workflow(
        load_workflow(reference=False),
        prompt="a real prompt",
        negative="text, watermark",
        width=1024,
        height=1024,
        seed=123456,
        project_id="project-1",
        shot_index=3,
    )

    assert graph["4"]["class_type"] == "TextEncodeZImageOmni"
    assert graph["4"]["inputs"]["prompt"] == "a real prompt"
    assert "image1" not in graph["4"]["inputs"]
    assert graph["6"]["inputs"]["width"] == 1024
    assert graph["6"]["inputs"]["height"] == 1024
    assert graph["7"]["inputs"]["seed"] == 123456
    assert graph["9"]["inputs"]["filename_prefix"] == "lumen/project-1/shot_03"
    assert size_for("4:5") == (896, 1120)


def test_reference_workflow_routes_the_upload_into_the_conditioner() -> None:
    graph = bind_workflow(
        load_workflow(reference=True),
        prompt="a real prompt",
        negative="text, watermark",
        width=896,
        height=1120,
        seed=7,
        project_id="project-2",
        shot_index=1,
        reference="lumen_ref_deadbeef.png",
    )

    assert graph["4"]["inputs"]["prompt"] == "a real prompt"
    assert graph["4"]["inputs"]["vae"] == ["3", 0]
    assert graph["4"]["inputs"]["auto_resize_images"] is False
    assert graph["4"]["inputs"]["image1"] == ["10", 0]
    assert graph["10"]["class_type"] == "LoadImage"
    assert graph["10"]["inputs"]["image"] == "lumen_ref_deadbeef.png"
    assert graph["6"]["inputs"]["width"] == 896


def test_reference_is_normalised_to_patchable_dimensions(tmp_path) -> None:
    # 1344×768 is the reference that originally failed: auto_resize produced
    # 1352×776, whose 169×97 latent cannot be patchified at 2×2.
    assert reference_dimensions(1344, 768) == (1344, 768)
    assert reference_dimensions(4000, 3000) == (1184, 880)

    source = tmp_path / "source.png"
    Image.new("RGB", (401, 299), "#335577").save(source)
    prepared = prepare_reference(source)
    try:
        assert prepared.suffix == ".png"
        with Image.open(prepared) as image:
            assert image.mode == "RGB"
            width, height = image.size
            assert width % 16 == 0
            assert height % 16 == 0
            assert (width // 8) % 2 == 0
            assert (height // 8) % 2 == 0
    finally:
        prepared.unlink(missing_ok=True)


def test_store_tracks_done_and_interrupted_renders(isolated_db) -> None:
    plan = _plan()
    store.save_project(
        project_id="project-store",
        brief="测试需求",
        plan=plan,
        reference_id=None,
    )

    queued = store.begin_render("project-store", 1)
    assert queued.status == "queued"
    store.update_render(
        queued.render_id,
        status="done",
        file_url="/media/renders/project-store/shot_01.png",
        width=896,
        height=1120,
    )
    store.set_shot_status("project-store", 1, "done")

    project = store.get_project("project-store")
    assert project is not None
    assert project.status == "partial"
    assert project.done_count == 1
    assert project.cover_urls == ["/media/renders/project-store/shot_01.png"]

    running = store.begin_render("project-store", 2)
    store.update_render(running.render_id, status="running")
    assert store.fail_interrupted_renders("API restarted") == 1

    project = store.get_project("project-store")
    assert project is not None
    interrupted = store.get_render(running.render_id)
    assert interrupted is not None
    assert interrupted.status == "failed"
    assert interrupted.error == "API restarted"
    assert project.failed_count == 1
    assert project.plan.shots[1].status == "failed"


def test_project_api_returns_saved_data_and_zip(isolated_db) -> None:
    from fastapi.testclient import TestClient

    from studio.api.main import app

    store.save_project(
        project_id="project-api",
        brief="为商品做五张主图。",
        plan=_plan(),
        reference_id=None,
    )

    with TestClient(app) as client:
        listing = client.get("/api/projects")
        assert listing.status_code == 200
        assert listing.json()["total"] == 1

        detail = client.get("/api/projects/project-api")
        assert detail.status_code == 200
        payload = detail.json()
        assert payload["plan"]["shots"][0]["aspect"] == "4:5"

        patched = client.patch(
            "/api/projects/project-api/shots/1",
            json={"title": "改过的标题"},
        )
        assert patched.status_code == 200
        assert patched.json()["plan"]["shots"][0]["title"] == "改过的标题"

        exported = client.get("/api/projects/project-api/export")
        assert exported.status_code == 200
        assert exported.headers["content-type"] == "application/zip"
        with ZipFile(BytesIO(exported.content)) as archive:
            names = set(archive.namelist())
        assert {"plan.json", "prompts.md", "README.txt"} <= names

        missing = client.get("/api/projects/not-a-project")
        assert missing.status_code == 404
