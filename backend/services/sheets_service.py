"""Клиент Google-таблицы: один лист на товар, одна строка на позицию заказа.

Низкий уровень — здесь только работа с самой таблицей, про заказы из БД
этот модуль не знает (этим занимается sheets_export.py). Разделение то же,
что у СДЭК: cdek_service.py — общение с чужим API, cdek_sync.py — наша логика.

Лист не дописывается, а перекладывается заново: строки идут в том порядке,
в каком их прислал sheets_export, а между группами (разными размерами) кладётся
пустая строка. Порядок строк на листе поэтому наш, а не «в каком пришли продажи».

Что при этом не теряется:
  * отметка о пошиве (Status) — она переносится к строке по её ключу;
  * строки, которых в выгрузке больше нет (отменённый заказ, ручная запись), —
    они уезжают в конец листа, а не удаляются.

Отметок «выгружено» в базе для этого не нужно: что уже в таблице, знает сама
таблица — по ключу строки (KEY_HEADERS).

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

# Новый лист: 100 строк с запасом, дальше растим по мере надобности (_ensure_grid)
NEW_SHEET_ROWS = 100

# Первая строка на каждом листе — шапка
HEADER_ROWS = 1

# Значения пишем как есть, без разбора «как при ручном вводе» (USER_ENTERED).
# С разбором телефон «+7 999 123-45-67» Google принимает за формулу и кладёт
# в ячейку #ERROR!, а имя или адрес, начинающийся с «=», стал бы живой формулой
# в чужой таблице. Числа при этом остаются числами: мы их числами и передаём.
VALUE_INPUT = "RAW"

# Порядок размеров на листе. Магазин пользуется двумя шкалами — буквенной
# и Mini/Medium/Big; у одного товара в ходу одна из них, так что то, что
# в этом списке они идут подряд, ничему не мешает.
SIZE_ORDER = (
    "xxs", "xs", "s", "m", "l", "xl", "xxl", "xxxl",
    "mini", "medium", "big",
)
SIZE_RANK = {label: i for i, label in enumerate(SIZE_ORDER)}
# Незнакомый размер — после всех известных, дальше по алфавиту.
# Пустой размер (у товара их просто нет) — в самый конец.
RANK_UNKNOWN = len(SIZE_ORDER) + 1
RANK_EMPTY = len(SIZE_ORDER) + 2


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


def size_group(cell) -> str:
    """Размер без количества: «M × 3» → «M».

    Количество живёт в той же ячейке (отдельного столбца под него нет), но
    к группировке и к опознанию строки оно отношения не имеет: доложили ещё
    одну футболку того же размера — это та же строка, а не новая.
    """
    return _as_text(cell).split("×")[0].strip()


def size_sort_key(cell) -> tuple[int, str]:
    """По чему сортировать строки внутри листа."""
    label = size_group(cell)
    if not label:
        return (RANK_EMPTY, "")
    normalized = label.casefold()
    if normalized in SIZE_RANK:
        return (SIZE_RANK[normalized], "")
    return (RANK_UNKNOWN, normalized)


class GoogleSheet:
    HEADERS = [
        "Order ID", "Status", "Дата заказа",
        "Товар", "Цвет", "Размер", "Вес",
        "Заплачено", "Стоимость доставки", "Итог",
        "ФИО", "Телефон", "Почта",
        "Адрес доставки", "Способ доставки", "Трек отправки",
    ]

    # Чем строка опознаётся при повторной выгрузке: заказ, товар, цвет и размер.
    # На листе товара «Товар» одинаков во всех строках, так что по сути ключ —
    # это заказ плюс то, что в нём взяли. Цвет нужен потому, что две футболки
    # разного цвета — два товара с одинаковым названием; размер — потому что
    # одну и ту же вещь берут в двух размерах, и это две разные строки.
    ID_HEADER = "Order ID"
    KEY_HEADERS = ("Order ID", "Товар", "Цвет", "Размер")
    # Из ключа обязательны только эти: цвет и размер часто пусты,
    # и пустые они — нормальная часть ключа, а не повод отказать
    REQUIRED_HEADERS = ("Order ID", "Товар")

    # Единственный столбец, который ведёт человек, а не выгрузка: отметка о пошиве.
    # Ради неё таблица и существует. Новой строке ставим начальное значение,
    # дальше не трогаем никогда — иначе синхронизация затирала бы работу владельца.
    MANUAL_HEADERS = ("Status",)
    NEW_ROW_STATUS = "Не пошито"

    def __init__(self, key_file: str | Path, spreadsheet_id: str) -> None:
        creds = Credentials.from_service_account_file(
            filename=str(key_file), scopes=SCOPES
        )
        self.sh = gspread.authorize(creds).open_by_key(spreadsheet_id)
        self._ws_cache: dict[str, gspread.Worksheet] = {}
        # Содержимое листов: {лист: {ключ строки: (номер строки, значения)}}.
        # Читаем лист один раз за проход — не ради скорости, а ради лимитов
        # Sheets API: проверять каждый заказ отдельным запросом нельзя, на сотне
        # заказов это упёрлось бы в 429 («60 запросов в минуту»).
        self._index_cache: dict[str, dict[tuple[str, ...], tuple[int, list[str]]]] = {}
        # Сколько строк занимало тело листа до нашей записи: хвост от прошлого
        # прохода надо затереть, иначе после сортировки останутся объедки
        self._body_len: dict[str, int] = {}

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

    def _ensure_grid(self, ws: gspread.Worksheet, rows: int) -> None:
        """Дорастить лист, если строк на нём меньше, чем мы собираемся записать.

        Раньше об этом заботился append_rows — он расширял лист сам. Мы пишем
        диапазоном, а запись за пределы сетки Google просто отвергает.
        """
        if ws.row_count < rows:
            ws.add_rows(rows - ws.row_count)

    def index(self, title: str) -> dict[tuple[str, ...], tuple[int, list[str]]]:
        """Что на листе уже есть: ключ строки -> (номер строки, её значения).

        Строки-разделители (пустые) сюда не попадают: у них нет номера заказа.
        """
        if title not in self._index_cache:
            ws = self.ws(title)
            rows = ws.get_all_values()[HEADER_ROWS:]
            self._body_len[title] = len(rows)
            index: dict[tuple[str, ...], tuple[int, list[str]]] = {}
            for offset, row in enumerate(rows):
                # хвостовые пустые ячейки Google не присылает — дополняем сами
                padded = list(row) + [""] * (len(self.HEADERS) - len(row))
                key = self._key(padded)
                # дубль (например, строка, вписанная руками) — держимся первой
                if key[0] and key not in index:
                    index[key] = (offset + HEADER_ROWS + 1, padded)
            self._index_cache[title] = index
        return self._index_cache[title]

    # ---------- строки ----------

    def _key(self, row: list[str]) -> tuple[str, ...]:
        """Ключ строки из её значений — по нему сверяемся с тем, что уже на листе."""
        parts = []
        for header in self.KEY_HEADERS:
            value = row[self.HEADERS.index(header)]
            # размер сравниваем без количества: «M» и «M × 2» — одна и та же строка
            parts.append(size_group(value) if header == "Размер" else _as_text(value))
        return tuple(parts)

    def _row_for(self, data: dict) -> tuple[tuple[str, ...], list]:
        """Проверяет поля строки, раскладывает её по столбцам и считает ключ."""
        unknown = set(data) - set(self.HEADERS)
        if unknown:
            raise KeyError(f"Неизвестные поля: {', '.join(sorted(unknown))}")

        # Пустое обязательное поле — это тихая беда: строку не с чем сопоставить,
        # и каждая выгрузка добавляла бы её заново. Лучше упасть сразу и громко.
        missing = [h for h in self.REQUIRED_HEADERS if not _as_text(data.get(h))]
        if missing:
            raise ValueError(f"В строке не заполнено: {', '.join(missing)}")

        row = [data.get(h, "") for h in self.HEADERS]
        status_col = self.HEADERS.index("Status")
        row[status_col] = data.get("Status") or self.NEW_ROW_STATUS
        return self._key(row), row

    def _differs(self, current: list[str], desired: list) -> bool:
        """Разошлась ли строка с базой в тех столбцах, за которые отвечаем мы."""
        return any(
            _as_text(current[col]) != _as_text(desired[col])
            for col, header in enumerate(self.HEADERS)
            if header not in self.MANUAL_HEADERS
        )

    def _layout(self, ordered: list[list], extra: list[list], group_header: str) -> list[list]:
        """Тело листа: строки в присланном порядке, между группами — пустая строка.

        Группа — это значение столбца group_header (для листа товара «Размер»,
        для сводного — номер заказа). Разделитель ставится там, где оно меняется.

        Строки, которых в выгрузке больше нет, кладём в самый конец: удалять
        чужую работу выгрузка не должна, но и в отсортированной части им не место.
        """
        blank = [""] * len(self.HEADERS)
        column = self.HEADERS.index(group_header)

        body: list[list] = []
        previous = None
        for row in ordered:
            group = size_group(row[column]) if group_header == "Размер" else _as_text(row[column])
            if previous is not None and group != previous:
                body.append(list(blank))
            body.append(row)
            previous = group

        if extra:
            if body:
                body.append(list(blank))
            body.extend(extra)
        return body

    def _write_body(self, title: str, body: list[list]) -> None:
        """Записывает тело листа одним запросом, затирая хвост прошлого прохода."""
        ws = self.ws(title)
        blank = [""] * len(self.HEADERS)
        # добиваем пустыми строками до прежней длины — иначе после сортировки
        # внизу останутся строки, которых в новом теле уже нет
        tail = max(0, self._body_len.get(title, 0) - len(body))
        values = body + [list(blank) for _ in range(tail)]
        if not values:
            return

        first = HEADER_ROWS + 1
        last = HEADER_ROWS + len(values)
        self._ensure_grid(ws, last)
        ws.update(
            values=values,
            range_name=f"A{first}:{rowcol_to_a1(last, len(self.HEADERS))}",
            value_input_option=VALUE_INPUT,
        )
        # лист переложен — прежний слепок больше не описывает его
        self._index_cache.pop(title, None)
        self._body_len[title] = len(body)

    def sync_orders(self, title: str, rows: list[dict], group_header: str = "Размер") -> tuple[int, int]:
        """Перекладывает лист под присланные строки. Возвращает (добавлено, обновлено).

        Порядок строк — тот, в каком они пришли (сортирует их sheets_export);
        между сменой группы кладётся пустая строка. Отметка о пошиве переезжает
        к своей строке по ключу, так что сортировка её не путает.

        Два запроса на лист: одно чтение и одна запись тела целиком.
        """
        if not rows:
            return 0, 0

        existing = self.index(title)  # заодно создаёт лист, если его ещё нет
        ordered: list[list] = []
        seen: set[tuple[str, ...]] = set()
        added = updated = 0

        for data in rows:
            key, row = self._row_for(data)
            if key in seen:
                continue  # один и тот же заказ дважды в одной пачке
            seen.add(key)

            known = existing.get(key)
            if known is None:
                added += 1
            else:
                _, current = known
                # отметку о пошиве не выдумываем — переносим из таблицы
                for col, header in enumerate(self.HEADERS):
                    if header in self.MANUAL_HEADERS:
                        row[col] = current[col]
                if self._differs(current, row):
                    updated += 1
            ordered.append(row)

        # то, что было на листе, но в выгрузку не попало: отменённый заказ,
        # строка, вписанная руками. Не наше дело её удалять — сдвигаем вниз.
        extra = [values for key, (_, values) in existing.items() if key not in seen]

        self._write_body(title, self._layout(ordered, extra, group_header))
        return added, updated

    def add_order(self, title: str, data: dict) -> bool:
        """Один заказ на лист товара.

        False — такой заказ на листе уже есть: второй строки он не получит,
        обновятся наши столбцы в существующей (ключ строки — см. KEY_HEADERS).

        Порядок остальных строк при этом не восстанавливается: разложить лист
        по размерам можно только зная все строки сразу, а тут их одна. Этим
        занимается sync_orders, который зовёт полная выгрузка.
        """
        existing = self.index(title)
        key, row = self._row_for(data)
        known = existing.get(key)

        if known is None:
            self.ws(title).append_row(row, value_input_option=VALUE_INPUT)
            self._index_cache.pop(title, None)
            return True

        row_number, current = known
        for col, header in enumerate(self.HEADERS):
            if header in self.MANUAL_HEADERS:
                row[col] = current[col]
        if self._differs(current, row):
            self.ws(title).update(
                values=[row],
                range_name=f"A{row_number}:{rowcol_to_a1(row_number, len(self.HEADERS))}",
                value_input_option=VALUE_INPUT,
            )
            self._index_cache.pop(title, None)
        return False
