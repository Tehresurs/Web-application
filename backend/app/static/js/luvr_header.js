function initLuvrHeaderSettings() {
    const $=id=>document.getElementById(id),panel=$('luvrHeaderSettings');if(!panel)return;
    const fields={approver_position:'luvrApproverPosition',approver_name:'luvrApproverName',document_title:'luvrDocumentTitle',
        developer_position:'luvrDeveloperPosition',developer_name:'luvrDeveloperName',agreed_position:'luvrAgreedPosition',agreed_name:'luvrAgreedName',legend:'luvrLegend'};
    const button=$('luvrHeaderSave'),message=$('luvrHeaderMessage');let loaded=false,busy=false;
    panel.addEventListener('toggle',async()=>{
        if(!panel.open||loaded||busy)return;busy=true;
        try{const result=await luvrHistoryRequest('/api/luvr/month/settings');for(const [key,id] of Object.entries(fields))$(id).value=result.item[key];loaded=true;}
        catch(e){message.textContent=e.message;}
        finally{busy=false;button.disabled=!loaded;}
    });
    $('luvrHeaderForm').onsubmit=async event=>{
        event.preventDefault();if(!loaded||busy)return;busy=true;button.disabled=true;
        try{await luvrHistoryRequest('/api/luvr/month/settings','PUT',Object.fromEntries(Object.entries(fields).map(([key,id])=>[key,$(id).value])));message.textContent='Настройки сохранены. Сформированные месяцы не изменены.';}
        catch(e){message.textContent=e.message;}
        finally{busy=false;button.disabled=false;}
    };
}
if(typeof document!=='undefined')initLuvrHeaderSettings();
