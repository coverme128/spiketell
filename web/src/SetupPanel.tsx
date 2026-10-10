import {useEffect,useState} from 'react';
import {api} from './types';

type Setup = {baseline_ready_count:number;eligible_watch_count:number;enabled_watch_count:number;baseline_status:'READY'|'WARMING'|'UNAVAILABLE';provider:{personal_use_confirmed?:boolean;timestamp_semantics?:string;finalization_verified?:boolean;capacity_verified?:boolean;qualified_pool_size?:number};calendar_ready:boolean;clock_ready:boolean;calibration:{state:string;message:string};measurements:{complete_sessions:number;coverage_ratio:number|null;visible_alert_p95_seconds:number|null;visible_alert_samples:number};maintenance:{database_check?:string}};

export function SetupPanel(){
 const [value,setValue]=useState<Setup|null>(null);const [error,setError]=useState('');const [accepted,setAccepted]=useState(false);const [saving,setSaving]=useState(false);
 const refresh=()=>api<Setup>('/setup').then(setValue).catch(()=>{});
 useEffect(()=>{void refresh();const timer=setInterval(()=>void refresh(),10000);return()=>clearInterval(timer)},[]);
 if(!value)return null;
 const p=value.provider;
 const stages=[['交易日历',value.calendar_ready],['本机时钟',value.clock_ready],['分钟边界与收盘确认',p.finalization_verified],['自选池采集能力',p.capacity_verified]] as const;
 return <section className="setup-panel" aria-label="真实行情接入"><div className="section-heading"><h2>真实行情准备</h2><span>{p.finalization_verified&&p.capacity_verified?'接入检查通过':'自动检查中'}</span></div>
 {!p.personal_use_confirmed?<><p>数据来自东方财富与新浪公开行情接口。确认你具备所选数据源的个人使用权限后，开始本机采集与盘中核验。</p><p><a href="https://github.com/akfamily/akshare" target="_blank" rel="noreferrer">查看数据源项目与使用说明 ↗</a></p><label><input type="checkbox" checked={accepted} onChange={e=>setAccepted(e.target.checked)}/> 我已核实数据使用范围，仅在本机个人使用</label><button className="primary" disabled={!accepted||saving} onClick={async()=>{setSaving(true);try{setValue(await api<Setup>('/setup/source',{method:'POST',body:JSON.stringify({personal_use_confirmed:true})}));setError('')}catch(e){setError(String(e))}finally{setSaving(false)}}}>{saving?'正在保存…':'开始真实行情准备'}</button></>:<><div className="setup-stages">{stages.map(([title,ready])=><span key={title} className={ready?'ready':''}>{ready?'✓':'○'} {title}</span>)}</div><p>{value.calibration.message}{p.qualified_pool_size?` · 已测股票池 ${p.qualified_pool_size} 只`:''}</p><p className="muted">休市时准备证券资料和历史数据；盘中自动校准。未通过检查的股票暂停提醒。</p></>}
 <p className="muted">已启用 {value.enabled_watch_count??0} 只 · 当前资料合格 {value.eligible_watch_count??0} 只 · 全时段成交基准就绪 {value.baseline_ready_count??0}/{value.eligible_watch_count??0}。{value.baseline_status==='READY'?'成交基准已就绪。':'成交基准积累中；符合条件的快速价格关注可先使用，缺基准不发 HIGH。'}</p>
 {error&&<p className="error" role="alert">{error}</p>}
 <details><summary>实盘运行记录</summary><p>完整 50 股交易日：{value.measurements.complete_sessions} / 2 · 有效分钟覆盖率：{value.measurements.coverage_ratio===null?'尚无样本':(value.measurements.coverage_ratio*100).toFixed(1)+'%'} · 可见提醒 p95：{value.measurements.visible_alert_p95_seconds===null?'尚无样本':value.measurements.visible_alert_p95_seconds.toFixed(1)+' 秒'}</p><p>这些数据来自实际运行，不使用模拟样本补齐。<a href="/api/v1/measurements" target="_blank" rel="noreferrer">查看完整记录</a></p></details></section>
}
