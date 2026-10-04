const {test}=require('node:test');
const assert=require('node:assert/strict');
const fields=require('../app/static/js/luvr_directories.js');
function setup(){
    const ids={};const doc={getElementById:id=>ids[id] ||= {value:'',textContent:'',hidden:false,disabled:false,validity:{badInput:false}}};
    doc.getElementById('positionWorkSchedule').options=[{value:''},{value:'SHIFT'},{value:'FIVE_TWO'}];
    return {ids,doc};
}
test('new and legacy positions remain unknown without guessed defaults',()=>{
    const {doc}=setup();fields.fillPositionSettings(null,doc);
    assert.deepEqual(fields.positionSettingsPayload(doc),{specialty:null,work_location:null,work_schedule:null});
});
test('OBJECT selects SHIFT and disables FIVE_TWO',()=>{
    const {doc,ids}=setup();fields.fillPositionSettings({specialty:'ОС/СТ',work_location:'OBJECT',work_schedule:'FIVE_TWO'},doc);
    assert.equal(ids.positionWorkSchedule.value,'SHIFT');assert.ok(ids.positionWorkSchedule.disabled);
    assert.ok(ids.positionWorkSchedule.options.find(x=>x.value==='FIVE_TWO').disabled);
    assert.deepEqual(fields.positionSettingsPayload(doc),{specialty:'ОС/СТ',work_location:'OBJECT',work_schedule:'SHIFT'});
});
test('OFFICE permits both schedules and preserves action-independent settings',()=>{
    const {doc,ids}=setup();
    for(const schedule of ['SHIFT','FIVE_TWO']){
        fields.fillPositionSettings({work_location:'OFFICE',work_schedule:schedule},doc);
        assert.equal(ids.positionWorkSchedule.disabled,false);
        assert.equal(fields.positionSettingsPayload(doc).work_schedule,schedule);
        assert.ok(ids.positionWorkSchedule.options.every(x=>!x.disabled));
    }
});
test('changing location from OBJECT to OFFICE enables schedule choice',()=>{
    const {doc,ids}=setup();fields.fillPositionSettings({work_location:'OBJECT'},doc);
    ids.positionWorkLocation.value='OFFICE';fields.syncPositionSchedule(doc);
    assert.equal(ids.positionWorkSchedule.disabled,false);ids.positionWorkSchedule.value='FIVE_TWO';
    assert.equal(fields.positionSettingsPayload(doc).work_schedule,'FIVE_TWO');
});
test('employee metadata follows the selected position and has no editable copy',()=>{
    const {doc,ids}=setup();
    fields.showEmployeePositionSettings({specialty:'ОС/СТ',work_location:'OBJECT',work_schedule:'SHIFT'},doc);
    assert.equal(ids.employeeSpecialty.textContent,'ОС/СТ');assert.equal(ids.employeeWorkLocation.textContent,'Объект');
    assert.equal(ids.employeeWorkSchedule.textContent,'Вахта');assert.equal(ids.employeeShiftLimits.hidden,false);
    fields.showEmployeePositionSettings({specialty:'Офис',work_location:'OFFICE',work_schedule:'FIVE_TWO'},doc);
    assert.equal(ids.employeeSpecialty.textContent,'Офис');assert.equal(ids.employeeWorkSchedule.textContent,'5/2');assert.equal(ids.employeeShiftLimits.hidden,true);
    fields.showEmployeePositionSettings(null,doc);assert.equal(ids.employeeSpecialty.textContent,'Не указана');
});
test('NRS and manual shift limits round trip, empty fields clear to null',()=>{
    const {doc,ids}=setup();fields.fillEmployeePersonalSettings({nrs_number:'00-НРС / А',max_shift_days:45,max_off_shift_days:21},doc);
    // Native input values are strings.
    ids.employeeMaxShiftDays.value=String(ids.employeeMaxShiftDays.value);ids.employeeMaxOffShiftDays.value=String(ids.employeeMaxOffShiftDays.value);
    fields.showEmployeePositionSettings({work_schedule:'SHIFT'},doc);
    assert.deepEqual(fields.employeePersonalSettingsPayload(doc),{nrs_number:'00-НРС / А',max_shift_days:45,max_off_shift_days:21});
    fields.fillEmployeePersonalSettings(null,doc);
    assert.deepEqual(fields.employeePersonalSettingsPayload(doc),{nrs_number:null,max_shift_days:null,max_off_shift_days:null});
});
test('FIVE_TWO hides limits without erasing stored settings or sending them',()=>{
    const {doc,ids}=setup();fields.fillEmployeePersonalSettings({max_shift_days:45,max_off_shift_days:21},doc);
    fields.showEmployeePositionSettings({work_schedule:'FIVE_TWO'},doc);
    assert.deepEqual(fields.employeePersonalSettingsPayload(doc),{nrs_number:null});
    assert.equal(ids.employeeMaxShiftDays.value,45);
});
test('invalid day counts cannot be submitted',()=>{
    const {doc,ids}=setup();fields.fillEmployeePersonalSettings(null,doc);fields.showEmployeePositionSettings({work_schedule:'SHIFT'},doc);
    for(const value of ['0','-1','1.5','abc','2147483648']){
        ids.employeeMaxShiftDays.value=value;assert.throws(()=>fields.employeePersonalSettingsPayload(doc),/положительным целым/);
    }
    ids.employeeMaxShiftDays.value='';ids.employeeMaxShiftDays.validity.badInput=true;
    assert.throws(()=>fields.employeePersonalSettingsPayload(doc));
});
