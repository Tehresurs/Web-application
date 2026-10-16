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
        // Also cover the existing contractors page even without a sidebar entry.
        await ev('showMainSection(document.getElementById("contractorsPage"),null)');
        await hidden('contractorsPage');
        assert.deepEqual(errors,[]);
        console.log('PASS: initial page, six main sections, all three LUVR tabs, contractors page; same ticket component, no JS exceptions');
    } finally {ws.close();await fetch(base+'/json/close/'+page.id);}
})().catch(error=>{console.error(error);process.exitCode=1;});
