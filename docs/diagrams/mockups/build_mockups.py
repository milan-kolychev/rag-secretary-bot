"""Макет интерфейса бота (п. 10 чек-листа): экраны студента, секретаря и раскадровка.

Генерирует HTML и рендерит PNG через Playwright (Chromium):

    uv run --with playwright python docs/diagrams/mockups/build_mockups.py

Тексты реализованных экранов совпадают с bot/texts.py. Экраны секретаря
(спринт 3) показывают проектируемые тексты.
"""

import html
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent

CSS = """
* { box-sizing: border-box; }
body { margin: 0; padding: 16px; background: #fff; color: #000;
       font-family: 'Liberation Serif', 'Times New Roman', serif; font-size: 15px; }
.row { display: flex; gap: 22px; align-items: flex-start; }
.col { display: flex; flex-direction: column; align-items: center; gap: 8px; }
.cap { font-size: 16px; text-align: center; width: 300px; }
.phone { width: 300px; height: 560px; border: 2px solid #000; border-radius: 22px;
         display: flex; flex-direction: column; overflow: hidden; }
.bar { border-bottom: 1.5px solid #000; padding: 9px 12px; font-weight: bold;
       display: flex; justify-content: space-between; }
.bar small { font-weight: normal; }
.chat { flex: 1; padding: 10px; display: flex; flex-direction: column; gap: 7px;
        justify-content: flex-end; overflow: hidden; }
.msg { max-width: 88%; border: 1px solid #000; border-radius: 10px; padding: 6px 8px;
       line-height: 1.25; white-space: pre-wrap; }
.bot { align-self: flex-start; }
.me { align-self: flex-end; border: 3px double #000; }
.sys { align-self: center; border-style: dashed; font-size: 13px; }
.kb { display: grid; gap: 4px; margin-top: -3px; align-self: flex-start; width: 88%; }
.kb2 { grid-template-columns: 1fr 1fr; }
.btn { border: 1px solid #000; border-radius: 6px; text-align: center; padding: 4px 2px;
       font-size: 14px; }
.reply { border-top: 1.5px solid #000; padding: 7px; display: grid;
         grid-template-columns: 1fr 1fr; gap: 6px; }
.input { border-top: 1.5px solid #000; padding: 9px 12px; color: #000; font-style: italic; }
.file { align-self: flex-end; border: 3px double #000; border-radius: 10px; padding: 6px 8px;
        display: flex; gap: 8px; align-items: center; }
.file .ic { border: 1px solid #000; width: 26px; height: 32px; font-size: 10px;
            display: flex; align-items: center; justify-content: center; }
.arrow { font-size: 34px; align-self: center; margin-top: -40px; width: 30px; text-align: center; }
.legend { margin-top: 14px; font-size: 14px; }
"""


def esc(text: str) -> str:
    return html.escape(text)


def bot(text: str) -> str:
    return f'<div class="msg bot">{esc(text)}</div>'


def me(text: str) -> str:
    return f'<div class="msg me">{esc(text)}</div>'


def sys_note(text: str) -> str:
    return f'<div class="msg sys">{esc(text)}</div>'


def buttons(*rows: tuple[str, ...]) -> str:
    out = []
    for row in rows:
        cls = "kb kb2" if len(row) == 2 else "kb"
        out.append(
            f'<div class="{cls}">'
            + "".join(f'<div class="btn">{esc(b)}</div>' for b in row)
            + "</div>"
        )
    return "".join(out)


def file_msg(name: str, size: str) -> str:
    ext = name.rsplit(".", 1)[-1].upper()
    return (
        f'<div class="file"><div class="ic">{ext}</div>'
        f"<div>{esc(name)}<br><small>{esc(size)}</small></div></div>"
    )


def phone(
    title: str,
    body: str,
    bottom: str = "keyboard",
    subtitle: str = "бот",
    height: int = 470,
    width: int = 300,
) -> str:
    if bottom == "keyboard":
        foot = '<div class="reply"><div class="btn">Задать вопрос</div><div class="btn">Помощь</div></div>'
    elif bottom:
        foot = f'<div class="input">{esc(bottom)}</div>'
    else:
        foot = ""
    return (
        f'<div class="phone" style="height:{height}px;width:{width}px">'
        f'<div class="bar"><span>{esc(title)}</span>'
        f"<small>{esc(subtitle)}</small></div>"
        f'<div class="chat">{body}</div>{foot}</div>'
    )


def screen(caption: str, ph: str, width: int = 300) -> str:
    return (
        f'<div class="col">{ph}<div class="cap" style="width:{width}px">{esc(caption)}</div></div>'
    )


BOT = "Бот ФПИ"
SEC_CHAT = "Секретари ФПИ"
START = (
    "Здравствуйте! Я бот факультета прикладной информатики.\n\n"
    "Отвечаю на вопросы об учёбе по документам факультета. "
    "На вопросы не по учёбе ответить не смогу.\n"
    "Если в документах ответа нет, вопрос можно передать секретарю.\n\n"
    "Нажмите «Задать вопрос» или просто напишите вопрос сообщением."
)
QUESTION = "Как получить справку об обучении?"
ANSWER = (
    "Справку об обучении выдаёт деканат. Заявление подаётся через секретаря "
    "или в личном кабинете, справка готова через 3 рабочих дня.\n\n"
    "Источники:\n• Регламент деканата, п. 4.2"
)
NO_ANSWER = (
    "В документах факультета ответа на этот вопрос нет. "
    "Попробуйте сформулировать иначе или нажмите «Позвать секретаря»."
)
CARD = (
    "Обращение № 0142 · открыто\n"
    "Студент: id 7426…, 08.10 13:40\n\n"
    "Вопрос:\nМожно ли перенести защиту практики на другую дату?\n\n"
    "Найденные фрагменты:\n"
    "1. Положение о практике, п. 6.3 (0,61)\n"
    "2. Регламент деканата, п. 2.1 (0,48)\n\n"
    "Черновик ответа:\nПеренос защиты возможен по заявлению на имя декана "
    "при уважительной причине (Положение о практике, п. 6.3)."
)

CARD_SHORT = (
    "Обращение № 0142 · открыто\n\n"
    "Вопрос: Можно ли перенести защиту практики на другую дату?\n\n"
    "Фрагменты: Положение о практике, п. 6.3; Регламент деканата, п. 2.1\n\n"
    "Черновик: Перенос возможен по заявлению на имя декана при уважительной причине."
)

STUDENT = [
    screen("а) Начало работы: /start", phone(BOT, bot(START))),
    screen(
        "б) Ответ с источником и кнопками",
        phone(
            BOT,
            me(QUESTION) + bot(ANSWER) + buttons(("👍", "👎"), ("Позвать секретаря",)),
        ),
    ),
    screen(
        "в) Ответа в документах нет",
        phone(
            BOT,
            me("Когда будет выпускной вечер?") + bot(NO_ANSWER) + buttons(("Позвать секретаря",)),
        ),
    ),
    screen(
        "г) Передача секретарю и его ответ (спринт 3)",
        phone(
            BOT,
            bot("Вопрос передан секретарю. Ответ придёт в этот чат.")
            + sys_note("через некоторое время")
            + bot(
                "Ответ секретаря на ваш вопрос «Можно ли перенести защиту практики?»:\n\n"
                "Да, напишите заявление на имя декана и приложите документ, "
                "подтверждающий причину."
            ),
        ),
    ),
]

SECRETARY = [
    screen(
        "а) Карточка обращения в чате секретарей",
        phone(
            SEC_CHAT,
            bot(CARD) + buttons(("Отправить черновик",), ("Ответить своим текстом",), ("Закрыть",)),
            bottom="",
            subtitle="группа",
        ),
    ),
    screen(
        "б) Ответ своим текстом",
        phone(
            SEC_CHAT,
            bot("Напишите ответ на обращение № 0142 одним сообщением. Отмена: /cancel")
            + me(
                "Да, напишите заявление на имя декана и приложите документ, подтверждающий причину."
            )
            + bot("Ответ отправлен студенту. Обращение № 0142 закрыто: отвечено секретарём."),
            bottom="Сообщение",
            subtitle="группа",
        ),
    ),
    screen(
        "в) Загрузка документа",
        phone(
            BOT,
            me("/upload")
            + bot("Отправьте файл PDF, DOCX или TXT. Отмена: /cancel")
            + file_msg("Положение_о_практике_2026.pdf", "1,2 МБ")
            + bot("Как назвать документ?")
            + buttons(("Оставить имя файла",))
            + me("Положение о практике")
            + bot("Документ принят, идёт индексация.")
            + bot("«Положение о практике» проиндексирован: 86 фрагментов."),
            bottom="Сообщение",
        ),
    ),
    screen(
        "г) Неотвеченные обращения: /tickets",
        phone(
            BOT,
            me("/tickets")
            + bot("Неотвеченные обращения (3), сначала старые:")
            + buttons(
                ("№ 0139 · 07.10 · Пересдача по физике",),
                ("№ 0141 · 08.10 · Академический отпуск",),
                ("№ 0142 · 08.10 · Перенос защиты практики",),
            )
            + sys_note("кнопка открывает карточку обращения"),
            bottom="Сообщение",
        ),
    ),
]


def mini(title: str, body: str, subtitle: str = "бот") -> str:
    return phone(title, body, bottom="", subtitle=subtitle, height=400, width=280)


STORY = [
    ("1. Студент открывает бота и видит, что можно спросить", mini(BOT, bot(START))),
    (
        "2. Пишет вопрос своими словами",
        mini(BOT, me("Можно ли перенести защиту практики на другую дату?")),
    ),
    (
        "3. Бот отвечает по документам со ссылкой на источник",
        mini(
            BOT,
            bot(
                "Перенос возможен по заявлению на имя декана.\n\nИсточники:\n• Положение о практике, п. 6.3"
            )
            + buttons(("👍", "👎"), ("Позвать секретаря",)),
        ),
    ),
    (
        "4. Ответ не помог: студент зовёт секретаря",
        mini(
            BOT,
            buttons(("Позвать секретаря",))
            + bot("Вопрос передан секретарю. Ответ придёт в этот чат."),
        ),
    ),
    (
        "5. Секретарь получает карточку с фрагментами и черновиком",
        mini(
            SEC_CHAT,
            bot(CARD_SHORT) + buttons(("Отправить черновик",), ("Ответить своим текстом",)),
            subtitle="группа",
        ),
    ),
    (
        "6. Студент получает ответ секретаря в том же чате",
        mini(
            BOT,
            bot(
                "Ответ секретаря:\n\nДа, напишите заявление на имя декана и приложите документ, подтверждающий причину."
            ),
        ),
    ),
]


def page(content: str, width: int) -> str:
    return (
        f'<!doctype html><html lang="ru"><meta charset="utf-8"><style>{CSS}'
        f"body{{width:{width}px}}</style><body>{content}</body></html>"
    )


def grid(items: list[str], per_row: int) -> str:
    rows = [items[i : i + per_row] for i in range(0, len(items), per_row)]
    return (
        '<div class="col" style="gap:26px">'
        + "".join('<div class="row">' + "".join(r) + "</div>" for r in rows)
        + "</div>"
    )


def story_html() -> str:
    cells = []
    for cap, ph in STORY:
        cells.append(screen(cap, ph, width=280))
    rows = []
    for start in (0, 3):
        part = cells[start : start + 3]
        joined = '<div class="arrow">→</div>'.join(part)
        rows.append(f'<div class="row">{joined}</div>')
    return '<div class="col" style="gap:26px">' + "".join(rows) + "</div>"


def main() -> None:
    pages = {
        "10_mockup_student": page(grid(STUDENT, 2), 660),
        "10_mockup_secretary": page(grid(SECRETARY, 2), 660),
        "10_storyboard": page(story_html(), 1000),
    }
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(device_scale_factor=2, viewport={"width": 1100, "height": 800})
        for name, content in pages.items():
            (OUT / "mockups" / f"{name}.html").write_text(content, encoding="utf-8")
            pg = ctx.new_page()
            pg.set_content(content)
            pg.add_style_tag(content="html{filter:grayscale(1)}")
            pg.locator("body").screenshot(path=str(OUT / f"{name}.png"))
            pg.close()
        browser.close()
    print("ok", file=sys.stderr)


if __name__ == "__main__":
    main()
