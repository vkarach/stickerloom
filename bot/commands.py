from dataclasses import dataclass

from aiogram.types import BotCommand
from aiogram.utils.formatting import BotCommand as CommandText
from aiogram.utils.formatting import Bold, Text, as_list, as_marked_section

from i18n import Translator


@dataclass(frozen=True)
class CommandSpec:
    name: str
    group: str = "group.general"
    hidden: bool = False
    admin: bool = False

    @property
    def description(self) -> str:
        return f"cmd.{self.name}"


COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("start"),
    CommandSpec("help"),
    CommandSpec("cancel"),
    CommandSpec("lang"),

    CommandSpec("newpack", group="group.packs"),
    CommandSpec("done", group="group.packs"),
    CommandSpec("mypacks", group="group.packs"),
    CommandSpec("import", group="group.packs"),
    CommandSpec("emoji", group="group.packs"),

    CommandSpec("format", group="group.reference"),

    CommandSpec("stats", group="group.admin", admin=True),
)

BY_NAME: dict[str, CommandSpec] = {c.name: c for c in COMMANDS}


def menu(t: Translator, *, admin: bool = False) -> list[BotCommand]:
    return [
        BotCommand(command=c.name, description=t(c.description))
        for c in COMMANDS if not c.hidden and (admin or not c.admin)
    ]


def help_content(t: Translator, *, admin: bool = False) -> Text:
    sections = []
    for group in dict.fromkeys(c.group for c in COMMANDS):
        rows = [
            Text(CommandText(f"/{c.name}"), " : ", t(c.description))
            for c in COMMANDS
            if c.group == group and not c.hidden and (admin or not c.admin)
        ]
        if rows:
            sections.append(as_marked_section(Bold(t(group)), *rows, marker="- "))
    return as_list(*sections, sep="\n\n")
