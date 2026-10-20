"""B1 only. Pure checks plus opt-in native Excel COM verification."""
import json
import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from app.services import vou_excel_com as com

def normalized(element):
    return (element.tag,tuple(sorted((k,v) for k,v in element.attrib.items() if k!="quotePrefix")),
            (element.text or "").strip(),tuple(normalized(child) for child in element))

class ValidationTests(unittest.TestCase):
    def test_shift_column_cannot_be_written(self):
        for operation in [{"type":"set_value","address":"AL14","value":1},
                          {"type":"set_formula","address":"AL14","formula":"=SUM(F14:AJ14)"}]:
            with self.assertRaises(ValueError):com.validate_operations([operation])

    def test_external_formulas_ranges_and_unknown_operations_rejected(self):
        for operation in [{"type":"set_formula","address":"AK15","formula":"=RUN()"},
                          {"type":"set_formula","address":"AK15","formula":"='[other.xlsm]Sheet1'!A1"},
                          {"type":"set_value","address":"A1:B2","value":1},
                          {"type":"macro","name":"Запуск_всех_шагов"}]:
            with self.assertRaises(ValueError):com.validate_operations([operation])

    def test_approved_master_unchanged(self):
        self.assertEqual(com.sha256(com.MASTER),com.EXPECTED_MASTER_SHA256)

    def test_output_cannot_escape_project(self):
        with self.assertRaises(ValueError):com.fill_copy(com.MASTER)

    def test_production_checks_approved_fingerprint(self):
        with patch.object(com,'sha256',return_value='changed'):
            with self.assertRaises(com.ExcelComError):com.fill_copy(com.OUTPUT/('blocked_'+uuid4().hex+'.xlsm'))

    def test_vba_stream_inventory(self):
        source=com.inventory(com.MASTER)
        self.assertEqual(len(source["vba_streams"]),116)
        self.assertEqual(len(source["controls"]),8)
        self.assertEqual(len(source["print_areas"]),4)

@unittest.skipUnless(os.getenv("VOU_COM_TEST")=="1","Opt-in native Windows Excel COM")
class NativeExcelTests(unittest.TestCase):
    def test_insert_fill_save_reopen_and_preservation(self):
        output=com.OUTPUT/("B1_technical_"+uuid4().hex+".xlsm")
        operations=[
            {"type":"insert_rows","before_row":61,"count":2,"prototype_row":60},
            {"type":"set_value","address":"C61","value":"Тест Б1 — объект"},
            {"type":"set_value","address":"D61","value":"Проверка механизма COM, не фактический отчёт"},
            {"type":"set_value","address":"E61","value":"Тестовый сотрудник Б1"},
            {"type":"set_value","address":"F61","value":0.5},
            {"type":"set_formula","address":"AK61","formula":"=SUM(F61:AJ61)"},
            {"type":"set_value","address":"C62","value":"=Это текст, а не формула"},
            {"type":"set_value","address":"F62","value":0.25},
            {"type":"set_formula","address":"AK62","formula":"=SUM(F62:AJ62)"}]
        result=com.fill_copy(output,operations,readback=["C61","C62","AK61","AK62","AK14","AK274","AL61","AL62"],
                             calculate_personnel=True,timeout=60,technical_only=True,control_pdf=output.with_suffix(".pdf"))
        # Validate the actual native Excel PDF, not just a successful COM return.
        from pypdf import PdfReader
        pages=PdfReader(result["pdf_path"]).pages
        self.assertEqual(len(pages),8)
        texts=[page.extract_text() for page in pages]
        self.assertTrue(all(text.strip() for text in texts))
        whole=" ".join(" ".join(texts).split())
        for title in ["Инженерная подготовка", "Трубопроводы", "Обустройство кустовых площадок",
                      "Объекты энергетики", "Площадочные объекты", "Прочее", "ИТОГО",
                      "Представитель по доверенности", "Генеральный директор", "Мясников"]:
            self.assertIn(title,whole)
        self.assertIn("1087,25",whole)
        for page in pages:
            self.assertAlmostEqual(float(page.mediabox.width),841.9,delta=1)
            self.assertAlmostEqual(float(page.mediabox.height),595.3,delta=1)
        self.assertIn("Microsoft Print to PDF",result["fresh_excel"]["pdf_setup"]["active_printer"])
        before=com.inventory(com.MASTER);after=result["inventory"];excel=result["com"]
        self.assertEqual(result["fresh_excel"]["print_area"],"$A$1:$AL$285")
        self.assertTrue(result["fresh_excel"]["excel_process_exited"])
        self.assertTrue(result["printer_profile_restoration"]["other_parts_byte_identical"])
        self.assertTrue(result["preservation_accepted"])
        self.assertTrue(excel["reopened"]);self.assertTrue(excel["excel_process_exited"])
        self.assertFalse(excel["events_enabled"])
        self.assertEqual(excel["macros_security"],3)
        self.assertEqual(before["vba_streams"],after["vba_streams"])
        self.assertEqual(set(before["parts"]),set(after["parts"]))
        self.assertEqual(before["controls"],after["controls"])
        self.assertEqual(before["drawings"],after["drawings"])
        read=excel["readback"]
        self.assertEqual(read["AK61"]["value"],0.5);self.assertEqual(read["AK62"]["value"],0.25)
        self.assertEqual(read["AK14"]["formula"],"=SUM(AK15:AK63)")
        self.assertAlmostEqual(read["AK14"]["value"],153.92,places=6)
        self.assertAlmostEqual(read["AK274"]["value"],1087.25,places=6)
        self.assertIsNone(read["AL61"]["value"]);self.assertIsNone(read["AL62"]["value"])
        self.assertEqual(read["C62"]["value"],"=Это текст, а не формула")
        self.assertIn("AE285:AK285",after["sheets"]["Персонал"]["merges"])
        self.assertIn("Персонал!$A$1:$AL$285",after["print_areas"])
        with ZipFile(com.MASTER) as a,ZipFile(output) as b:
            styles_a=[normalized(e) for e in ET.fromstring(a.read("xl/styles.xml")).find("m:cellXfs",com.NS)]
            styles_b=[normalized(e) for e in ET.fromstring(b.read("xl/styles.xml")).find("m:cellXfs",com.NS)]
            for name in before["sheets"]:
                source=ET.fromstring(a.read(before["sheets"][name]["path"]))
                target=ET.fromstring(b.read(after["sheets"][name]["path"]))
                cells={c.get("r"):c for c in target.findall(".//m:c",com.NS)}
                for cell in source.findall(".//m:c",com.NS):
                    address=cell.get("r");match=re.fullmatch(r"([A-Z]+)([0-9]+)",address)
                    row=int(match[2])
                    shifted=match[1]+str(row+2) if name=="Персонал" and row>=61 else address
                    self.assertIn(shifted,cells)
                    self.assertEqual(styles_a[int(cell.get("s","0"))],
                                     styles_b[int(cells[shifted].get("s","0"))],(name,address))
            source=ET.fromstring(a.read("xl/worksheets/sheet1.xml"))
            target=ET.fromstring(b.read("xl/worksheets/sheet1.xml"))
            for name in before["sheets"]:
                sa=ET.fromstring(a.read(before["sheets"][name]["path"]))
                sb=ET.fromstring(b.read(after["sheets"][name]["path"]))
                for tag in ["pageMargins","pageSetup"]:
                    x,y=sa.find("m:"+tag,com.NS),sb.find("m:"+tag,com.NS)
                    self.assertEqual(normalized(x) if x is not None else None,normalized(y) if y is not None else None)
                if name!="Персонал":
                    self.assertEqual({k:(v['text'],{a:b for a,b in v['attributes'].items() if a!='ca'}) for k,v in before['sheets'][name]['formulas'].items()},
                                     {k:(v['text'],{a:b for a,b in v['attributes'].items() if a!='ca'}) for k,v in after['sheets'][name]['formulas'].items()})
                    self.assertEqual(set(before["sheets"][name]["merges"]),set(after["sheets"][name]["merges"]))
            for path in before["drawings"]+before["controls"]:
                self.assertEqual(normalized(ET.fromstring(a.read(path))),normalized(ET.fromstring(b.read(path))))
            original_cells={c.get("r"):c for c in source.findall(".//m:c",com.NS)}
            new_cells={c.get("r"):c for c in target.findall(".//m:c",com.NS)}
            for column in ["B","C","D","E","F","AJ","AK","AL"]:
                self.assertEqual(styles_a[int(original_cells[column+"60"].get("s","0"))],
                                 styles_b[int(new_cells[column+"61"].get("s","0"))])
            for cell in target.findall(".//m:c",com.NS):
                if cell.get("r").startswith("AL") and int(cell.get("r")[2:])>=14:
                    self.assertIsNone(cell.find("m:v",com.NS));self.assertIsNone(cell.find("m:f",com.NS))
            # Print profile device, orientation, paper, quality, colour and duplex.
            import struct
            for part in [n for n in before["parts"] if n.startswith("xl/printerSettings/")]:
                old,new=a.read(part),b.read(part)
                self.assertEqual(old,new,part)
                self.assertEqual(old[:64],new[:64],part)
                for offset in [76,78,80,82,86,90,92,94,96,98,100]:
                    self.assertEqual(struct.unpack_from("<h",old,offset),struct.unpack_from("<h",new,offset),(part,offset))
        self.assertEqual(com.sha256(com.MASTER),com.EXPECTED_MASTER_SHA256)
        with self.assertRaises(FileExistsError):com.fill_copy(output)
        summary=dict(path=str(output),pdf_path=result["pdf_path"],fresh_excel=result["fresh_excel"],printer_profile_restoration=result["printer_profile_restoration"],com=excel,master_sha256=com.sha256(com.MASTER),
                     vba_streams_preserved=len(after["vba_streams"]),
                     native_print_area_verified=bool(excel["print_area"]),
                     note="B1 technical verification only; no matrix facts were exported.")
        output.with_suffix(".json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
        print("B1_ARTIFACT="+str(output),flush=True)

    def test_excel_closes_on_error_and_no_file_published(self):
        output=com.OUTPUT/("B1_error_"+uuid4().hex+".xlsm")
        profiles={name:"B1 missing printer "+uuid4().hex for name in com.master_print_areas()}
        with patch.object(com,"master_print_profiles",return_value=profiles):
            with self.assertRaises(com.ExcelComError) as error:com.fill_copy(output,timeout=60,technical_only=True)
        self.assertIn("missing or ambiguous",str(error.exception))
        self.assertFalse(output.exists())
        self.assertEqual(com.sha256(com.MASTER),com.EXPECTED_MASTER_SHA256)
