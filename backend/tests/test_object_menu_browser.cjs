const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
test('catalog popover escapes clipped table, flips and preserves delegated actions', {skip:!process.env.MODAL_CDP_URL},async()=>{
    const base=process.env.MODAL_CDP_URL;
    const tab=await(await fetch(base+'/json/new?about:blank',{method:'PUT'})).json();
    const ws=new WebSocket(tab.webSocketDebuggerUrl);
    await new Promise(resolve=>ws.addEventListener('open',resolve,{once:true}));
    let id=0;const pending=new Map();
    ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result);}});
    const call=(method,params={})=>new Promise((resolve,reject)=>{const key=++id;pending.set(key,{resolve,reject});ws.send(JSON.stringify({id:key,method,params}));});
    const ev=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw new Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
    try {
        await call('Emulation.setDeviceMetricsOverride',{width:1000,height:768,deviceScaleFactor:1,mobile:false});
        const css=fs.readFileSync('app/static/css/directory_workspace.css','utf8');
        await ev(`document.head.innerHTML='<style>'+${JSON.stringify(css)}+'</style>';document.body.innerHTML='<section id="objectsPage" data-identity-preview-enabled="true"><div id="fixture" style="position:fixed;left:50px;right:50px;bottom:8px;height:90px;overflow:auto"></div></section>'`);
        await ev(fs.readFileSync('app/static/js/construction_choices.js','utf8'));
        await ev(fs.readFileSync('app/static/js/object_hierarchy.js','utf8'));
        await ev(`window.actions=0;window.host=document.getElementById('fixture');host.addEventListener('click',e=>{if(e.target.closest('.edit-object-directory'))window.actions++;});renderObjectHierarchy(host,objectHierarchyRows([{id:1,name:'Root'}],[]),{testMode:true,expanded:new Set(),onAdd:()=>{},onEdit:()=>{},onPromote:()=>{}});window.before={height:host.scrollHeight,width:host.scrollWidth};document.querySelector('.object-action-menu summary').click()`);
        const state=await ev(`(()=>{const p=document.querySelector('[popover]'),r=p.getBoundingClientRect(),a=document.querySelector('summary').getBoundingClientRect();return {open:p.matches(':popover-open'),up:p.dataset.direction,top:r.top,bottom:r.bottom,anchor:a.top,scrollHeight:host.scrollHeight,scrollWidth:host.scrollWidth,before:window.before,hit:p.contains(document.elementFromPoint(r.left+10,r.top+10))};})()`);
        assert.equal(state.open,true);assert.equal(state.up,'up');assert.ok(state.top>=8&&state.bottom<state.anchor);assert.ok(state.hit);
        assert.equal(state.scrollHeight,state.before.height);assert.equal(state.scrollWidth,state.before.width);
        await ev(`document.querySelector('.edit-object-directory').click()`);
        assert.equal(await ev('window.actions'),1);
        assert.equal(await ev(`document.querySelector('[popover]').matches(':popover-open')`),false);
        await ev(`host.style.top='8px';host.style.bottom='auto';document.querySelector('summary').click()`);
        assert.equal(await ev(`document.querySelector('[popover]').dataset.direction`),'down');
        await call('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
        await call('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
        assert.equal(await ev(`document.querySelector('[popover]').matches(':popover-open')`),false);
    } finally {ws.close();await fetch(base+'/json/close/'+tab.id);}
});
