import {datasets,jobs,calibrations} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {table} from '../components/common/table.js';
import {esc,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';

export async function workbench(){
 workspace.datasets=await datasets.list();
 workspace.calibrations=await calibrations.list();
 const m=workspace.meta,selectable=workspace.calibrations.filter(s=>s.status==='published'&&s.consistent!==false);
 return heading('03 / ANALYSIS LAB',m.workbench_title,'选择业务批次、分析口径与校时方案。参数、输入指纹、校时快照与计算结论随任务保存，便于复核和复现。')+'<div class="workbench-grid"><section class="panel"><form id="job-form"><label>分析任务名称<input name="name" required minlength="2" value="'+esc(m.name)+' · 复核试算"></label><label>数据批次<select name="dataset_id" required>'+workspace.datasets.map(d=>'<option value="'+d.id+'">'+esc(d.name)+' · '+d.rows+' 条</option>').join('')+'</select></label><label>校时方案<select name="calibration_scheme_id"><option value="">不应用校时（按原始读数）</option>'+selectable.map(s=>'<option value="'+s.id+'">'+esc(s.name)+' · 修订 '+s.revision+' · 参考 '+esc(s.reference_service)+'</option>').join('')+'</select></label><div class="parameter-grid">'+m.parameters.map(p=>'<label>'+esc(p.label)+(p.type==='select'?'<select name="param-'+esc(p.key)+'">'+p.options.map(o=>'<option value="'+esc(o.value)+'" '+(o.value==p.default?'selected':'')+'>'+esc(o.label)+'</option>').join('')+'</select>':'<input type="number" step="any" name="param-'+esc(p.key)+'" value="'+esc(p.default)+'" min="'+esc(p.min??'')+'" max="'+esc(p.max??'')+'" required>')+'</label>').join('')+'</div><button type="submit" class="primary" '+(session.user.role==='viewer'||!workspace.datasets.length?'disabled':'')+'>'+esc(m.action_label||'执行分析')+' ↗</button><p class="hint">选用校时方案时，只有全部可行校时下都成立的跟随才计为确定。方案须先在校时凭据页发布；断开的服务会被拒绝联合分析。</p></form></section><section class="method-sheet"><p class="eyebrow">METHOD / BUSINESS RULE</p><h2>'+esc(m.method)+'</h2><p>'+esc(m.tagline)+'</p><h3>业务判读边界</h3><ul>'+m.limitations.map(v=>'<li>'+esc(v)+'</li>').join('')+'</ul><div class="method-trace"><span>输入</span><strong>'+esc(m.dataset_name)+'</strong><span>输出</span><strong>可复核结果 / 校时快照 / 参数版本 / 分发归档</strong></div></section></div>';
}
export function bindWorkbench(){
 submit(document.querySelector('#job-form'),async f=>{
  const params={};for(const p of workspace.meta.parameters){const value=f.get('param-'+p.key);params[p.key]=p.type==='number'?Number(value):value;}
  const payload={name:f.get('name'),dataset_id:Number(f.get('dataset_id')),params};
  const scheme=f.get('calibration_scheme_id');
  if(scheme)payload.calibration_scheme_id=Number(scheme);
  const j=await jobs.create(payload);workspace.selectedJob=j.id;notify('分析任务已提交');location.hash='#/results/'+j.id;
 });
}
