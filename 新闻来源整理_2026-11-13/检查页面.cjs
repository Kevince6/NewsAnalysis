const fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process'),{pathToFileURL}=require('node:url');
(async()=>{
 const out=__dirname, edge='C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',port=19337;
 const profile=path.join(out,'qa-edge-profile-20261113');
 const proc=spawn(edge,['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-extensions','--remote-debugging-port='+port,'--remote-debugging-address=127.0.0.1','--user-data-dir='+profile,'about:blank'],{windowsHide:true,stdio:'ignore'});
 let ws;const pending=new Map;let seq=0;const errors=[];
 const pause=ms=>new Promise(r=>setTimeout(r,ms));
 try {
   let tabs;
   for(let i=0;i<80;i++){try{tabs=await(await fetch('http://127.0.0.1:'+port+'/json/list')).json();if(tabs.some(t=>t.type==='page'))break;}catch{}await pause(150);}
   if(!tabs)throw Error('No debugging endpoint');
   const t=tabs.find(t=>t.type==='page');ws=new WebSocket(t.webSocketDebuggerUrl);
   await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
   ws.addEventListener('message',e=>{const m=JSON.parse(String(e.data));if(m.id){const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}}else if(m.method==='Runtime.exceptionThrown'){errors.push(m.params.exceptionDetails.text);}});
   const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
   const evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
   const assert=(x,msg)=>{if(!x)throw Error(msg);};
   await send('Page.enable');await send('Runtime.enable');
   await send('Emulation.setDeviceMetricsOverride',{width:1360,height:1000,deviceScaleFactor:1,mobile:false});
   await send('Page.navigate',{url:pathToFileURL(path.join(out,'30条新闻来源核查.html')).href});await pause(550);
   const initial=await evaluate("({cards:document.querySelectorAll('.news-card').length,shown:[...document.querySelectorAll('.news-card')].filter(x=>!x.hidden).length,links:document.querySelectorAll('.source-link').length,overflow:document.documentElement.scrollWidth>innerWidth,count:document.getElementById('result-count').textContent})");
   assert(initial.cards===30&&initial.links===78&&initial.shown===30&&!initial.overflow,'Initial DOM invalid '+JSON.stringify(initial));
   fs.writeFileSync(path.join(out,'预览_桌面.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png'})).data,'base64'));
   const search=await evaluate("(()=>{const q=document.getElementById('search');q.value='育儿';q.dispatchEvent(new Event('input'));return [...document.querySelectorAll('.news-card')].filter(x=>!x.hidden).map(x=>x.id)})()");
   assert(JSON.stringify(search)==='[\"E013\"]','Search failed '+JSON.stringify(search));
   const finance=await evaluate("(()=>{document.getElementById('reset').click();const q=document.getElementById('category');q.value='金融';q.dispatchEvent(new Event('change'));return [...document.querySelectorAll('.news-card')].filter(x=>!x.hidden).map(x=>x.id)})()");
   assert(JSON.stringify(finance)==='[\"E007\",\"E030\"]','Category filter failed');
   const restricted=await evaluate("(()=>{document.getElementById('reset').click();const c=document.getElementById('limited-only');c.checked=true;c.dispatchEvent(new Event('change'));return [...document.querySelectorAll('.news-card')].filter(x=>!x.hidden).map(x=>x.id)})()");
   assert(JSON.stringify(restricted)==='[\"E006\",\"E013\"]','Restricted source filter failed');
   const noMatch=await evaluate("(()=>{document.getElementById('reset').click();const q=document.getElementById('search');q.value='zzzz-no-matches';q.dispatchEvent(new Event('input'));return !document.getElementById('empty').hidden})()");
   assert(noMatch,'Empty state failed');
   await evaluate("document.getElementById('reset').click();document.getElementById('search').blur();window.scrollTo(0,0)");
   await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
   await pause(250);
   const mobile=await evaluate("({overflow:document.documentElement.scrollWidth>innerWidth,viewport:innerWidth,scrollWidth:document.documentElement.scrollWidth,sidebar:getComputedStyle(document.querySelector('.sidebar')).display,toc:getComputedStyle(document.querySelector('.mobile-toc')).display})");
   assert(!mobile.overflow&&mobile.sidebar==='none'&&mobile.toc==='block','Mobile layout failed '+JSON.stringify(mobile));
   fs.writeFileSync(path.join(out,'预览_手机.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png'})).data,'base64'));
   const longCards=await evaluate("({cards:[...document.querySelectorAll('.news-card')].map(c=>({id:c.id,overflow:c.scrollWidth>c.clientWidth})).filter(x=>x.overflow),external:[...document.querySelectorAll('.source-link')].every(a=>a.target==='_blank'&&a.rel.includes('noopener')),cites:[...document.querySelectorAll('.cite')].every(a=>document.getElementById(a.hash.slice(1)))})");
   assert(longCards.cards.length===0&&longCards.external&&longCards.cites,'Content or link verification failed '+JSON.stringify(longCards));
   await evaluate("location.hash='E030'");await pause(200);
   fs.writeFileSync(path.join(out,'预览_长文尾部.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png'})).data,'base64'));
   assert(errors.length===0,'Runtime errors '+JSON.stringify(errors));
   const report={initial,search,finance,restricted,noMatch,mobile,longCards,errors,passed:true};fs.writeFileSync(path.join(out,'页面检查结果.json'),JSON.stringify(report,null,2),'utf8');console.log(JSON.stringify(report));
   await send('Browser.close');
 }finally{if(ws)ws.close();if(proc.exitCode===null)proc.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});

