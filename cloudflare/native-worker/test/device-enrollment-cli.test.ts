import { beforeAll, afterAll, describe, expect, it } from 'vitest';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp, readFile, writeFile, stat, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { Miniflare } from 'miniflare';
import { bundleWorker, applySqlText } from './golden/harness';
import { repoRoot, schemaPath } from './golden/paths';

const execute = promisify(execFile);
const admin = 'local-enrollment-cli-admin-fixture';
const shared = 'local-enrollment-cli-shared-fixture';
const python = process.env.AIUSAGE_TEST_PYTHON ?? 'python3';

describe.sequential('Python device CLI over verified local HTTPS to the real Worker', () => {
  let mf: Miniflare;
  let db: D1Database;
  let folder: string;
  let server: string;
  let ca: string;
  let sequence = 0;

  beforeAll(async () => {
    folder = await mkdtemp(path.join(tmpdir(), 'aiusage-cli-https-'));
    ca = path.join(folder, 'localhost-cert.pem');
    const key = path.join(folder, 'localhost-key.pem');
    await execute('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes',
      '-keyout', key, '-out', ca, '-days', '1', '-subj', '/CN=localhost',
      '-addext', 'subjectAltName=IP:127.0.0.1']);
    mf = new Miniflare({ modules: true, script: await bundleWorker(), scriptPath: 'index.mjs',
      compatibilityDate: '2026-06-21', host: '127.0.0.1', port: 0,
      https: true, httpsKeyPath: key, httpsCertPath: ca, d1Databases: ['AIUSAGE_DB'],
      bindings: { AIUSAGE_TOKEN: shared, AIUSAGE_DEVICE_ADMIN_TOKEN: admin,
        AIUSAGE_NOW: '2026-10-04T00:00:00Z', AIUSAGE_BACKEND_MODE: 'native_d1_production',
        AIUSAGE_DISABLE_SUMMARY_CACHE: 'true' } });
    server = (await mf.ready).origin;
    expect(new URL(server).hostname).toBe('127.0.0.1');
    expect(new URL(server).protocol).toBe('https:');
    db = await mf.getD1Database('AIUSAGE_DB');
    await applySqlText(db, await readFile(schemaPath, 'utf8'));
    await applySqlText(db, await readFile(path.join(repoRoot, 'cloudflare/migrations/0015_device_enrollment.sql'), 'utf8'));
  }, 30000);

  afterAll(async () => {
    await mf?.dispose();
    if (folder) await rm(folder, { recursive: true, force: true });
  });

  async function cli(args: string[], operator = admin, trustCertificate = ca) {
    const code = 'import sys;sys.path.insert(0,sys.argv.pop(1));from ai_usage_widget.cli import main;raise SystemExit(main(sys.argv[1:]))';
    const { stdout } = await execute(python, ['-I', '-c', code, path.join(repoRoot, 'src'), 'devices', ...args], {
      env: { ...process.env, SSL_CERT_FILE: trustCertificate, AI_USAGE_DEVICE_ADMIN_TOKEN: operator }, timeout: 20000,
    });
    return JSON.parse(stdout);
  }

  async function enroll(read: boolean, withAntigravity = false) {
    const pending = path.join(folder, `pending-${++sequence}.json`);
    const source = `local-cli-${sequence}`;
    const args = ['enroll', '--server', server, '--pending', pending,
      '--source-id', source, '--source-id', source + '-codex'];
    if (withAntigravity) args.push('--source-id', source + '-antigravity');
    if (read) args.push('--read');
    const request = await cli(args);
    expect(request.source_ids).toEqual([source, source + '-codex', ...(withAntigravity ? [source + '-antigravity'] : [])]);
    expect(request.read_requested).toBe(read);
    expect((await stat(pending)).mode & 0o777).toBe(0o600);
    const retry = await cli(args);
    expect(retry.request_id).toBe(request.request_id);
    const state = JSON.parse(await readFile(pending, 'utf8'));
    expect(JSON.stringify(request)).not.toContain(state.credential);
    expect(JSON.stringify(request)).not.toContain(state.request_secret);
    return { pending, source, request, credential: state.credential as string };
  }

  async function probe(url: string, credential: string, body?: unknown) {
    return mf.dispatchFetch(server + url, { method: body ? 'POST' : 'GET',
      headers: { Authorization: 'Bearer ' + credential, 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined });
  }

  it('TLS verification rejects an untrusted local certificate before registration', async () => {
    const before = await db.prepare('SELECT COUNT(*) AS n FROM device_enrollment_requests').first<{ n: number }>();
    await expect(cli(['enroll', '--server', server, '--pending', path.join(folder, 'untrusted.json'), '--source-id', 'untrusted-device'], admin, '')).rejects.toHaveProperty('code', 2);
    const after = await db.prepare('SELECT COUNT(*) AS n FROM device_enrollment_requests').first<{ n: number }>();
    expect(after?.n).toBe(before?.n);
  });

  it('Mac permission remains pending, then activates privately and preserves display settings', async () => {
    const { pending, source, request, credential } = await enroll(true);
    const config = path.join(folder, 'display.json');
    await writeFile(config, JSON.stringify({ server_url: server, timezone: 'Asia/Shanghai', extra: 'preserved' }));
    expect((await cli(['check', '--pending', pending, '--display-config', config])).status).toBe('pending');
    expect(JSON.parse(await readFile(config, 'utf8')).token).toBeUndefined();
    await expect(cli(['approve', '--server', server, '--request-id', request.request_id, '--read'], shared)).rejects.toHaveProperty('code', 2);
    const listed = await cli(['list', '--server', server]);
    expect(listed.requests).toHaveLength(1);
    expect(listed.requests[0].source_ids).toEqual([source, source + '-codex']);
    expect(JSON.stringify(listed)).not.toContain(credential);
    expect((await cli(['approve', '--server', server, '--request-id', request.request_id, '--read'])).status).toBe('approved');
    // Lost approval responses can be retried without creating a second grant.
    expect((await cli(['approve', '--server', server, '--request-id', request.request_id, '--read'])).status).toBe('approved');
    const result = await cli(['check', '--pending', pending, '--display-config', config]);
    expect(result.status).toBe('activated');
    expect(JSON.stringify(result)).not.toContain(credential);
    const saved = JSON.parse(await readFile(config, 'utf8'));
    expect(saved.timezone).toBe('Asia/Shanghai'); expect(saved.extra).toBe('preserved');
    expect(saved.token === credential).toBe(true);
    expect((await stat(config)).mode & 0o777).toBe(0o600);
    await expect(stat(pending)).rejects.toHaveProperty('code', 'ENOENT');
    expect((await probe('/api/mobile/summary', credential)).status).toBe(200);
    expect((await probe('/ingest', credential, { source_id: 'another-device' })).status).toBe(403);
    const count = await db.prepare('SELECT COUNT(*) AS n FROM device_credentials WHERE request_id=?').bind(request.request_id).first<{ n: number }>();
    expect(count?.n).toBe(1);
  });

  it('Linux grant cannot read or administer other devices and revocation is immediate', async () => {
    const { pending, source, request, credential } = await enroll(false);
    const env = path.join(folder, 'linux-token.env');
    expect((await cli(['approve', '--server', server, '--request-id', request.request_id])).status).toBe('approved');
    expect((await cli(['check', '--pending', pending, '--token-env-file', env])).status).toBe('activated');
    expect((await readFile(env, 'utf8')) === 'AI_USAGE_INGEST_TOKEN=' + credential + '\n').toBe(true);
    expect((await stat(env)).mode & 0o777).toBe(0o600);
    expect((await probe('/api/health', credential)).status).toBe(403);
    expect((await probe('/api/devices/enrollments', credential)).status).toBe(401);
    expect((await probe('/ingest', credential, { source_id: source })).status).toBe(400);
    expect((await probe('/ingest', credential, { source_id: 'another-device' })).status).toBe(403);
    expect((await cli(['revoke', '--server', server, '--request-id', request.request_id])).status).toBe('revoked');
    expect((await probe('/api/devices/self', credential)).status).toBe(401);
    expect((await probe('/ingest', credential, { source_id: source })).status).toBe(401);
  });

  async function publishLimits(source: string, credential: string, healthy: boolean, observed: string) {
    const fixture = path.join(folder, source + '-limits.json');
    // The collector owner emits the fixture; no hand-written wire payload or raw user logs.
    const generate = [
      'import sys,json;sys.path.insert(0,sys.argv[1])',
      'from ai_usage_widget.limits import LimitWindow',
      'from ai_usage_widget.limits_runtime import _failed_window',
      'path,source,healthy,observed=sys.argv[2:];healthy=healthy=="true"',
      'providers={}',
      'for provider,percent,kind in [("codex",20,"runtime_api"),("antigravity",1,"language_server")]:',
      ' window=LimitWindow(provider=provider,source_id=source+"-"+provider,window="week",used_percent=percent,remaining_percent=100-percent,reset_at="2026-10-11T00:00:00Z",window_duration_minutes=10080,observed_at=observed,source_type=kind,confidence="observed",status="ok") if healthy else _failed_window(provider,observed,source_id=source+"-"+provider)',
      ' providers[provider]=[window.to_snapshot_dict()]',
      'with open(path,"w") as output:json.dump({"providers":providers},output)',
    ].join('\n');
    await execute(python, ['-I', '-c', generate, path.join(repoRoot, 'src'), fixture, source, String(healthy), observed]);
    const code = 'import sys;sys.path.insert(0,sys.argv.pop(1));from ai_usage_widget.cli import main;raise SystemExit(main(sys.argv[1:]))';
    const args = ['-I', '-c', code, path.join(repoRoot, 'src'), 'push-limits',
      '--provider-fixture', fixture, '--url', server + '/ingest-limits'];
    let stdout: string;
    try {
      ({ stdout } = await execute(python, args, {
        env: { ...process.env, SSL_CERT_FILE: ca, AI_USAGE_INGEST_TOKEN: credential }, timeout: 20000,
      }));
      expect(healthy).toBe(true);
    } catch (error) {
      const failed = error as { code: number; stdout: string };
      expect(healthy).toBe(false);
      expect(failed.code).toBe(1);
      stdout = failed.stdout;
    }
    const result = JSON.parse(stdout);
    expect(result.success).toBe(healthy);
    expect(result.delivered).toBe(true);
    expect(result.windows_collected).toBe(2);
    expect(result.windows_written).toBe(2);
    expect(JSON.stringify(result)).not.toContain(credential);
    return result;
  }

  it('activated device publishes two official windows; other-device failures cannot mask them', async () => {
    const good = await enroll(true, true);
    const config = path.join(folder, 'quota-display.json');
    expect((await cli(['approve', '--server', server, '--request-id', good.request.request_id, '--read'])).status).toBe('approved');
    expect((await cli(['check', '--pending', good.pending, '--display-config', config])).status).toBe('activated');
    const saved = JSON.parse(await readFile(config, 'utf8'));
    expect(saved.token === good.credential).toBe(true);
    await publishLimits(good.source, saved.token, true, '2026-10-03T23:00:00Z');
    const bad = await enroll(false, true);
    expect((await cli(['approve', '--server', server, '--request-id', bad.request.request_id])).status).toBe('approved');
    expect((await cli(['check', '--pending', bad.pending, '--token-env-file', path.join(folder, 'quota-ingest.env')])).status).toBe('activated');
    await publishLimits(bad.source, bad.credential, false, '2026-10-03T23:30:00Z');
    for (const endpoint of ['/api/summary', '/api/mobile/summary']) {
      const response = await probe(endpoint, saved.token);
      expect(response.status).toBe(200);
      const summary = await response.json() as { provider_slots: { provider: string; quota: { status: string; source_id: string; last_verified_at: string; windows: Record<string, unknown>[] } }[] };
      expect(summary.provider_slots).toHaveLength(3);
      for (const [provider, percent] of [['codex', 20], ['antigravity', 1]] as const) {
        const quota = summary.provider_slots.find(slot => slot.provider === provider)?.quota;
        expect(quota?.status).toBe('available');
        expect(quota?.source_id).toBe(good.source + '-' + provider);
        expect(Date.parse(quota!.last_verified_at)).toBe(Date.parse('2026-10-03T23:00:00Z'));
        expect(quota?.windows).toHaveLength(1);
        const window = quota!.windows[0];
        expect(window.source_id).toBe(quota?.source_id);
        expect(window.official).toBe(true); expect(window.confidence).toBe('observed'); expect(window.status).toBe('ok');
        expect(window.used_percent).toBe(percent);
        expect(Date.parse(String(window.reset_at))).toBe(Date.parse('2026-10-11T00:00:00Z'));
      }
    }
    // A later failure on the same owned source must still remove its current availability.
    await publishLimits(good.source, saved.token, false, '2026-10-03T23:45:00Z');
    const degraded = await (await probe('/api/mobile/summary', saved.token)).json() as { provider_slots: { provider: string; quota: { status: string } }[] };
    const affected = degraded.provider_slots.filter(slot => ['codex', 'antigravity'].includes(slot.provider));
    expect(affected).toHaveLength(2);
    expect(affected.map(slot => slot.quota.status)).toEqual(['missing', 'missing']);
    expect((await cli(['revoke', '--server', server, '--request-id', good.request.request_id])).status).toBe('revoked');
    expect((await probe('/api/mobile/summary', saved.token)).status).toBe(401);
  });

  it('denied and expired requests never activate; an approved grant survives request expiry', async () => {
    const denied = await enroll(false);
    const env = path.join(folder, 'denied.env');
    expect((await cli(['deny', '--server', server, '--request-id', denied.request.request_id])).status).toBe('denied');
    expect((await cli(['check', '--pending', denied.pending, '--token-env-file', env])).status).toBe('denied');
    await expect(stat(env)).rejects.toHaveProperty('code', 'ENOENT');
    const expired = await enroll(false);
    await db.prepare('UPDATE device_enrollment_requests SET expires_at=? WHERE request_id=?').bind('2026-10-03T00:00:00Z', expired.request.request_id).run();
    await expect(cli(['approve', '--server', server, '--request-id', expired.request.request_id])).rejects.toHaveProperty('code', 2);
    expect((await probe('/api/devices/self', expired.credential)).status).toBe(401);
    const approved = await enroll(false);
    expect((await cli(['approve', '--server', server, '--request-id', approved.request.request_id])).status).toBe('approved');
    await db.prepare('UPDATE device_enrollment_requests SET expires_at=? WHERE request_id=?').bind('2026-10-03T00:00:00Z', approved.request.request_id).run();
    expect((await cli(['check', '--pending', approved.pending, '--token-env-file', path.join(folder, 'approved.env')])).status).toBe('activated');
  });
});
