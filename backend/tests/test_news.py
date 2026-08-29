import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.applications.news import NewsChannelManager, load_news_channels
from app.protocol import Command, parse_client_message
from app.state import ActiveApp, LauncherTile


def test_open_news_command_exists() -> None:
    assert Command.OPEN_NEWS == "OPEN_NEWS"
    assert ActiveApp.NEWS == "news"
    assert LauncherTile.NEWS == "news"


def test_search_video_message_sanitizes_and_bounds_query() -> None:
    message = parse_client_message(
        {"version": 1, "type": "search_video", "request_id": "s1", "query": "  cat videos\n"}
    )
    assert message.query == "cat videos"


def test_search_video_rejects_empty_or_oversized_query() -> None:
    with pytest.raises(ValidationError):
        parse_client_message(
            {"version": 1, "type": "search_video", "request_id": "s1", "query": "   "}
        )
    with pytest.raises(ValidationError):
        parse_client_message(
            {"version": 1, "type": "search_video", "request_id": "s1", "query": "x" * 129}
        )


def test_news_loader_rejects_non_youtube_https(tmp_path: Path) -> None:
    path = tmp_path / "news.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "bad",
                    "number": 1,
                    "name": "Bad",
                    "url": "https://example.com/live",
                    "enabled": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_news_channels(path)


def test_news_loader_rejects_insecure_or_invalid_youtube_urls(tmp_path: Path) -> None:
    path = tmp_path / "http_youtube.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "bad-http",
                    "number": 1,
                    "name": "Bad",
                    "url": "http://www.youtube.com/@dwnews/live",
                    "enabled": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_news_channels(path)

    path_sub = tmp_path / "subdomain.json"
    path_sub.write_text(
        json.dumps(
            [
                {
                    "id": "bad-sub",
                    "number": 1,
                    "name": "Bad",
                    "url": "https://m.youtube.com/@dwnews/live",
                    "enabled": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_news_channels(path_sub)


def test_news_loader_rejects_duplicate_ids_or_numbers(tmp_path: Path) -> None:
    path = tmp_path / "dup_id.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "dup",
                    "number": 1,
                    "name": "One",
                    "url": "https://www.youtube.com/@dwnews/live",
                    "enabled": True,
                },
                {
                    "id": "dup",
                    "number": 2,
                    "name": "Two",
                    "url": "https://www.youtube.com/@pbsnewshour/live",
                    "enabled": True,
                },
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="IDs must be unique"):
        load_news_channels(path)

    path_num = tmp_path / "dup_num.json"
    path_num.write_text(
        json.dumps(
            [
                {
                    "id": "one",
                    "number": 1,
                    "name": "One",
                    "url": "https://www.youtube.com/@dwnews/live",
                    "enabled": True,
                },
                {
                    "id": "two",
                    "number": 1,
                    "name": "Two",
                    "url": "https://www.youtube.com/@pbsnewshour/live",
                    "enabled": True,
                },
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="numbers must be unique"):
        load_news_channels(path_num)


def test_news_loader_rejects_non_array_or_missing_or_malformed(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.json"
    with pytest.raises(ValueError, match="not found"):
        load_news_channels(missing_path)

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not-valid-json}", encoding="utf-8")
    with pytest.raises(ValueError, match="valid JSON"):
        load_news_channels(bad_json)

    not_array = tmp_path / "obj.json"
    not_array.write_text(json.dumps({"id": "1"}), encoding="utf-8")
    with pytest.raises(ValueError, match="must contain an array"):
        load_news_channels(not_array)


def test_news_loader_loads_config_example_file() -> None:
    example_path = Path(__file__).resolve().parents[2] / "config" / "news.example.json"
    channels = load_news_channels(example_path)
    assert [c.id for c in channels] == [
        "ftv-news",
        "ttv-news",
        "ctv-news",
        "cts-news",
        "ebc-news",
        "set-news",
        "tvbs-news",
        "mnews",
        "pts-news",
        "cti-news",
        "pts-sports",
        "moe-sports",
        "elta-sports",
        "vl-sports",
        "ssutv-sports",
        "hop-sports",
        "mr-player",
        "hunger-games",
        "hot-door-night",
        "eent-100",
        "muyao4",
        "kuokuang-gang",
        "gtv-drama",
        "cts-drama",
        "ctv-classic",
        "set-drama",
        "muse-anime",
        "rock-records",
    ]
    assert all(c.enabled for c in channels)
    assert all(
        c.url.startswith("https://www.youtube.com/") and c.url.endswith("/live") for c in channels
    )


def test_news_manager_wraps_channels(tmp_path: Path) -> None:
    path = tmp_path / "news.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "dw-news",
                    "number": 1,
                    "name": "DW News",
                    "url": "https://www.youtube.com/@dwnews/live",
                    "enabled": True,
                },
                {
                    "id": "pbs-newshour",
                    "number": 2,
                    "name": "PBS NewsHour",
                    "url": "https://www.youtube.com/@pbsnewshour/live",
                    "enabled": True,
                },
            ]
        ),
        encoding="utf-8",
    )
    channels = load_news_channels(path)
    manager = NewsChannelManager(channels)
    assert manager.current.id == "dw-news"
    assert manager.preview_move(1).id == "pbs-newshour"
    assert manager.move(1).id == "pbs-newshour"
    assert manager.move(1).id == "dw-news"
    assert manager.move(-1).id == "pbs-newshour"
    assert len(manager.channels) == 2

    with pytest.raises(ValueError, match="direction must be -1 or 1"):
        manager.move(0)


def test_controller_build_news_loads_example_when_config_absent(
    monkeypatch, tmp_path: Path
) -> None:
    import app.controller as controller_module
    from app.config import Settings
    from app.controller import _build_news

    fake_project_root = tmp_path
    (fake_project_root / "config").mkdir()
    example_path = fake_project_root / "config" / "news.example.json"
    example_path.write_text(
        json.dumps(
            [
                {
                    "id": "dw-news",
                    "number": 1,
                    "name": "DW News",
                    "url": "https://www.youtube.com/@dwnews/live",
                    "enabled": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(controller_module, "project_root", lambda: fake_project_root)

    news = _build_news(Settings())
    assert isinstance(news, NewsChannelManager)
    assert news.current.id == "dw-news"


def test_controller_build_news_returns_unavailable_when_invalid(
    monkeypatch, tmp_path: Path
) -> None:
    import app.controller as controller_module
    from app.commands.ports import CommandExecutionError
    from app.config import Settings
    from app.controller import UnavailableNews, _build_news

    fake_project_root = tmp_path
    (fake_project_root / "config").mkdir()
    news_path = fake_project_root / "config" / "news.json"
    news_path.write_text("invalid json", encoding="utf-8")
    monkeypatch.setattr(controller_module, "project_root", lambda: fake_project_root)

    news = _build_news(Settings())
    assert isinstance(news, UnavailableNews)
    with pytest.raises(CommandExecutionError) as err:
        _ = news.current
    assert err.value.code == "news_not_configured"
    with pytest.raises(CommandExecutionError) as err:
        news.move(1)
    assert err.value.code == "news_not_configured"
