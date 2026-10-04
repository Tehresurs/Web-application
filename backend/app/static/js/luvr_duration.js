const LUVR_DURATION_LABELS={NORMAL:'Норма',WARNING_50:'50% срока',MAX_REACHED:'Максимальный срок',EXCEEDED:'Срок превышен',APPROVED_EXTENSION:'Согласованное продление',NONE:'Индикация отключена',UNKNOWN:'Состояние не определено'};
function luvrDurationSummary(status) {
    if(!status||status.current_state==='NOT_APPLICABLE')return '';
    if(status.current_state==='DISMISSED')return 'Уволен';
    if(status.current_state==='UNKNOWN')return 'Состояние не определено';
    const state=status.current_state==='ON_SHIFT'?'Вахта':'МВ';
    const days=status.maximum_days===null?`${status.current_duration_days} дней · максимум не задан`:`${status.current_duration_days} / ${status.maximum_days} дней`;
    return `${state} — ${days}\n${status.is_sick?'Болеет · индикация отключена':LUVR_DURATION_LABELS[status.indicator_status]}`;
}
function luvrDurationDetails(employee,projection=false) {
    const s=employee.duration;
    const lines=[employee.full_name,`На дату: ${s.as_of_date}${projection?' · Прогноз по известной истории':''}`,luvrDurationSummary(s),
        `С момента: ${s.state_since||'не определено'}`,
        `Продолжительность: ${s.current_duration_days===null?'не рассчитывается':s.current_duration_days+' дней'}`,
        `Допустимый максимум: ${s.maximum_days===null?'не задан':s.maximum_days+' дней'}`,
        `Процент: ${s.is_sick?'индикация отключена на период болезни':s.ratio===null?'не рассчитывается':(s.ratio*100).toLocaleString('ru-RU',{maximumFractionDigits:1})+'%'}`,
        `Болезнь на контрольную дату: ${s.is_sick?'да':'нет'}`,
        `Исключено дней болезни: ${s.excluded_sick_days}`];
    if(s.active_exceptions.length){for(const item of s.active_exceptions)lines.push(`Согласованное исключение: ${item.date_from} — ${item.date_to}. Причина: ${item.comment}`);}
    else lines.push('Активных согласованных исключений нет');
    if(s.sick_periods.length){for(const p of s.sick_periods)lines.push(`Болезнь: ${p.date_from} — ${p.date_to||'открытый период'}${p.comment?' · '+p.comment:''}`);}
    else lines.push('Периодов болезни в расчёте нет');
    for(const warning of s.warnings)lines.push(warning.message);
    return lines.join('\n');
}
if(typeof module!=='undefined')module.exports={luvrDurationSummary,luvrDurationDetails,LUVR_DURATION_LABELS};
