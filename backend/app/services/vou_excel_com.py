"""B1: isolated native Excel COM primitives, not a VOU report generator.

PowerShell supplies Windows COM without adding packages to the shared Python venv.
Only copies below backend/output/vou are opened; the master is never opened in Excel.
"""
from __future__ import annotations
from copy import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from zipfile import ZipFile

BACKEND = Path(__file__).resolve().parents[2]
MASTER = BACKEND / "templates/vou/АОС №8.26 от 31.08.2026 к договору MOS-25-0008.rev.2..xlsm"
OUTPUT = BACKEND / "output/vou"
SCRIPT = Path(__file__).with_suffix(".ps1")
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/package/2006/relationships"}
EXPECTED_MASTER_SHA256 = "a6d223353bf2f07b4cd5de0cb972827dbd40cf2efef3a174a501941c9b726e60"

class ExcelComError(RuntimeError):
    pass

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def validate_operations(operations: list[dict]) -> list[dict]:
    result=[]
    for op in operations:
        kind=op.get("type")
        if kind in ("set_value","set_formula"):
            allowed={"type","address","value"} if kind=="set_value" else {"type","address","formula"}
            if set(op)!=allowed:raise ValueError("Invalid cell operation")
            match=re.fullmatch(r"([A-Z]{1,2})([1-9][0-9]*)",str(op["address"]))
            if not match:raise ValueError("Use one explicit cell address")
            col,row=match[1],int(match[2])
            number=0
            for letter in col:number=number*26+ord(letter)-64
            if number<2 or number>38 or row>100000:raise ValueError("Cell outside personnel layout")
            if col=="AL" and row>=14:raise ValueError("AL shift values and formulas are forbidden")
            if kind=="set_formula":
                # B1 needs row totals only. Never evaluate user-supplied/VBA/external formulas.
                formula = op["formula"]
                row_sum = col == "AK" and re.fullmatch(r"=SUM\(F([1-9][0-9]*):AJ\1\)", formula)
                vertical = re.fullmatch(r"=SUM\("+col+r"[1-9][0-9]*:"+col+r"[1-9][0-9]*\)", formula)
                refs = re.fullmatch(r"=SUM\("+col+r"[1-9][0-9]*(?:,"+col+r"[1-9][0-9]*)*\)", formula)
                if number < 6 or number > 37 or not (row_sum or vertical or refs):
                    raise ValueError("Only native personnel row SUM formulas are allowed")
            elif not (op["value"] is None or type(op["value"]) in (str,int,float)):
                raise ValueError("Invalid literal cell value")
        elif kind=="insert_rows":
            if set(op)!={"type","before_row","count","prototype_row"}:raise ValueError("Invalid row operation")
            if not all(type(op[key]) is int for key in ("before_row","count","prototype_row")):
                raise ValueError("Row arguments must be integers")
            if not 15<=op["before_row"]<=100000 or not 15<=op["prototype_row"]<=100000 or not 1<=op["count"]<=10000:
                raise ValueError("Invalid row bounds")
        elif kind in ("delete_rows", "copy_row_format", "autofit_rows", "print_end", "clear_range", "set_block", "fit_signatures", "fit_header"):
            from app.services.vou_layout import validate_layout_operation
            validate_layout_operation(op)
        else:raise ValueError("Unsupported operation")
        result.append(dict(op))
    return result


def vba_stream_digests(blob: bytes) -> dict[str,str]:
    """Compare all logical OLE streams; Excel may reorder container sectors on save."""
    import struct
    if blob[:8]!=bytes.fromhex("D0CF11E0A1B11AE1"):raise ExcelComError("Invalid VBA OLE container")
    size=1<<struct.unpack_from("<H",blob,30)[0]
    mini_size=1<<struct.unpack_from("<H",blob,32)[0]
    if struct.unpack_from("<I",blob,72)[0]:
        raise ExcelComError("Extended OLE DIFAT requires a separate preservation audit")
    def sector(i):return blob[(i+1)*size:(i+2)*size]
    fat=[]
    for i in struct.unpack_from("<109I",blob,76):
        if i<0xfffffffa:fat.extend(struct.unpack("<"+"I"*(size//4),sector(i)))
    def chain(i,table):
        seen=set()
        while i<0xfffffffa:
            if i in seen or i>=len(table):raise ExcelComError("Invalid VBA allocation chain")
            seen.add(i);yield i;i=table[i]
    def big(i,n):return b"".join(sector(j) for j in chain(i,fat))[:n]
    raw=big(struct.unpack_from("<I",blob,48)[0],len(blob))
    entries=[]
    for i in range(0,len(raw),128):
        entry=raw[i:i+128]
        length=struct.unpack_from("<H",entry,64)[0]
        if length>=2:
            entries.append((entry[:length-2].decode("utf-16le"),entry[66],
                            struct.unpack_from("<I",entry,116)[0],struct.unpack_from("<Q",entry,120)[0]))
    root=next(e for e in entries if e[1]==5)
    mini=big(root[2],root[3])
    raw=big(struct.unpack_from("<I",blob,60)[0],struct.unpack_from("<I",blob,64)[0]*size)
    mini_fat=struct.unpack("<"+"I"*(len(raw)//4),raw)
    result={}
    for name,kind,start,length in entries:
        if kind!=2:continue
        if name in result:raise ExcelComError("Ambiguous VBA stream names")
        value=big(start,length) if length>=4096 else b"".join(
            mini[j*mini_size:(j+1)*mini_size] for j in chain(start,mini_fat))[:length]
        result[name]=hashlib.sha256(value).hexdigest()
    return result

def print_areas(path: Path) -> dict[str,str]:
    with ZipFile(path) as book:
        xml=ET.fromstring(book.read("xl/workbook.xml"))
        names=[s.get("name") for s in xml.findall("m:sheets/m:sheet",NS)]
        return {names[int(n.get("localSheetId"))]:n.text.rsplit("!",1)[1]
                for n in xml.findall("m:definedNames/m:definedName",NS)
                if n.get("name")=="_xlnm.Print_Area"}


def master_print_areas() -> dict[str,str]:
    areas=print_areas(MASTER)
    # The approved signature block ends at row 283. Native Excel row insertion
    # moves this named boundary along with the signature cells.
    areas["Персонал"]="$A$1:$AL$283"
    return areas


def restore_print_profiles(path: Path) -> dict:
    """Restore ONLY whole original DEVMODE parts after native Excel has closed.

    No isolated field patching; every other uncompressed package member must
    remain byte-identical to the native Excel result. The next COM open is
    read-only and must never save over these restored printer settings.
    """
    scratch=path.with_suffix(".profiles.xlsm")
    with ZipFile(MASTER) as master, ZipFile(path) as native:
        parts=[n for n in master.namelist() if n.startswith("xl/printerSettings/") and n.endswith(".bin")]
        if len(parts)!=4 or set(parts)!={n for n in native.namelist() if n.startswith("xl/printerSettings/") and n.endswith(".bin")}:
            raise ExcelComError("Unexpected printer-profile package layout")
        if len(native.namelist())!=len(set(native.namelist())):raise ExcelComError("Duplicate package members")
        changed=[n for n in parts if native.read(n)!=master.read(n)]
        with ZipFile(scratch,"w") as repaired:
            repaired.comment=native.comment
            for member in native.infolist():
                repaired.writestr(copy(member),master.read(member.filename) if member.filename in parts else native.read(member.filename))
        with ZipFile(scratch) as repaired:
            for name in native.namelist():
                expected=master.read(name) if name in parts else native.read(name)
                if repaired.read(name)!=expected:raise ExcelComError("Unsafe printer-profile restoration")
    scratch.replace(path)
    return {"restored_parts":parts,"normalized_by_excel":changed,"other_parts_byte_identical":True}


def inventory(path: Path) -> dict:
    """Inspect OOXML only; never rewrite the package with a spreadsheet library."""
    with ZipFile(path) as z:
        workbook=ET.fromstring(z.read("xl/workbook.xml"))
        rels=ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets={r.get("Id"):r.get("Target") for r in rels}
        sheets={}
        for entry in workbook.findall("m:sheets/m:sheet",NS):
            rid=entry.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target=targets[rid].lstrip("/")
            if not target.startswith("xl/"):target="xl/"+target
            sheet=ET.fromstring(z.read(target))
            formulas={c.get("r"):{"text":c.find("m:f",NS).text,"attributes":dict(c.find("m:f",NS).attrib)}
                      for c in sheet.findall(".//m:c",NS) if c.find("m:f",NS) is not None}
            sheets[entry.get("name")]=dict(
                state=entry.get("state","visible"),path=target,
                merges=[m.get("ref") for m in sheet.findall("m:mergeCells/m:mergeCell",NS)],
                formulas=formulas,
                conditional_formatting=[ET.tostring(c,encoding="unicode") for c in sheet.findall("m:conditionalFormatting",NS)],
                page_setup=ET.tostring(sheet.find("m:pageSetup",NS),encoding="unicode") if sheet.find("m:pageSetup",NS) is not None else None)
        parts=z.namelist()
        return dict(sha256=sha256(path),sheets=sheets,
                    vba_sha256=hashlib.sha256(z.read("xl/vbaProject.bin")).hexdigest(),
                    vba_streams=vba_stream_digests(z.read("xl/vbaProject.bin")),
                    parts=parts,
                    binary_parts={p:hashlib.sha256(z.read(p)).hexdigest() for p in parts if p.endswith((".bin",".vml"))},
                    drawings=[p for p in parts if p.startswith("xl/drawings/")],
                    controls=[p for p in parts if p.startswith("xl/ctrlProps/")],
                    print_areas=[n.text for n in workbook.findall("m:definedNames/m:definedName",NS) if n.get("name")=="_xlnm.Print_Area"])


def master_print_profiles() -> dict[str,str]:
    import posixpath
    source=inventory(MASTER)
    result={}
    with ZipFile(MASTER) as book:
        for name in master_print_areas():
            path=source["sheets"][name]["path"]
            sheet=ET.fromstring(book.read(path))
            setup=sheet.find("m:pageSetup",NS)
            rid=setup.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            relation_path=posixpath.join(posixpath.dirname(path),"_rels",posixpath.basename(path)+".rels")
            relations=ET.fromstring(book.read(relation_path))
            target=next(r.get("Target") for r in relations if r.get("Id")==rid)
            printer_path=posixpath.normpath(posixpath.join(posixpath.dirname(path),target))
            result[name]=book.read(printer_path)[:64].decode("utf-16le").split(chr(0),1)[0]
    return result


def _cleanup_lease(lease: Path) -> None:
    """Timeout fallback: terminate only the recorded new Excel PID/start-time pair."""
    if not lease.exists():return
    data=json.loads(lease.read_text(encoding="utf-8-sig"))
    pid,ticks=int(data["process_id"]),int(data["start_ticks"])
    command=("$p=Get-Process -Id "+str(pid)+" -ErrorAction SilentlyContinue;"
             "if($p -and $p.ProcessName -eq 'EXCEL' -and "
             "$p.StartTime.ToUniversalTime().Ticks -eq "+str(ticks)+"){Stop-Process -Id "+str(pid)+" -Force}")
    subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-WindowStyle","Hidden","-Command",command],
                   timeout=15,capture_output=True)

def fill_copy(destination: Path, operations: list[dict] | None=None, *,
              readback: list[str] | None=None, calculate_personnel=False, timeout=120, technical_only=False, control_pdf: Path | None=None,
              readback_ranges: list[str] | None=None) -> dict:
    """Fill a new uniquely named XLSM copy; publish only after save and reopen succeed."""
    if os.name!="nt":raise ExcelComError("Microsoft Excel COM requires Windows")
    destination=Path(destination).resolve()
    output=OUTPUT.resolve()
    if not destination.is_relative_to(output) or destination.suffix.lower()!=".xlsm":
        raise ValueError("Output must be an XLSM file under backend/output/vou")
    if destination.exists():raise FileExistsError("Existing reports must never be overwritten")
    # B1 preservation was accepted; production uses the same isolated worker.
    pdf=Path(control_pdf).resolve() if control_pdf is not None else None
    if pdf is not None:
        if not pdf.is_relative_to(output) or pdf.suffix.lower()!=".pdf":raise ValueError("PDF must be under backend/output/vou")
        if pdf.exists():raise FileExistsError("Existing PDFs must never be overwritten")
    ops=validate_operations(operations or [])
    addresses=readback or []
    if any(not re.fullmatch(r"[A-Z]{1,2}[1-9][0-9]*",a) for a in addresses):
        raise ValueError("Invalid readback address")
    blocks=readback_ranges or []
    for block in blocks:
        from app.services.vou_layout import validate_readback_range
        validate_readback_range(block)
    if not MASTER.is_file():raise ExcelComError("Approved VOU template is missing")
    before=sha256(MASTER)
    if before!=EXPECTED_MASTER_SHA256:raise ExcelComError("Approved master fingerprint changed")
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vou-com-",dir=destination.parent) as folder:
        temp=Path(folder).resolve()
        assert temp.is_relative_to(output)
        working=temp/"working.xlsm"
        shutil.copyfile(MASTER,working)
        request=temp/"request.json";result_path=temp/"result.json";lease=temp/"excel.json"
        request.write_text(json.dumps(dict(workbook_path=str(working),operations=ops,
                           readback=addresses,readback_ranges=blocks,calculate_personnel=bool(calculate_personnel),print_areas=master_print_areas(),print_profiles=master_print_profiles(),
                           result_path=str(result_path),lease_path=str(lease)),ensure_ascii=False),encoding="utf-8")
        try:
            process=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-WindowStyle","Hidden","-STA",
                                    "-File",str(SCRIPT),"-RequestPath",str(request)],
                                   timeout=timeout,capture_output=True)
            result=json.loads(result_path.read_text(encoding="utf-8-sig")) if result_path.exists() else {}
            if process.returncode or not result.get("ok"):
                message=result.get("error") or process.stderr.decode("utf-8",errors="replace")[:1500]
                raise ExcelComError("Excel COM failed: "+message+"; stage="+str(result.get("stage"))+"; printer="+str(result.get("active_printer_before")))
            if not result.get("excel_process_exited"):raise ExcelComError("Excel did not exit cleanly")
            if sha256(MASTER)!=before:raise ExcelComError("Master changed during generation")
            repair=restore_print_profiles(working)
            verification_pdf=temp/"control.pdf" if pdf is not None else None
            verification=dict(workbook_path=str(working),verify_only=True,operations=[],
                readback=addresses,readback_ranges=blocks,print_areas=print_areas(working),print_profiles=master_print_profiles(),
                result_path=str(result_path),lease_path=str(lease))
            if verification_pdf is not None:verification["pdf_path"]=str(verification_pdf)
            request.write_text(json.dumps(verification,ensure_ascii=False),encoding="utf-8")
            saved_hash=sha256(working)
            process=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-WindowStyle","Hidden","-STA",
                                    "-File",str(SCRIPT),"-RequestPath",str(request)],timeout=timeout,capture_output=True)
            verified=json.loads(result_path.read_text(encoding="utf-8-sig"))
            if process.returncode or not verified.get("ok") or not verified.get("excel_process_exited"):
                raise ExcelComError("Fresh Excel verification failed: "+str(verified.get("error")))
            if sha256(working)!=saved_hash:raise ExcelComError("Read-only verification modified the output")
            info=inventory(working)
            if info["vba_streams"]!=inventory(MASTER)["vba_streams"]:
                raise ExcelComError("VBA project changed; output has not been published")
            if sha256(MASTER)!=before:raise ExcelComError("Master changed during verification")
            working.rename(destination)
            if pdf is not None:
                verification_pdf.rename(pdf)
                verified["pdf_path"]=str(pdf)
            return dict(path=str(destination),pdf_path=str(pdf) if pdf else None,com=result,
                        fresh_excel=verified,printer_profile_restoration=repair,inventory=info,master_unchanged=True,
                        technical_only=bool(technical_only),preservation_accepted=True,
                        limitations=["COM locale workaround reapplies saved print areas in memory on each open",
                                     "Whole original printer profiles restored after native Excel save; verification is read-only",
                                     "Control PDF requires installed Microsoft Print to PDF; Adobe PDF produces an incorrect media size on this machine"])
        except subprocess.TimeoutExpired as exc:
            stage=json.loads(result_path.read_text(encoding='utf-8-sig')).get('stage') if result_path.exists() else 'startup'
            raise ExcelComError('Excel COM timed out at '+str(stage)+'; the owned instance was stopped') from exc
        finally:
            _cleanup_lease(lease)
