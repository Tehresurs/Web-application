"""Safe PDF fixtures: only the required text regions; no passports, QR or prices."""
from io import BytesIO
from pypdf import PdfWriter
from pypdf import PdfReader


def combine_pdfs(*documents):
    writer=PdfWriter()
    for data in documents:
        for page in PdfReader(BytesIO(data)).pages:writer.add_page(page)
    output=BytesIO();writer.write(output);return output.getvalue()
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject


def coupon_pdf(full_name="ИВАНОВ ИВАН ИВАНОВИЧ", departure_station="Тюмень", arrival_station="Салым",
               departure_datetime="10.09.2026 23:04",arrival_datetime="11.09.2026 07:29",header=True):
    parts=[]
    if header:parts.append((42,49,"ЭЛЕКТРОННЫЙ БИЛЕТ. КОНТРОЛЬНЫЙ КУПОН"))
    if full_name:
        words=full_name.split();parts.extend([(318,151," ".join(words[:2])),(318,168," ".join(words[2:]))])
    for y,label,station,stamp in [(135,"Отправление по",departure_station,departure_datetime),(237,"Прибытие по",arrival_station,arrival_datetime)]:
        parts.append((48,y+13,label))
        if station:parts.extend([(130,y+17,station[:1]),(141,y+17,station[1:])])
        if stamp:
            day,clock=stamp.split();parts.extend([(48,y,clock),(130,y,day)])
    return text_pdf(parts)


def text_pdf(parts):
    writer=PdfWriter();page=writer.add_blank_page(width=595,height=842)
    cmap=DecodedStreamObject()
    mapping=[]
    for n in range(256):
        char=bytes([n]).decode('cp1251',errors='replace')
        mapping.append(f'<{n:02X}> <{char.encode("utf-16-be").hex()}>')
    cmap.set_data(('begincmap\n1 begincodespacerange\n<00> <FF>\nendcodespacerange\n256 beginbfchar\n'+'\n'.join(mapping)+'\nendbfchar\nendcmap').encode())
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica'),NameObject('/ToUnicode'):writer._add_object(cmap)})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    content=DecodedStreamObject();chunks=[]
    for x,y,text in parts:
        for shift in (0,-.3):
            chunks.append(f'BT /F1 12 Tf 1 0 0 1 {x+shift} {842-y} Tm <{text.encode("cp1251").hex()}> Tj ET')
    content.set_data('\n'.join(chunks).encode());page[NameObject('/Contents')]=writer._add_object(content)
    out=BytesIO();writer.write(out);return out.getvalue()
