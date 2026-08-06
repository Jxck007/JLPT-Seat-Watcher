document.documentElement.classList.add("js");
const REFRESH_INTERVAL_MS = 60_000;
const DATA_FILES=["status.json","history.json","metrics.json","health.json"];
const $=id=>document.getElementById(id), n=v=>v===null||v===undefined||v===""||Number.isNaN(Number(v))?null:Number(v);
const valid=v=>v&&!Number.isNaN(new Date(v).getTime());
const date=v=>valid(v)?new Intl.DateTimeFormat("en-IN",{dateStyle:"medium",timeStyle:"short",timeZone:"Asia/Kolkata"}).format(new Date(v)):"Awaiting data";
const short=v=>valid(v)?new Intl.DateTimeFormat("en-IN",{month:"short",day:"numeric",hour:"2-digit",minute:"2-digit",timeZone:"Asia/Kolkata"}).format(new Date(v)):"Awaiting data";
const text=(id,v)=>{if($(id))$(id).textContent=v};
let feeds={},refreshing=false;
function render(){
  const s=feeds.status||{},m=feeds.metrics||{},h=feeds.health||{},seats=s.seats||{};
  const remaining=n(s.current_remaining??s.remaining_seats??seats.remaining),applied=s.applied??seats.applied,total=s.total??seats.total;
  const last=s.last_check??s.checked_at, next=s.next_check, workflow=String(s.workflow_status??h.workflow_status??"unknown").toLowerCase();
  text("remaining",remaining===null?"–":remaining.toLocaleString());text("applied",applied??"–");text("total",total??"–");text("last-check",short(last));text("next-check",short(next));text("updated",valid(last)?`Updated ${short(last)}`:"Awaiting first check");
  const badge=$("availability-status");if(badge){badge.className="status-badge "+(remaining===null?"":remaining>0?"is-available":"is-full");badge.textContent=remaining===null?"Loading":remaining>0?"Available":"Full"}
  const stale=Boolean(h.stale)||(valid(last)&&Date.now()-new Date(last).getTime()>15*60*1000),failed=workflow==="failure"||workflow==="failed"||h.healthy===false;
  text("monitor-title",failed?"Failed":stale?"Delayed":"Healthy");const dot=$("health-dot");if(dot)dot.className="dot "+(failed?"is-failed":stale?"is-full":"is-available");
  const alert=s.last_notification??m.last_successful_alert??h.last_successful_alert;const alertAt=typeof alert==="object"?alert?.at:alert;
  text("last-heartbeat",valid(h.last_heartbeat_at??s.last_heartbeat_at)?date(h.last_heartbeat_at??s.last_heartbeat_at):"Not sent yet");text("last-alert",valid(alertAt)?date(alertAt):"No seat alert yet");
}
async function load(file){const response=await fetch(`${file}?refresh=${Date.now()}`,{cache:"no-store"});if(!response.ok)throw Error(response.status);return response.json()}
async function refresh(){if(refreshing)return;refreshing=true;try{const values=await Promise.all(DATA_FILES.map(load));DATA_FILES.forEach((file,i)=>feeds[file.slice(0,-5)]=values[i]);render();$("offline").hidden=true}catch{const box=$("offline");box.hidden=false;box.textContent="Live data unavailable · showing last published state"}finally{refreshing=false}}
function theme(){const saved=localStorage.getItem("jlpt-dashboard-theme")||"dark";document.documentElement.dataset.theme=saved;$("theme-toggle").onclick=()=>{const next=document.documentElement.dataset.theme==="dark"?"light":"dark";localStorage.setItem("jlpt-dashboard-theme",next);document.documentElement.dataset.theme=next}}
document.addEventListener("DOMContentLoaded",()=>{theme();$("refresh").onclick=refresh;refresh();setInterval(refresh,REFRESH_INTERVAL_MS)});
