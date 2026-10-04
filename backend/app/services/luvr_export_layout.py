"""Remove unused employee rows without reserializing workbook styles."""
from io import BytesIO
import re
from zipfile import ZipFile


def compact_month(workbook, employee_count):
    if not 0 <= employee_count <= 76:
        raise ValueError('Допустимо не более 76 сотрудников.')
    shift = 76 - employee_count
    if not shift:
        return workbook
    total_row = 9 + employee_count

    def reference(match):
        column, number = match.groups()
        row = int(number)
        return column + str(row - shift if row >= 85 else min(row, total_row - 1))

    def refs(text):
        return re.sub(r'(\$?[A-Z]{1,3}\$?)(\d+)', reference, text)

    def formula(match):
        # Remaining MASTER formula subtracts single employee cells.
        # Removed cells were blank, hence contribute zero.
        def cell(m):
            return '0' if total_row <= int(m[2]) < 85 else reference(m)
        return match[1]+re.sub(r'(\$?[A-Z]{1,3}\$?)(\d+)',cell,match[2])+match[3]

    def row(match):
        number = int(match[1])
        if total_row <= number < 85:
            return ''
        xml = re.sub(r'(<f\b[^>]*>)(.*?)(</f>)',formula,match[0],flags=re.S)
        if number >= 85:
            xml = re.sub(r'(<row\b[^>]*\br=")\d+',lambda m:m[1]+str(number-shift),xml,count=1)
            xml = re.sub(r'(<c\b[^>]*\br=")([^\"]+)',lambda m:m[1]+refs(m[2]),xml)
        return xml

    output = BytesIO()
    with ZipFile(BytesIO(workbook)) as source, ZipFile(output,'w') as target:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename == 'xl/worksheets/sheet1.xml':
                xml = re.sub(r'<row\b[^>]*\br="(\d+)"[^>]*?(?:/>|>.*?</row>)',row,content.decode(),flags=re.S)
                xml = re.sub(r'\b(ref|sqref)="([^\"]+)"',lambda m:m[1]+'="'+refs(m[2])+'"',xml)
                content = xml.encode()
            elif entry.filename == 'xl/workbook.xml':
                content = re.sub(r'(<definedName\b[^>]*>)(.*?)(</definedName>)',lambda m:m[1]+refs(m[2])+m[3],content.decode(),flags=re.S).encode()
            elif re.fullmatch(r'xl/drawings/drawing\d+\.xml',entry.filename):
                content = re.sub(r'(<(?:\w+:)?row>)(\d+)(</(?:\w+:)?row>)',lambda m:m[1]+str(int(m[2])-shift if int(m[2])>=84 else min(int(m[2]),total_row-2))+m[3],content.decode()).encode()
            target.writestr(entry,content)
    return output.getvalue()
