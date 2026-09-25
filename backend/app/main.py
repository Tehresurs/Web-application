from pathlib import Path
import tkinter as tk
from tkinter import filedialog

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.services.processing_service import list_report_files, process_folder
from app.repositories.assignments import (
    get_employee_assignments,
    create_employee_assignment,
    update_employee_assignment,
    delete_employee_assignment,
)
from app.repositories.employees import (
    get_crews,
    create_crew,
    update_crew,
    delete_crew,
    get_positions,
    get_employees,
    create_employee,
    update_employee,
    delete_employee,
    create_position,
    rename_position,
    delete_position,
)
from app.repositories.objects import (
    get_objects,
    create_object,
    update_object,
    delete_object,
    get_object_categories,
    get_po_types,
    create_subcategory,
    rename_subcategory,
    delete_subcategory,
    create_po_type,
    rename_po_type,
    delete_po_type,
)

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
    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        folder_path = filedialog.askdirectory(
            parent=root,
            title="Выберите папку с Word-отчётами",
        )
    except tk.TclError:
        return JSONResponse(status_code=503, content={
            "status": "error",
            "message": "Не удалось открыть выбор папки. Введите путь вручную в поле папки.",
        })
    finally:
        if root is not None:
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


class CreateObjectRequest(BaseModel):
    name: str = Field(min_length=1)


class CreateSubcategoryRequest(BaseModel):
    name: str = Field(min_length=1)


class RenameSubcategoryRequest(BaseModel):
    name: str = Field(min_length=1)


class PoTypeRequest(BaseModel):
    name: str = Field(min_length=1)


class CrewRequest(BaseModel):
    driver_full_name: str = Field(min_length=1)
    driver_phone: str | None = None
    vehicle_make: str | None = None
    vehicle_plate: str | None = None


class EmployeeRequest(BaseModel):
    full_name: str = Field(min_length=1)
    position_id: int | None = None
    phone: str | None = None
    crew_id: int | None = None


class EmployeeAssignmentRequest(BaseModel):
    object_id: int
    po_id: int
    category_id: int




class PositionRequest(BaseModel):
    name: str = Field(min_length=1)
    action_description: str | None = None


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


@app.get("/api/object-categories")
def object_categories():
    return {
        "status": "ok",
        "items": get_object_categories(),
    }


@app.get("/api/po-types")
def po_types():
    return {
        "status": "ok",
        "items": get_po_types(),
    }


@app.get("/api/objects")
def objects():
    return {
        "status": "ok",
        "items": get_objects(),
    }


@app.post("/api/objects")
def add_object(payload: CreateObjectRequest):
    try:
        new_object = create_object(
            name=payload.name,
        )
        return {
            "status": "ok",
            "object": new_object,
        }
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": str(error),
            },
        )
    except Exception as error:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": "Не удалось добавить объект",
                "details": str(error),
            },
        )


@app.patch("/api/objects/{object_id}")
def edit_object(object_id: int, payload: CreateObjectRequest):
    try:
        item = update_object(object_id=object_id, name=payload.name)
        return {"status": "ok", "object": item}
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": str(error)},
        )


@app.delete("/api/objects/{object_id}")
def remove_object(object_id: int):
    try:
        return {
            "status": "ok",
            **delete_object(object_id),
        }
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": str(error)},
        )


@app.post("/api/object-categories/{parent_id}/children")
def add_object_subcategory(
    parent_id: int,
    payload: CreateSubcategoryRequest,
):
    try:
        item = create_subcategory(
            parent_id=parent_id,
            name=payload.name,
        )

        return {
            "status": "ok",
            "item": item,
        }

    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": str(error),
            },
        )


@app.patch("/api/object-categories/{category_id}")
def update_object_subcategory(
    category_id: int,
    payload: RenameSubcategoryRequest,
):
    try:
        item = rename_subcategory(
            category_id=category_id,
            name=payload.name,
        )

        return {
            "status": "ok",
            "item": item,
        }

    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": str(error),
            },
        )


@app.delete("/api/object-categories/{category_id}")
def remove_object_subcategory(category_id: int):
    try:
        result = delete_subcategory(category_id)

        return {
            "status": "ok",
            **result,
        }

    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": str(error),
            },
        )


@app.post("/api/po-types")
def add_po_type(payload: PoTypeRequest):
    try:
        item = create_po_type(payload.name)

        return {
            "status": "ok",
            "item": item,
        }

    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": str(error),
            },
        )


@app.patch("/api/po-types/{po_id}")
def update_po_type(
    po_id: int,
    payload: PoTypeRequest,
):
    try:
        item = rename_po_type(
            po_id=po_id,
            name=payload.name,
        )

        return {
            "status": "ok",
            "item": item,
        }

    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": str(error),
            },
        )


@app.delete("/api/po-types/{po_id}")
def remove_po_type(po_id: int):
    try:
        result = delete_po_type(po_id)

        return {
            "status": "ok",
            **result,
        }

    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": str(error),
            },
        )


@app.get("/api/positions")
def positions():
    return {
        "status": "ok",
        "items": get_positions(),
    }


@app.post("/api/positions")
def add_position(payload: PositionRequest):
    try:
        item = create_position(
            name=payload.name,
            action_description=payload.action_description,
        )

        return {
            "status": "ok",
            "item": item,
        }

    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": str(error),
            },
        )


@app.patch("/api/positions/{position_id}")
def update_position(
    position_id: int,
    payload: PositionRequest,
):
    try:
        item = rename_position(
            position_id=position_id,
            name=payload.name,
            action_description=payload.action_description,
        )

        return {
            "status": "ok",
            "item": item,
        }

    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": str(error),
            },
        )


@app.delete("/api/positions/{position_id}")
def remove_position(position_id: int):
    try:
        result = delete_position(position_id)

        return {
            "status": "ok",
            **result,
        }

    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": str(error),
            },
        )


@app.get("/api/employees")
def employees():
    return {
        "status": "ok",
        "items": get_employees(),
    }


@app.post("/api/employees")
def add_employee(payload: EmployeeRequest):
    try:
        employee_id = create_employee(
            full_name=payload.full_name,
            position_id=payload.position_id,
            phone=payload.phone,
            crew_id=payload.crew_id,
        )

        return {
            "status": "ok",
            "id": employee_id,
        }

    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": str(error),
            },
        )


@app.patch("/api/employees/{employee_id}")
def edit_employee(
    employee_id: int,
    payload: EmployeeRequest,
):
    try:
        update_employee(
            employee_id=employee_id,
            full_name=payload.full_name,
            position_id=payload.position_id,
            phone=payload.phone,
            crew_id=payload.crew_id,
        )

        return {
            "status": "ok",
            "id": employee_id,
        }

    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": str(error),
            },
        )


@app.delete("/api/employees/{employee_id}")
def remove_employee(employee_id: int):
    try:
        return {
            "status": "ok",
            **delete_employee(employee_id),
        }

    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": str(error),
            },
        )


@app.get("/api/employees/{employee_id}/assignments")
def employee_assignments(employee_id: int):
    try:
        result = get_employee_assignments(employee_id)
        return {
            "status": "ok",
            **result,
        }
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": str(error)},
        )


@app.post("/api/employees/{employee_id}/assignments")
def add_employee_assignment(
    employee_id: int,
    payload: EmployeeAssignmentRequest,
):
    try:
        item = create_employee_assignment(
            employee_id=employee_id,
            object_id=payload.object_id,
            po_id=payload.po_id,
            category_id=payload.category_id,
        )
        return {
            "status": "ok",
            "item": item,
        }
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": str(error)},
        )


@app.patch("/api/employees/{employee_id}/assignments/{assignment_id}")
def edit_employee_assignment(
    employee_id: int,
    assignment_id: int,
    payload: EmployeeAssignmentRequest,
):
    try:
        item = update_employee_assignment(
            employee_id=employee_id,
            assignment_id=assignment_id,
            object_id=payload.object_id,
            po_id=payload.po_id,
            category_id=payload.category_id,
        )
        return {
            "status": "ok",
            "item": item,
        }
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": str(error)},
        )


@app.delete("/api/employees/{employee_id}/assignments/{assignment_id}")
def remove_employee_assignment(
    employee_id: int,
    assignment_id: int,
):
    try:
        return {
            "status": "ok",
            **delete_employee_assignment(employee_id, assignment_id),
        }
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": str(error)},
        )


@app.get("/api/crews")
def crews():
    return {
        "status": "ok",
        "items": get_crews(),
    }


@app.post("/api/crews")
def add_crew(payload: CrewRequest):
    try:
        crew_id = create_crew(
            driver_full_name=payload.driver_full_name,
            driver_phone=payload.driver_phone,
            vehicle_make=payload.vehicle_make,
            vehicle_plate=payload.vehicle_plate,
        )

        return {
            "status": "ok",
            "id": crew_id,
        }

    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": str(error),
            },
        )


@app.patch("/api/crews/{crew_id}")
def edit_crew(
    crew_id: int,
    payload: CrewRequest,
):
    try:
        update_crew(
            crew_id=crew_id,
            driver_full_name=payload.driver_full_name,
            driver_phone=payload.driver_phone,
            vehicle_make=payload.vehicle_make,
            vehicle_plate=payload.vehicle_plate,
        )

        return {
            "status": "ok",
            "id": crew_id,
        }

    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": str(error),
            },
        )


@app.delete("/api/crews/{crew_id}")
def remove_crew(crew_id: int):
    try:
        return {
            "status": "ok",
            **delete_crew(crew_id),
        }

    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": str(error),
            },
        )
