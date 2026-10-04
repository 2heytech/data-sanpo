"""Excel（.xlsx）のシートを値の表として読む・書く（標準ライブラリだけ。書くのは見本データ用）。

.xlsx は XML を ZIP にまとめたもの。セルの値だけを読み、書式・数式は扱わない（数式のセルは保存された値）。
文字列は共有文字列（sharedStrings.xml）とセル内の文字列（inlineStr）の両方に対応する。
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
Cell = str | float | None


def _text(el) -> str:
    """文字列の要素の文字。ふりがな（rPh）の文字は含めない（日本語の Excel は読みを一緒に保存する）。"""
    m = NS["m"]
    out = []
    for child in el:
        if child.tag == f"{{{m}}}t":
            out.append(child.text or "")
        elif child.tag == f"{{{m}}}r":            # 書式つきの文字の並び
            out += [t.text or "" for t in child.findall(f"{{{m}}}t")]
    return "".join(out)


def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def sheet_names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
    return [s.get("name") for s in wb.iter(f"{{{NS['m']}}}sheet")]


def read_sheet(path: Path, sheet: int | str = 0) -> list[list[Cell]]:
    """シートの各行をセルの値のリストで返す（空のセルは None、数値は float、文字列は str）。"""
    with zipfile.ZipFile(path) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        sheets = list(wb.iter(f"{{{NS['m']}}}sheet"))
        el = sheets[sheet] if isinstance(sheet, int) else next(s for s in sheets if s.get("name") == sheet)
        rid = el.get(f"{{{NS['r']}}}id")
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = next(r.get("Target") for r in rels if r.get("Id") == rid)
        target = target.lstrip("/")
        target = target if target.startswith("xl/") else f"xl/{target}"
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            shared = [_text(si) for si in ET.fromstring(z.read("xl/sharedStrings.xml"))]
        root = ET.fromstring(z.read(target))
    rows: list[list[Cell]] = []
    for row in root.iter(f"{{{NS['m']}}}row"):
        values: list[Cell] = []
        for c in row.iter(f"{{{NS['m']}}}c"):
            i = _col_index(c.get("r")) if c.get("r") else len(values)
            values += [None] * (i - len(values))
            kind, v = c.get("t"), c.find("m:v", NS)
            if kind == "inlineStr":
                cell: Cell = _text(c.find("m:is", NS))
            elif v is None or v.text is None:
                cell = None
            elif kind == "s":
                cell = shared[int(v.text)]
            elif kind in ("str", "e"):
                cell = v.text
            elif kind == "b":
                cell = float(v.text)
            else:
                cell = float(v.text)
            values.append(cell)
        r = int(row.get("r", len(rows) + 1)) - 1
        rows += [[] for _ in range(r - len(rows))]
        rows.append(values)
    return rows


def write_sheet(path: Path, rows: list[list[Cell]], sheet_name: str = "Sheet1") -> None:
    """値だけの1シートの .xlsx を書く（見本データ用。文字列はセル内の文字列で書く）。"""
    write_sheets(path, {sheet_name: rows})


def write_sheets(path: Path, sheets: dict[str, list[list[Cell]]]) -> None:
    """値だけの複数シートの .xlsx を書く（見本データ用）。"""
    def col(i: int) -> str:
        s = ""
        i += 1
        while i:
            i, rem = divmod(i - 1, 26)
            s = chr(65 + rem) + s
        return s

    def sheet_xml(rows: list[list[Cell]]) -> str:
        body = []
        for r, row in enumerate(rows, 1):
            cells = []
            for i, v in enumerate(row):
                ref = f"{col(i)}{r}"
                if v is None or v == "":
                    continue
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    cells.append(f'<c r="{ref}"><v>{v}</v></c>')
                else:
                    cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>')
            body.append(f'<row r="{r}">{"".join(cells)}</row>')
        return (f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{NS["m"]}">'
                f'<sheetData>{"".join(body)}</sheetData></worksheet>')

    names = list(sheets)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{k}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for k in range(1, len(names) + 1)) +
                   '</Types>')
        z.writestr("_rels/.rels",
                   f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{NS["rel"]}">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '</Relationships>')
        z.writestr("xl/workbook.xml",
                   f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="{NS["m"]}" xmlns:r="{NS["r"]}"><sheets>'
                   + "".join(f'<sheet name="{escape(n)}" sheetId="{k}" r:id="rId{k}"/>' for k, n in enumerate(names, 1))
                   + '</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{NS["rel"]}">'
                   + "".join(f'<Relationship Id="rId{k}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{k}.xml"/>'
                             for k in range(1, len(names) + 1))
                   + '</Relationships>')
        for k, n in enumerate(names, 1):
            z.writestr(f"xl/worksheets/sheet{k}.xml", sheet_xml(sheets[n]))
