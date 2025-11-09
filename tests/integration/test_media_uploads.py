from tempfile import SpooledTemporaryFile

import pytest
from starlette.datastructures import Headers, UploadFile

from app.services import media_service


@pytest.mark.anyio("asyncio")
async def test_create_media_cleans_up_on_metadata_failure(in_memory_db, tmp_path, monkeypatch) -> None:
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()

    monkeypatch.setattr(media_service, "MEDIA_ROOT", uploads_dir, raising=False)
    monkeypatch.setattr(media_service.mimetypes, "guess_type", lambda *_args, **_kwargs: ("video/mp4", None))

    file_obj = SpooledTemporaryFile()
    file_obj.write(b"fake-video-data")
    file_obj.seek(0)
    upload = UploadFile(
        file_obj,
        filename="sample.mp4",
        headers=Headers({"content-type": "video/mp4"}),
    )

    async def failing_extract(*_args, **_kwargs):
        raise RuntimeError("metadata failure")

    monkeypatch.setattr(media_service.metadata_extractor, "extract_metadata", failing_extract)

    with pytest.raises(RuntimeError):
        await media_service.create_media(
            in_memory_db,
            title="Sample",
            genre="action",
            duration_seconds=120,
            upload=upload,
        )

    assert not list(uploads_dir.iterdir())
