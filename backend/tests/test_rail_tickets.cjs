const {test}=require('node:test');const assert=require('node:assert/strict');
const {RailTicketController,railDate,RAIL_STATUS_LABELS,railDropFiles,railBatchStats,railEmployeeName}=require('../app/static/js/rail_tickets.js');
test('new employee prefill uses full title case, without correcting names or mutating ticket',()=>{
    for(const raw of ['ТРОФИМОВ СЕРГЕЙ НИКОЛАЕВИЧ','трофимов сергей николаевич',' ТРОФИМОВ   СЕРГЕЙ   НИКОЛАЕВИЧ ']){
        const ticket=Object.freeze({full_name:raw});assert.equal(railEmployeeName(ticket.full_name),'Трофимов Сергей Николаевич');assert.equal(ticket.full_name,raw);
    }
    assert.equal(railEmployeeName('ТРОФИМАВ СЕРГЕЙ НИКОЛАЕВИЧ'),'Трофимав Сергей Николаевич');
    assert.equal(railEmployeeName(''),'');
});
function harness(request){const errors=[],renders=[];const c=new RailTicketController(request,s=>renders.push(s.items.slice()),m=>errors.push(m));return {c,errors,renders};}
const file=(name='ticket.pdf',data='%PDF-test')=>new File([data],name,{type:'application/pdf'});
test('folder, file picker and drag files use one multipart upload endpoint',async()=>{
    const calls=[];const {c}=harness(async(...args)=>{calls.push(args);return {items:[{id:1}]};});
    for(const files of [[file()],[file('copy.pdf')],[file('folder.pdf')]])await c.upload(files);
    assert.ok(calls.every(([url,options])=>url==='/api/rail-tickets/upload'&&options.method==='POST'&&options.body instanceof FormData));
    assert.equal(c.items.length,1);
});
test('upload only displays parsing results, never automatically confirms',async()=>{
    const calls=[];const {c}=harness(async url=>{calls.push(url);return {items:[{id:1,processing_status:'READY'}]};});
    await c.upload([file()]);assert.deepEqual(calls,['/api/rail-tickets/upload']);assert.equal(c.items[0].processing_status,'READY');
});
test('one error does not hide other batch results',async()=>{
    const items=[{id:1,processing_status:'NEEDS_DIRECTION'},{id:2,processing_status:'EMPLOYEE_NOT_FOUND'},{id:null,processing_status:'PARSE_ERROR'},{id:3,processing_status:'DUPLICATE'}];
    const {c}=harness(async()=>({items}));await c.upload([file()]);assert.deepEqual(c.items,items);
});
test('pending duplicate merges by ticket ID and preserves ready state',()=>{
    const {c}=harness();c.merge([{id:1,processing_status:'NEEDS_DIRECTION'}]);c.merge([{id:1,processing_status:'READY',movement_type:'ARRIVAL',duplicate:true}]);
    assert.equal(c.items.length,1);assert.equal(c.items[0].movement_type,'ARRIVAL');
});
test('employee creation refreshes existing parsed ticket without reupload',async()=>{
    const calls=[];const {c}=harness(async(...args)=>{calls.push(args);return {item:{id:17,processing_status:'NEEDS_DIRECTION',match_status:'FOUND'}};});
    c.merge([{id:17,processing_status:'EMPLOYEE_NOT_FOUND'}]);await c.action(17,'refresh');
    assert.equal(c.items[0].match_status,'FOUND');assert.equal(calls.length,1);assert.equal(calls[0][0],'/api/rail-tickets/17');
    assert.deepEqual(calls[0][1],{});
});
test('direction uses explicit PATCH, confirmation sends no client facts',async()=>{
    const calls=[];const {c}=harness(async(...args)=>{calls.push(args);return {item:{id:1,processing_status:'READY'}};});
    await c.action(1,'direction','DEPARTURE');await c.action(1,'confirm');
    assert.equal(calls[0][1].method,'PATCH');assert.deepEqual(JSON.parse(calls[0][1].body),{movement_type:'DEPARTURE'});
    assert.equal(calls[1][0],'/api/rail-tickets/1/confirm');assert.deepEqual(JSON.parse(calls[1][1].body),{});
});
test('reject only requests rejection, does not confirm',async()=>{
    const calls=[];const {c}=harness(async(url,options)=>{calls.push([url,options.method]);return {item:{id:1,processing_status:'REJECTED'}};});
    await c.action(1,'reject');assert.deepEqual(calls,[['/api/rail-tickets/1/reject','POST']]);
});
test('double confirmation click sends one request',async()=>{
    let finish,calls=0;const {c}=harness(()=>{calls++;return new Promise(resolve=>finish=resolve);});
    const first=c.action(1,'confirm');await c.action(1,'confirm');assert.equal(calls,1);
    finish({item:{id:1,processing_status:'CONFIRMED'}});await first;assert.equal(c.pending.size,0);
});
test('failed confirmation retains parsed ticket and permits retry',async()=>{
    const {c,errors}=harness(async()=>{throw new Error('Сотрудник находится в архиве');});c.merge([{id:1,full_name:'Иванов'}]);
    await c.action(1,'confirm');assert.equal(c.items[0].full_name,'Иванов');assert.equal(errors.length,1);assert.equal(c.pending.size,0);
});
test('archived employee status never invokes restoration',()=>{
    let calls=0;const {c}=harness(()=>calls++);c.merge([{id:1,processing_status:'ARCHIVED_EMPLOYEE'}]);assert.equal(calls,0);
    assert.match(RAIL_STATUS_LABELS.ARCHIVED_EMPLOYEE,/архиве/);
});
test('repeated upload while busy is blocked',async()=>{
    let finish,calls=0;const {c}=harness(()=>{calls++;return new Promise(resolve=>finish=resolve);});
    const first=c.upload([file()]);await c.upload([file()]);assert.equal(calls,1);finish({items:[]});await first;assert.equal(c.uploading,false);
});
test('large recursive selection is split into requests without dropping files',async()=>{
    const sizes=[];const {c}=harness(async(url,options)=>{const files=options.body.getAll('files');sizes.push(files.length);return {items:files.map(f=>({source_filename:f.name}))};});
    await c.upload([]);assert.equal(sizes.length,0);await c.upload(Array.from({length:101},()=>file()));assert.deepEqual(sizes,[50,50,1]);assert.equal(c.batchItems.length,101);
});
const entry=(name)=>({name,isFile:true,file:resolve=>resolve(file(name))});
function directory(name,batches){return {name,isDirectory:true,createReader(){let i=0;return {readEntries:resolve=>resolve(batches[i++]||[])}}};}
test('drop folder drains every reader batch and every depth, continues after read failure',async()=>{
    const broken={name:'unreadable.pdf',isFile:true,file:(ok,fail)=>fail(new Error('unreadable'))};
    let deep=entry('deep.pdf');for(let n=0;n<150;n++)deep=directory('depth'+n,[[deep]]);
    const root=directory('root',[[entry('root.pdf'),directory('Ivanov',[[entry('first.pdf'),deep]])],[directory('Petrov',[[entry('second.pdf'),broken,entry('other.txt')]])]]);
    const result=await railDropFiles({items:[{kind:'file',webkitGetAsEntry:()=>root}],files:[]});
    assert.deepEqual(result.files.map(f=>f.name).sort(),['deep.pdf','first.pdf','other.txt','root.pdf','second.pdf']);assert.equal(result.errors.length,1);
});
test('drop individual files falls back when directory API is unavailable',async()=>{
    const files=[file(),file('second.pdf')];assert.deepEqual((await railDropFiles({items:[],files})).files,files);
});
test('browser recursive FileList sends basenames only, never relative client paths',async()=>{
    const paths=['Tickets/root.pdf','Tickets/Ivanov/first.pdf','Tickets/Ivanov/October/deep.pdf','Tickets/Petrov/other.pdf'];
    const files=paths.map(path=>{const f=file(path.split('/').pop());Object.defineProperty(f,'webkitRelativePath',{value:path});return f;});
    const names=[];const {c}=harness(async(url,o)=>{names.push(...o.body.getAll('files').map(f=>f.name));return {items:[]};});await c.upload(files);
    assert.deepEqual(names,['root.pdf','first.pdf','deep.pdf','other.pdf']);assert.ok(names.every(x=>!/[\\/]/.test(x)));
});
test('failed chunk does not stop remaining recursive files',async()=>{
    let calls=0;const {c}=harness(async()=>{if(++calls===1)throw Error('network');return {items:[{source_filename:'last.pdf',processing_status:'READY'}]};});
    await c.upload(Array.from({length:51},()=>file()));assert.equal(calls,2);assert.equal(c.batchItems.length,51);assert.equal(c.batchItems[50].processing_status,'READY');
});
test('batch statistics count files including duplicate paths and separate excluded routes from errors',()=>{
    const stats=railBatchStats([{processing_status:'NOT_LUVR_ROUTE',is_luvr_route:false},{processing_status:'UNSUPPORTED'},{processing_status:'PARSE_ERROR'},{processing_status:'READY',is_luvr_route:true},{processing_status:'READY',is_luvr_route:true,duplicate:true}]);
    assert.equal(stats['Найдено файлов'],5);assert.equal(stats['Без станции Салым'],1);assert.equal(stats['Ошибки парсинга'],1);assert.equal(stats['Посторонние файлы'],1);assert.equal(stats['Дубликаты'],1);
});
test('dates are local and duplicates have a clear Russian status',()=>{
    assert.equal(railDate('2026-09-10T23:04:00'),'10.09.2026 23:04');assert.equal(RAIL_STATUS_LABELS.DUPLICATE,'Билет уже обработан');
});
test('one PDF can show two independent tickets while file count stays one',async()=>{
    const items=[{id:1,source_page:1,movement_type:'DEPARTURE',processing_status:'READY'},{id:2,source_page:2,movement_type:'ARRIVAL',processing_status:'READY'}];
    const {c}=harness(async()=>({items}));await c.upload([file('round.pdf')]);
    assert.equal(c.items.length,2);assert.equal(railBatchStats(c.batchItems,c.fileCount)['Найдено файлов'],1);
    c.merge([{...items[0],processing_status:'CONFIRMED'}]);assert.equal(c.items[1].processing_status,'READY');
});

test('complete arrival assignment sends object PO and category in one request',async()=>{
 const calls=[];const {c}=harness(async(url,options)=>{calls.push([url,options]);return {item:{id:5}};});
 await c.action(5,'object',{entity_id:16,po_id:2,category_id:3});
 assert.equal(calls.length,1);assert.equal(calls[0][1].method,'PATCH');
 assert.deepEqual(JSON.parse(calls[0][1].body),{entity_id:16,po_id:2,category_id:3});
});
