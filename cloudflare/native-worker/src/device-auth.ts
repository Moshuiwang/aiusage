import type { Env } from './index';
import { authTokens, isAuthenticated } from './auth';
import { json } from './http';
import { validateLimitsPayload } from './write-model/validate';

type DeviceIdentity = { request_id:string; source_ids:string; read_allowed:number };
const MAX_PENDING=16, MAX_DEVICES=64, HOURLY_LIMIT=32, TTL_MS=10*60*1000;
const failure=(status:number,error_type:string)=>json({status:'error',error_type},status);
const now=(env:Env)=>new Date(env.AIUSAGE_NOW??Date.now()).toISOString();
const bearer=(request:Request)=>request.headers.get('Authorization')?.match(/^Bearer (.{1,256})$/i)?.[1]??'';
export async function digest(value:string):Promise<string> {
 return [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value)))].map(x=>x.toString(16).padStart(2,'0')).join('');
}
export async function deviceIdentity(request:Request,env:Env):Promise<DeviceIdentity|null>{
 const token=bearer(request);
 if(!token.startsWith('dvc_'))return null;
 try{return await env.AIUSAGE_DB.prepare('SELECT request_id,source_ids,read_allowed FROM device_credentials WHERE credential_hash=? AND revoked_at IS NULL').bind(await digest(token)).first<DeviceIdentity>();}
 catch{return null;}
}
export async function canRead(request:Request,env:Env):Promise<boolean>{
 if(await isAuthenticated(request,env))return true;
 return (await deviceIdentity(request,env))?.read_allowed===1;
}
export function ownsPayload(payload:unknown,identity:DeviceIdentity,limits=false):boolean{
 const allowed=new Set<string>(JSON.parse(identity.source_ids));
 function check(value:unknown):boolean{
  if(Array.isArray(value))return value.every(check);
  if(value&&typeof value==='object'){
   return Object.entries(value).every(([key,item])=>key==='source_id'?typeof item==='string'&&allowed.has(item):check(item));
  }
  return true;
 }
 if(!check(payload))return false;
 if(limits){
  try{return validateLimitsPayload(payload).windows.every(window=>allowed.has(window.source_id));}
  catch{return true;} // Canonical schema validation will reject malformed payloads before any write.
 }
 return true;
}
class InvalidBody extends Error {}
async function object(request:Request):Promise<Record<string,unknown>>{
 const reader=request.body?.getReader();
 const chunks:Uint8Array[]=[];let length=0;
 if(!reader)throw new InvalidBody();
 try{
  for(;;){const part=await reader.read();if(part.done)break;length+=part.value.length;
   if(length>4096){await reader.cancel();throw new InvalidBody();}chunks.push(part.value);}
  const bytes=new Uint8Array(length);let offset=0;
  for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
  const body:unknown=JSON.parse(new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(bytes));
  if(!body||typeof body!=='object'||Array.isArray(body))throw new InvalidBody();
  return body as Record<string,unknown>;
 }catch{throw new InvalidBody();}finally{reader.releaseLock();}
}
function administratorToken(env:Env):string|undefined {
 const token=env.AIUSAGE_DEVICE_ADMIN_TOKEN?.trim();
 return token && !authTokens(env).includes(token) ? token : undefined;
}
async function operator(request:Request,env:Env):Promise<boolean>{
 const token=administratorToken(env);
 return !!token && bearer(request)===token;
}
export async function deviceRoute(request:Request,env:Env):Promise<Response|null>{
 const path=new URL(request.url).pathname;
 if(!path.startsWith('/api/devices'))return null;
 try{
  if(path==='/api/devices/self'&&request.method==='GET'){
   const device=await deviceIdentity(request,env);
   return device?json({status:'approved',request_id:device.request_id,source_ids:JSON.parse(device.source_ids),read_allowed:device.read_allowed===1}):failure(401,'device_unauthorized');
  }
  if(path==='/api/devices/enrollments'&&request.method==='POST'){
   if(!administratorToken(env))return failure(503,'device_admin_unconfigured');
   const data=await object(request);
   const fields=['source_ids','machine','os_user','platform','credential_hash','request_secret_hash','read_requested'];
   if(Object.keys(data).some(key=>!fields.includes(key)))return failure(400,'invalid_registration');
   const ids=data.source_ids;
   if(!Array.isArray(ids)||ids.length<1||ids.length>8||new Set(ids).size!==ids.length||ids.some(id=>typeof id!=='string'||!/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(id)))return failure(400,'invalid_registration');
   for(const key of ['machine','os_user'])if(typeof data[key]!=='string'||!(data[key] as string).length||(data[key] as string).length>128||/[\x00-\x1f\x7f]/.test(data[key] as string))return failure(400,'invalid_registration');
   if(!['linux','darwin'].includes(String(data.platform))||typeof data.read_requested!=='boolean'||!['credential_hash','request_secret_hash'].every(key=>typeof data[key]==='string'&&/^[a-f0-9]{64}$/.test(data[key] as string)))return failure(400,'invalid_registration');
   const time=now(env),hour=time.slice(0,13);
   const existing=await env.AIUSAGE_DB.prepare('SELECT request_id,user_code,expires_at FROM device_enrollment_requests WHERE credential_hash=? AND request_secret_hash=? AND expires_at>?').bind(data.credential_hash,data.request_secret_hash,time).first();
   if(existing)return json(existing,201);
   const id=crypto.randomUUID(),code=crypto.randomUUID().replaceAll('-','').slice(0,10).toUpperCase();
   const expiry=new Date(Date.parse(time)+TTL_MS).toISOString();
   const db=env.AIUSAGE_DB;
   const results=await db.batch([
    db.prepare('DELETE FROM device_enrollment_requests WHERE expires_at<=?').bind(time),
    db.prepare('DELETE FROM device_enrollment_budget WHERE hour<?').bind(hour),
    db.prepare('INSERT OR IGNORE INTO device_enrollment_budget(hour,count) VALUES(?,0)').bind(hour),
    db.prepare(`INSERT OR IGNORE INTO device_enrollment_requests(request_id,user_code,request_secret_hash,credential_hash,source_ids,machine,os_user,platform,read_requested,created_at,expires_at)
     SELECT ?,?,?,?,?,?,?,?,?,?,? WHERE (SELECT count FROM device_enrollment_budget WHERE hour=?)<? AND (SELECT COUNT(*) FROM device_enrollment_requests WHERE status='pending')<? AND (SELECT COUNT(*) FROM device_credentials)<?`)
     .bind(id,code,data.request_secret_hash,data.credential_hash,JSON.stringify(ids),data.machine,data.os_user,data.platform,data.read_requested?1:0,time,expiry,hour,HOURLY_LIMIT,MAX_PENDING,MAX_DEVICES),
    db.prepare('UPDATE device_enrollment_budget SET count=count+1 WHERE hour=? AND EXISTS(SELECT 1 FROM device_enrollment_requests WHERE request_id=?)').bind(hour,id),
   ]);
   if(!results[3].meta.changes)return failure(429,'registration_limit_reached');
   return json({request_id:id,user_code:code,expires_at:expiry},201);
  }
  const statusMatch=path.match(/^\/api\/devices\/enrollments\/([a-f0-9-]{36})\/status$/);
  if(statusMatch&&request.method==='POST'){
   const data=await object(request);
   if(typeof data.request_secret!=='string'||data.request_secret.length>128)return failure(401,'invalid_request_secret');
   const row=await env.AIUSAGE_DB.prepare('SELECT status,expires_at FROM device_enrollment_requests WHERE request_id=? AND request_secret_hash=?').bind(statusMatch[1],await digest(data.request_secret)).first<{status:string;expires_at:string}>();
   if(!row)return failure(401,'invalid_request_secret');
   if(row.expires_at<=now(env))return failure(410,'registration_expired');
   return json({status:row.status,expires_at:row.expires_at});
  }
  if(!administratorToken(env))return failure(503,'device_admin_unconfigured');
  if(!(await operator(request,env)))return failure(401,'operator_auth_required');
  if(path==='/api/devices/enrollments'&&request.method==='GET'){
   const result=await env.AIUSAGE_DB.prepare("SELECT request_id,user_code,source_ids,machine,os_user,platform,read_requested,status,created_at,expires_at FROM device_enrollment_requests WHERE status='pending' AND expires_at>? ORDER BY created_at").bind(now(env)).all();
   return json({requests:result.results.map(row=>({...row,source_ids:JSON.parse(String(row.source_ids)),read_requested:row.read_requested===1}))});
  }
  if(path==='/api/devices'&&request.method==='GET'){
   const result=await env.AIUSAGE_DB.prepare('SELECT request_id,source_ids,read_allowed,approved_at,revoked_at FROM device_credentials ORDER BY approved_at').all();
   return json({devices:result.results.map(row=>({...row,source_ids:JSON.parse(String(row.source_ids)),read_allowed:row.read_allowed===1}))});
  }
  const action=path.match(/^\/api\/devices\/enrollments\/([a-f0-9-]{36})\/(approve|deny)$/);
  if(action&&request.method==='POST'){
   const id=action[1],time=now(env),db=env.AIUSAGE_DB;
   if(action[2]==='deny'){
    const result=await db.prepare("UPDATE device_enrollment_requests SET status='denied' WHERE request_id=? AND status='pending' AND expires_at>?").bind(id,time).run();
    return result.meta.changes?json({status:'denied'}):failure(409,'registration_not_pending');
   }
   const data=await object(request);
   if(typeof data.read_allowed!=='boolean')return failure(400,'invalid_approval');
   const read=data.read_allowed?1:0;
   // Idempotent retry is allowed only for the same grant; it cannot expand an approved device.
   const grant=await db.prepare('SELECT read_allowed,revoked_at FROM device_credentials WHERE request_id=?').bind(id).first<{read_allowed:number;revoked_at:string|null}>();
   if(grant)return grant.read_allowed===read&&!grant.revoked_at?json({status:'approved'}):failure(409,'approval_conflict');
   const results=await db.batch([
    db.prepare(`INSERT OR IGNORE INTO device_credentials(credential_hash,request_id,source_ids,read_allowed,approved_at)
     SELECT credential_hash,request_id,source_ids,?,? FROM device_enrollment_requests WHERE request_id=? AND status='pending' AND expires_at>? AND (?=0 OR read_requested=1) AND NOT EXISTS(SELECT 1 FROM device_credentials c,json_each(c.source_ids) owned,json_each(device_enrollment_requests.source_ids) requested WHERE c.revoked_at IS NULL AND owned.value=requested.value)`).bind(read,time,id,time,read),
    db.prepare("UPDATE device_enrollment_requests SET status='approved' WHERE request_id=? AND status='pending' AND EXISTS(SELECT 1 FROM device_credentials WHERE request_id=? AND read_allowed=?)").bind(id,id,read),
   ]);
   return results[0].meta.changes?json({status:'approved'}):failure(409,'registration_not_pending');
  }
  const revoke=path.match(/^\/api\/devices\/([a-f0-9-]{36})\/revoke$/);
  if(revoke&&request.method==='POST'){
   const result=await env.AIUSAGE_DB.prepare('UPDATE device_credentials SET revoked_at=COALESCE(revoked_at,?) WHERE request_id=?').bind(now(env),revoke[1]).run();
   return result.meta.changes?json({status:'revoked'}):failure(404,'device_not_found');
  }
  return failure(404,'device_route_not_found');
 }catch(error){return error instanceof InvalidBody?failure(400,'invalid_registration'):failure(503,'device_registration_unavailable');}
}
