import { beforeEach, describe, expect, it } from 'vitest';
import { readFile } from 'node:fs/promises';
import { acquireWorker, applySqlText } from './golden/harness';
import { token as legacyToken } from './golden/paths';
const token='device-admin-test-token';
import type { Miniflare } from 'miniflare';

async function hash(value: string): Promise<string> {
 return Buffer.from(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value))).toString('hex');
}

describe.sequential('device registration and source-scoped authentication',()=>{
 let mf:Miniflare; let db:D1Database;
 const credential='dvc_test_device_credential_012345678901234567890';
 const secret='enrollment_secret_012345678901234567890123456';
 async function request(path:string, body?:unknown, auth?:string, method?:string){
  const headers:Record<string,string>={'Content-Type':'application/json'};
  if(auth)headers.Authorization='Bearer '+auth;
  return mf.dispatchFetch('https://example.test'+path,{method:method??(body?'POST':'GET'),headers,body:body?JSON.stringify(body):undefined});
 }
 async function begin(){
  const response=await request('/api/devices/enrollments',{source_ids:['new-linux','new-linux-codex'],machine:'new-linux',os_user:'alice',platform:'linux',credential_hash:await hash(credential),request_secret_hash:await hash(secret),read_requested:false});
  expect(response.status).toBe(201);
  return await response.json() as {request_id:string;user_code:string;expires_at:string};
 }
 beforeEach(async()=>{
  ({mf,db}=await acquireWorker({AIUSAGE_NOW:'2026-10-02T00:00:00Z',AIUSAGE_DEVICE_ADMIN_TOKEN:token}));
  await applySqlText(db,await readFile('cloudflare/migrations/0015_device_enrollment.sql','utf8'));
  await db.exec('DELETE FROM device_credentials; DELETE FROM device_enrollment_requests; DELETE FROM device_enrollment_budget;');
 });
 it('requires approval and never returns a credential or secret to an operator',async()=>{
  const pending=await begin();
  expect((await request('/api/devices/self',undefined,credential)).status).toBe(401);
  const list=await request('/api/devices/enrollments',undefined,token);
  const text=await list.text();
  const listed=JSON.parse(text);expect(listed.requests).toHaveLength(1);expect(listed.requests[0].source_ids).toEqual(['new-linux','new-linux-codex']);expect(listed.requests[0].read_requested).toBe(false);
  expect(list.status).toBe(200);expect(text).toContain('new-linux');expect(text).toContain(pending.user_code);
  expect(text).not.toContain(await hash(credential));expect(text).not.toContain(secret);
  expect((await request('/api/devices/enrollments/'+pending.request_id+'/approve',{read_allowed:false},legacyToken)).status).toBe(401);
  const approval=await request('/api/devices/enrollments/'+pending.request_id+'/approve',{read_allowed:false},token);
  expect(approval.status).toBe(200);
  expect((await request('/api/devices/self',undefined,credential)).status).toBe(200);
  expect((await request('/api/health',undefined,credential)).status).toBe(403);
  const wrong=await request('/api/devices/enrollments/'+pending.request_id+'/status',{request_secret:'wrong'});
  expect(wrong.status).toBe(401);
  const status=await request('/api/devices/enrollments/'+pending.request_id+'/status',{request_secret:secret});
  expect((await status.json() as {status:string}).status).toBe('approved');
 });
 it('device credentials cannot approve devices or claim another source',async()=>{
  const pending=await begin();
  await request('/api/devices/enrollments/'+pending.request_id+'/approve',{read_allowed:false},token);
  expect((await request('/api/devices/enrollments/'+pending.request_id+'/approve',{read_allowed:true},credential)).status).toBe(401);
  expect((await request('/ingest',{source_id:'other-machine'},credential)).status).toBe(403);
  expect((await request('/ingest-limits',{windows:[{source_id:'other-machine'}]},credential)).status).toBe(403);
  const window={provider:'codex',window:'five_hour',reset_at:'2026-10-02T05:00:00Z',observed_at:'2026-10-02T00:00:00Z',window_duration_minutes:300,used_percent:10,remaining_percent:90,source_type:'codex_wham',confidence:'observed',status:'ok'};
  const implicit=await request('/ingest-limits',{schema_version:1,observed_at:'2026-10-02T00:00:00Z',windows:[window]},credential);
  expect(implicit.status).toBe(403);
  // The owned-source request reaches schema validation rather than being rejected by authentication.
  expect((await request('/ingest',{source_id:'new-linux'},credential)).status).toBe(400);
 });
 it('revocation takes effect for ingest and self immediately',async()=>{
  const pending=await begin();
  await request('/api/devices/enrollments/'+pending.request_id+'/approve',{read_allowed:false},token);
  const response=await request('/api/devices/'+pending.request_id+'/revoke',{},token);
  expect(response.status).toBe(200);
  expect((await request('/api/devices/self',undefined,credential)).status).toBe(401);
  expect((await request('/ingest',{source_id:'new-linux'},credential)).status).toBe(401);
 });
 it('expired and denied requests cannot become active; repeat approval cannot expand access',async()=>{
  const pending=await begin();
  await db.prepare('UPDATE device_enrollment_requests SET expires_at=? WHERE request_id=?').bind('2026-10-01T00:00:00Z',pending.request_id).run();
  expect((await request('/api/devices/enrollments/'+pending.request_id+'/approve',{read_allowed:false},token)).status).toBe(409);
  expect((await request('/api/devices/self',undefined,credential)).status).toBe(401);
  await db.exec('DELETE FROM device_enrollment_requests;');
  const next=await begin();
  await request('/api/devices/enrollments/'+next.request_id+'/approve',{read_allowed:false},token);
  expect((await request('/api/devices/enrollments/'+next.request_id+'/approve',{read_allowed:true},token)).status).toBe(409);
  expect((await request('/api/health',undefined,credential)).status).toBe(403);
 });
 it('allows requested read permission, rejects source collisions and malformed JSON',async()=>{
  const input={source_ids:['new-linux'],machine:'new-linux',os_user:'alice',platform:'linux',credential_hash:await hash(credential),request_secret_hash:await hash(secret),read_requested:true};
  const first=await request('/api/devices/enrollments',input);expect(first.status).toBe(201);
  const pending=await first.json() as {request_id:string};
  expect((await request('/api/devices/enrollments/'+pending.request_id+'/approve',{read_allowed:true},token)).status).toBe(200);
  expect((await request('/api/health',undefined,credential)).status).toBe(200);
  const second=await request('/api/devices/enrollments',{...input,credential_hash:await hash(credential+'2')});expect(second.status).toBe(201);
  const other=await second.json() as {request_id:string};
  expect((await request('/api/devices/enrollments/'+other.request_id+'/approve',{read_allowed:false},token)).status).toBe(409);
  expect((await request('/api/devices/self',undefined,credential+'2')).status).toBe(401);
  const malformed=await mf.dispatchFetch('https://example.test/api/devices/enrollments',{method:'POST',body:'{'});expect(malformed.status).toBe(400);
  const count=await db.prepare('SELECT COUNT(*) AS n FROM device_credentials').first<{n:number}>();expect(count?.n).toBe(1);
 });
 it('supports retiring shared tokens without anonymous access or trusting the admin key for ingest',async()=>{
  ({mf,db}=await acquireWorker({AIUSAGE_NOW:'2026-10-02T00:00:00Z',AIUSAGE_DEVICE_ADMIN_TOKEN:token,AIUSAGE_TOKEN:'',AIUSAGE_TOKEN_SPECS:'',AIUSAGE_BACKEND_MODE:'native_d1_production'}));
  const pending=await begin();
  expect((await request('/ingest',{})).status).toBe(401);
  expect((await request('/api/summary')).status).toBe(401);
  expect((await request('/ingest',{},token)).status).toBe(401);
  expect((await request('/api/devices/enrollments/'+pending.request_id+'/approve',{read_allowed:false},token)).status).toBe(200);
  expect((await request('/api/devices/self',undefined,credential)).status).toBe(200);
  expect((await request('/ingest',{source_id:'new-linux'},credential)).status).toBe(400);
  expect((await request('/api/health',undefined,credential)).status).toBe(403);
 });
 it('rejects configuration that reuses a shared collector token as the administrator',async()=>{
  ({mf,db}=await acquireWorker({AIUSAGE_DEVICE_ADMIN_TOKEN:legacyToken}));
  expect((await request('/api/devices/enrollments',undefined,legacyToken)).status).toBe(503);
  expect((await request('/api/devices/enrollments',{})).status).toBe(503);
 });
 it('enforces bounded registrations and rejects malformed identities without storing them',async()=>{
  const invalid=await request('/api/devices/enrollments',{source_ids:['../bad'],credential_hash:'secret'});
  expect(invalid.status).toBe(400);
  const count=await db.prepare('SELECT COUNT(*) AS n FROM device_enrollment_requests').first<{n:number}>();expect(count?.n).toBe(0);
  await begin();
  await db.prepare('UPDATE device_enrollment_budget SET count=32').run();
  const blocked=await request('/api/devices/enrollments',{source_ids:['second'],machine:'second',os_user:'alice',platform:'linux',credential_hash:await hash(credential+'2'),request_secret_hash:await hash(secret+'2'),read_requested:false});
  expect(blocked.status).toBe(429);
 });
});
