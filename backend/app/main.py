from pathlib import Path
import tkinter as tk
from tkinter import filedialog

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.services.processing_service import list_report_files, process_folder

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Техресурс")

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/")
async def processing_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="processing.html",
        context={},
    )


@app.get("/api/select-folder")
def select_folder():
    root = tk.Tk()
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        folder_path = filedialog.askdirectory(
            parent=root,
            title="Выберите папку с Word-отчётами",
        )
    finally:
        root.destroy()

    if not folder_path:
        return {"status": "cancelled", "path": None}
    return {"status": "ok", "path": folder_path}


@app.get("/api/check-folder")
async def check_folder(path: str):
    folder = Path(path)

    if not folder.exists():
        return JSONResponse(
            status_code=404,
            content={
                "status": "error",
                "message": "Папка не найдена",
                "count": 0,
            },
        )

    if not folder.is_dir():
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": "Указанный путь не является папкой",
                "count": 0,
            },
        )

    files = list_report_files(folder)
    return {
        "status": "ok",
        "message": "Папка найдена",
        "count": len(files),
        "files": [file.name for file in files],
    }


class ProcessFolderRequest(BaseModel):
    path: str = Field(min_length=1)


@app.post("/api/process-folder")
def process_reports(payload: ProcessFolderRequest):
    if not payload.path.strip():
        return JSONResponse(status_code=400, content={"status": "error", "message": "Укажите путь к папке"})
    try:
        return {"status": "ok", **process_folder(payload.path.strip())}
    except ValueError as error:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(error)})
    except Exception as error:
        return JSONResponse(status_code=500, content={
            "status": "error",
            "message": "Ошибка обработки отчётов",
            "details": str(error),
        })
