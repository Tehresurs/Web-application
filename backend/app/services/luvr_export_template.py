
"""Expand only the in-memory XLSX copy; keep MASTER and unrelated ZIP parts intact."""
from io import BytesIO
import re
from zipfile import ZipFile

def expand_employee_rows(workbook, total_row, employee_count):
    capacity=total_row-9
    if type(employee_count) is not int or employee_count<0:
        raise ValueError('Invalid employee row count')
    delta=employee_count-capacity
    if delta<=0:return workbook
    with ZipFile(BytesIO(workbook)) as original:
        source=original.read('xl/worksheets/sheet1.xml').decode('utf-8')
        row_pattern=r'<row\b[^>]*\br="(\d+)"[^>]*?(?:/>|>.*?</row>)'
        sample=next((m[0] for m in re.finditer(row_pattern,source,re.S) if int(m[1])==9),None)
        max_row=max((int(m[1]) for m in re.finditer(row_pattern,source,re.S)),default=0)
        if not sample or max_row+delta>1048576:raise ValueError('Template exceeds Excel row capacity')
        def cell_ref(m):
            col,row=m.groups();n=int(row);return col+str(n+delta if n>=total_row else n)
        def refs(text):
            # A body range ending immediately above the old total must grow too.
            ranges=r'(\$?[A-Z]{1,3}\$?)(\d+):(\$?[A-Z]{1,3}\$?)(\d+)'
            def interval(m):
                a,b=int(m[2]),int(m[4]);end=b+delta if b>=total_row or (b==total_row-1 and a<b) else b
                return m[1]+str(a+delta if a>=total_row else a)+':'+m[3]+str(end)
            return re.sub(ranges,interval,text) if re.fullmatch(ranges,text) else re.sub(r'(\$?[A-Z]{1,3}\$?)(\d+)',cell_ref,text)
        def formula(m):
            if m[0].endswith('/>'):return m[0]
            f=re.fullmatch(r'(<f\b[^>]*>)(.*?)(</f>)',m[0],re.S)
            # Formula ranges can be mixed into expressions.
            parts=re.split(r'((?:\$?[A-Z]{1,3}\$?\d+):(?:\$?[A-Z]{1,3}\$?\d+))',f[2])
            return f[1]+''.join(refs(p) for p in parts)+f[3]
        def clone(row_number):
            xml=re.sub(r'(<row\b[^>]*\br=")\d+',lambda m:m[1]+str(row_number),sample,count=1)
            def empty_cell(m):
                opening=m[0].split('>',1)[0].rstrip('/')
                opening=re.sub(r'\s+t="[^"]*"','',opening)
                opening=re.sub(r'(\br="[A-Z]+)\d+',lambda x:x[1]+str(row_number),opening)
                return opening+'/>'
            return re.sub(r'<c\b[^>]*?(?:/>|>.*?</c>)',empty_cell,xml,flags=re.S)
        inserted=''.join(clone(n) for n in range(total_row,total_row+delta))
        def row(m):
            n=int(m[1]);xml=re.sub(r'<f\b[^>]*?(?:/>|>.*?</f>)',formula,m[0],flags=re.S)
            if n>=total_row:
                xml=re.sub(r'(<row\b[^>]*\br=")\d+',lambda x:x[1]+str(n+delta),xml,count=1)
                xml=re.sub(r'(<c\b[^>]*\br=")([^\"]+)',lambda x:x[1]+refs(x[2]),xml)
            return (inserted if n==total_row else '')+xml
        source=re.sub(row_pattern,row,source,flags=re.S)
        source=re.sub(r'\b(ref|sqref)="([^\"]+)"',lambda m:m[1]+'="'+' '.join(refs(p) for p in m[2].split())+'"',source)
        def breaks(m):return re.sub(r'(\bid=")(\d+)',lambda x:x[1]+str(int(x[2])+delta if int(x[2])>=total_row else int(x[2])),m[0])
        source=re.sub(r'<rowBreaks\b.*?</rowBreaks>',breaks,source,flags=re.S)
        output=BytesIO()
        with ZipFile(output,'w') as target:
            for entry in original.infolist():
                content=original.read(entry.filename)
                if entry.filename=='xl/worksheets/sheet1.xml':content=source.encode('utf-8')
                elif entry.filename=='xl/workbook.xml':
                    content=re.sub(r'(<definedName\b[^>]*>)(.*?)(</definedName>)',lambda m:m[1]+refs(m[2])+m[3],content.decode(),flags=re.S).encode()
                elif re.fullmatch(r'xl/drawings/drawing\d+\.xml',entry.filename):
                    content=re.sub(r'(<(?:\w+:)?row>)(\d+)(</(?:\w+:)?row>)',lambda m:m[1]+str(int(m[2])+delta if int(m[2])>=total_row-1 else int(m[2]))+m[3],content.decode()).encode()
                target.writestr(entry,content)
    return output.getvalue()
