import pytest
from aiogram.exceptions import TelegramBadRequest

from db.connection import connect
from db.packs import PackRepo
from packs.errors import NameTaken, PackFull, PackNotFound, PackNotOurs
from packs.manager import MAX_INITIAL, PackManager

ALICE = 1
BOT_NAME = "stickerloom_bot"


class FakeMe:
    username = BOT_NAME


class FakeSticker:
    def __init__(self, file_id, emoji):
        self.file_id = file_id
        self.emoji = emoji


class FakeSet:
    def __init__(self, stickers):
        self.stickers = stickers
        self.title = "Source"


class FakeBot:
    def __init__(self, raises=None, source=None):
        self.calls = []
        self.raises = raises or {}
        self.source = source

    async def me(self):
        return FakeMe()

    def _maybe_raise(self, method):
        problem = self.raises.get(method)
        if problem:
            raise TelegramBadRequest(method=method, message=problem)

    async def create_new_sticker_set(self, **kwargs):
        self.calls.append(("create", kwargs))
        self._maybe_raise("create")
        return True

    async def add_sticker_to_set(self, **kwargs):
        self.calls.append(("add", kwargs))
        self._maybe_raise("add")
        return True

    async def get_sticker_set(self, **kwargs):
        self.calls.append(("get", kwargs))
        self._maybe_raise("get")
        return self.source


@pytest.fixture
async def repo(tmp_path, monkeypatch):
    monkeypatch.setattr("db.connection.DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr("db.connection.DB_DIR", tmp_path)
    conn = await connect()
    yield PackRepo(conn)
    await conn.close()


@pytest.fixture
def sticker_file(tmp_path):
    path = tmp_path / "s.webm"
    path.write_bytes(b"not really a webm")
    return path


async def test_creating_a_pack_uses_the_bot_suffix(repo, sticker_file):
    bot = FakeBot()
    pack = await PackManager(bot, repo).create(ALICE, "My Pack", sticker_file, "\U0001f525")

    assert pack.name.endswith(f"_by_{BOT_NAME}")
    assert pack.title == "My Pack"
    assert bot.calls[0][0] == "create"


async def test_a_created_pack_is_remembered_and_made_active(repo, sticker_file):
    manager = PackManager(FakeBot(), repo)
    pack = await manager.create(ALICE, "My Pack", sticker_file, "\U0001f525")

    assert [p.name for p in await repo.list_for(ALICE)] == [pack.name]
    assert await repo.active_for(ALICE) == pack.name


async def test_the_first_sticker_carries_the_emoji(repo, sticker_file):
    bot = FakeBot()
    await PackManager(bot, repo).create(ALICE, "My Pack", sticker_file, "\U0001f525")

    stickers = bot.calls[0][1]["stickers"]
    assert len(stickers) == 1
    assert stickers[0].emoji_list == ["\U0001f525"]
    assert stickers[0].format == "video"


async def test_adding_uses_add_sticker_to_set(repo, sticker_file):
    bot = FakeBot()
    await PackManager(bot, repo).add(ALICE, "cats_by_bot", sticker_file, "\U0001f600")

    kind, kwargs = bot.calls[0]
    assert kind == "add"
    assert kwargs["name"] == "cats_by_bot"
    assert kwargs["sticker"].emoji_list == ["\U0001f600"]


async def test_a_foreign_pack_is_rejected_clearly(repo, sticker_file):
    bot = FakeBot(raises={"add": "Bad Request: STICKERSET_INVALID"})
    with pytest.raises(PackNotOurs):
        await PackManager(bot, repo).add(ALICE, "someone_elses", sticker_file, "\U0001f600")


async def test_a_full_pack_is_reported_as_full(repo, sticker_file):
    bot = FakeBot(raises={"add": "Bad Request: STICKERSET_STICKERS_TOO_MUCH"})
    with pytest.raises(PackFull):
        await PackManager(bot, repo).add(ALICE, "cats_by_bot", sticker_file, "\U0001f600")


async def test_an_occupied_name_is_reported(repo, sticker_file):
    bot = FakeBot(raises={"create": "Bad Request: sticker set name is already occupied"})
    with pytest.raises(NameTaken):
        await PackManager(bot, repo).create(ALICE, "My Pack", sticker_file, "\U0001f525")


async def test_importing_copies_every_sticker_with_its_emoji(repo):
    source = FakeSet([FakeSticker(f"fid{i}", "\U0001f600") for i in range(3)])
    bot = FakeBot(source=source)

    pack = await PackManager(bot, repo).import_set(ALICE, "tiktok", "Copied")

    created = [c for c in bot.calls if c[0] == "create"][0][1]
    assert len(created["stickers"]) == 3
    assert [s.sticker for s in created["stickers"]] == ["fid0", "fid1", "fid2"]
    assert await repo.active_for(ALICE) == pack.name


async def test_importing_falls_back_when_a_source_sticker_has_no_emoji(repo):
    bot = FakeBot(source=FakeSet([FakeSticker("fid0", None)]))
    await PackManager(bot, repo).import_set(ALICE, "tiktok", "Copied")

    created = [c for c in bot.calls if c[0] == "create"][0][1]
    assert created["stickers"][0].emoji_list == [await repo.emoji_for(ALICE)]


async def test_a_large_source_is_created_then_topped_up(repo):
    source = FakeSet([FakeSticker(f"fid{i}", "\U0001f600") for i in range(MAX_INITIAL + 7)])
    bot = FakeBot(source=source)

    await PackManager(bot, repo).import_set(ALICE, "big", "Copied")

    created = [c for c in bot.calls if c[0] == "create"]
    added = [c for c in bot.calls if c[0] == "add"]
    assert len(created) == 1
    assert len(created[0][1]["stickers"]) == MAX_INITIAL
    assert len(added) == 7


async def test_importing_an_unknown_set_says_so(repo):
    bot = FakeBot(raises={"get": "Bad Request: STICKERSET_INVALID"})
    with pytest.raises(PackNotFound):
        await PackManager(bot, repo).import_set(ALICE, "nope", "Copied")


async def test_importing_an_empty_set_says_so(repo):
    bot = FakeBot(source=FakeSet([]))
    with pytest.raises(PackNotFound):
        await PackManager(bot, repo).import_set(ALICE, "empty", "Copied")


def test_the_link_points_at_telegram():
    assert PackManager.link("cats_by_bot") == "https://t.me/addstickers/cats_by_bot"


class FlakyBot(FakeBot):
    """Fails the first add the way a freshly created set does, then succeeds."""

    def __init__(self, failures):
        super().__init__()
        self.failures = failures

    async def add_sticker_to_set(self, **kwargs):
        self.calls.append(("add", kwargs))
        if self.failures > 0:
            self.failures -= 1
            raise TelegramBadRequest(method="add", message="Bad Request: STICKERSET_INVALID")
        return True


async def test_a_set_that_is_not_ready_yet_is_retried(repo, sticker_file, monkeypatch):
    monkeypatch.setattr("packs.manager.RETRY_DELAYS", (0.0, 0.0, 0.0))
    bot = FlakyBot(failures=2)
    await PackManager(bot, repo).add(ALICE, "cats_by_bot", sticker_file, "\U0001f600")
    assert len([c for c in bot.calls if c[0] == "add"]) == 3


async def test_retries_give_up_and_report_a_foreign_pack(repo, sticker_file, monkeypatch):
    monkeypatch.setattr("packs.manager.RETRY_DELAYS", (0.0, 0.0, 0.0))
    bot = FlakyBot(failures=99)
    with pytest.raises(PackNotOurs):
        await PackManager(bot, repo).add(ALICE, "someone_elses", sticker_file, "\U0001f600")


async def test_a_full_pack_is_not_retried(repo, sticker_file):
    bot = FakeBot(raises={"add": "Bad Request: STICKERSET_STICKERS_TOO_MUCH"})
    with pytest.raises(PackFull):
        await PackManager(bot, repo).add(ALICE, "cats_by_bot", sticker_file, "\U0001f600")
    assert len([c for c in bot.calls if c[0] == "add"]) == 1
