from dataclasses import dataclass

from aiogram.types import BotCommand
from aiogram.utils.formatting import BotCommand as CommandText
from aiogram.utils.formatting import Bold, Text, as_list, as_marked_section


@dataclass(frozen=True)
class CommandSpec:
    name: str
    description: str
    group: str = "General"
    hidden: bool = False


COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("start", "What this bot does"),
    CommandSpec("help", "Show all commands"),
    CommandSpec("cancel", "Drop everything still queued"),
    CommandSpec("newpack", "Start a pack, filled by the files you send", group="Packs"),
    CommandSpec("mypacks", "Your packs, and which one is being filled", group="Packs"),
    CommandSpec("nopack", "Stop adding to a pack", group="Packs"),
    CommandSpec("import", "Copy an existing pack so this bot can fill it", group="Packs"),
    CommandSpec("emoji", "Emoji for files that carry none", group="Packs"),

    CommandSpec("format", "The exact format the bot produces", group="Reference"),
    CommandSpec("pack", "Building a pack by hand in @Stickers", group="Reference"),
)

BY_NAME: dict[str, CommandSpec] = {c.name: c for c in COMMANDS}


def menu() -> list[BotCommand]:
    return [
        BotCommand(command=c.name, description=c.description)
        for c in COMMANDS if not c.hidden
    ]


def help_content() -> Text:
    sections = []
    for group in dict.fromkeys(c.group for c in COMMANDS):
        rows = [
            Text(CommandText(f"/{c.name}"), " : ", c.description)
            for c in COMMANDS if c.group == group and not c.hidden
        ]
        if rows:
            sections.append(as_marked_section(Bold(group), *rows, marker="- "))
    return as_list(*sections, sep="\n\n")
