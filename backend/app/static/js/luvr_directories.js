/* Stage 1: directory settings only, no workday/status calculations. */
function positionWorkLabels(position) {
    return {
        specialty: position?.specialty || "Не указана",
        location: {OBJECT:"Объект", OFFICE:"Офис"}[position?.work_location] || "Не указано",
        schedule: {SHIFT:"Вахта", FIVE_TWO:"5/2"}[position?.work_schedule] || "Не указан",
    };
}

function syncPositionSchedule(doc = document) {
    const location = doc.getElementById("positionWorkLocation");
    const schedule = doc.getElementById("positionWorkSchedule");
    const object = location.value === "OBJECT";
    if (object) schedule.value = "SHIFT";
    schedule.disabled = object;
    for (const option of schedule.options) option.disabled = object && option.value !== "SHIFT";
}

function fillPositionSettings(item, doc = document) {
    doc.getElementById("positionSpecialty").value = item?.specialty ?? "";
    doc.getElementById("positionWorkLocation").value = item?.work_location ?? "";
    doc.getElementById("positionWorkSchedule").value = item?.work_schedule ?? "";
    syncPositionSchedule(doc);
}

function positionSettingsPayload(doc = document) {
    syncPositionSchedule(doc);
    return {
        specialty: doc.getElementById("positionSpecialty").value.trim() || null,
        work_location: doc.getElementById("positionWorkLocation").value || null,
        work_schedule: doc.getElementById("positionWorkSchedule").value || null,
    };
}

function showEmployeePositionSettings(position, doc = document) {
    const labels = positionWorkLabels(position);
    doc.getElementById("employeeSpecialty").textContent = labels.specialty;
    doc.getElementById("employeeWorkLocation").textContent = labels.location;
    doc.getElementById("employeeWorkSchedule").textContent = labels.schedule;
    doc.getElementById("employeeShiftLimits").hidden = position?.work_schedule !== "SHIFT";
}

function fillEmployeePersonalSettings(employee, doc = document) {
    doc.getElementById("employeeNrsNumber").value = employee?.nrs_number ?? "";
    doc.getElementById("employeeMaxShiftDays").value = employee?.max_shift_days ?? "";
    doc.getElementById("employeeMaxOffShiftDays").value = employee?.max_off_shift_days ?? "";
}

function employeePersonalSettingsPayload(doc = document) {
    const result = {nrs_number: doc.getElementById("employeeNrsNumber").value.trim() || null};
    if (!doc.getElementById("employeeShiftLimits").hidden) {
        for (const [id,key] of [["employeeMaxShiftDays","max_shift_days"],["employeeMaxOffShiftDays","max_off_shift_days"]]) {
            const input = doc.getElementById(id);
            const value = input.value.trim();
            if (input.validity?.badInput || (value && (!/^\d+$/.test(value) || Number(value) <= 0 || Number(value) > 2147483647))) {
                throw new Error("Количество дней должно быть положительным целым числом");
            }
            result[key] = value ? Number(value) : null;
        }
    }
    return result;
}

if (typeof module !== "undefined") module.exports = {positionWorkLabels, syncPositionSchedule,
    fillPositionSettings, positionSettingsPayload, showEmployeePositionSettings,
    fillEmployeePersonalSettings, employeePersonalSettingsPayload};
