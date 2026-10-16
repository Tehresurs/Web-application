/* Small local SVG set: no network, fonts or external icon dependency. */
function uiIcon(name){
    const paths={
        user:['M20 21v-2a7 7 0 0 0-14 0v2','M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8'],
        settings:['M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8','M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1Z'],
        calendar:['M4 5h16v16H4Z','M8 3v4m8-4v4M4 10h16m-12 4h3m2 3h3'],
        truck:['M3 6h11v12H3Zm11 5h4l3 4v3h-7','M7 16a2 2 0 1 0 0 4 2 2 0 0 0 0-4m11 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4'],
        box:['m3 7 9-4 9 4v11l-9 4-9-4Z','m3 7 9 5 9-5m-9 5v10'],
        graduation:['m2 8 10-5 10 5-10 5Z','M6 10v7q6 5 12 0v-7m4-2v9'],
        office:['M5 21V3h14v18M3 21h18M9 7h1m4 0h1M9 11h1m4 0h1M10 21v-5h4v5'],
        object:['M3 21h18M5 21V10h14v11M3 10l9-7 9 7M10 21v-6h4v6'],
        check:['m5 12 4 4L19 6'],
        clock:['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18','M12 7v5l3 2'],
        alert:['m12 3 10 18H2Z','M12 9v5m0 3v1'],
        close:['m6 6 12 12M6 18 18 6'],
        bolt:['m13 2-9 12h7l-1 8 10-13h-8Z'],
        plus:['M12 5v14M5 12h14'],
        edit:['m4 16 11-11 4 4L8 20H4Zm9-9 4 4'],
        phone:['M6 3H3c0 10 8 18 18 18v-4l-5-2-2 2a14 14 0 0 1-7-7l2-2Z'],
        id:['M3 5h18v14H3Z','M7 9h3v3H7Zm-1 6h5m3-6h4m-4 4h4'],
    };
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.8');svg.setAttribute('stroke-linecap','round');svg.setAttribute('stroke-linejoin','round');svg.setAttribute('aria-hidden','true');svg.setAttribute('focusable','false');svg.classList.add('ui-icon');
    for(const d of paths[name]||paths.user){const p=document.createElementNS(svg.namespaceURI,'path');p.setAttribute('d',d);svg.append(p);}return svg;
}
