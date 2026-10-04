/* One table, two synchronized native horizontal scroll surfaces. No wheel interception. */
function initLuvrScroll() {
    const page=document.getElementById('luvrMonthPage');
    const container=page?.querySelector('.luvr-month-scroll');
    const table=container?.querySelector('table');
    if(!table)return;
    const bar=document.createElement('div'),track=document.createElement('div');
    bar.className='luvr-fixed-scroll';bar.hidden=true;bar.tabIndex=0;
    bar.setAttribute('role','region');bar.setAttribute('aria-label','Горизонтальная прокрутка таблицы ЛУВР');
    container.id='luvrMonthScroll';bar.setAttribute('aria-controls',container.id);
    track.className='luvr-fixed-scroll-track';bar.append(track);page.append(bar);
    let frame=0;
    function update() {
        frame=0;
        if(page.hidden||!container.getClientRects().length){bar.hidden=true;return;}
        const rect=container.getBoundingClientRect();
        const viewportHeight=document.documentElement.clientHeight;
        // The page retains its normal vertical scroll. Offset the real sticky header
        // inside its horizontal overflow ancestor to the visible viewport's top.
        const headerHeight=table.tHead?.getBoundingClientRect().height||0;
        container.style.setProperty('--luvr-header-top',`${Math.min(Math.max(0,-rect.top),Math.max(0,container.clientHeight-headerHeight))}px`);
        const first=table.tHead?.rows[0]?.cells[0];
        container.style.setProperty('--luvr-number-width',`${first?.getBoundingClientRect().width||44}px`);
        const needed=container.scrollWidth>container.clientWidth+1;
        bar.hidden=!(needed&&rect.top<viewportHeight-24&&rect.bottom>viewportHeight+1&&rect.right>0&&rect.left<document.documentElement.clientWidth);
        if(!bar.hidden){
            bar.style.left=`${rect.left}px`;bar.style.width=`${container.clientWidth}px`;
            track.style.width=`${container.scrollWidth}px`;
            if(Math.abs(bar.scrollLeft-container.scrollLeft)>0.5)bar.scrollLeft=container.scrollLeft;
        }
    }
    function schedule(){if(!frame)frame=requestAnimationFrame(update);}
    container.addEventListener('scroll',()=>{
        if(!bar.hidden&&Math.abs(bar.scrollLeft-container.scrollLeft)>0.5)bar.scrollLeft=container.scrollLeft;
    },{passive:true});
    bar.addEventListener('scroll',()=>{
        if(!bar.hidden&&Math.abs(container.scrollLeft-bar.scrollLeft)>0.5)container.scrollLeft=bar.scrollLeft;
    },{passive:true});
    window.addEventListener('scroll',schedule,{passive:true,capture:true});
    window.addEventListener('resize',schedule,{passive:true});
    const resize=new ResizeObserver(schedule);resize.observe(container);resize.observe(table);
    const content=new MutationObserver(schedule);content.observe(table,{childList:true,subtree:true});
    const visibility=new MutationObserver(schedule);visibility.observe(page,{attributes:true,attributeFilter:['hidden']});
    document.fonts?.ready.then(schedule);
    schedule();
}
if(typeof document!=='undefined')initLuvrScroll();
