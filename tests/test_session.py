import pytest

from bot.handlers.session import prompt_keyboard, prompt_text
from convert.spec import conforms
from db.connection import connect
from db.packs import PackRepo
from models import MediaInfo, QueuedSticker

ALICE = 1


def info(**over):
    base = dict(width=512, height=374, duration=1.0, frames=30, is_animated=True,
                codec="vp9", container="matroska,webm", fps=30.0, size=40_000)
    base.update(over)
    return MediaInfo(**base)


@pytest.fixture
async def repo(tmp_path, monkeypatch):
    monkeypatch.setattr("db.connection.DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr("db.connection.DB_DIR", tmp_path)
    conn = await connect()
    yield PackRepo(conn)
    await conn.close()


def test_a_valid_video_sticker_is_left_alone():
    assert conforms(info())


@pytest.mark.parametrize("broken", [
    {"codec": "vp8"}, {"container": "mp4"}, {"size": 900_000}, {"has_audio": True},
    {"width": 400, "height": 300}, {"duration": 5.0}, {"fps": 60.0}, {"height": 375},
])
def test_anything_off_spec_is_converted(broken):
    assert not conforms(info(**broken))


def test_a_still_image_is_not_mistaken_for_a_sticker():
    assert not conforms(info(codec="png", container="png_pipe", duration=0.0, fps=0.0))


async def test_stickers_wait_in_order(repo):
    for index in range(3):
        await repo.push_sticker(ALICE, f"fid{index}", f"s{index}.webm", None)

    head = await repo.head_sticker(ALICE)
    assert head.file_id == "fid0"
    await repo.pop_sticker(head.id)
    assert (await repo.head_sticker(ALICE)).file_id == "fid1"
    assert await repo.count_stickers(ALICE) == 2


async def test_the_queue_is_per_user(repo):
    await repo.push_sticker(ALICE, "mine", "a.webm", None)
    await repo.push_sticker(2, "theirs", "b.webm", None)
    assert (await repo.head_sticker(2)).file_id == "theirs"
    assert await repo.count_stickers(ALICE) == 1


async def test_clearing_reports_how_many_were_dropped(repo):
    for index in range(4):
        await repo.push_sticker(ALICE, f"fid{index}", "s.webm", None)
    assert await repo.clear_stickers(ALICE) == 4
    assert await repo.head_sticker(ALICE) is None


async def test_the_suggested_emoji_is_kept(repo):
    await repo.push_sticker(ALICE, "fid", "s.webm", "\U0001f631")
    assert (await repo.head_sticker(ALICE)).suggested == "\U0001f631"


async def test_peeking_at_a_pending_title_does_not_consume_it(repo):
    await repo.set_pending(ALICE, "Cats")
    assert await repo.peek_pending(ALICE) == "Cats"
    assert await repo.peek_pending(ALICE) == "Cats"
    assert await repo.take_pending(ALICE) == "Cats"


def test_the_button_offers_the_suggested_emoji():
    button = prompt_keyboard("\U0001f631").inline_keyboard[0][0]
    assert button.text == "Click to \U0001f631"


def test_the_prompt_mentions_the_backlog():
    one = QueuedSticker(1, ALICE, "fid", "s.webm", None)
    assert "more waiting" not in prompt_text(one, waiting=1)
    assert "2 more waiting" in prompt_text(one, waiting=3)
