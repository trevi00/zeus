'use strict';
// Real filesystem/Git/CLI observations. No mocked upstream modules or services.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const CLI = '/source/get-shit-done/bin/gsd-tools.cjs';
const root = fs.mkdtempSync('/tmp/zeus-gsd-observation-');
fs.mkdirSync('/tmp/home', { recursive: true });
const outputs = [];

function write(base, relative, text) {
  const target = path.resolve(base, relative);
  if (!target.startsWith(root + path.sep)) throw new Error('scratch containment');
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, text);
}

function run(cwd, command, args) {
  const started = Date.now();
  console.log(JSON.stringify({ event: 'command-start', cwd, command, args }));
  const result = spawnSync(command, args, { cwd, encoding: 'utf8', timeout: 15000 });
  console.log(JSON.stringify({ event: 'command-end', command, elapsed_ms: Date.now() - started,
    status: result.status, signal: result.signal, error: result.error?.message || null }));
  return { command, args, status: result.status, signal: result.signal,
    stdout: result.stdout || '', stderr: result.stderr || '', error: result.error?.message || null };
}

function git(cwd, args) {
  const result = run(cwd, 'git', args);
  if (result.status !== 0) throw new Error(JSON.stringify(result));
  return result.stdout.trim();
}

function repo(name) {
  const base = path.join(root, name);
  fs.mkdirSync(base);
  git(base, ['init', '-q']);
  git(base, ['config', 'user.name', 'Zeus isolated review']);
  git(base, ['config', 'user.email', 'review@example.invalid']);
  git(base, ['config', 'commit.gpgsign', 'false']);
  return base;
}

function commit(base, message) {
  git(base, ['add', '-A']);
  git(base, ['commit', '-q', '-m', message]);
  return git(base, ['rev-parse', 'HEAD']);
}

function cli(base, args) {
  const result = run(base, 'node', [CLI, '--cwd', base, ...args]);
  try {
    const raw = result.stdout.trim();
    result.json = JSON.parse(raw.startsWith('@file:') ? fs.readFileSync(raw.slice(6), 'utf8') : raw);
  } catch (error) { result.json_error = error.message; }
  return result;
}

// A real normal merge control, a false claimed base, and an unrelated branch.
for (const [name, wrongBase, branch] of [
  ['merge-control', false, 'gsd/quick-review'],
  ['merge-invalid-base', true, 'gsd/quick-review'],
  ['merge-foreign-branch', false, 'unrelated-owner'],
]) {
  const base = repo(name);
  const qid = '260909-test';
  const qdir = `.planning/quick/${qid}-review`;
  write(base, '.planning/STATE.md', '# STATE\nmain-state\n');
  write(base, '.planning/ROADMAP.md', '# ROADMAP\nmain-roadmap\n');
  write(base, `${qdir}/${qid}-PLAN.md`, '# PLAN\nreview task\n');
  const expectedBase = commit(base, 'base');
  const worker = path.join(root, `${name}-worker`);
  git(base, ['worktree', 'add', '-q', '-b', branch, worker, 'HEAD']);
  write(worker, 'code.txt', name + '\n');
  commit(worker, 'code change');
  write(worker, `${qdir}/${qid}-SUMMARY.md`, '# SUMMARY\nresult\n');
  commit(worker, 'summary');
  const requestedBase = wrongBase ? 'not-a-real-commit' : expectedBase;
  const result = cli(base, ['quick-merge-back', '--quick-id', qid, '--quick-dir', qdir, '--expected-base', requestedBase]);
  outputs.push({ name, requestedBase, branch, result, worker_exists: fs.existsSync(worker),
    final_code: fs.existsSync(path.join(base, 'code.txt')) ? fs.readFileSync(path.join(base, 'code.txt'), 'utf8') : null,
    worktrees: git(base, ['worktree', 'list', '--porcelain']) });
  console.log(JSON.stringify(outputs.at(-1)));
}

// Execute original phase remove against an explicitly owned disposable definition.
{
  const base = repo('phase-renumber');
  const before = '# Roadmap\n\n### Phase 5: Removed\nold\n\n### Phase 6: Six\n**Depends on:** Phase 5\n\n### Phase 7: Seven\n**Depends on:** Phase 6\n';
  write(base, '.planning/ROADMAP.md', before);
  write(base, '.planning/STATE.md', '# State\n\n**Total Phases:** 7\n');
  for (const dir of ['05-removed', '06-six', '07-seven']) write(base, `.planning/phases/${dir}/.gitkeep`, '');
  commit(base, 'phase definitions');
  const result = cli(base, ['phase', 'remove', '5']);
  outputs.push({ name: 'phase-renumber', result, before, after: fs.readFileSync(path.join(base, '.planning/ROADMAP.md'), 'utf8'),
    directories: fs.readdirSync(path.join(base, '.planning/phases')), state: fs.readFileSync(path.join(base, '.planning/STATE.md'), 'utf8') });
  console.log(JSON.stringify(outputs.at(-1)));
}

// Original profile writer receives inert labelled strings, never actual sessions/secrets.
for (const field of ['evidence', 'evidence_quotes']) {
  const base = path.join(root, `profile-${field}`);
  fs.mkdirSync(base);
  const marker = 'password=ZEUS_SYNTHETIC_SENTINEL';
  const analysis = { profile_version: '1.0', projects_list: [], dimensions: {
    communication_style: { confidence: 'LOW', rating: 'mixed', [field]: [{ quote: marker, project: 'sterile-scratch' }] }
  } };
  write(base, 'analysis.json', JSON.stringify(analysis));
  const result = cli(base, ['write-profile', '--input', 'analysis.json', '--output', 'profile.md']);
  const file = path.join(base, 'profile.md');
  const rendered = fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : '';
  outputs.push({ name: `profile-${field}`, result, sentinel_present: rendered.includes(marker), redacted_present: rendered.includes('[REDACTED]'), rendered_sha256: crypto.createHash('sha256').update(rendered).digest('hex') });
  console.log(JSON.stringify(outputs.at(-1)));
}

console.log(JSON.stringify({ summary: { observations: outputs.length, platform: os.platform(), node: process.version,
  runtime_error_count: outputs.filter(o => o.result.status !== 0 || o.result.json_error).length,
  original_test_suite: false, acceptance: false } }));
if (outputs.some(o => o.result.status !== 0 || o.result.json_error)) process.exitCode = 1;
// Scratch disappears with the named container. No host cleanup or source edits.
