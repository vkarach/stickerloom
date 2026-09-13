import pytest

from db.connection import connect
from db.packs import PackRepo

ALICE = 1
BOB = 2


@pytest.fixture
async def repo(tmp_path, monkeypatch):
    monkeypatch.setattr("db.connection.DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr("db.connection.DB_DIR", tmp_path)
    conn = await connect()
    yield PackRepo(conn)
    await conn.close()


async def test_a_remembered_pack_is_listed_for_its_owner(repo):
    await repo.remember(ALICE, "cats_by_bot", "Cats")
    packs = await repo.list_for(ALICE)
    assert [(p.name, p.title) for p in packs] == [("cats_by_bot", "Cats")]


async def test_packs_do_not_leak_between_users(repo):
    await repo.remember(ALICE, "cats_by_bot", "Cats")
    assert await repo.list_for(BOB) == []


async def test_remembering_the_same_pack_twice_is_harmless(repo):
    await repo.remember(ALICE, "cats_by_bot", "Cats")
    await repo.remember(ALICE, "cats_by_bot", "Cats")
    assert len(await repo.list_for(ALICE)) == 1


async def test_the_active_pack_round_trips(repo):
    await repo.remember(ALICE, "cats_by_bot", "Cats")
    await repo.set_active(ALICE, "cats_by_bot")
    assert await repo.active_for(ALICE) == "cats_by_bot"


async def test_nothing_is_active_to_begin_with(repo):
    assert await repo.active_for(ALICE) is None


async def test_clearing_the_active_pack_keeps_it_listed(repo):
    await repo.remember(ALICE, "cats_by_bot", "Cats")
    await repo.set_active(ALICE, "cats_by_bot")
    await repo.clear_active(ALICE)
    assert await repo.active_for(ALICE) is None
    assert len(await repo.list_for(ALICE)) == 1


async def test_a_new_pending_title_replaces_the_old_one(repo):
    await repo.set_pending(ALICE, "Cats")
    await repo.set_pending(ALICE, "Dogs")
    assert await repo.peek_pending(ALICE) == "Dogs"


async def test_the_default_emoji_round_trips(repo):
    await repo.set_emoji(ALICE, "\U0001f525")
    assert await repo.emoji_for(ALICE) == "\U0001f525"


async def test_there_is_a_default_emoji_out_of_the_box(repo):
    assert await repo.emoji_for(ALICE)


async def test_state_survives_a_reconnect(repo, tmp_path):
    await repo.remember(ALICE, "cats_by_bot", "Cats")
    await repo.set_active(ALICE, "cats_by_bot")

    conn = await connect()
    try:
        again = PackRepo(conn)
        assert await again.active_for(ALICE) == "cats_by_bot"
        assert len(await again.list_for(ALICE)) == 1
    finally:
        await conn.close()


async def test_packs_come_back_newest_last(repo):
    for index in range(3):
        await repo.remember(ALICE, f"p{index}_by_bot", f"Pack {index}")
    assert [p.name for p in await repo.list_for(ALICE)] == ["p0_by_bot", "p1_by_bot", "p2_by_bot"]


async def test_what_the_bot_is_asking_round_trips(repo):
    assert await repo.asking_for(ALICE) is None
    await repo.set_asking(ALICE, "prefix")
    assert await repo.asking_for(ALICE) == "prefix"
    await repo.set_asking(ALICE, None)
    assert await repo.asking_for(ALICE) is None


async def test_what_is_asked_is_per_user(repo):
    await repo.set_asking(ALICE, "title")
    assert await repo.asking_for(BOB) is None


async def test_the_chosen_language_round_trips(repo):
    assert await repo.lang_for(ALICE) is None
    await repo.set_lang(ALICE, "ru")
    assert await repo.lang_for(ALICE) == "ru"


async def test_an_older_database_gains_the_new_column(tmp_path, monkeypatch):
    import aiosqlite

    path = tmp_path / "old.db"
    async with aiosqlite.connect(path) as old:
        await old.execute(
            "CREATE TABLE users (user_id INTEGER PRIMARY KEY, active_pack TEXT, "
            "pending_title TEXT, emoji TEXT)"
        )
        await old.execute("INSERT INTO users (user_id, emoji) VALUES (1, '\U0001f525')")
        await old.commit()

    monkeypatch.setattr("db.connection.DB_PATH", path)
    monkeypatch.setattr("db.connection.DB_DIR", tmp_path)
    conn = await connect()
    try:
        migrated = PackRepo(conn)
        assert await migrated.asking_for(1) is None
        assert await migrated.lang_for(1) is None
        assert await migrated.emoji_for(1) == "\U0001f525"
    finally:
        await conn.close()
