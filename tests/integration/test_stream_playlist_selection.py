from pathlib import Path

import pytest
from sqlalchemy import asc, select

from app.db.base import Base
from app.db.init_db import ensure_playlist_counter
from app.models import MediaAsset, PlaylistEntry
from app.services.stream_manager import stream_manager


@pytest.mark.anyio("asyncio")
async def test_collects_playlist_from_requested_entry(tmp_path, anyio_backend):
    db_path = Path(tmp_path) / "playlist.sqlite"
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(
        f"sqlite:///{db_path}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True, expire_on_commit=False)

    media_files = []
    with SessionLocal() as session:
        ensure_playlist_counter(session)
        for idx in range(4):
            media_file = tmp_path / f"media_{idx}.mp4"
            media_file.write_bytes(b"fake")
            asset = MediaAsset(
                title=f"Media {idx}",
                genre="test",
                duration_seconds=60,
                file_path=str(media_file),
                checksum=f"sum{idx}",
            )
            session.add(asset)
            session.flush()
            media_files.append((asset.id, media_file))
            entry = PlaylistEntry(media_id=asset.id, position=idx + 1)
            session.add(entry)
        session.commit()

    with SessionLocal() as session:
        entry = session.execute(
            select(PlaylistEntry).order_by(asc(PlaylistEntry.position))
        ).scalars().all()[1]
        files, first_media = stream_manager._collect_media_files(session, entry.id, None)

    assert first_media == media_files[1][0]
    expected_paths = [item[1] for item in media_files[1:]]
    assert files == expected_paths
