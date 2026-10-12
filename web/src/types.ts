import type {Movements} from './MovementPanel';
export type Scenario = 'RAPID_RISE'|'MOMENTUM_ACCELERATION'|'VOLUME_BREAKOUT'|'SPIKE_REVERSAL';
export type Card = {
  primary_scenario?:Scenario|null;matched_scenarios?:Scenario[];is_attention_eligible?:boolean;
  episode_id:string;symbol:string;name:string;priority:'HIGH'|'MEDIUM'|'LOW';episode_state:string;
  score:number;last_bar_end_at:string;trigger_bar_start_at:string;received_at:string;updated_at:string;
  reference_close_cny:string;ret1_pct:string;ret3_pct:string|null;turnover_burst:string|null;
  action:string;reasons:string[];risks:string[];feed_health:string;data_mode:string;rule_version:string;
};
export type Feed = {status:string;session:string;updated_at:string;available_count:number;monitored_count:number;last_bar_end_at:string|null;reasons:string[];data_mode:string;release_status:string};
export type CardEvidence = {amount_cny:string;source:string};
export type Diagnostic = {symbol:string;bar_end_at:string;received_at:string;event_types:string[];data_mode:string};
export type Radar = {movements?:Movements;scenario_diagnostics?:Diagnostic[];feed:Feed;monitored_count:number;available_count:number;today_episode_count:number;high_count:number;top_cards:Card[];risk_cards?:Card[];all_cards:Card[];historical_cards:Card[];cursor:number;card_evidence:Record<string,CardEvidence>};
export type Watch = {symbol:string;name:string;enabled:boolean;source_state:string;last_bar_end_at:string|null;preparation?:{state:string;message:string;error?:string};baseline?:{historical_days:number;slots_with_five_days:number;semantics_verified:boolean}};
export type Settings = {quiet_mode:boolean;notification_enabled:boolean;max_watchlist:number;retention_days?:number};
export type EpisodeEvent = {event_id:string;audit_sequence:number;event_type:string;next_state:string;recorded_at:string;source:string;rule_version:string;source_received_at:string;bar_end_at:string;delivery_mode:string;alert_kind:string|null;episode_id:string;card:Card};
export type Detail = {card:Card;history:EpisodeEvent[];bars:Record<string,unknown>[];metrics?:{prior20_high_cny:string|null;pullback_pct:string|null;ignored:boolean}};
export async function api<T>(path:string, init?:RequestInit):Promise<T> {
  const response = await fetch('/api/v1'+path,{...init,headers:{'Content-Type':'application/json',...init?.headers}});
  if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(body.message||(typeof body.detail==='string'?body.detail:`请求失败 (${response.status})`))}
  return response.status===204 ? undefined as T : response.json();
}
