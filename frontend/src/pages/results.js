import {jobs} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {chart} from '../components/common/chart.js';
import {table} from '../components/common/table.js';
import {status} from '../components/common/status.js';
import {esc,fmt,date,notify} from '../utils/dom.js';

function calibrationSheet(j,r){
 const cal=r.calibration||(j.calibration_snapshot?.solution?{...j.calibration_snapshot.solution,scheme_id:j.calibration_snapshot.scheme_id,revision:j.calibration_snapshot.revision}:null);
 const scheme=j.calibration_scheme_id;
 if(!scheme&&!cal)return '<p class="hint">本次试验未选用校时方案，按原始读数判定先后；时钟偏差可能颠倒故障顺序。</p>';
 const ranges=(cal?.ranges||{});
 const scheduleBlock='<p>依据校时方案 <a class="text-link" href="#/calibrations/'+esc(scheme)+'">#'+esc(scheme)+'</a> 修订 '+esc(j.calibration_revision)+'，参考服务 '+esc(cal?.reference||j.calibration_snapshot?.reference||'')+'。结果只代表创建时的快照；方案撤销或修订后自动失效。</p>'+
  (j.invalidated?'<p class="warning">该试验已失效：'+esc(j.invalidation_reason)+'。结果仅供追溯，不能批准或分发。</p>':'')+
  '<div class="table-wrap"><table><thead><tr><th>服务</th><th>可行修正下限(min)</th><th>可行修正上限(min)</th></tr></thead><tbody>'+Object.keys(ranges).sort().map(k=>'<tr><td>'+esc(k)+'</td><td>'+(ranges[k].lower===null?'—':esc(fmt(ranges[k].lower)))+'</td><td>'+(ranges[k].upper===null?'—':esc(fmt(ranges[k].upper)))+'</td></tr>').join('')+'</tbody></table></div>'+
  ((cal?.conflicts||[]).length?'<p class="warning">冲突链：'+esc(cal.conflicts.map(c=>c.message).join(' | '))+'</p>':'');
 return scheduleBlock;
}

function pendingTable(examples){
 if(!examples?.length)return '';
 return '<section class="panel"><div class="section-title"><h2>待定跟随样例</h2><span>可行校时下顺序会变化</span></div><div class="table-wrap"><table><thead><tr><th>先发生服务</th><th>后继服务</th><th>源事件</th><th>可行时滞下限(min)</th><th>可行时滞上限(min)</th></tr></thead><tbody>'+examples.map(x=>'<tr><td>'+esc(x.source)+'</td><td>'+esc(x.target)+'</td><td>'+esc(x.source_event)+'</td><td>'+esc(fmt(x.lag_low))+'</td><td>'+esc(fmt(x.lag_high))+'</td></tr>').join('')+'</tbody></table></div></section>';
}

export async function results(id){
 workspace.jobs=await jobs.list();const j=id?await jobs.get(id):(workspace.jobs.find(j=>j.id===workspace.selectedJob)||workspace.jobs[0]);
 if(j&&!workspace.jobs.some(x=>x.id===j.id))workspace.jobs.push(j);
 if(!j)return heading('04 / REVIEW','结果复核','尚无分析结果。')+'<div class="empty">先到分析工作台，选择批次并提交一次计算。<a href="#/workbench">前往工作台 ↗</a></div>';
 workspace.selectedJob=j.id;const r=j.result||{};
 const canApprove=session.user.role==='admin'&&!j.approved&&!j.invalidated;
 return heading('04 / REVIEW','结果复核与业务解释',j.name,'<button class="button" id="refresh-results">刷新结果 ↻</button>')+'<div class="result-selector"><label>分析记录<select id="select-job">'+workspace.jobs.map(x=>'<option value="'+x.id+'" '+(x.id===j.id?'selected':'')+'>'+esc(x.name)+' · '+esc(x.status)+(x.invalidated?' · 已失效':'')+'</option>').join('')+'</select></label>'+status(j.status)+'<span>'+date(j.created_at)+'</span><span class="approval">'+(j.invalidated?'依据撤销，试验失效':(j.approved?'已获业务批准':'待负责人复核'))+'</span></div>'+(j.status==='completed'?'<section class="result-lead"><p class="eyebrow">COMPUTED FINDING</p><h2>'+esc(r.summary)+'</h2><div class="metrics">'+(r.metrics||[]).map(m=>'<div><span>'+esc(m.label)+'</span><strong>'+esc(fmt(m.value))+'<small>'+esc(m.unit||'')+'</small></strong></div>').join('')+'</div></section><section class="panel">'+chart(r.chart)+'</section><div class="two-columns"><section class="panel"><div class="section-title"><h2>业务解释</h2><span>由计算结果生成</span></div><ol class="questions">'+(r.findings||[]).map(v=>'<li>'+esc(v)+'</li>').join('')+'</ol>'+(r.warnings||[]).map(v=>'<p class="warning">'+esc(v)+'</p>').join('')+'</section><section class="method-sheet compact"><p class="eyebrow">REPRODUCIBILITY</p><h3>计算口径与参数</h3><p>'+esc(r.method)+'</p><pre>'+esc(JSON.stringify(j.params,null,2))+'</pre>'+(canApprove?'<button class="primary" id="approve-job">批准此业务结论</button>':'')+'<p class="hint">仅批准结果可进入定时分发档案；校时依据被撤销后批准与分发都会被拒绝。</p><div class="method-trace"><span>校时</span><div>'+calibrationSheet(j,r)+'</div></div></section></div><section class="panel"><div class="section-title"><h2>结果明细</h2><span>'+(r.table?.rows?.length||0)+' 行</span></div>'+table(r.table?.columns||[],r.table?.rows||[])+'</section>'+pendingTable(r.pending_examples):'<section class="panel empty">'+(j.status==='failed'?'计算失败：'+esc(j.error)+'。请返回工作台调整参数或数据。':'后台正在执行计算。点击刷新结果查看最新进展。')+'<a href="#/workbench">返回工作台 ↗</a></section>');
}
export function bindResults(refresh){document.querySelector('#refresh-results')?.addEventListener('click',refresh);document.querySelector('#select-job')?.addEventListener('change',e=>{workspace.selectedJob=Number(e.target.value);location.hash='#/results/'+e.target.value;});document.querySelector('#approve-job')?.addEventListener('click',async()=>{try{await jobs.approve(workspace.selectedJob);notify('已批准，可创建分发计划');await refresh();}catch(e){notify(e.message,true);}});}
