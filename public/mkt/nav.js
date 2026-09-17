/* /mkt/nav.js — shared workspace navigation strip for The Adamson Group working pages.
   Include with <script src="/mkt/nav.js" data-internal="1"></script> on internal pages (always shown),
   or without data-internal on client-facing pages (shown only in a browser that holds the CMA edit key).
   Resolves the current property from the URL (/mkt/<slug>/..., /mkt/<cma-folder>/..., /str-dashboard/) via the
   shared registry (str-reports?action=list, cached 5 min in sessionStorage) and links every workspace for it. */
(function(){
  var me=document.currentScript||{}; var internal=me.getAttribute&&me.getAttribute('data-internal')==='1';
  var hasKey=false; try{ hasKey=!!localStorage.getItem('cma-edit-key'); }catch(e){}
  if(!internal && !hasKey) return;
  try{ if(window.top!==window) return; }catch(e){ return; }   // embedded in the Property Intelligence tabs: no second nav bar
  var path=location.pathname, seg=(path.match(/^\/mkt\/([a-z0-9][a-z0-9-]{2,63})(?:\/|$)/i)||[])[1];
  if(seg==='admin') seg=null;
  if(!seg){ var qs=new URLSearchParams(location.search).get('slug'); if(qs&&/^[a-z0-9][a-z0-9-]{2,63}$/i.test(qs)) seg=qs.toLowerCase(); }
  var page = /\/str-dashboard\/report/.test(path)||/\/mkt\/[^/]+\/report$/.test(path) ? 'report'
           : /\/str-dashboard/.test(path)||/\/invest$/.test(path) ? 'invest'
           : /workbench\.html/.test(path) ? 'workbench' : /estimator\.html/.test(path) ? 'estimator'
           : /\/mkt\/admin/.test(path) ? 'admin' : path==='/mkt/'||path==='/mkt/index.html' ? 'home'
           : seg ? (/\/mkt\/[^/]+\/?$/.test(path)?'property':'cma') : '';
  var css='#agnav{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;font-size:12.5px;background:#071528;color:#cdd6e4;border-bottom:1px solid #1d3355;position:relative;z-index:1500}'
   +'#agnav .in{max-width:1240px;margin:0 auto;padding:6px 18px;display:flex;align-items:center;gap:4px;flex-wrap:wrap}'
   +'#agnav a,#agnav .dd>span{color:#cdd6e4;text-decoration:none;padding:5px 9px;border-radius:6px;white-space:nowrap;display:inline-block;cursor:pointer}'
   +'#agnav a:hover,#agnav .dd>span:hover{background:#12294a;color:#fff}'
   +'#agnav a.on{background:#C9A961;color:#1a2233;font-weight:600}'
   +'#agnav a.home{font-weight:600;color:#fff}#agnav .sep{opacity:.35;padding:0 2px}#agnav .prop{color:#C9A961;font-family:Georgia,serif;font-size:13px;padding:5px 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:320px}'
   +'#agnav .dim{opacity:.45;cursor:default}#agnav .dim:hover{background:none}'
   +'#agnav .dd{position:relative}#agnav .dd .menu{display:none;position:absolute;top:100%;left:0;background:#fff;color:#16233a;border:1px solid #cdd6e2;border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.18);min-width:300px;padding:6px;z-index:1600}'
   +'#agnav .dd.open .menu{display:block}#agnav .menu a{display:flex;justify-content:space-between;gap:12px;color:#16233a;padding:7px 9px;border-radius:6px;white-space:normal}#agnav .menu a:hover{background:#eef2f8;color:#16233a}'
   +'#agnav .menu a small{color:#6b7688;white-space:nowrap}#agnav .menu .hd{font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:#6b7688;padding:6px 9px 2px}'
   +'#agnav .right{margin-left:auto;display:flex;gap:4px;align-items:center}'
   +'@media print{#agnav{display:none!important}}';
  var st=document.createElement('style'); st.textContent=css; document.head.appendChild(st);
  var nav=document.createElement('nav'); nav.id='agnav'; nav.className='noprint no-print';
  function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g,function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function fmt(iso){ if(!iso) return ''; var d=new Date(iso); return d.toLocaleDateString('en-US',{month:'short',day:'numeric'})+' '+d.toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit'}); }
  function link(href,label,key,dim){ if(!href) return '<a class="dim">'+label+'</a>'; return '<a href="'+href+'" class="'+(page===key?'on':'')+'">'+label+'</a>'; }
  function render(P){
    var slug=P&&P.slug, h='<a class="home" href="/mkt/">&#8962; Workspaces</a>';
    if(P){
      var reps=P.reports||[];
      h+='<span class="sep">|</span><a class="prop" href="'+(P.home_url||('/mkt/'+slug+'/'))+'" title="Property home">'+esc(P.address||slug)+'</a><span class="sep">&rsaquo;</span>';
      h+=link(P.workbench_url,'CMA workbench','workbench')+link(P.cma_url,'CMA client page','cma')+link(P.estimator_url,'Closing costs','estimator');
      h+=link(P.invest_url||('/mkt/'+slug+'/invest'),'Property Intelligence','invest');
      h+='<span class="dd"><span>Client reports'+(reps.length?' ('+reps.length+')':'')+' &#9662;</span><div class="menu">'
        +(reps.length?'<div class="hd">Saved investment reports</div>'+reps.slice(0,12).map(function(r){ return '<a href="/mkt/'+slug+'/report?id='+r.id+'" target="_blank">'+esc(r.title||'Report')+'<small>'+fmt(r.created_at)+'</small></a>'; }).join(''):'<div class="hd">No investment reports saved yet</div>')
        +(P.cma_url?'<div class="hd">CMA</div><a href="'+P.cma_url+'" target="_blank">CMA client page<small>'+(P.cma&&P.cma.profile?esc(P.cma.profile):'')+'</small></a>':'')
        +'<a href="'+(P.home_url||('/mkt/'+slug+'/'))+'">All files for this property &rarr;</a></div></span>';
    } else if(seg){ h+='<span class="sep">|</span><span class="prop">'+esc(seg)+'</span>'; }
    h+='<span class="right">'+link('/str-dashboard/','+ New property','')+link('/mkt/admin/','CMA admin','admin')+'</span>';
    nav.innerHTML='<div class="in">'+h+'</div>';
    nav.querySelectorAll('.dd>span').forEach(function(s){ s.onclick=function(e){ e.stopPropagation(); s.parentNode.classList.toggle('open'); }; });
    document.addEventListener('click',function(){ nav.querySelectorAll('.dd.open').forEach(function(d){ d.classList.remove('open'); }); });
  }
  function match(list,key){ if(!key) return null; key=key.toLowerCase();
    return list.find(function(p){ return p.slug===key; }) || list.find(function(p){ return p.cma&&p.cma.slug===key; }) || list.find(function(p){ return p.pages&&p.pages.folder===key; }) || list.find(function(p){ return p.slug===key.replace(/-cma$/,''); }) || null; }
  var LIST=null;
  function load(cb){ if(LIST) return cb(LIST);
    try{ var c=JSON.parse(sessionStorage.getItem('agnav-list')||'null'); if(c&&c.t&&Date.now()-c.t<300000){ LIST=c.list; return cb(LIST); } }catch(e){}
    fetch('/.netlify/functions/str-reports?action=list',{cache:'no-store'}).then(function(r){return r.json()}).then(function(d){ LIST=(d&&d.properties)||[]; try{ sessionStorage.setItem('agnav-list',JSON.stringify({t:Date.now(),list:LIST})); }catch(e){} cb(LIST); }).catch(function(){ cb([]); }); }
  render(null);
  function mount(){ if(document.body && !nav.parentNode) document.body.insertBefore(nav, document.body.firstChild); }
  if(document.body) mount(); else document.addEventListener('DOMContentLoaded',mount);
  var cur=seg;
  function refresh(){ load(function(list){ render(match(list,cur)); }); }
  if(cur) refresh();
  // pages that resolve the property later (STR dashboard after Analyze) call AGNav.setSlug(slug); saving a report calls AGNav.invalidate()
  window.AGNav={ setSlug:function(s){ if(!s||s===cur) return; cur=s; refresh(); }, invalidate:function(){ LIST=null; try{ sessionStorage.removeItem('agnav-list'); }catch(e){} refresh(); } };
})();
