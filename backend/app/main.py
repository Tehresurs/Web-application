from datetime import date, datetime
from typing import Literal
from pathlib import Path
import os
import tkinter as tk
from tkinter import filedialog

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, StrictBool, model_validator
from app.api.daily_control import router as daily_control_router
from app.api.known_values import router as known_values_router
from app.api.luvr_history import router as luvr_history_router
from app.api.rail_tickets import router as rail_tickets_router
from app.api.luvr_calendar import router as luvr_calendar_router
from app.api.luvr_month import router as luvr_month_router
from app.api.employee_absences import router as employee_absences_router
from app.api.production_assignments import router as production_assignments_router
from app.api.production_matrix_overrides import router as production_matrix_overrides_router
from app.api.production_matrix import router as production_matrix_router
from app.api.deployment import router as deployment_router
from app.api.crew_memberships import router as crew_memberships_router
from app.api.object_archive import router as object_archive_router
from app.api.construction_identity import router as construction_identity_router

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
    set_employee_archived,
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
from app.api.user_auth import router as user_auth_router
app.include_router(user_auth_router)
from app.api.personnel_transfers import router as personnel_transfers_router
app.include_router(personnel_transfers_router)
app.include_router(daily_control_router)
app.include_router(known_values_router)
app.include_router(luvr_history_router)
app.include_router(rail_tickets_router)
app.include_router(luvr_calendar_router)
app.include_router(luvr_month_router)
app.include_router(employee_absences_router)
app.include_router(production_assignments_router)
app.include_router(production_matrix_overrides_router)
app.include_router(production_matrix_router)
from app.api.matrix_dk import router as matrix_dk_router
app.include_router(matrix_dk_router)
app.include_router(deployment_router)
app.include_router(crew_memberships_router)
app.include_router(object_archive_router)
app.include_router(construction_identity_router)
from app.api.vou_settings import router as vou_settings_router
app.include_router(vou_settings_router)
from app.api.vou_archive import router as vou_archive_router
app.include_router(vou_archive_router)
from app.api.clean_construction import router as clean_construction_router
app.include_router(clean_construction_router)

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
        context={"test_mode": os.getenv("APP_DB_PROFILE") == "test"},
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
    default_category_id: int | None = Field(default=None,gt=0)


class CrewRequest(BaseModel):
    driver_full_name: str = Field(min_length=1)
    driver_phone: str | None = None
    vehicle_make: str | None = None
    vehicle_plate: str | None = None


class EmployeeRequest(BaseModel):
    email: str | None = Field(default=None, max_length=254)
    full_name: str = Field(min_length=1)
    position_id: int | None = None
    phone: str | None = None
    crew_id: int | None = None
    dismissal_date: date | None = None
    nrs_number: str | None = None
    max_shift_days: int | None = Field(default=None, strict=True, gt=0, le=2147483647)
    max_off_shift_days: int | None = Field(default=None, strict=True, gt=0, le=2147483647)


class EmployeeAssignmentRequest(BaseModel):
    entity_id: int | None = Field(default=None, gt=0)
    object_id: int | None = None
    po_id: int
    category_id: int

    @model_validator(mode='after')
    def reference_required(self):
        if self.entity_id is None and self.object_id is None:
            raise ValueError('Укажите entity_id или object_id')
        return self


class EmployeeArchiveState(BaseModel):
    id: int
    full_name: str
    is_archived: bool
    archived_at: datetime | None
    dismissal_date: date | None


class EmployeeArchiveResponse(BaseModel):
    status: Literal["ok"] = "ok"
    item: EmployeeArchiveState




class PositionRequest(BaseModel):
    name: str = Field(min_length=1)
    action_description: str | None = None
    specialty: str | None = None
    work_location: Literal["OBJECT", "OFFICE"] | None = None
    work_schedule: Literal["SHIFT", "FIVE_TWO"] | None = None
    report_description: str | None = None
    aos_description: str | None = None
    requires_daily_report: StrictBool = False
    equipment_description: str | None = None
    planned_count: int = Field(default=0, ge=0, le=2147483647, strict=True)


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
def objects(archive: Literal["active", "archived", "all"] = "all"):
    return {
        "status": "ok",
        "items": get_objects(archive),
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
def edit_object(object_id: int, payload: CreateObjectRequest, id_type: Literal['legacy','entity']='legacy'):
    try:
        if id_type == 'entity':
            from app.api.construction_identity import change_entity
            return {'status':'ok','object':change_entity(object_id,name=payload.name)}
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
        item = create_po_type(payload.name,payload.default_category_id)

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
            default_category_id=payload.default_category_id if "default_category_id" in payload.model_fields_set else ...,
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
            **payload.model_dump(include={"specialty", "work_location", "work_schedule", "report_description", "aos_description", "requires_daily_report", "planned_count", "equipment_description"}, exclude_unset=True),
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
            **payload.model_dump(include={"specialty", "work_location", "work_schedule", "report_description", "aos_description", "requires_daily_report", "planned_count", "equipment_description"}, exclude_unset=True),
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
def employees(archived: bool = False, include_archived: bool = False):
    return {
        "status": "ok",
        "items": get_employees(archived=None if include_archived else archived),
    }


@app.post("/api/employees")
def add_employee(payload: EmployeeRequest):
    try:
        employee_id = create_employee(
            full_name=payload.full_name,
            position_id=payload.position_id,
            phone=payload.phone,
            crew_id=payload.crew_id,
            **payload.model_dump(include={"nrs_number", "max_shift_days", "max_off_shift_days", "dismissal_date", "email"}, exclude_unset=True),
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
            **payload.model_dump(include={"nrs_number", "max_shift_days", "max_off_shift_days", "dismissal_date", "email"}, exclude_unset=True),
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


@app.delete("/api/employees/{employee_id}", deprecated=True, summary="Физическое удаление отключено: используйте архив")
def remove_employee(employee_id: int):
    try:
        return {
            "status": "ok",
            **delete_employee(employee_id),
        }

    except ValueError as error:
        return JSONResponse(
            status_code=getattr(error, "status_code", 400),
            content={
                "status": "error",
                "message": str(error),
            },
        )


def _archive_employee(employee_id, archived):
    try:
        return {"status": "ok", "item": set_employee_archived(employee_id, archived)}
    except ValueError as error:
        return JSONResponse(status_code=getattr(error, "status_code", 400),
                            content={"status": "error", "message": str(error)})


@app.post("/api/employees/{employee_id}/archive", response_model=EmployeeArchiveResponse, summary="Перевести сотрудника в архив без удаления истории")
def archive_employee(employee_id: int):
    return _archive_employee(employee_id, True)


@app.post("/api/employees/{employee_id}/restore", response_model=EmployeeArchiveResponse, summary="Восстановить сотрудника, сохранив дату увольнения")
def restore_employee(employee_id: int):
    return _archive_employee(employee_id, False)


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
            entity_id=payload.entity_id,
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
            entity_id=payload.entity_id,
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
