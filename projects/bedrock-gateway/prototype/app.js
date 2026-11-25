
'use strict';
const demoDay='2026-11-25', storageKey='bedrock-web-demo-v3';
const routeData=[['DXB-01','192.0.2.10'],['DXB-02','198.51.100.20'],['DXB-03','203.0.113.30']];
const profiles=['企业 A · 文档标注','企业 B · 质检复核','企业 C · 资料提取'];
function seed(){return {n:2,up:[true,true,true],t:[
{id:'TEN-017',name:profiles[0],role:'svc-label-a',services:[{id:'label',name:'文档标注',day:8500,used:4180,hold:500},{id:'review',name:'抽样复核',day:3000,used:2140,hold:0}],profile:'已关联',day:10000,mo:200000,used:6320,month:86240,hold:500,open:1,conc:8,rpm:120,net:0,backup:false,spare:-1,state:'服务中'},
{id:'TEN-024',name:profiles[1],role:'svc-review-b',services:[{id:'review',name:'质检复核',day:7500,used:1840,hold:0}],profile:'已关联',day:7500,mo:150000,used:1840,month:48210,hold:0,open:0,conc:4,rpm:60,net:0,backup:true,spare:1,state:'服务中'},
{id:'TEN-031',name:profiles[2],role:'svc-extract-c',services:[{id:'extract',name:'资料提取',day:5000,used:1120,hold:0}],profile:'已关联',day:5000,mo:90000,used:1120,month:27110,hold:0,open:0,conc:3,rpm:60,net:0,backup:false,spare:-1,state:'服务中'}],
events:[{id:'E-0001',time:'09:00:00',tenant:'系统',op:'载入演示快照',detail:'两条出口均在批准集合内'}],holds:[],receipts:{},usageTimes:[[],[],[]],reconciled:false,seq:1};}
function loadDemo(){
 try{
  const previous=JSON.parse(localStorage.getItem(storageKey));
  if(previous && Array.isArray(previous.t) && previous.t.length===3 &&
     previous.t.every(t=>Array.isArray(t.services) && t.services.length>0) &&
     Array.isArray(previous.up) && Array.isArray(previous.usageTimes) &&
     Array.isArray(previous.holds) && Array.isArray(previous.events) && previous.receipts) return previous;
 }catch(_){}
 return seed();
}
let db=loadDemo();
let page='overview',sel=0,portal=false,msg='',err=false,proc=null;const sim={idx:0,service:0,amount:'2.50',key:'REQ-1001',outcome:'正常完成'};
function save(){try{localStorage.setItem(storageKey,JSON.stringify(db))}catch(_){}}
const icons={overview:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',tenants:'M3 20v-2c0-3 3-5 6-5s6 2 6 5v2 M9 10a3 3 0 1 0 0-6 3 3 0 1 0 0 6 M15 6c4-1 5 5 1 6 M17 15c3 0 4 2 4 4',egress:'M4 12h11 M11 7l5 5-5 5 M17 4h4v16h-4',billing:'M5 4h14v17l-3-2-4 2-4-2-3 2z M8 8h8 M8 12h6',audit:'M5 3h14v18H5z M8 8h8 M8 12h8 M8 16h5',logo:'M4 15l5-7 4 7 6-9'};
function ic(k){return '<svg aria-hidden="true" class="ico" viewBox="0 0 24 24"><path d="'+icons[k]+'"/></svg>'}
const pages={overview:'运营总览',tenants:'客户与额度',egress:'迪拜出口',billing:'账单核对',audit:'操作记录'};
function esc(v){return String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
const usd=c=>'$'+(c/100).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
function moneyIn(s){const v=String(s).trim();if(!/^\d{1,7}(\.\d{1,2})?$/.test(v))return NaN;const a=v.split('.');return Number(a[0])*100+Number((a[1]||'').padEnd(2,'0'))}
function effective(v){return Math.floor(v*9/10)}
function room(t){return Math.max(0,Math.min(effective(t.day)-t.used-t.hold,effective(t.mo)-t.month-t.hold))}
function serviceRoom(t,s){return Math.max(0,Math.min(room(t),effective(s.day)-s.used-s.hold))}
function percent(t){return Math.min(100,Math.round((t.used+t.hold)/Math.max(1,effective(t.day))*100))}
function badge(s,cl){return '<span class="badge '+(cl||'neutral')+'">'+esc(s)+'</span>'}
function state(t){return badge(t.state,t.state==='服务中'?'ok':t.state==='上游受限'?'bad':'warn')}
function card(label,value,note){return '<div class="card"><div class="label">'+label+'</div><div class="metric">'+value+'</div><div class="hint">'+note+'</div></div>'}
function title(h,sub,act){return '<div class="title"><div><h1>'+h+'</h1><p>'+sub+'</p></div>'+(act||'')+'</div>'}
function log(tenant,op,detail){db.seq++;db.events.unshift({id:'E-'+String(db.seq).padStart(4,'0'),time:new Date().toISOString().slice(11,19),tenant,op,detail})}
function tell(s,bad){msg=s;err=!!bad;save();render()}
function nav(k){page=k;msg='';render()}
function pick(i){sel=Number(i);msg='';render()}
function openTenant(i){sel=i;nav('tenants')}
function routePick(t){if(t.net<db.n&&db.up[t.net])return t.net;if(t.backup&&t.spare!==t.net&&t.spare>=0&&t.spare<db.n&&db.up[t.spare])return t.spare;return -1}
function options(which){return db.t.map((t,i)=>'<option value="'+i+'" '+(i===which?'selected':'')+'>'+esc(t.name)+'</option>').join('')}
function render(){const navs=Object.entries(pages).map(([k,v])=>'<button type="button" data-nav="'+k+'" class="'+(page===k?'active':'')+'">'+ic(k)+v+'</button>').join('');
document.getElementById('app').innerHTML='<div class="shell"><aside class="side"><div class="brand"><span class="brandmark">'+ic('logo')+'</span>Bedrock 服务台</div><nav aria-label="主要导航">'+(portal?'<button class="active">'+ic('overview')+'我的服务</button>':navs)+'</nav><div class="sidefoot"><div>业务时段与账期采用 UTC</div></div></aside><div class="workspace"><div class="top"><span><a href="../">工程手册</a><i class="dot"></i>模拟数据</span><span>'+(portal?'客户视图':'运营工作台')+' <button data-action="'+(portal?'leave-portal':'reset-demo')+'">'+(portal?'返回运营原型':'重置演示')+'</button></span></div><main class="inner"><div id="feedback" class="feedback '+(err?'err':'')+'" role="status">'+esc(msg)+'</div>'+(portal?portalPage():({overview,tenants,egress,billing,audit}[page])())+'<div class="footer">交互原型仅使用本机示例数据。金额单位为 USD。</div></main></div></div>';
}
function overview(){const total=db.t.reduce((a,t)=>a+t.used,0),up=db.up.slice(0,db.n).filter(Boolean).length;
return title('运营总览','当前快照　'+demoDay+' UTC')+'<div class="cards">'+card('今日预估用量费',usd(total),'仅含已结算的演示请求')+card('可用迪拜出口',up+'<small>/ '+db.n+'</small>','批准的固定 IPv4 地址')+card('服务中客户',db.t.filter(t=>t.state==='服务中').length+'<small>/ '+db.t.length+'</small>','按实际企业客户归属')+'</div><div class="split"><section class="panel"><div class="rowHead"><h2>客户额度</h2><span class="type">已用及预占 / 日可用上限</span></div>'+db.t.map((t,i)=>'<div class="serviceRow"><div><button class="nameBtn" data-action="open-tenant" data-index="'+i+'">'+esc(t.name)+'</button><span class="sub">'+t.id+'</span></div><div><span class="small money">'+usd(t.used+t.hold)+' / '+usd(effective(t.day))+'</span><div class="bar"><i style="width:'+percent(t)+'%"></i></div></div><div>'+state(t)+'</div></div>').join('')+'</section><section class="panel"><div class="rowHead"><h2>固定出口</h2><button data-action="egress">管理</button></div>'+routeData.slice(0,db.n).map((r,i)=>'<div class="routeRow"><div>'+r[0]+'<span class="sub compact">'+r[1]+'</span></div>'+badge(db.up[i]?'可用':'线路故障',db.up[i]?'ok':'bad')+'</div>').join('')+'</section></div><div class="sp"></div>'+simPanel()}
function simPanel(){return '<section class="panel last"><div class="rowHead"><h2>试运行一次请求</h2><span class="type">模拟网关准入与计量</span></div><div class="form"><label>客户服务<select id="sTenant" data-field="sim-tenant">'+options(sim.idx)+'</select></label><label>业务服务<select id="sService" data-field="sim-service">'+db.t[sim.idx].services.map((s,i)=>'<option value="'+i+'" '+(i===sim.service?'selected':'')+'>'+esc(s.name)+'</option>').join('')+'</select></label><label>预占上界（USD）<input id="sAmount" value="'+esc(sim.amount)+'" inputmode="decimal" data-field="sim-amount"></label><label>幂等键<input id="sKey" value="'+esc(sim.key)+'" maxlength="40" data-field="sim-key"></label><label>上游结果<select id="sOutcome" data-field="sim-outcome">'+['正常完成','发送后结果未知','已收到平台对该客户的限制通知'].map(x=>'<option '+(x===sim.outcome?'selected':'')+'>'+x+'</option>').join('')+'</select></label><div><button class="mainBtn" data-action="send-request">发起模拟请求</button></div></div><p class="hint">正常完成按预占额的 80% 模拟实际计费。同一幂等键可以重试。</p></section>'}
function sendSim(){const t=db.t[sim.idx],amt=moneyIn(sim.amount),key=sim.key.trim();
if(sim.outcome==='已收到平台对该客户的限制通知'){if(t.state!=='上游受限'){t.state='上游受限';log(t.id,'上游限制','已确认企业范围。冻结新调用，保留在途预占。')}return tell('403 已冻结客户，本笔未发送。',true)}
if(!Number.isSafeInteger(amt)||amt<=0||!/^[A-Za-z0-9_-]{1,40}$/.test(key))return tell('请输入正数金额和有效幂等键（字母、数字、短横线或下划线）。',true);
const svc=t.services[sim.service];if(!svc)return tell('此项目未开通选定服务。',true);const k=t.id+'|'+svc.id+'|'+key,old=db.receipts[k];if(old){if(old.amount!==amt)return tell('409　同一幂等键的业务参数不同。',true);return tell('幂等回放　'+old.result+'，未新增调用或计费。')}
if(t.state!=='服务中')return tell('403　客户已暂停或上游受限。',true);const r=routePick(t);if(r<0)return tell('503　批准的线路不可用，未发送。',true);
if(serviceRoom(t,svc)<amt)return tell('429　此服务剩余可预占 '+usd(serviceRoom(t,svc))+'，未发送。',true);
const now=Date.now();db.usageTimes[sim.idx]=db.usageTimes[sim.idx].filter(v=>v>now-60000);
if(t.open>=t.conc||db.usageTimes[sim.idx].length>=t.rpm)return tell('429　并发或每分钟请求数达到上限，未发送。',true);
db.usageTimes[sim.idx].push(now);let res;if(sim.outcome==='发送后结果未知'){t.hold+=amt;svc.hold+=amt;t.open++;db.holds.push({tenant:sim.idx,service:sim.service,key,amount:amt});res='202 结果待核，保留预占 '+usd(amt);log(t.id,'待核对',svc.name+' · '+key+' · '+routeData[r][0]+' · '+usd(amt))}
else{const actual=Math.ceil(amt*8/10);t.used+=actual;svc.used+=actual;t.month+=actual;res='200 已计 '+usd(actual)+' · '+routeData[r][0];log(t.id,'请求结算',svc.name+' · '+key+' · '+routeData[r][0]+' · '+usd(actual))}
db.receipts[k]={amount:amt,result:res};tell(res)}
function tenants(){const t=db.t[sel];return title('客户与额度','选择企业客户，调整业务限额或查看客户侧页面。','<select aria-label="选择客户" class="pick" data-field="tenant-filter">'+options(sel)+'</select>')+'<div class="cards">'+card('今日已计',usd(t.used),t.id)+card('当前预占',usd(t.hold),'含结果未知的请求')+card('当前可预占',usd(room(t)),'日、月余额取较小值')+'</div><section class="panel"><div class="rowHead"><h2>'+esc(t.name)+'</h2>'+state(t)+'</div><div class="two"><div>服务端角色<span class="sub compact">'+t.role+'</span></div><div>Anthropic 企业档案<span class="sub">'+t.profile+'（演示）</span></div></div><div class="sp"></div><div class="form"><label>日预算 USD<input id="dayCap" value="'+(t.day/100).toFixed(2)+'" inputmode="decimal"></label><label>月预算 USD<input id="monthCap" value="'+(t.mo/100).toFixed(2)+'" inputmode="decimal"></label><label>每分钟请求数<input id="rpm" type="number" min="1" value="'+t.rpm+'"></label><label>并发上限<input id="conc" type="number" min="1" value="'+t.conc+'"></label><label>主出口<select id="net">'+routeData.slice(0,db.n).map((r,i)=>'<option value="'+i+'" '+(t.net===i?'selected':'')+'>'+r[0]+'</option>').join('')+'</select></label><label>线路故障策略<select id="backup"><option value="-1" '+(!t.backup?'selected':'')+'>固定主出口，故障停发</option>'+routeData.slice(0,db.n).map((r,i)=>'<option value="'+i+'" '+(t.backup&&t.spare===i?'selected':'')+'>备用 '+r[0]+'</option>').join('')+'</select></label></div><div class="sp"></div><h3>服务子额度</h3><div class="scroller"><table><tr><th>业务</th><th>今日已计</th><th>预占</th><th>日预算 USD</th></tr>'+t.services.map((v,i)=>'<tr><td>'+esc(v.name)+'</td><td>'+usd(v.used)+'</td><td>'+usd(v.hold)+'</td><td><input id="svcCap'+i+'" aria-label="'+esc(v.name)+'日预算" inputmode="decimal" style="width:100px" value="'+(v.day/100).toFixed(2)+'"></td></tr>').join('')+'</table></div><div class="band">演示预留 10% 安全余量。客户总额和当前服务子额度同时生效。下调至当前用量以下会立即停止新请求，在途预占继续保留。</div><div class="toolbar"><div class="actions"><button class="mainBtn" data-action="save-tenant">保存配置</button><button data-action="pause-tenant" '+(t.state==='上游受限'?'disabled':'')+'>'+(t.state==='运营暂停'?'恢复客户':'暂停客户')+'</button></div><button data-action="show-portal">预览客户视图</button></div></section>'}
function saveTenant(){const t=db.t[sel],d=moneyIn(document.getElementById('dayCap').value),m=moneyIn(document.getElementById('monthCap').value),c=Number(document.getElementById('conc').value),rp=Number(document.getElementById('rpm').value),nt=Number(document.getElementById('net').value),sp=Number(document.getElementById('backup').value),back=sp>=0;if(![c,rp,d,m].every(v=>Number.isSafeInteger(v)&&v>0)||c>100000||rp>1000000||m<d)return tell('额度必须为正，月预算须大于等于日预算，并发和频率须为有效正整数。',true);
const sub=t.services.map((_,i)=>moneyIn(document.getElementById('svcCap'+i).value));if(sub.some(v=>!Number.isSafeInteger(v)||v<=0))return tell('请输入大于零的服务日预算。',true);
if(back&&(db.n<2||sp===nt))return tell('备用出口须与主出口不同，并已列入批准集合。',true);
confirmAct('保存客户配置','更改将立即影响该客户的新请求。',()=>{Object.assign(t,{day:d,mo:m,conc:c,rpm:rp,net:nt,backup:back,spare:sp});t.services.forEach((v,i)=>v.day=sub[i]);log(t.id,'修改客户配置','日 '+usd(d)+'，月 '+usd(m)+'，主出口 '+routeData[nt][0]);tell('客户配置已保存。')})}
function pauseT(){const t=db.t[sel];if(t.state==='上游受限')return tell('上游限制需正式解除后才能恢复。',true);const v=t.state==='运营暂停'?'服务中':'运营暂停';confirmAct(v==='服务中'?'恢复客户':'暂停客户','只变更所选客户的新请求准入。',()=>{t.state=v;log(t.id,'客户状态',v);tell('客户状态已更新。')})}
function showPortal(){portal=true;msg='';render()}function leavePortal(){portal=false;msg='';render()}
function portalPage(){const t=db.t[sel];return title(t.name,'客户服务视图 · '+t.id)+'<div class="cards">'+card('今日用量费预估',usd(t.used),'演示当日 UTC')+card('在途预占',usd(t.hold),'尚未结算')+card('可用额度',usd(room(t)),'当日及本月剩余取低值')+'</div><div class="panel"><div class="rowHead"><h2>我的服务</h2>'+state(t)+'</div><div class="two"><div>日预算<span class="sub">'+usd(t.day)+'</span></div><div>本月预估累计<span class="sub">'+usd(t.month)+'</span></div></div><div class="band">上期业务服务账单　'+(db.reconciled?invoice(sel)+' · '+billRow(sel)[3]:'等待核对')+'</div><div class="toolbar"><span class="small">示例合同单列用量费与固定业务服务费。</span><button data-action="export-own">导出我的账单 CSV</button></div></div><div class="panel"><h2>我的服务记录</h2>'+eventList(db.events.filter(e=>e.tenant===t.id))+'</div>'}
function egress(){return title('迪拜出口','演示地址使用文档保留网段。真实上线需运营商证明与 AWS 源地址记录。')+'<section class="panel"><div class="rowHead"><h2>批准的地址集合</h2><div class="actions"><select id="poolN" aria-label="批准的地址数">'+[1,2,3].map(i=>'<option '+(i===db.n?'selected':'')+' value="'+i+'">'+i+' 个出口</option>').join('')+'</select><button data-action="change-count">应用数量</button></div></div>'+routeData.slice(0,db.n).map((r,i)=>'<div class="routeRow"><div><strong>'+r[0]+'</strong><span class="sub compact">'+r[1]+' / IPv4</span></div><div class="actions">'+badge(db.up[i]?'线路可用':'线路故障',db.up[i]?'ok':'bad')+'<button data-action="flip-route" data-index="'+i+'">'+(db.up[i]?'模拟断线':'恢复线路')+'</button></div></div>').join('')+'<div class="band">固定主出口的客户在线路故障时停发。允许备用的客户仅能切换到已批准的线路。上游封控或限流不会触发换线。</div></section><section class="panel"><h2>客户出口映射</h2><div class="scroller"><table><tr><th>客户</th><th>主出口</th><th>备用策略</th><th>当前可用路径</th></tr>'+db.t.map(t=>{const r=routePick(t);return '<tr><td>'+esc(t.name)+'</td><td>'+routeData[t.net][0]+'</td><td>'+(t.backup?'备用 '+routeData[t.spare][0]:'故障停发')+'</td><td>'+(r<0?'停发':routeData[r][0])+'</td></tr>'}).join('')+'</table></div></section>'}
function changeN(){const n=Number(document.getElementById('poolN').value);if(db.t.some(t=>t.net>=n||t.backup&&t.spare>=n))return tell('配置冲突，先在“客户与额度”调整被移除的主出口或备用策略。',true);if(n===db.n)return tell('批准的出口数量未改变。');confirmAct('调整批准集合','变更演示预登记的出口集合，现有客户的主备绑定继续以客户配置为准。',()=>{db.n=n;log('系统','调整出口集合','批准数量 '+n);tell('批准集合已更新。')})}
function flipRoute(i){const next=!db.up[i];confirmAct(next?'恢复线路':'模拟网络故障','将重新计算各客户可用的已批准路径。',()=>{db.up[i]=next;log('系统','线路'+(next?'恢复':'故障'),routeData[i][0]);tell(routeData[i][0]+' 已'+(next?'恢复。':'断线。'))})}
const est=[6240,1690,1120],aws=[6240,1840,1120],fees=[2000,1200,1500];function invoice(i){return db.reconciled&&aws[i]===est[i]?usd(aws[i]+fees[i]):'待复核'}
function receiptRows(i){const t=db.t[i];return [['账期 UTC','客户','客户编号','币种','合同用量费','固定业务服务费','应付金额','状态'],['2026-11-23',t.name,t.id,'USD',db.reconciled?(aws[i]/100).toFixed(2):'待核',(fees[i]/100).toFixed(2),invoice(i),db.reconciled?billRow(i)[3]:'等待导入']]}
function exportBill(i){if(portal&&sel!==i)return;const rows=receiptRows(i);const csv=rows.map(r=>r.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\r\n');const url=URL.createObjectURL(new Blob(['\uFEFF'+csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='Bill_2026-11-23_'+db.t[i].id+'.csv';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);}
function billRow(i){const v=aws[i]-est[i];return [usd(est[i]),usd(aws[i]),usd(v),v!==0?'有差异，待复核':'已核对']}
function billing(){return title('账单核对','样例账期　2026-11-23 UTC','<button class="mainBtn" data-action="reconcile">'+(db.reconciled?'重跑同一版本':'导入样例 CUR 并核对')+'</button>')+'<div class="cards">'+card('网关已归属预估','$90.50','按客户的用量明细')+card('AWS 用量小计',db.reconciled?'$92.80':'—','含尚未分配的费用')+card('未分配费用',db.reconciled?'$0.80':'—','缺少可核实的调用身份')+'</div><section class="panel"><h2>按客户核对</h2><div class="scroller"><table><tr><th>客户 / 调用角色</th><th>网关预估</th><th>AWS 用量费</th><th>差额</th><th>客户应付</th><th>状态</th><th>客户单</th></tr>'+db.t.map((t,i)=>{const b=billRow(i);return '<tr><td>'+esc(t.name)+'<span class="sub compact">'+t.role+'</span></td><td>'+b[0]+'</td><td>'+(db.reconciled?b[1]:'—')+'</td><td>'+(db.reconciled?b[2]:'—')+'</td><td>'+invoice(i)+'</td><td>'+badge(db.reconciled?b[3]:'等待导入',db.reconciled&&i!==1?'ok':'warn')+'</td><td><button data-action="export-bill" data-index="'+i+'">导出 CSV</button></td></tr>'}).join('')+'</table></div><div class="band">仅比较相同的用量费口径。未分配费用进入待核项。客户单另外计入约定的固定业务服务费。</div></section><section class="panel"><h2>待核对请求</h2><p class="notice">必须取得可关联的最终用量证据后关账。汇总 CUR 不能证明某一笔请求的费用。</p>'+(db.holds.length?db.holds.map((h,i)=>'<div class="routeRow"><div>'+db.t[h.tenant].id+' / '+esc(h.key)+'<span class="sub">保留预占 '+usd(h.amount)+'</span></div><button data-action="settle-hold" data-index="'+i+'">模拟收到最终用量凭证</button></div>').join(''):'<p class="small">当前没有在原型内新增的待核请求。</p>')+'</section>'}
function reconcile(){if(db.reconciled)return tell('同一 CUR 版本已处理，无重复入账。');db.reconciled=true;log('系统','核对样例 CUR','版本 v1 · 已归属差异 $1.50 · 未归属 $0.80');tell('样例账期核对完成，1 笔客户差异和 1 笔未分配费用待复核。')}
function settleHold(i){const h=db.holds[i];if(!h)return;confirmAct('模拟最终用量凭证','演示凭证包含同一请求号及费用 '+usd(Math.ceil(h.amount*.8))+'。',()=>{const t=db.t[h.tenant],svc=t.services[h.service],act=Math.ceil(h.amount*8/10);t.hold-=h.amount;svc.hold-=h.amount;t.open--;t.used+=act;svc.used+=act;t.month+=act;db.holds.splice(i,1);db.receipts[t.id+'|'+svc.id+'|'+h.key].result='200 已核实 '+usd(act);log(t.id,'核实未知结果',h.key+' · '+usd(act));tell('已按模拟凭证结算，并释放预占差额。')})}
function eventList(arr){return arr.length?arr.map(e=>'<div class="eventRow"><div><strong>'+esc(e.op)+'</strong><span class="sub">'+esc(e.detail)+'</span></div><div style="text-align:right">'+badge(e.tenant)+'<span class="sub compact">'+esc(e.time)+' UTC</span></div></div>').join(''):'<p class="notice">暂无记录。</p>'}
let auditFilter='全部';function audit(){const places=['全部','系统'].concat(db.t.map(t=>t.id));return title('操作记录','模拟配置变更、上游调用与人工核对事件。','<select aria-label="记录范围" data-field="audit-filter">'+places.map(s=>'<option '+(s===auditFilter?'selected':'')+'>'+s+'</option>').join('')+'</select>')+'<section class="panel"><div class="rowHead"><h2>事件时间线</h2><span class="type">最新在前</span></div>'+eventList(db.events.filter(e=>auditFilter==='全部'||e.tenant===auditFilter))+'</section>'}
function confirmAct(t,d,f){proc=f;document.getElementById('confirmTitle').textContent=t;document.getElementById('confirmText').textContent=d;openConfirmation()}
document.getElementById('confirmBtn').onclick=()=>{closeConfirmation();const fn=proc;proc=null;if(fn)fn()};document.getElementById('cancelBtn').onclick=()=>{proc=null;closeConfirmation()};
function resetDemo(){confirmAct('重置本机演示','恢复初始客户、额度、出口和账单样例。',()=>{db=seed();sel=0;page='overview';auditFilter='全部';Object.assign(sim,{idx:0,service:0,amount:'2.50',key:'REQ-1001',outcome:'正常完成'});tell('已恢复初始演示数据。')})}
function openConfirmation(){
 const dialog=document.getElementById('confirmBox');
 if(typeof dialog.showModal==='function')dialog.showModal();
 else dialog.setAttribute('open','');
}
function closeConfirmation(){
 const dialog=document.getElementById('confirmBox');
 if(typeof dialog.close==='function')dialog.close();
 else dialog.removeAttribute('open');
}
const actions={
 'send-request':sendSim,'save-tenant':saveTenant,'pause-tenant':pauseT,'show-portal':showPortal,
 'leave-portal':leavePortal,'reset-demo':resetDemo,'change-count':changeN,'reconcile':reconcile,
 'egress':()=>nav('egress'),'open-tenant':openTenant,'flip-route':flipRoute,'settle-hold':settleHold,
 'export-bill':exportBill,'export-own':()=>exportBill(sel)
};
const mount=document.getElementById('app');
mount.addEventListener('click',event=>{
 const target=event.target.closest('button');
 if(!target || target.disabled)return;
 if(target.dataset.nav){ nav(target.dataset.nav); return; }
 const handler=actions[target.dataset.action];
 if(handler)handler(target.dataset.index===undefined?undefined:Number(target.dataset.index));
});
mount.addEventListener('change',event=>{
 const input=event.target;
 switch(input.dataset.field){
 case 'tenant-filter':pick(input.value);break;
 case 'audit-filter':auditFilter=input.value;render();break;
 case 'sim-tenant':sim.idx=Number(input.value);sim.service=0;render();break;
 case 'sim-service':sim.service=Number(input.value);break;
 case 'sim-outcome':sim.outcome=input.value;break;
 }
});
mount.addEventListener('input',event=>{
 const field=event.target.dataset.field;
 if(field==='sim-amount')sim.amount=event.target.value;
 if(field==='sim-key')sim.key=event.target.value;
});
render();
