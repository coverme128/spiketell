import {useEffect,useState} from 'react';
import {api} from './types';

type Verification={symbol:string;name:string;state:string;message:string;session:string;data_mode:string;checked_at:string;blockers:string[];today_received_minutes:number;source_receive_delay_seconds:number|null;latest_bar_age_seconds:number|null;latest_final_bar:null|{bar_start_at:string;bar_end_at:string;received_at:string;source:string;open:string;high:string;low:string;close:string;amount_cny:string};latest_decision:null|{bar_start_at:string;details:{error:string|null;priority:string;ret1_pct:string|null;turnover_burst:string|null;reasons:string[];risks:string[]}};baseline:{historical_days:number;slots_with_five_days:number};calibration:{message?:string;error?:string}};
const stamp=(s:string)=>new Date(s).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
const decisionErrors:Record<string,string>={NO_TRIGGER:'尚未达到异动阈值',INSUFFICIENT_CONTIGUOUS_BARS:'等待可比的连续分钟',LOW_TURNOVER:'本分钟成交额低于 100 万元',DIAGNOSTIC_ONLY:'仅记录冲高回落风险',STALE_BAR:'该分钟已过期'};
export function StockVerification({symbol,onClose,reasons}:{symbol:string;onClose:()=>void;reasons:Record<string,string>}){
 const [value,setValue]=useState<Verification|null>(null);const [error,setError]=useState('');
 useEffect(()=>{let active=true;const refresh=()=>api<Verification>('/watchlist/'+symbol+'/verification').then(v=>{if(active){setValue(v);setError('')}}).catch(e=>{if(active)setError(String(e))});void refresh();const timer=setInterval(()=>void refresh(),10000);return()=>{active=false;clearInterval(timer)}},[symbol]);
 const b=value?.latest_final_bar;const d=value?.latest_decision;
 return <dialog open className="verification-dialog" aria-label="个股实盘验证"><div className="dialog-head"><h2>{value?.name??symbol} · 实盘验证</h2><button aria-label="关闭实盘验证" onClick={onClose}>×</button></div>{error&&<p role="alert">{error}；当前显示为上次结果。</p>}{value?<>
 <p><strong>{value.message}</strong></p><p className="muted">{value.data_mode} · 状态核对 {stamp(value.checked_at)} · 每 10 秒刷新</p>
 {value.blockers.length>0&&<div className="verification-blockers"><strong>暂停或等待原因</strong><ul>{value.blockers.map(r=><li key={r}>{reasons[r]??r}</li>)}</ul>{value.calibration.message&&<p>{value.calibration.message}</p>}{value.calibration.error&&<small>{value.calibration.error}</small>}</div>}
 <p>今日已存完整分钟 {value.today_received_minutes} 根；历史 {value.baseline.historical_days} 日，{value.baseline.slots_with_five_days}/237 个分钟时段具备五日成交基准。</p>
 <p className="muted">基准不足时，符合条件的快速价格关注仍可提醒；不会产生 HIGH 或认定横盘放量突破。</p>
 <h3>最后接收的完整分钟</h3>{b?<><p>{stamp(b.bar_start_at)} — {stamp(b.bar_end_at)}<br/>系统收到 {stamp(b.received_at)} · 接收延迟 {value.source_receive_delay_seconds?.toFixed(1)} 秒</p><p>开 {b.open} / 高 {b.high} / 低 {b.low} / 收 {b.close}<br/>成交额 {(Number(b.amount_cny)/10000).toFixed(2)} 万元 · {b.source}</p><p className="muted">这根分钟距现在 {Math.max(0,value.latest_bar_age_seconds??0).toFixed(0)} 秒；历史数据不会当作新实盘提醒。</p></>:<p>尚未接收通过校准与最终化检查的分钟线。没有填入演示行情。</p>}
 <h3>最后一次检测</h3>{d?<><p>{stamp(d.bar_start_at)} 开始的分钟 · {decisionErrors[d.details.error??'']??d.details.error??d.details.priority}</p><p>{d.details.reasons.join('；')} {d.details.risks.join('；')}</p></>:<p>尚未形成检测记录；休市、校准和冷启动期间不会补发历史异动。</p>}
 <a className="text-button" href={'/api/v1/watchlist/'+symbol+'/verification'} target="_blank" rel="noreferrer">查看本股验证记录 JSON ↗</a>
 </>:<p>正在读取实际采集状态…</p>}</dialog>
}
