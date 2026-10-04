// Browser layout regression: MODAL_CDP_URL points to an isolated Chrome debugging port.
// Reads existing directories only; never submits forms or changes database records.
const {test}=require('node:test');
const assert=require('node:assert/strict');
test('dialog scrolling at desktop and laptop sizes', {skip:!process.env.MODAL_CDP_URL}, async()=>{
    const pages=await(await fetch(process.env.MODAL_CDP_URL+'/json')).json();
    const ws=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);
    await new Promise(resolve=>ws.addEventListener('open',resolve,{once:true}));
    let id=0;const pending=new Map();
    ws.addEventListener('message',event=>{const m=JSON.parse(event.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}});
    const call=(method,params={})=>new Promise((resolve,reject)=>{const key=++id;pending.set(key,{resolve,reject});ws.send(JSON.stringify({id:key,method,params}));});
    const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw new Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
    const wait=async expression=>{for(let n=0;n<100;n++){if(await ev(expression))return;await new Promise(r=>setTimeout(r,50));}throw new Error('Timeout: '+expression);};
    try {
        await call('Page.enable');await call('Network.enable');await call('Network.setCacheDisabled',{cacheDisabled:true});
        await call('Page.navigate',{url:process.env.MODAL_APP_URL || 'http://127.0.0.1:8000/'});
        await wait('typeof openEmployeeModal === "function"');
        const employee=await ev('(async()=>{const d=await(await fetch("/api/employees")).json();return d.items.filter(x=>x.objects_count>=14).sort((a,b)=>b.objects_count-a.objects_count)[0];})()');
        assert.ok(employee,'Expected a real employee with at least 14 objects for scrolling');
        for(const [width,height] of [[1920,1080],[1600,900],[1366,768]]){
            await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
            await ev(`openEmployeeModal(${JSON.stringify(employee)})`);
            const geometry=await ev(`(()=>{const modal=document.querySelector('#employeeModal .modal'),body=modal.querySelector('.modal-body');
                const h=modal.querySelector('.modal-header'),f=modal.querySelector('.modal-footer');
                return {top:modal.getBoundingClientRect().top,bottom:modal.getBoundingClientRect().bottom,
                    scroll:body.scrollHeight>body.clientHeight,overflow:getComputedStyle(body).overflowY,
                    horizontal:body.scrollWidth>body.clientWidth,rows:document.querySelectorAll('#employeeAssignmentsList .assignment-row').length,
                    header:h.getBoundingClientRect().top,footer:f.getBoundingClientRect().bottom,
                    locked:getComputedStyle(document.documentElement).overflowY==='hidden'};})()`);
            assert.ok(geometry.top>=15&&geometry.bottom<=height-15,JSON.stringify(geometry));
            assert.ok(geometry.scroll);assert.equal(geometry.overflow,'auto');assert.equal(geometry.horizontal,false);
            assert.ok(geometry.rows>=14);assert.ok(geometry.locked);
            const visible=await ev(`(()=>{const body=document.querySelector('#employeeModal .modal-body');
                return [...document.querySelectorAll('#employeeAssignmentsList .assignment-row')].every(row=>{
                    body.scrollTop+=row.getBoundingClientRect().top-body.getBoundingClientRect().top;
                    const r=row.getBoundingClientRect(),b=body.getBoundingClientRect();return r.top>=b.top-1&&r.bottom<=b.bottom+1;
                });})()`);
            assert.ok(visible,'Every assignment must be reachable');
            const after=await ev(`(()=>{const m=document.querySelector('#employeeModal .modal');return {header:m.querySelector('.modal-header').getBoundingClientRect().top,footer:m.querySelector('.modal-footer').getBoundingClientRect().bottom};})()`);
            assert.equal(after.header,geometry.header);assert.equal(after.footer,geometry.footer);
            const wheel=await ev(`(()=>{const b=document.querySelector('#employeeModal .modal-body');b.scrollTop=b.scrollHeight;const r=b.getBoundingClientRect();return {x:r.x+50,y:r.y+50,page:scrollY};})()`);
            await call('Input.dispatchMouseEvent',{type:'mouseWheel',x:wheel.x,y:wheel.y,deltaX:0,deltaY:600});
            await new Promise(r=>setTimeout(r,100));assert.equal(await ev('scrollY'),wheel.page);
            await ev('closeEmployeeModal()');
            assert.notEqual(await ev('getComputedStyle(document.documentElement).overflowY'),'hidden');
            console.log(`${width}x${height}: real employee ${employee.id}, ${geometry.rows} assignments reachable; header/footer visible; background locked`);
        }
        // All shared dialogs, including the form-based subobject dialog, use the same scroll owner.
        const shared=await ev(`(()=>{const result=[];for(const overlay of document.querySelectorAll('.modal-overlay')){
            const modal=overlay.querySelector('.modal'),body=modal?.querySelector(':scope > .modal-body');if(!body)continue;
            overlay.hidden=false;const content=document.createElement('div');content.style.height='2400px';content.textContent='ДлинноеНазвание'.repeat(80);body.append(content);
            const rect=modal.getBoundingClientRect();result.push({id:overlay.id,inside:rect.top>=0&&rect.bottom<=innerHeight,scroll:body.scrollHeight>body.clientHeight,horizontal:body.scrollWidth>body.clientWidth});
            content.remove();overlay.hidden=true;
        }return result;})()`);
        for(const modal of shared){assert.ok(modal.inside&&modal.scroll&&!modal.horizontal,JSON.stringify(modal));}
        await ev('openObjectDirectoryModal()');
        assert.ok(await ev(`(()=>{const m=document.querySelector('#objectDirectoryModal .modal'),b=m.querySelector('.modal-body');return m.getBoundingClientRect().height<innerHeight-32&&b.scrollHeight<=b.clientHeight;})()`));
        await ev('closeObjectDirectoryModal()');
        const drawer=await ev(`(()=>{const p=document.getElementById('detailsPanel'),b=p.querySelector('.details-content');const d=document.createElement('div');d.style.height='2400px';b.append(d);p.classList.add('open');const ok=getComputedStyle(b).overflowY==='auto'&&b.scrollHeight>b.clientHeight&&p.getBoundingClientRect().height<=innerHeight;d.remove();p.classList.remove('open');return ok;})()`);
        assert.ok(drawer);
        console.log('Shared dialogs checked:',shared.map(x=>x.id).join(', '));
    } finally {ws.close();}
});
