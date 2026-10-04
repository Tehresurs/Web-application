function employeeArchiveListUrl(archived) {
    return archived ? '/api/employees?archived=true' : '/api/employees';
}
function employeeArchiveDate(value) {
    if(!value)return '—';
    return value.slice(0,10).split('-').reverse().join('.')+(value.includes('T')?' '+value.slice(11,16):'');
}
async function changeEmployeeArchive(item, request, confirmAction) {
    const restoring=Boolean(item.is_archived);
    const message=restoring
        ? `Восстановить сотрудника «${item.full_name}»? Дата увольнения останется без изменений.`
        : `Перевести сотрудника «${item.full_name}» в архив? Его история и назначения сохранятся.`;
    if(!confirmAction(message))return false;
    await request(`/api/employees/${item.id}/${restoring?'restore':'archive'}`, {method:'POST'});
    return true;
}
if(typeof module!=='undefined')module.exports={employeeArchiveListUrl,employeeArchiveDate,changeEmployeeArchive};
