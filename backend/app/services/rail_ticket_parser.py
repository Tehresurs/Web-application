"""Text-layer parser for the one-page RZD control-coupon layout supplied for stage 3.

No OCR, fuzzy names or SQL. Only the relevant header/route/name regions are retained.
"""
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
import re

from pypdf import PdfReader

MAX_TICKET_BYTES = 10 * 1024 * 1024


def safe_filename(value):
    name = (value or "ticket.pdf").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r'[\x00-\x1f\x7f<>:"|?*]', "_", name).strip(" .")
    return name[:240] or "ticket.pdf"


def normalize_passenger(value):
    return " ".join((value or "").split()).casefold()


def luvr_route(departure, arrival):
    """Exact station comparison only; no inferred region/code suffixes."""
    origin = normalize_passenger(departure) == "салым"
    destination = normalize_passenger(arrival) == "салым"
    return origin or destination, ("ARRIVAL" if destination else "DEPARTURE") if origin != destination else None


@dataclass
class ParsedRailTicket:
    source_filename: str
    full_name: str | None = None
    departure_station: str | None = None
    departure_datetime: datetime | None = None
    arrival_station: str | None = None
    arrival_datetime: datetime | None = None
    parse_status: str = "PARSE_ERROR"
    parse_errors: list[str] = field(default_factory=list)
    source_page: int | None = None
    source_sha256: str | None = None

    @property
    def full_name_raw(self):
        return self.full_name


def _fragments(page):
    """Coordinates normalized to the supplied A4 layout, top-down.

    The coupons simulate bold with two almost coincident copies. Deduplicate
    identical text only at the same coordinates, never repeated name characters.
    """
    result = []
    width, height = float(page.mediabox.width), float(page.mediabox.height)

    def visitor(text, cm, tm, font, size):
        if not text.strip() or abs(cm[1]) > .01 or abs(cm[2]) > .01:
            return
        x = (tm[4] * cm[0] + tm[5] * cm[2] + cm[4]) * 595 / width
        y = (height - (tm[4] * cm[1] + tm[5] * cm[3] + cm[5])) * 842 / height
        scaled_size = abs(size * cm[0]) * 595 / width
        # No passport, birthday, prices, order number or vertical service text.
        allowed = (x < 310 and 40 <= y <= 55) or (x < 280 and 125 <= y <= 265) or (310 <= x <= 560 and 142 <= y <= 177 and scaled_size >= 10)
        if not allowed:
            return
        text = " ".join(text.split())
        if any(t == text and abs(px-x) < 1 and abs(py-y) < 1 for px,py,t in result):
            return
        result.append((x,y,text))

    page.extract_text(visitor_text=visitor)
    return result


def _region(parts, x1, x2, y1, y2):
    lines = []
    for x,y,text in sorted((p for p in parts if x1 <= p[0] <= x2 and y1 <= p[1] <= y2), key=lambda p:(round(p[1]),p[0])):
        if not lines or abs(lines[-1][0]-y) > 2:
            lines.append((y,[(x,text)]))
        else:
            lines[-1][1].append((x,text))
    # Within a station the PDF splits its capital from the rest; no invented space.
    return " ".join("".join(t for _,t in sorted(chunks)) for _,chunks in lines).strip()


def parse_rail_ticket(data: bytes, filename: str, *, _page=None) -> ParsedRailTicket:
    result = ParsedRailTicket(safe_filename(filename))
    if not data or len(data) > MAX_TICKET_BYTES:
        result.parse_errors.append("Пустой файл или размер более 10 МБ")
        return result
    if not filename.lower().endswith(".pdf") or not data.startswith(b"%PDF-"):
        result.parse_status = "UNSUPPORTED"
        result.parse_errors.append("Поддерживается PDF с текстовым слоем типового контрольного купона РЖД")
        return result
    try:
        if _page is None:
            reader = PdfReader(BytesIO(data), strict=True)
            if reader.is_encrypted or len(reader.pages) != 1:
                result.parse_status = "UNSUPPORTED"
                raise ValueError("PDF содержит несколько страниц или зашифрован; требуется раздельный разбор страниц")
            _page=reader.pages[0]
        parts = _fragments(_page)
        if not any("ЭЛЕКТРОННЫЙ БИЛЕТ. КОНТРОЛЬНЫЙ КУПОН" in t for _,_,t in parts):
            result.parse_status = "UNSUPPORTED"
            raise ValueError("Не найден текстовый слой поддерживаемого контрольного купона")
        name = _region(parts,310,560,142,177)
        if re.fullmatch(r"[А-ЯЁA-Z][А-ЯЁA-Zа-яёa-z'-]*(?:\s+[А-ЯЁA-Z][А-ЯЁA-Zа-яёa-z'-]*){1,3}",name):
            result.full_name=name
        for prefix in ("departure","arrival"):
            expected = "Отправление" if prefix=="departure" else "Прибытие"
            anchors=[(x,y) for x,y,text in parts if x<120 and text.startswith(expected+' по')]
            if len(anchors)!=1:
                continue
            x,y=anchors[0]
            # The confirmed coupon layout has date/time above each semantic marker,
            # station to its right. Independent of PDF text stream ordering.
            clock = _region(parts,x-8,x+65,y-17,y-9)
            day = _region(parts,x+70,x+147,y-17,y-9)
            station = _region(parts,x+70,x+232,y-1,y+16)
            if station and re.fullmatch(r"[А-Яа-яЁёA-Za-z0-9 .()/-]+",station):
                setattr(result,prefix+"_station",station)
            try:
                value=datetime.strptime(day+" "+clock,"%d.%m.%Y %H:%M")
                setattr(result,prefix+"_datetime",value)
            except ValueError:
                pass
        for key,label in (("full_name","ФИО пассажира"),("departure_station","станция отправления"),("departure_datetime","дата и время отправления"),("arrival_station","станция прибытия"),("arrival_datetime","дата и время прибытия")):
            if getattr(result,key) is None:result.parse_errors.append("Не найдено: "+label)
        # Different local time zones can make arrival look earlier; no UTC guess.
        if not result.parse_errors:result.parse_status="PARSED"
    except ValueError as error:
        result.parse_errors.append(str(error) if str(error).startswith(("Нужен", "Не найден")) else "Не удалось прочитать структуру PDF")
    except Exception:
        result.parse_errors.append("Повреждённый PDF или неподдерживаемая структура")
    return result


def parse_rail_document(data: bytes, filename: str) -> list[ParsedRailTicket]:
    """One independent supported coupon per page; never join routes across pages."""
    import hashlib
    if not data or len(data)>MAX_TICKET_BYTES or not filename.lower().endswith('.pdf') or not data.startswith(b'%PDF-'):
        return [parse_rail_ticket(data,filename)]
    try:
        reader=PdfReader(BytesIO(data),strict=True)
        if reader.is_encrypted or not reader.pages:
            return [parse_rail_ticket(data,filename)]
        results=[]
        for index,page in enumerate(reader.pages,1):
            parsed=parse_rail_ticket(data,filename,_page=page)
            parsed.source_page=index
            parsed.source_sha256=hashlib.sha256(data).hexdigest()
            results.append(parsed)
        return results
    except Exception:
        return [parse_rail_ticket(data,filename)]
