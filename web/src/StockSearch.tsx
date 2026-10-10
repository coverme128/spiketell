import {useEffect,useState} from 'react';
import {api} from './types';

export function StockSearch({onAdded}:{onAdded:()=>void}){
 const [query,setQuery]=useState('');const [items,setItems]=useState<{symbol:string;name:string}[]>([]);const [message,setMessage]=useState('');const [busy,setBusy]=useState(false);
 useEffect(()=>{let current=true;if(!query.trim()){setItems([]);return}const timer=setTimeout(()=>{setMessage('正在搜索真实证券…');void api<{items:typeof items}>('/instruments/search?q='+encodeURIComponent(query)).then(r=>{if(current){setItems(r.items);setMessage(r.items.length?'':'未找到支持的沪深 A 股')}}).catch(()=>{if(current)setMessage('证券搜索暂不可用，可稍后重试')})},350);return()=>{current=false;clearTimeout(timer)}},[query]);
 return <div className="stock-search"><label>搜索证券名称或代码<input aria-label="搜索证券" placeholder="例如：浦发银行 / 600000" value={query} onChange={e=>setQuery(e.target.value)}/></label>{message&&<small role="status">{message}</small>}{items.length>0&&<ul>{items.map(item=><li key={item.symbol}><span><strong>{item.name}</strong> <small>{item.symbol}</small></span><button disabled={busy} onClick={async()=>{setBusy(true);try{const r=await api<{items:{status:string;reason?:string}[]}>('/watchlist',{method:'POST',body:JSON.stringify({symbols:[item.symbol]})});setMessage(r.items[0].status==='ADDED'?'已添加，正在准备真实行情':r.items[0].status==='ALREADY_EXISTS'?'已在自选股中':r.items[0].reason||'暂时无法添加');onAdded()}catch(e){setMessage(String(e))}finally{setBusy(false)}}}>添加</button></li>)}</ul>}</div>
}
