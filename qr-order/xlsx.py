"""Excel (.xlsx) files with the standard library only.

  build(sheets)                      -> a new workbook
  fill_layout(data, values, lists)   -> a copy of a layout workbook with its {{placeholders}} filled in

A layout is an ordinary .xlsx. A single value goes wherever {{sales}} is written. A row that contains list
placeholders such as {{order.token}} is repeated once for every order, keeping its formatting; rows below move
down, and formulas on the same sheet that cover that row grow with it. Text is always written as text, so a
guest's name starting with '=' can never become a formula.

Layouts are uploaded files, so they are treated as hostile: size limits, no macros, no links to other files,
no XML tricks."""
import io
import re
import zipfile
from xml.dom import minidom
from xml.sax.saxutils import escape

MAX_UPLOAD = 2 * 1024 * 1024
MAX_UNPACKED = 20 * 1024 * 1024
MAX_PARTS = 300
MAX_ROWS = 50_000

PLACE = re.compile(r"\{\{\s*([a-z_]+(?:\.[a-z_]+)?)\s*\}\}")
BAD_XML = re.compile("[^\t\n\r\x20-퟿-�\U00010000-\U0010ffff]")
REF = re.compile(r"(?<![\w$.])(?P<sheet>(?:'(?:[^']|'')*'|[A-Za-z_][\w.]*)!)?(?P<c1>\$?[A-Z]{1,3})(?P<a1>\$?)(?P<r1>\d+)"
                 r"(?::(?P<c2>\$?[A-Z]{1,3})(?P<a2>\$?)(?P<r2>\d+))?(?![\w(!])")


class LayoutError(Exception):
    """Something about the file that the owner can fix. The message is shown to them."""


def column(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def safe(text):
    return BAD_XML.sub("", str(text))[:32000]


# ------------------------------------------------------------ a new workbook
# styles: 0 normal, 1 heading, 2 money, 3 title, 4 percent, 5 quantity
STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="2"><numFmt numFmtId="164" formatCode="#,##0.00"/><numFmt numFmtId="165" formatCode="#,##0.###"/></numFmts>
<fonts count="3"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="16"/><name val="Calibri"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFF2E3B3"/></patternFill></fill></fills>
<borders count="2"><border/><border><bottom style="thin"/></border></borders>
<cellStyleXfs count="1"><xf/></cellStyleXfs>
<cellXfs count="6"><xf/><xf fontId="1" fillId="2" borderId="1" applyFont="1" applyFill="1" applyBorder="1"/><xf numFmtId="164" applyNumberFormat="1"/><xf fontId="2" applyFont="1"/><xf numFmtId="10" applyNumberFormat="1"/><xf numFmtId="165" applyNumberFormat="1"/></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def build(sheets):
    """sheets: [(name, [column widths], [[cell, ...], ...])]; a cell is None, a value, or (value, style)."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        types = ['<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
                 '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>']
        rels, names = [], []
        for i, (name, widths, rows) in enumerate(sheets, 1):
            xml = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet xmlns="%s">' % NS]
            xml.append("<cols>%s</cols><sheetData>" % "".join('<col min="%d" max="%d" width="%s" customWidth="1"/>' % (n, n, w) for n, w in enumerate(widths, 1)))
            for r, row in enumerate(rows, 1):
                cells = []
                for c, cell in enumerate(row, 1):
                    if cell is None:
                        continue
                    value, style = cell if isinstance(cell, tuple) else (cell, 0)
                    ref = '%s%d' % (column(c), r)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        cells.append('<c r="%s" s="%d"><v>%r</v></c>' % (ref, style, value))
                    else:
                        cells.append('<c r="%s" s="%d" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (ref, style, escape(safe(value))))
                xml.append('<row r="%d">%s</row>' % (r, "".join(cells)))
            xml.append("</sheetData></worksheet>")
            z.writestr("xl/worksheets/sheet%d.xml" % i, "".join(xml))
            types.append('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % i)
            rels.append('<Relationship Id="rId%d" Type="%s/worksheet" Target="worksheets/sheet%d.xml"/>' % (i, REL, i))
            names.append('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (escape(name, {'"': "&quot;"}), i, i))
        rels.append('<Relationship Id="rId%d" Type="%s/styles" Target="styles.xml"/>' % (len(sheets) + 1, REL))
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>%s</Types>' % "".join(types))
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="%s/officeDocument" Target="xl/workbook.xml"/></Relationships>' % REL)
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>' % "".join(rels))
        z.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook xmlns="%s" xmlns:r="%s"><sheets>%s</sheets></workbook>' % (NS, REL, "".join(names)))
        z.writestr("xl/styles.xml", STYLES)
    return out.getvalue()


# ------------------------------------------------------------ reading an uploaded layout safely
def open_parts(data):
    if len(data) > MAX_UPLOAD:
        raise LayoutError("The file is larger than 2 MB")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        infos = z.infolist()
        if len(infos) > MAX_PARTS or sum(i.file_size for i in infos) > MAX_UNPACKED:
            raise LayoutError("The file unpacks to too much data")
        parts, total = {}, 0
        for info in infos:
            with z.open(info) as f:
                blob = f.read(MAX_UNPACKED - total + 1)  # never trust the size written in the file
            total += len(blob)
            if total > MAX_UNPACKED:
                raise LayoutError("The file unpacks to too much data")
            parts[info.filename] = blob
    except LayoutError:
        raise
    except Exception:
        raise LayoutError("This is not a readable .xlsx file")
    if "xl/workbook.xml" not in parts or "[Content_Types].xml" not in parts:
        raise LayoutError("This is not an Excel .xlsx file")
    for name in parts:
        low = name.lower()
        if "vbaproject" in low or "macrosheet" in low or "activex" in low or "/embeddings/" in low:
            raise LayoutError("Files with macros or embedded objects are not accepted")
        if "externallink" in low or "connections.xml" in low or "querytable" in low:
            raise LayoutError("Files that link to other files or data sources are not accepted")
    for name, blob in parts.items():
        if name.endswith(".rels") and re.search(rb"""TargetMode\s*=\s*["']External["']""", blob) and b"/hyperlink" not in blob:
            raise LayoutError("Files that link to other files or data sources are not accepted")
    return parts


def xml_text(blob):
    try:
        text = blob.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise LayoutError("The file uses an unsupported text format")
    if "<!DOCTYPE" in text or "<!ENTITY" in text:  # stops 'billion laughs' and file-reading XML attacks
        raise LayoutError("The file contains unsafe XML")
    return text


def parse(blob):
    try:
        return minidom.parseString(xml_text(blob).encode("utf-8"))
    except LayoutError:
        raise
    except Exception:
        raise LayoutError("Part of the file is damaged")


def tags(node, name):
    return list(node.getElementsByTagNameNS("*", name))


def kids(node, name):
    return [k for k in node.childNodes if k.nodeType == k.ELEMENT_NODE and k.localName == name]


def text_of(node):
    """The words in a shared or inline string (ignores phonetic guides)."""
    out = []
    for t in tags(node, "t"):
        if t.parentNode.localName != "rPh":
            out.append("".join(c.data for c in t.childNodes if c.nodeType in (c.TEXT_NODE, c.CDATA_SECTION_NODE)))
    return "".join(out)


def make(doc, like, name):
    tag = (like.prefix + ":" + name) if like.prefix else name
    return doc.createElementNS(like.namespaceURI, tag)


def split_ref(ref):
    m = re.match(r"^([A-Z]{1,3})(\d+)$", ref or "")
    if not m:
        raise LayoutError("Part of the file is damaged")
    return m.group(1), int(m.group(2))


def move_refs(text, first, last, own=None):
    """Rewrite same-sheet references after rows were repeated. first(r)/last(r) give where old row r now starts/ends.
    own=(old row, new row): inside a repeated row, references to that row follow the copy."""
    def one(m):
        if m.group("sheet"):
            return m.group(0)
        r1 = int(m.group("r1"))
        if m.group("c2") is None:
            new = own[1] if own and r1 == own[0] else first(r1)
            return "%s%s%d" % (m.group("c1"), m.group("a1"), new)
        r2 = int(m.group("r2"))
        if own and r1 == r2 == own[0]:
            a, b = own[1], own[1]
        else:
            a, b = first(r1), last(r2)
        return "%s%s%d:%s%s%d" % (m.group("c1"), m.group("a1"), a, m.group("c2"), m.group("a2"), b)

    pieces = text.split('"')  # never touch what is inside quotes
    for i in range(0, len(pieces), 2):
        pieces[i] = REF.sub(one, pieces[i])
    return '"'.join(pieces)


def set_cell(doc, cell, value):
    for k in list(cell.childNodes):
        cell.removeChild(k)
    if cell.hasAttribute("t"):
        cell.removeAttribute("t")
    if value is None or value == "":
        return
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        v = make(doc, cell, "v")
        v.appendChild(doc.createTextNode(repr(value)))
        cell.appendChild(v)
        return
    cell.setAttribute("t", "inlineStr")
    holder, t = make(doc, cell, "is"), make(doc, cell, "t")
    t.setAttribute("xml:space", "preserve")
    t.appendChild(doc.createTextNode(safe(value)))
    holder.appendChild(t)
    cell.appendChild(holder)


def cell_text(cell, shared):
    kind = cell.getAttribute("t")
    if kids(cell, "f"):
        return None
    if kind == "s":
        v = kids(cell, "v")
        try:
            return shared[int(v[0].firstChild.data)]
        except (IndexError, ValueError, AttributeError):
            raise LayoutError("Part of the file is damaged")
    if kind == "inlineStr":
        return text_of(cell)
    return None


def fill_sheet(doc, shared, values, lists, budget):
    """Returns how many placeholders the sheet had."""
    data = tags(doc, "sheetData")
    if not data:
        return 0
    plan, found, previous = [], 0, 0
    for row in kids(data[0], "row"):
        raw = row.getAttribute("r")
        number = int(raw) if raw.isdigit() else previous + 1
        previous = number
        cells, kinds = [], set()
        for c in kids(row, "c"):
            text = cell_text(c, shared)
            if text is None or "{{" not in text:
                cells.append(None)
                continue
            for key in PLACE.findall(text):
                found += 1
                if "." in key:
                    group, field = key.split(".", 1)
                    if group not in lists or field not in lists[group]["fields"]:
                        raise LayoutError("Unknown placeholder {{%s}}" % key)
                    kinds.add(group)
                elif key not in values:
                    raise LayoutError("Unknown placeholder {{%s}}" % key)
            cells.append(text)
        if len(kinds) > 1:
            raise LayoutError("Row %d mixes two lists (%s). Put each list on its own row." % (number, ", ".join(sorted(kinds))))
        plan.append((number, row, cells, kinds.pop() if kinds else None))

    repeats = {n: max(len(lists[g]["rows"]), 1) for n, _, _, g in plan if g}
    if repeats:
        if tags(doc, "tablePart"):
            raise LayoutError("A sheet with repeating rows cannot contain an Excel 'table'. Convert it to a normal range.")
        if any(f.getAttribute("t") in ("shared", "array") for f in tags(data[0], "f")):
            raise LayoutError("A sheet with repeating rows cannot use filled-down or array formulas. Type each formula on its own.")

    def first(r):
        return r + sum(c - 1 for n, c in repeats.items() if n < r)

    def last(r):
        return first(r) + repeats.get(r, 1) - 1

    merges = []
    for number, row, cells, group in plan:
        copies = repeats.get(number, 1)
        budget[0] -= copies
        if budget[0] < 0:
            raise LayoutError("Too many rows for one sheet. Choose a shorter period.")
        template = row.cloneNode(True)
        anchor = row.nextSibling
        for k in range(copies):
            target = row if k == 0 else template.cloneNode(True)
            if k:
                data[0].insertBefore(target, anchor)
            new = first(number) + k
            target.setAttribute("r", str(new))
            record = lists[group]["rows"][k] if group and lists[group]["rows"] else None
            for cell, text in zip(kids(target, "c"), cells):
                if cell.getAttribute("r"):
                    cell.setAttribute("r", "%s%d" % (split_ref(cell.getAttribute("r"))[0], new))
                formulas = kids(cell, "f")
                if formulas:
                    for f in formulas:
                        if f.firstChild is not None:
                            f.firstChild.data = move_refs(f.firstChild.data, first, last, (number, new) if group else None)
                        if f.getAttribute("ref"):
                            f.setAttribute("ref", move_refs(f.getAttribute("ref"), first, last, (number, new) if group else None))
                    for v in kids(cell, "v"):
                        cell.removeChild(v)  # Excel works the answer out again when the file opens
                    continue
                if text is None:
                    continue

                def lookup(key):
                    if "." not in key:
                        return values[key]
                    return record.get(key.split(".", 1)[1]) if record else None

                whole = PLACE.fullmatch(text.strip())
                if whole:
                    set_cell(doc, cell, lookup(whole.group(1)))
                else:
                    set_cell(doc, cell, PLACE.sub(lambda m: "" if lookup(m.group(1)) is None else str(lookup(m.group(1))), text))

    if repeats:
        for dim in tags(doc, "dimension"):
            dim.parentNode.removeChild(dim)
        for m in tags(doc, "mergeCell"):
            a, _, b = m.getAttribute("ref").partition(":")
            (ca, ra), (cb, rb) = split_ref(a), split_ref(b or a)
            if ra == rb and ra in repeats:  # a merge inside a repeated row is repeated with it
                merges.append((m, ["%s%d:%s%d" % (ca, first(ra) + k, cb, first(ra) + k) for k in range(repeats[ra])]))
            else:
                m.setAttribute("ref", "%s%d:%s%d" % (ca, first(ra), cb, last(rb)))
        for m, refs in merges:
            parent = m.parentNode
            for ref in refs:
                extra = m.cloneNode(True)
                extra.setAttribute("ref", ref)
                parent.insertBefore(extra, m)
            parent.removeChild(m)
        for holder in tags(doc, "mergeCells"):
            holder.setAttribute("count", str(len(tags(holder, "mergeCell"))))
        for name, attr in (("autoFilter", "ref"), ("conditionalFormatting", "sqref"), ("dataValidation", "sqref"), ("hyperlink", "ref")):
            for node in tags(doc, name):
                if node.getAttribute(attr):
                    node.setAttribute(attr, " ".join(move_refs(p, first, last) for p in node.getAttribute(attr).split()))
        for f in tags(doc, "formula"):  # inside conditional formatting
            if f.firstChild is not None:
                f.firstChild.data = move_refs(f.firstChild.data, first, last)
    return found


def fill_layout(data, values, lists):
    """lists: {"order": {"fields": [...], "rows": [dict, ...]}, ...}. Raises LayoutError."""
    parts = open_parts(data)
    shared = []
    if "xl/sharedStrings.xml" in parts:
        shared = [text_of(si) for si in tags(parse(parts["xl/sharedStrings.xml"]), "si")]
    budget, found = [MAX_ROWS], 0
    sheets = [n for n in parts if re.match(r"^xl/worksheets/[^/]+\.xml$", n)]
    if not sheets:
        raise LayoutError("The file has no worksheets")
    for name in sheets:
        doc = parse(parts[name])
        found += fill_sheet(doc, shared, values, lists, budget)
        parts[name] = doc.toxml(encoding="UTF-8")
    if not found:
        raise LayoutError("The file has no placeholders such as {{sales}} or {{order.token}}, so there is nothing to fill")
    # the stored calculation order no longer fits: remove it and ask Excel to recalculate on opening
    parts.pop("xl/calcChain.xml", None)
    types = xml_text(parts["[Content_Types].xml"])
    parts["[Content_Types].xml"] = re.sub(r"<Override[^>]*calcChain[^>]*/>", "", types).encode()
    if "xl/_rels/workbook.xml.rels" in parts:
        parts["xl/_rels/workbook.xml.rels"] = re.sub(r"<Relationship [^>]*calcChain[^>]*/>", "", xml_text(parts["xl/_rels/workbook.xml.rels"])).encode()
    book = xml_text(parts["xl/workbook.xml"])
    if re.search(r"<(\w+:)?calcPr\b", book):
        if "fullCalcOnLoad" not in book:
            book = re.sub(r"<((?:\w+:)?calcPr)\b", r'<\1 fullCalcOnLoad="1"', book, count=1)
    else:
        m = re.search(r"</((?:\w+:)?)definedNames>", book) or re.search(r"</((?:\w+:)?)sheets>", book)
        if m:
            book = book[:m.end()] + '<%scalcPr fullCalcOnLoad="1"/>' % m.group(1) + book[m.end():]
    parts["xl/workbook.xml"] = book.encode("utf-8")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, blob in parts.items():
            z.writestr(name, blob)
    return out.getvalue()
