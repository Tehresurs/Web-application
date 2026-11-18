"""Remove unused employee rows without reserializing workbook styles."""
from io import BytesIO
import re
from zipfile import ZipFile
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from app.services.luvr_export_table import table_total_row


def compact_month(workbook, employee_count):
    template_total=table_total_row(load_workbook(BytesIO(workbook)).active)
    capacity=template_total-9
    if not 0 <= employee_count <= capacity:
        raise ValueError(f'Допустимо не более {capacity} сотрудников.')
    shift = capacity - employee_count
    total_row = 9 + employee_count

    def reference(match):
        column, number = match.groups()
        row = int(number)
        return column + str(row - shift if row >= template_total else min(row, total_row - 1))

    def refs(text):
        return re.sub(r'(\$?[A-Z]{1,3}\$?)(\d+)', reference, text)

    def formula(token):
        # Empty/shared follower formula nodes must never consume a later </f>.
        if token[0].endswith('/>'):return token[0]
        match=re.fullmatch(r'(<f\b[^>]*>)(.*?)(</f>)',token[0],re.S)
        # Remaining MASTER formula subtracts single employee cells.
        # Removed cells were blank, hence contribute zero.
        def cell(m):
            return '0' if total_row <= int(m[2]) < template_total else reference(m)
        return match[1]+re.sub(r'(\$?[A-Z]{1,3}\$?)(\d+)',cell,match[2])+match[3]

    def clear_cache(token):
        cell=token[0]
        if not re.search(r'<f\b',cell):return cell
        return re.sub(r'<v\b[^>]*?(?:/>|>.*?</v>)','',cell,flags=re.S)

    def row(match):
        number = int(match[1])
        if total_row <= number < template_total:
            return ''
        xml = re.sub(r'<f\b[^>]*?(?:/>|>.*?</f>)',formula,match[0],flags=re.S)
        # Values cached by the filled MASTER do not belong to the exported month.
        xml = re.sub(r'<c\b[^>]*?(?:/>|>.*?</c>)',clear_cache,xml,flags=re.S)
        if number >= template_total:
            xml = re.sub(r'(<row\b[^>]*\br=")\d+',lambda m:m[1]+str(number-shift),xml,count=1)
            xml = re.sub(r'(<c\b[^>]*\br=")([^\"]+)',lambda m:m[1]+refs(m[2]),xml)
        return xml

    output = BytesIO()
    with ZipFile(BytesIO(workbook)) as source, ZipFile(output,'w') as target:
        for entry in source.infolist():
            # Excel rebuilds this optional dependency chain after row/formula edits.
            if entry.filename=='xl/calcChain.xml':continue
            content = source.read(entry.filename)
            if entry.filename == 'xl/worksheets/sheet1.xml':
                xml = re.sub(r'<row\b[^>]*\br="(\d+)"[^>]*?(?:/>|>.*?</row>)',row,content.decode(),flags=re.S)
                xml = re.sub(r'\b(ref|sqref)="([^\"]+)"',lambda m:m[1]+'="'+refs(m[2])+'"',xml)
                # After all rows/references have reached their final positions,
                # total only actual employee rows. Keep freshly computed numeric
                # caches so data_only readers receive the same authoritative sums.
                def total_cell(match):
                    cell=match[0];address=re.search(r'\br="([A-Z]+)([0-9]+)"',cell)
                    if not address or int(address[2])!=total_row:return cell
                    column=address[1]
                    if column not in [get_column_letter(c) for c in range(6,40)]:return cell
                    value=re.search(r'<v>([-+0-9.eE]+)</v>',cell)
                    if value is None:return cell
                    expression=f'SUM({column}9:{column}{total_row-1})' if employee_count else '0'
                    return cell[:value.start()]+'<f>'+expression+'</f>'+cell[value.start():]
                xml=re.sub(r'<c\b[^>]*?(?:/>|>.*?</c>)',total_cell,xml,flags=re.S)
                content = xml.encode()
            elif entry.filename == 'xl/workbook.xml':
                xml = re.sub(r'(<definedName\b[^>]*>)(.*?)(</definedName>)',lambda m:m[1]+refs(m[2])+m[3],content.decode(),flags=re.S)
                def recalc(m):
                    tag=m[0]
                    for key,value in (('fullCalcOnLoad','1'),('forceFullCalc','1'),('calcMode','auto')):
                        tag=re.sub(r'\s+'+key+r'="[^"]*"','',tag)
                        tag=tag.replace('/>',' '+key+'="'+value+'"/>')
                    return tag
                xml=re.sub(r'<calcPr\b[^>]*?/>',recalc,xml)
                content=xml.encode()
            elif entry.filename=='xl/_rels/workbook.xml.rels':
                content=re.sub(r'<Relationship\b[^>]*\bType="[^"]*/calcChain"[^>]*?/>','',content.decode()).encode()
            elif entry.filename=='[Content_Types].xml':
                content=re.sub(r'<Override\b[^>]*\bPartName="/xl/calcChain.xml"[^>]*?/>','',content.decode()).encode()
            elif re.fullmatch(r'xl/drawings/drawing\d+\.xml',entry.filename):
                content = re.sub(r'(<(?:\w+:)?row>)(\d+)(</(?:\w+:)?row>)',lambda m:m[1]+str(int(m[2])-shift if int(m[2])>=template_total-1 else min(int(m[2]),total_row-2))+m[3],content.decode()).encode()
            target.writestr(entry,content)
    return output.getvalue()
