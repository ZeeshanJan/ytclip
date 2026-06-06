import tempfile
import uuid
from pathlib import Path

import pytest

from ytclip.database import delete_job, get_job, insert_job, list_completed_jobs, update_job_status
from ytclip.models import ClipJob, JobStatus, OutputFormat


@pytest.fixture
async def db_path():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    from ytclip.database import init_db
    await init_db(path)
    yield path
    path.unlink(missing_ok=True)


def make_job(**kwargs) -> ClipJob:
    defaults = dict(
        id=str(uuid.uuid4()),
        url="https://youtube.com/watch?v=test",
        start_time=10.0,
        end_time=40.0,
        output_format=OutputFormat.MP4,
    )
    defaults.update(kwargs)
    return ClipJob(**defaults)


async def test_insert_and_get(db_path):
    job = make_job()
    await insert_job(db_path, job)
    fetched = await get_job(db_path, job.id)
    assert fetched is not None
    assert fetched.id == job.id
    assert fetched.url == job.url
    assert fetched.start_time == 10.0
    assert fetched.end_time == 40.0


async def test_update_status(db_path):
    job = make_job()
    await insert_job(db_path, job)
    await update_job_status(db_path, job.id, JobStatus.COMPLETED, progress=100, video_title="Test Video")
    fetched = await get_job(db_path, job.id)
    assert fetched.status == JobStatus.COMPLETED
    assert fetched.progress == 100
    assert fetched.video_title == "Test Video"
    assert fetched.completed_at is not None


async def test_delete_job(db_path):
    job = make_job()
    await insert_job(db_path, job)
    result = await delete_job(db_path, job.id)
    assert result is True
    assert await get_job(db_path, job.id) is None


async def test_list_completed(db_path):
    j1 = make_job(status=JobStatus.COMPLETED)
    j2 = make_job(status=JobStatus.FAILED)
    j3 = make_job(status=JobStatus.COMPLETED)

    for j in [j1, j2, j3]:
        await insert_job(db_path, j)

    # Mark j1 and j3 completed
    await update_job_status(db_path, j1.id, JobStatus.COMPLETED)
    await update_job_status(db_path, j3.id, JobStatus.COMPLETED)

    completed = await list_completed_jobs(db_path)
    ids = {j.id for j in completed}
    assert j1.id in ids
    assert j3.id in ids


async def test_get_nonexistent(db_path):
    result = await get_job(db_path, "nonexistent-id")
    assert result is None
