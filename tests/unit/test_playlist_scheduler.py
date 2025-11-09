from app.models import MediaAsset
from app.schemas import PlaylistGenerationRequest, PlaylistRules
from app.services.playlist_scheduler import playlist_scheduler


def test_generate_playlist_with_invalid_timezone(in_memory_db, tmp_path) -> None:
    media_path = tmp_path / "movie.mp4"
    media_path.write_text("test")
    asset = MediaAsset(
        title="Test Movie",
        genre="action",
        duration_seconds=1800,
        file_path=str(media_path),
        checksum="abc123",
    )
    in_memory_db.add(asset)
    in_memory_db.commit()

    request = PlaylistGenerationRequest(hours=1, timezone="Mars/Colony")
    playlist = playlist_scheduler.generate_playlist(in_memory_db, request)
    assert playlist
    assert playlist[0].media_id == asset.id


def test_generate_playlist_respects_genre_rotation(in_memory_db, tmp_path) -> None:
    for idx, genre in enumerate(["action", "comedy", "action"]):
        media_path = tmp_path / f"movie_{idx}.mp4"
        media_path.write_text("test")
        asset = MediaAsset(
            title=f"Movie {idx}",
            genre=genre,
            duration_seconds=1200,
            file_path=str(media_path),
            checksum=f"ck{idx}",
        )
        in_memory_db.add(asset)
    in_memory_db.commit()

    rules = PlaylistRules(max_consecutive_same_genre=1)
    request = PlaylistGenerationRequest(hours=2, strategy="genre-rotation", rules=rules)
    playlist = playlist_scheduler.generate_playlist(in_memory_db, request)

    assert len(playlist) >= 2
    # Ensure no two consecutive entries share the same genre when rule disallows it.
    for prev, curr in zip(playlist, playlist[1:]):
        assert prev.genre != curr.genre
