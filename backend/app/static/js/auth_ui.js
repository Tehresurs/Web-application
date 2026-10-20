/* Opt-in UI; HttpOnly session cookie is managed exclusively by the server. */
(()=>{'use strict';
const nativeFetch=window.fetch.bind(window);let csrf=null,user=null;
const mutating=m=>!['GET','HEAD','OPTIONS'].includes(m.toUpperCase());
function notice(text){let el=document.getElementById('authNotice');if(!el){el=document.createElement('div');el.id='authNotice';el.setAttribute('role','alert');document.body.append(el);}el.textContent=text;}
function expired(){csrf=null;user=null;location.replace('/login');}
// Install before application scripts; gate initial requests on authoritative /me.
const ready=location.pathname==='/login'?Promise.resolve():nativeFetch('/api/auth/me',{credentials:'same-origin',cache:'no-store'}).then(async r=>{if(r.status===401){expired();throw Error('Session expired');}if(!r.ok)throw Error('Session unavailable');const data=await r.json();csrf=data.csrf_token;user=data.user;return user;});
window.fetch=async(input,options={})=>{
 const url=new URL(input instanceof Request?input.url:input,location.href);
 if(url.origin!==location.origin)return nativeFetch(input,options);
 if(!url.pathname.startsWith('/api/auth/'))await ready;
 const headers=new Headers(input instanceof Request?input.headers:undefined);new Headers(options.headers).forEach((v,k)=>headers.set(k,v));
 const method=(options.method||(input instanceof Request?input.method:'GET')).toUpperCase();
 if(mutating(method)&&csrf)headers.set('X-CSRF-Token',csrf);
 const response=await nativeFetch(input,{...options,headers,credentials:'same-origin'});
 if(response.status===401&&!url.pathname.endsWith('/login'))expired();
 if(response.status===403)notice('Действие недоступно для вашей учётной записи.');
 return response;
};
function engineer(){return user?.roles.includes('SYSTEM_TECHNICIAN')&&user?.permissions.includes('data.create');}
// The UI hides actions; server policies remain the authority for every request.
const alwaysDenied=/согласовать|принять как правило|отменить правило|массов|перенести.*всех|перевести.*экипаж|отклон|помет.*отсутств|сохран.*правило|удал|подтверд|аннулир|архивир|восстанов|настройк.*сохран|сохран.*настройк|сохран.*реквизит|утверд|замен.*факт|примен.*правил|загрузить папку|выбрать папку|обработать папку/i;
const writeAction=/добав|созда|редакт|измен|сохран|загруз|обработ|сформировать месяц|сформировать отчет воу|сформировать отчёт воу|пересчит|назнач/i;
const forbiddenIds=new Set(['railChooseFolder','selectFolderButton','checkFolderButton','parseButton','processButton','luvrHeaderSave','cleanAssignmentSave']);
function permitted(el){
 // Named personnel confirmation is distinct from forbidden ticket/workflow confirmations.
 if(el.matches('[data-personnel-write]'))return user?.roles.includes('SYSTEM_TECHNICIAN')&&user?.permissions.includes('data.update');
 const id=el.id||'',text=[el.textContent,el.title,el.getAttribute('aria-label'),el.getAttribute('data-action')].filter(Boolean).join(' ');
 if(/^back/i.test(id)||id==='pmOpenReports')return true;
 if(el.closest('.navigation,.luvr-tabs,[role="tablist"]')||/NavButton$|Tab$|Refresh$|Export$|Download$/.test(id))return true;
 if(/DK|Absence|Archive|Restore|Bulk|Confirm|Annul|SettingsSave|HeaderSave/i.test(id))return false;
 if(forbiddenIds.has(id)||id.startsWith('clean')||alwaysDenied.test(text))return false;
 if(el.closest('#settingsPage,.review-category,.review-rules,#vouSettingsForm,#luvrHeaderForm'))return false;
 if(el.type==='file')return engineer();
 if(writeAction.test(text)||el.isContentEditable)return engineer();
 return true;
}
function apply(){
 document.querySelectorAll('#vouSettingsForm input,#luvrHeaderForm input,#luvrHeaderForm select').forEach(el=>el.disabled=true);
 if(!engineer())document.querySelectorAll('#railTicketDrop,[data-rail-upload]').forEach(el=>el.setAttribute('data-auth-denied',''));
 document.querySelectorAll('.pm-editor select').forEach(el=>{if(!engineer())el.disabled=true;});
 document.querySelectorAll('.pm-chip').forEach(el=>{if(!engineer()&&el.tagName==='BUTTON')el.disabled=true;});
 document.querySelectorAll('button,a[role="button"],input[type="file"],[contenteditable="true"],[data-action]').forEach(el=>{
 const allow=permitted(el);if(!allow){if(!el.hasAttribute('data-auth-denied'))el.setAttribute('data-auth-denied','');if('disabled' in el)el.disabled=true;el.setAttribute('aria-disabled','true');}
 });
 const files=document.getElementById('railTicketFiles');if(files)files.multiple=false;
}
async function init(){
 const form=document.getElementById('authLoginForm');
 if(form){
  form.dataset.authReady='true';form.querySelector('button').disabled=false;
  form.addEventListener('submit',async e=>{e.preventDefault();const button=form.querySelector('button'),message=document.getElementById('authMessage');button.disabled=true;message.textContent='';
   try{const response=await nativeFetch('/api/auth/login',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({login:form.elements.login.value.trim(),password:form.elements.password.value})});form.elements.password.value='';
    if(response.ok){location.replace('/');return;}message.textContent=response.status===429?'Слишком много попыток. Повторите позже.':response.status===401?'Неверный логин или пароль.':'Вход временно недоступен.';
   }catch{message.textContent='Не удалось связаться с сервером.';}finally{form.elements.password.value='';button.disabled=false;}
  });return;
 }
 try{await ready;}catch{notice('Не удалось проверить сессию. Обновите страницу.');document.querySelector('.app')?.setAttribute('inert','');return;}
 const header=document.querySelector('.header-user');if(header){header.replaceChildren();const label=document.createElement('span');label.id='authIdentity';label.textContent=user.login+' · '+(engineer()?'Инженер Системотехник':'Руководитель офиса');const logout=document.createElement('button');logout.id='authLogout';logout.textContent='Выйти';logout.onclick=async()=>{try{const r=await fetch('/api/auth/logout',{method:'POST'});if(r.ok)expired();}catch{notice('Выход не выполнен. Повторите попытку.');}};header.append(label,logout);}
 apply();document.body.classList.remove('auth-loading');new MutationObserver(apply).observe(document.body,{childList:true,subtree:true});
 document.addEventListener('click',e=>{const el=e.target.closest('button,[data-action],[contenteditable="true"]');if(el&&!permitted(el)){e.preventDefault();e.stopImmediatePropagation();notice('Действие недоступно для вашей учётной записи.');}},true);
 // Recheck after returning to a background tab and periodically without touching production data.
 const check=()=>nativeFetch('/api/auth/me',{cache:'no-store',credentials:'same-origin'}).then(async r=>{if(r.status===401)expired();else if(r.ok){const d=await r.json();csrf=d.csrf_token;user=d.user;apply();}}).catch(()=>{});
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)check();});setInterval(check,60000);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
