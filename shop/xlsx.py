"""Minimal dependency-free .xlsx and .csv writers."""
import csv
import io
import zipfile
from datetime import date
from xml.sax.saxutils import escape

# Indian digit grouping (12,34,567.89) with a rupee sign.
INR_FORMAT = ('[>=10000000]"₹"##\\,##\\,##\\,##0.00;[>=100000]"₹"##\\,##\\,##0.00;"₹"#,##0.00;'
              '-"₹"#,##0.00')
STYLE_IDS = {"text": 0, "header": 1, "money": 2, "date": 3, "qty": 4, "pct": 5, "int": 6, "title": 7,
             "total_money": 8, "total_text": 9}


def _styles():
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<numFmts count="3">'
        '<numFmt numFmtId="164" formatCode="%s"/>'
        '<numFmt numFmtId="165" formatCode="dd-mm-yyyy"/>'
        '<numFmt numFmtId="166" formatCode="#,##0.###"/>'
        '</numFmts>'
        '<fonts count="3"><font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="14"/><name val="Calibri"/></font></fonts>'
        '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFE8EEF4"/></patternFill></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="10">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
        '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '<xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '<xf numFmtId="10" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '<xf numFmtId="1" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        '<xf numFmtId="164" fontId="1" fillId="2" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
        '</cellXfs></styleSheet>' % escape(INR_FORMAT, {'"': "&quot;"})
    )


def _col(n):
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def month_label(key):
    try:
        return "%s %s" % (MONTHS[int(key[5:7]) - 1], key[:4])
    except (ValueError, IndexError, TypeError):
        return key


def _excel_date(iso):
    try:
        return (date.fromisoformat(iso[:10]) - date(1899, 12, 30)).days
    except (ValueError, TypeError):
        return None


def _cell(ref, value, kind, style=None):
    if value is None or value == "":
        return ""
    sid = STYLE_IDS[style or kind] if (style or kind) in STYLE_IDS else 0
    if kind in ("money", "qty", "int", "pct") and isinstance(value, (int, float)):
        v = value / 100.0 if kind == "pct" else value
        return '<c r="%s" s="%d"><v>%r</v></c>' % (ref, sid, float(v))
    if kind == "month":
        value = month_label(str(value))
    if kind == "date":
        serial = _excel_date(str(value))
        if serial is not None:
            return '<c r="%s" s="%d"><v>%d</v></c>' % (ref, STYLE_IDS["date"], serial)
    text = "".join(ch for ch in str(value) if ch in "\t\n\r" or ord(ch) >= 32)
    return '<c r="%s" s="%d" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (
        ref, sid, escape(text))


def _sheet(title, subtitle, columns, data, totals):
    out = []
    r = 1
    out.append('<row r="%d">%s</row>' % (r, _cell("A%d" % r, title, "text", "title")))
    r += 1
    if subtitle:
        out.append('<row r="%d">%s</row>' % (r, _cell("A%d" % r, subtitle, "text")))
        r += 1
    r += 1
    header_row = r
    out.append('<row r="%d">%s</row>' % (r, "".join(
        _cell("%s%d" % (_col(i), r), c[1], "text", "header") for i, c in enumerate(columns))))
    for row in data:
        r += 1
        out.append('<row r="%d">%s</row>' % (r, "".join(
            _cell("%s%d" % (_col(i), r), row.get(c[0]), c[2]) for i, c in enumerate(columns))))
    if totals:
        r += 1
        cells = []
        for i, c in enumerate(columns):
            v = totals.get(c[0])
            if i == 0 and v is None:
                v = "Total"
            style = "total_money" if c[2] == "money" else "total_text"
            cells.append(_cell("%s%d" % (_col(i), r), v, c[2] if c[2] != "money" else "money", style))
        out.append('<row r="%d">%s</row>' % (r, "".join(cells)))
    def width(c):
        fixed = {"money": 16, "date": 12, "qty": 11, "pct": 10, "int": 9, "month": 11}.get(c[2])
        if fixed:
            return max(fixed, len(c[1]) + 3)
        longest = max([len(str(row.get(c[0]) or "")) for row in data] + [len(c[1])])
        return max(10, min(45, longest + 2))
    widths = "".join('<col min="%d" max="%d" width="%d" customWidth="1"/>' % (i + 1, i + 1, width(c))
                     for i, c in enumerate(columns))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="%d" topLeftCell="A%d" activePane="bottomLeft" '
        'state="frozen"/></sheetView></sheetViews>'
        '<cols>%s</cols><sheetData>%s</sheetData></worksheet>' % (header_row, header_row + 1, widths, "".join(out))
    )


def build_xlsx(sheets):
    """sheets: list of dicts with name, title, subtitle, columns, rows, totals."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" '
                   'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" '
                   'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join('<Override PartName="/xl/worksheets/sheet%d.xml" '
                             'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             % (i + 1) for i in range(len(sheets)))
                   + '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                   'officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (
                       escape(_sheet_name(s["name"])), i + 1, i + 1) for i, s in enumerate(sheets))
                   + '</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                             'relationships/worksheet" Target="worksheets/sheet%d.xml"/>' % (i + 1, i + 1)
                             for i in range(len(sheets)))
                   + '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                     'relationships/styles" Target="styles.xml"/></Relationships>' % (len(sheets) + 1))
        z.writestr("xl/styles.xml", _styles())
        for i, s in enumerate(sheets):
            z.writestr("xl/worksheets/sheet%d.xml" % (i + 1),
                       _sheet(s["title"], s.get("subtitle"), s["columns"], s["rows"], s.get("totals")))
    return buf.getvalue()


def _sheet_name(name):
    for ch in "[]:*?/\\":
        name = name.replace(ch, " ")
    return name[:31]


def _csv_value(value, kind):
    if value is None:
        return ""
    if kind == "date" and isinstance(value, str) and len(value) >= 10 and value[4] == "-":
        return "%s-%s-%s" % (value[8:10], value[5:7], value[0:4])
    if kind == "money" and isinstance(value, (int, float)):
        return "%.2f" % value
    if kind == "month":
        return month_label(str(value))
    if isinstance(value, float) and value.is_integer():
        return "%d" % value
    text = str(value)
    if text[:1] in ("=", "+", "-", "@") and kind == "text":
        text = "'" + text  # guard against spreadsheet formula injection
    return text


def build_csv(columns, data, totals=None):
    buf = io.StringIO()
    buf.write("﻿")  # BOM so Excel opens UTF-8 (₹) correctly
    w = csv.writer(buf)
    w.writerow([c[1] for c in columns])
    for row in data:
        w.writerow([_csv_value(row.get(c[0]), c[2]) for c in columns])
    if totals:
        w.writerow([_csv_value(totals.get(c[0], "Total" if i == 0 else None), c[2]) for i, c in enumerate(columns)])
    return buf.getvalue().encode("utf-8")
