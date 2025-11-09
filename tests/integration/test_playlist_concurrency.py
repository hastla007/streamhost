import concurrent.futures
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.init_db import ensure_playlist_counter
from app.models import MediaAsset, PlaylistEntry
from app.schemas import PlaylistCreate
from app.services.playlist_service import add_playlist_item


@pytest.mark.anyio("asyncio")
async def test_concurrent_playlist_additions(tmp_path) -> None:
    db_path = Path(tmp_path) / "playlist.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, future=True, expire_on_commit=False)

    with Session() as session:
        ensure_playlist_counter(session)
        media = MediaAsset(
            title="Test Media",
            genre="action",
            duration_seconds=120,
            file_path=str(db_path.parent / "media.mp4"),
            checksum="checksum",
        )
        session.add(media)
        session.commit()
        media_id = media.id

    def worker() -> None:
        with Session() as session:
            payload = PlaylistCreate(media_id=media_id)
            add_playlist_item(session, payload)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(worker) for _ in range(12)]
        for future in futures:
            future.result()

    with Session() as session:
        positions = (
            session.execute(
                select(PlaylistEntry.position).order_by(PlaylistEntry.position)
            )
            .scalars()
            .all()
        )

    assert positions == sorted(set(positions))
    assert positions == list(range(1, len(positions) + 1))
