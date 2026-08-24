"""Клиент Google-таблицы: один лист на товар, одна строка на заказ.

Низкий уровень — здесь только работа с самой таблицей, про заказы из БД
этот модуль не знает (этим занимается sheets_export.py). Разделение то же,
что у СДЭК: cdek_service.py — общение с чужим API, cdek_sync.py — наша логика.

Главное свойство: таблица — не свалка, а рабочий документ, в котором владелец
руками ведёт отметки о пошиве. Поэтому выгрузка не переписывает лист целиком,
а сверяется с ним: незнакомый заказ дописывает, знакомый — обновляет только
в «своих» столбцах. Отметок «выгружено» в базе для этого не нужно: что уже
выгружено, знает сама таблица (столбец Order ID).

gspread работает синхронно (внутри requests), поэтому вызывать его из async-кода
напрямую нельзя — см. asyncio.to_thread в sheets_export.py.
"""

from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound
from gspread.utils import rowcol_to_a1

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Google не пускает эти символы в название листа и режет его на 100 знаках.
# Название товара приходит из админки, где ограничение другое (200) — приводим сами,
# иначе add_worksheet упадёт на первом же товаре со слэшем в названии.
FORBIDDEN_IN_TITLE = "[]:*?/\\"
MAX_TITLE = 100
FALLBACK_TITLE = "Без названия"

# Новый лист: 100 строк с запасом, дальше Google расширит его сам при append
NEW_SHEET_ROWS = 100

# Первая строка на каждом листе — шапка
HEADER_ROWS = 1

# Значения пишем как есть, без разбора «как при ручном вводе» (USER_ENTERED).
# С разбором телефон «+7 999 123-45-67» Google принимает за формулу и кладёт
# в ячейку #ERROR!, а имя или адрес, начинающийся с «=», стал бы живой формулой
# в чужой таблице. Числа при этом остаются числами: мы их числами и передаём.
VALUE_INPUT = "RAW"


def rgb(r: int, g: int, b: int) -> dict:
    return {"red": r / 255, "green": g / 255, "blue": b / 255}


def sheet_title(name: str) -> str:
    """Название листа из названия товара — с оглядкой на запреты Google."""
    cleaned = "".join(" " if ch in FORBIDDEN_IN_TITLE else ch for ch in (name or ""))
    # лишние пробелы схлопываем: после замены запрещённых символов их станет много
    cleaned = " ".join(cleaned.split())[:MAX_TITLE]
    # апостроф по краям Google тоже не принимает
    return cleaned.strip("'").strip() or FALLBACK_TITLE


def _as_text(value) -> str:
    """Сравнивать значения приходится в том виде, в каком их отдаёт таблица:
    оттуда всё приходит строками, а у нас «Заплачено» — число."""
    return "" if value is None else str(value).strip()


class GoogleSheet:
    HEADERS = [
        "Order ID", "Status", "Дата заказа",
        "Товар", "Цвет", "Размер", "Вес",
        "Заплачено",
        "ФИО", "Телефон", "Почта",
        "Адрес доставки", "Способ доставки", "Трек отправки",
    ]

    # Чем строка опознаётся при повторной выгрузке: номер заказа и товар.
    # На листе товара «Товар» одинаков во всех строках, поэтому проверка сводится
    # ровно к номеру заказа. А на сводном листе «Мультизаказ» один заказ даёт
    # несколько строк (разные товары), и без товара в ключе они затирали бы друг друга.
    ID_HEADER = "Order ID"
    KEY_HEADERS = ("Order ID", "Товар")

    # Столбцы, которые ведёт человек, а не выгрузка.
    # Status — отметка о пошиве, ради неё таблица и существует; цвет и вес
    # в базе магазина не хранятся вовсе. Новой строке Status ставим начальное
    # значение, дальше эти три столбца не трогаем никогда — иначе очередная
    # синхронизация затирала бы работу владельца.
    MANUAL_HEADERS = ("Status", "Цвет", "Вес")
    NEW_ROW_STATUS = "Не пошито"

    def __init__(self, key_file: str | Path, spreadsheet_id: str) -> None:
        creds = Credentials.from_service_account_file(
            filename=str(key_file), scopes=SCOPES
        )
        self.sh = gspread.authorize(creds).open_by_key(spreadsheet_id)
        self._ws_cache: dict[str, gspread.Worksheet] = {}
        # Содержимое листов: {лист: {Order ID: [номер строки, значения]}}.
        # Читаем лист один раз за проход — не ради скорости, а ради лимитов
        # Sheets API: проверять каждый заказ отдельным запросом нельзя, на сотне
        # заказов это упёрлось бы в 429 («60 запросов в минуту»).
        self._index_cache: dict[str, dict[tuple[str, ...], tuple[int | None, list[str]]]] = {}

    # ---------- листы ----------

    def ws(self, title: str) -> gspread.Worksheet:
        if title not in self._ws_cache:
            try:
                w = self.sh.worksheet(title)
            except WorksheetNotFound:
                w = self.sh.add_worksheet(title=title, rows=NEW_SHEET_ROWS, cols=len(self.HEADERS))
                self._init_page(w)
            self._ws_cache[title] = w
        return self._ws_cache[title]

    def _init_page(self, ws: gspread.Worksheet) -> None:
        if ws.row_values(1):
            return
        last = rowcol_to_a1(1, len(self.HEADERS))
        ws.update(values=[self.HEADERS], range_name="A1")
        ws.format(f"A1:{last}", {
            "backgroundColor": rgb(255, 204, 153),
            "textFormat": {"bold": True, "foregroundColor": rgb(0, 0, 0)},
        })
        ws.freeze(rows=1)

    def index(self, title: str) -> dict[tuple[str, ...], tuple[int | None, list[str]]]:
        """Что на листе уже есть: ключ строки -> (номер строки, её значения).

        Номер None — строку дописали прямо сейчас и настоящий её номер
        назначает Google; обновлять такую строку в этом же проходе нечего.
        """
        if title not in self._index_cache:
            ws = self.ws(title)
            rows = ws.get_all_values()[HEADER_ROWS:]
            index: dict[tuple[str, ...], tuple[int | None, list[str]]] = {}
            for offset, row in enumerate(rows):
                # хвостовые пустые ячейки Google не присылает — дополняем сами
                padded = list(row) + [""] * (len(self.HEADERS) - len(row))
                key = self._key(padded)
                # дубль (например, строка, вписанная руками) — держимся первой
                if key[0] and key not in index:
                    index[key] = (offset + HEADER_ROWS + 1, padded)
            self._index_cache[title] = index
        return self._index_cache[title]

    def _key(self, row: list[str]) -> tuple[str, ...]:
        """Ключ строки из её значений — по нему сверяемся с тем, что уже на листе."""
        return tuple(_as_text(row[self.HEADERS.index(h)]) for h in self.KEY_HEADERS)

    # ---------- строки ----------

    def _row_for(self, data: dict) -> tuple[tuple[str, ...], list]:
        """Проверяет поля строки, раскладывает её по столбцам и считает ключ."""
        unknown = set(data) - set(self.HEADERS)
        if unknown:
            raise KeyError(f"Неизвестные поля: {', '.join(sorted(unknown))}")

        if not _as_text(data.get(self.ID_HEADER)):
            # Без номера строку не отличить от уже выгруженной — а значит,
            # следующая выгрузка добавила бы её второй раз. Лучше упасть сразу.
            raise ValueError(f"В строке нет поля «{self.ID_HEADER}»")

        row = [data.get(h, "") for h in self.HEADERS]
        status_col = self.HEADERS.index("Status")
        row[status_col] = data.get("Status") or self.NEW_ROW_STATUS
        return self._key(row), row

    def _changed_ranges(self, row_number: int, current: list[str], desired: list) -> list[dict]:
        """Диапазоны существующей строки, которые разошлись с базой.

        Столбцы из MANUAL_HEADERS всегда считаем совпавшими — их не сверяем
        и не пишем. Соседние изменившиеся ячейки собираем в один диапазон,
        чтобы batch_update не раздувался.
        """
        updates: list[dict] = []
        start: int | None = None

        def close(end: int) -> None:
            updates.append({
                "range": f"{rowcol_to_a1(row_number, start + 1)}:{rowcol_to_a1(row_number, end + 1)}",
                "values": [desired[start:end + 1]],
            })

        for col, header in enumerate(self.HEADERS):
            owned = header not in self.MANUAL_HEADERS
            if owned and _as_text(current[col]) != _as_text(desired[col]):
                if start is None:
                    start = col
            elif start is not None:
                close(col - 1)
                start = None
        if start is not None:
            close(len(self.HEADERS) - 1)
        return updates

    def sync_orders(self, title: str, rows: list[dict]) -> tuple[int, int]:
        """Приводит лист товара в соответствие с базой.

        Незнакомый заказ дописывается в конец, знакомый — обновляется в тех
        столбцах, за которые отвечаем мы (адрес поправили, трек-номер появился).
        Возвращает (сколько добавили, сколько обновили).

        Три запроса на лист в худшем случае: одно чтение (чтобы понять, что там
        уже есть), один batch_update на правки и одна дозапись новых строк.
        """
        if not rows:
            return 0, 0

        index = self.index(title)  # заодно создаёт лист, если его ещё нет
        fresh: list[list] = []
        updates: list[dict] = []
        updated_rows: set[int] = set()

        for data in rows:
            key, row = self._row_for(data)
            known = index.get(key)
            if known is None:
                fresh.append(row)
                # Номер строки пока неизвестен — его назначит сам Google при
                # дозаписи. None и означает «эту строку мы уже положили»:
                # повторный вызов с тем же заказом её не задвоит и не полезет
                # обновлять чужую строку по угаданному номеру.
                index[key] = (None, row)
                continue

            row_number, current = known
            if row_number is None:
                continue  # только что дописали в этом же проходе

            # Status/Цвет/Вес не выдумываем — оставляем то, что в таблице
            for col, header in enumerate(self.HEADERS):
                if header in self.MANUAL_HEADERS:
                    row[col] = current[col]

            changed = self._changed_ranges(row_number, current, row)
            if changed:
                updates.extend(changed)
                updated_rows.add(row_number)
                index[key] = (row_number, row)

        if updates:
            self.ws(title).batch_update(updates, value_input_option=VALUE_INPUT)
        if fresh:
            self.ws(title).append_rows(fresh, value_input_option=VALUE_INPUT)

        return len(fresh), len(updated_rows)

    def add_order(self, title: str, data: dict) -> bool:
        """Один заказ на лист товара.

        False — такой заказ на листе уже есть: второй строки он не получит,
        вместо этого обновятся наши столбцы в существующей (см. KEY_HEADERS).
        """
        added, _ = self.sync_orders(title, [data])
        return added == 1
