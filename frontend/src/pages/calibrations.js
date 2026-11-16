import {calibrations} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {table} from '../components/common/table.js';
import {esc,fmt,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';

const STATUS={'draft':'草稿','published':'已发布','revoked':'已撤销','active':'有效'};
const statusLabel=s=>'<span class="status '+esc(s)+'">'+esc(STATUS[s]||s)+'</span>';

function rangeTable(solution){
 const ranges=solution?.ranges||{},names=Object.keys(ranges).sort();
 if(!names.length)return '<p class="empty">尚无凭据，无法计算可行时间范围。</p>';
 return '<div class="table-wrap"><table><thead><tr><th>服务</th><th>相对参考服务的修正下限(min)</th><th>修正上限(min)</th><th>是否连通</th></tr></thead><tbody>'+
  names.map(name=>{const r=ranges[name];return '<tr><td>'+esc(name)+'</td><td>'+(r.lower===null?'—':esc(fmt(r.lower)))+'</td><td>'+(r.upper===null?'—':esc(fmt(r.upper)))+'</td><td>'+(r.reachable?'与参考服务连通':'<strong>断开，拒绝联合分析</strong>')+'</td></tr>';}).join('')+
  '</tbody></table></div>';
}

function conflictBlock(solution){
 if(solution?.consistent!==false)return '<p class="hint">当前有效凭据无矛盾。</p>';
 return (solution.conflicts||[]).map(c=>'<div class="warning"><strong>'+esc((c.credential_ids||[]).map(id=>'#'+id).join('、'))+'</strong><p>'+esc(c.message)+'</p><p>'+esc(c.steps.map(s=>s.from+'→'+s.to+(s.direction==='reverse'?'（反向）':'')).join(' · '))+'</p></div>').join('');
}

export async function calibrationPage(id){
 const list=await calibrations.list();workspace.calibrations=list;
 const selectedId=id?Number(id):(list[0]?.id||null);
 const raw=selectedId?await calibrations.get(selectedId):null;
 const detail=raw?{...raw,...(await calibrations.affected(selectedId))}:null;
 const canWrite=session.user.role!=='viewer',isAdmin=session.user.role==='admin';
 const listHtml=list.map(s=>'<a class="batch-item" href="#/calibrations/'+s.id+'"><strong>'+esc(s.name)+'</strong><span>'+statusLabel(s.status)+' · 修订 '+s.revision+' · '+(s.consistent?'凭据一致':'<strong>存在冲突链</strong>')+'</span><small>参考服务 '+esc(s.reference_service)+' · '+s.service_count+' 个连通服务</small></a>').join('')||'<p class="empty">尚未登记校时方案。</p>';
 const formBlock=canWrite?'<form id="scheme-form"><label>方案名称<input name="name" required minlength="2" placeholder="例如：第46周告警时钟校时"></label><label>参考服务<input name="reference_service" required value="cache" placeholder="以哪个服务的时钟为基准"></label><label>登记说明<textarea name="note" rows="2" placeholder="校时方法与凭据来源"></textarea></label><button type="submit" class="primary">登记草稿 ↗</button><p class="hint">草稿发布后才能被分析试验选用；发布前可先登记、撤销凭据并检查冲突链。</p></form>':'<p class="hint">观察员只读校时方案、可行范围与冲突链。</p>';
 const credForm=detail&&canWrite&&detail.status!=='revoked'?'<form id="credential-form" class="inline-form"><div class="parameter-grid"><label>源服务<input name="source_service" required placeholder="cache"></label><label>目标服务<input name="target_service" required placeholder="api-gateway"></label></div><div class="parameter-grid"><label>允许偏差下限(min)<input name="lower_min" type="number" step="any" required value="-1"></label><label>允许偏差上限(min)<input name="upper_min" type="number" step="any" required value="1"></label></div><p class="hint">语义：目标服务读数 − 源服务读数 ∈ [下限, 上限]；可间接推导未直接登记的服务对。</p><button type="submit" class="primary">登记凭据</button></form>':'';
 const credRows=(detail?.credentials||[]).map(c=>'<tr><td>#'+c.id+'</td><td>'+esc(c.source_service)+' → '+esc(c.target_service)+'</td><td>['+esc(fmt(c.lower_min))+', '+esc(fmt(c.upper_min))+']</td><td>'+statusLabel(c.status)+'</td><td>'+esc(c.note)+'</td><td>'+(c.status==='active'&&isAdmin?'<button class="text-button" data-revoke-cred="'+c.id+'">撤销凭据</button>':'')+'</td></tr>').join('');
 const conflictRows=conflictBlock(detail?.solution);
 const affected=detail?.affected||{jobs:[],reports:[],deliveries:[]};
 const revocations=detail?.revocations||[];
 const jobRows=affected.jobs.map(j=>'<tr><td>#'+j.id+'</td><td>'+esc(j.name)+'</td><td>'+esc(j.status)+'</td><td>'+(j.approved?'已批准':'未批准')+'</td><td>'+(j.invalidated?'<strong>已失效</strong>':'有效')+'</td><td>'+esc(j.invalidation_reason||'')+'</td></tr>').join('');
 const reportRows=affected.reports.map(r=>'<tr><td>#'+r.id+'</td><td>'+esc(r.name)+'</td><td>'+(r.enabled?'运行':'已暂停')+'</td><td>'+(r.basis_revoked?'依据撤销':'有效')+'</td><td>'+esc(r.revocation_note||'')+'</td></tr>').join('');
 const deliveryRows=affected.deliveries.map(d=>'<tr><td>#'+d.id+'</td><td>'+esc(d.filename)+'</td><td>'+(d.basis_revoked?'依据撤销':'有效')+'</td><td>'+date(d.created_at)+'</td><td>'+esc(d.revocation_note||'')+'</td></tr>').join('');
 const solution=detail?.solution;
 return heading('06 / CLOCK CALIBRATION','服务间校时凭据与方案','登记服务间校时凭据和允许误差，求各服务的可行时间范围与冲突链；只把所有可行校时下都成立的跟随计为确定。断开的服务拒绝联合分析。')+
 '<div class="dataset-grid"><section class="panel"><div class="section-title"><h2>校时方案</h2><span>'+list.length+' 个</span></div><div class="batch-list">'+listHtml+'</div><div class="section-title"><h2>登记新方案</h2></div>'+formBlock+'</section><section class="panel">'+
 (detail?'<div class="section-title"><h2>'+esc(detail.name)+'</h2>'+statusLabel(detail.status)+'</div><p class="hint">参考服务 '+esc(detail.reference_service)+' · 修订 '+detail.revision+' · 最近发布 '+esc(detail.published_at?date(detail.published_at):'尚未发布')+'</p>'+
  (detail.status==='draft'&&isAdmin?'<button class="primary" id="publish-scheme">发布方案（发布后供试验选用）</button> ':'')+
  (detail.status!=='revoked'&&isAdmin?'<button class="button" id="revoke-scheme">撤销整个方案</button>':'')+
  (detail.status==='revoked'?'<p class="warning">方案已撤销：'+esc(detail.revocation_note||'')+'</p>':'')+
  '<div class="section-title"><h2>可行时间范围</h2><span>由凭据及间接关系闭包求得</span></div>'+rangeTable(solution)+
  '<div class="section-title"><h2>冲突链</h2><span>'+(solution?.consistent===false?'存在矛盾凭据':'无矛盾')+'</span></div>'+conflictRows+
  '<div class="section-title"><h2>服务间可行时差回查</h2></div><form id="range-form" class="inline-form"><div class="parameter-grid"><label>先发生服务<input name="source" value="cache" required></label><label>后继服务<input name="target" value="api-gateway" required></label></div><button type="submit" class="button">求可行时差范围</button></form><div id="range-result" class="hint"></div>'+
  '<div class="section-title"><h2>凭据</h2><span>'+(detail.credentials||[]).length+' 条</span></div>'+
  ((detail.credentials||[]).length?'<div class="table-wrap"><table><thead><tr><th>编号</th><th>服务对</th><th>允许误差(min)</th><th>状态</th><th>说明</th><th></th></tr></thead><tbody>'+credRows+'</tbody></table></div>':'<p class="empty">尚无凭据。</p>')+credForm+
  '<div class="section-title"><h2>受影响的试验与材料</h2><span>撤销即失效，不恢复资格</span></div>'+
  (jobRows?'<div class="table-wrap"><table><thead><tr><th>试验</th><th>名称</th><th>状态</th><th>批准</th><th>有效</th><th>失效原因</th></tr></thead><tbody>'+jobRows+'</tbody></table></div>':'<p class="hint">暂无试验选用此方案。</p>')+
  (reportRows?'<div class="table-wrap"><table><thead><tr><th>简报</th><th>名称</th><th>运行</th><th>依据</th><th>说明</th></tr></thead><tbody>'+reportRows+'</tbody></table></div>':'')+
  (deliveryRows?'<div class="table-wrap"><table><thead><tr><th>归档</th><th>文件</th><th>依据</th><th>生成时间</th><th>说明</th></tr></thead><tbody>'+deliveryRows+'</tbody></table></div>':'')+
  (revocations.length?'<div class="section-title"><h2>撤销登记</h2><span>每条凭据仅一次</span></div><div class="table-wrap"><table><thead><tr><th>凭据</th><th>原因</th><th>操作者</th><th>修订</th><th>时间</th></tr></thead><tbody>'+revocations.map(r=>'<tr><td>#'+r.credential_id+'</td><td>'+esc(r.reason)+'</td><td>'+esc(r.requested_by)+'</td><td>'+r.revision+'</td><td>'+date(r.at)+'</td></tr>').join('')+'</tbody></table></div>':'')
  :'<p class="empty">从左侧选择一个校时方案，或先登记草稿。</p>')+
 '</section></div>';
}

export function bindCalibration(refresh){
 const schemeForm=document.querySelector('#scheme-form');
 if(schemeForm)submit(schemeForm,async f=>{const s=await calibrations.create({name:f.get('name'),reference_service:f.get('reference_service'),note:f.get('note')||''});notify('校时方案草稿已登记');location.hash='#/calibrations/'+s.id;await refresh();});
 const credForm=document.querySelector('#credential-form');
 if(credForm)submit(credForm,async f=>{const id=Number((location.hash.split('/')[2]||''));await calibrations.addCredential(id,{source_service:f.get('source_service'),target_service:f.get('target_service'),lower_min:Number(f.get('lower_min')),upper_min:Number(f.get('upper_min'))});notify('凭据已登记，可检查冲突链');await refresh();});
 const publish=document.querySelector('#publish-scheme');
 if(publish)publish.onclick=async()=>{try{const id=Number(location.hash.split('/')[2]);await calibrations.publish(id);notify('方案已发布，可在分析工作台选用');await refresh();}catch(e){notify(e.message,true);}};
 const revokeScheme=document.querySelector('#revoke-scheme');
 if(revokeScheme)revokeScheme.onclick=async()=>{const id=Number(location.hash.split('/')[2]);const reason=prompt('撤销方案原因（将立即失效所有依赖试验与材料）');if(reason===null)return;try{await calibrations.revoke(id,reason);notify('方案已撤销，依赖试验失效');await refresh();}catch(e){notify(e.message,true);}};
 document.querySelectorAll('[data-revoke-cred]').forEach(b=>b.onclick=async()=>{const id=Number(location.hash.split('/')[2]);const reason=prompt('撤销凭据原因（依赖试验将立即失效）');if(reason===null)return;try{await calibrations.revokeCredential(id,Number(b.dataset.revokeCred),reason);notify('凭据已撤销');await refresh();}catch(e){notify(e.message,true);}});
 const rangeForm=document.querySelector('#range-form');
 if(rangeForm)rangeForm.addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(rangeForm),id=Number(location.hash.split('/')[2]);const out=document.querySelector('#range-result');try{const r=await calibrations.range(id,f.get('source'),f.get('target'));out.innerHTML='<p>在全部可行校时下，'+esc(r.source)+' 与 '+esc(r.target)+' 的修正差落在 ['+esc(fmt(r.lower_min))+', '+esc(fmt(r.upper_min))+'] 分钟。</p>';}catch(error){out.innerHTML='<p class="warning">'+esc(error.message)+'</p>';}});
}
