// Read-only browser regression. Run after node --test tests/*.cjs.
const assert = require('node:assert/strict');
(async () => {
    const base = process.env.MODAL_CDP_URL || 'http://127.0.0.1:9234';
    const page = await (await fetch(base + '/json/new?about:blank', {method:'PUT'})).json();
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise(resolve => ws.addEventListener('open',resolve,{once:true}));
    let id=0; const pending=new Map(),errors=[];
    ws.onmessage = e => {const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params);};
    const call=(method,params={})=>new Promise((resolve,reject)=>{pending.set(++id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
    const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
    const wait=async expression=>{for(let i=0;i<100;i++){if(await ev(expression))return;await new Promise(r=>setTimeout(r,50));}throw Error('Timeout '+expression);};
    const state=()=>ev(`(()=>{const p=document.getElementById('railTicketsPage');return {hidden:p.hidden,display:getComputedStyle(p).display,boxes:p.getClientRects().length,count:document.querySelectorAll('#railTicketsPage').length,navHidden:document.getElementById('luvrNavigation').hidden};})()`);
    const hidden=async label=>{const s=await state();assert.equal(s.hidden,true,label);assert.equal(s.display,'none',label);assert.equal(s.boxes,0,label);assert.equal(s.count,1);};
    try {
        await call('Runtime.enable');await call('Network.enable');await call('Network.setCacheDisabled',{cacheDisabled:true});
        await call('Page.navigate',{url:process.env.MODAL_APP_URL||'http://127.0.0.1:8000/'});
        await wait('typeof showMainSection === "function"');
        await hidden('initial page');
        await ev('window.originalTicketNode=document.getElementById("railTicketsPage")');
        const sections=['processingNavButton','employeesNavButton','objectsNavButton','crewsNavButton','journalNavButton','logsNavButton'];
        for(const button of sections){
            await ev('document.getElementById("luvrNavButton").click();document.getElementById("railTicketsNavButton").click()');
            assert.equal((await state()).display,'block');assert.equal((await state()).navHidden,false);
            await ev(`document.getElementById('${button}').click()`);
            await hidden(button);assert.equal((await state()).navHidden,true);
        }
        await ev('document.getElementById("luvrNavButton").click()');
        for(const button of ['luvrMonthNavButton','luvrCalendarNavButton']){
            await ev(`document.getElementById('${button}').click()`);
            await hidden(button);assert.equal((await state()).navHidden,false);
        }
        await ev('document.getElementById("railTicketsNavButton").click()');
        assert.equal((await state()).display,'block');
        assert.equal(await ev('originalTicketNode===document.getElementById("railTicketsPage")'),true);
        assert.equal(await ev('!!document.getElementById("railTicketFiles") && !!document.getElementById("railTicketFolder") && !!document.getElementById("railTicketDrop")'),true);
        await wait('document.querySelectorAll("#railTicketList tr").length>0');
        await ev('document.querySelector("#railTicketList tr").click()');
        for(const [nav,ready] of [
          ['railTicketsNavButton','document.querySelectorAll("#railTicketList tr").length>0'],
          ['luvrMonthNavButton','document.querySelectorAll("#luvrMonthBody tr").length>0'],
          ['luvrCalendarNavButton','document.querySelectorAll("#luvrCalendarBody tr").length>0']]){
          await ev(`document.getElementById('${nav}').click()`);
          if(nav==='luvrCalendarNavButton')await ev("document.getElementById('luvrCalendarNavButton').onclick()");
          if(nav==='luvrCalendarNavButton')await wait('document.getElementById("luvrCalendarEmployee").options.length>1');
          if(nav==='luvrCalendarNavButton')await ev(`(()=>{const s=document.getElementById('luvrCalendarEmployee');s.selectedIndex=1;s.dispatchEvent(new Event('change'));document.getElementById('luvrCalendarRefresh').click()})()`);
          await wait(ready);
          if(nav==='luvrMonthNavButton'){
            const result=await ev(`(()=>{const rows=[...document.querySelectorAll('#luvrMonthBody tr[data-employee]')],total=document.getElementById('luvrMonthTotals').textContent;
              const f=document.querySelector('.luvr-day-filter[data-date="2026-10-05"]');if(!f)throw Error('October filter missing');
              const expected=rows.filter(r=>r.querySelector('[data-date="2026-10-05"]').textContent.match(/^(1|0,5)$/)).map(r=>r.dataset.employee);
              f.value='WORKING';f.dispatchEvent(new Event('change'));
              return {expected,actual:[...document.querySelectorAll('#luvrMonthBody tr[data-employee]:not([hidden])')].map(r=>r.dataset.employee),all:document.querySelectorAll('#luvrMonthBody tr[data-employee]').length,before:rows.length,totalsSame:total===document.getElementById('luvrMonthTotals').textContent};})()`);
            assert.deepEqual(result.actual,result.expected);assert.equal(result.all,result.before);assert.ok(result.totalsSame);
            await ev('document.getElementById("luvrDayFiltersReset").click()');
            assert.equal(await ev('document.querySelectorAll("#luvrMonthBody tr[hidden]").length'),0);
          }
          for(const [width,height] of [[1920,1080],[1366,768],[1280,800]]){
            await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
            assert.ok(await ev('document.documentElement.scrollWidth<=innerWidth+1'),'No page overflow '+nav+' '+width);
            if(nav==='railTicketsNavButton')assert.ok(await ev('document.getElementById("railTicketDrop").getBoundingClientRect().height<=60'));
            const fs=require('node:fs');fs.mkdirSync('C:/Projects/luvr-style-review',{recursive:true});
            const shot=await call('Page.captureScreenshot',{format:'png'});
            fs.writeFileSync(`C:/Projects/luvr-style-review/${nav}-${width}x${height}.png`,Buffer.from(shot.data,'base64'));
          }
        }
        // Also cover the existing contractors page even without a sidebar entry.
        await ev('showMainSection(document.getElementById("contractorsPage"),null)');
        await hidden('contractorsPage');
        assert.deepEqual(errors,[]);
        console.log('PASS: initial page, six main sections, all three LUVR tabs, contractors page; same ticket component, no JS exceptions');
    } finally {ws.close();await fetch(base+'/json/close/'+page.id);}
})().catch(error=>{console.error(error);process.exitCode=1;});
