'use strict';
// Observe the unchanged upstream test in this isolated container only.
const fs = require('node:fs');
const { spawn } = require('node:child_process');
fs.mkdirSync('/tmp/home', { recursive: true });
const args = ['--test', '--test-reporter=tap', '/source/get-shit-done/bin/lib/__tests__/merge-back.test.cjs'];
const started = Date.now();
const child = spawn('node', args, { stdio: ['ignore', 'inherit', 'inherit'] });
console.log(JSON.stringify({ event: 'launch', pid: child.pid, args }));
function observe() {
  const rows = [];
  for (const id of fs.readdirSync('/proc').filter(x => /^\d+$/.test(x))) {
    try {
      rows.push({ pid: Number(id), cmdline: fs.readFileSync(`/proc/${id}/cmdline`, 'utf8').replaceAll('\0', ' '),
        status: fs.readFileSync(`/proc/${id}/status`, 'utf8').split('\n').filter(x => /^(Name|State|PPid|Threads):/.test(x)),
        wchan: fs.readFileSync(`/proc/${id}/wchan`, 'utf8') });
    } catch (error) { rows.push({ pid: Number(id), read_error: error.code }); }
  }
  console.log(JSON.stringify({ event: 'process-observation', elapsed_ms: Date.now() - started, rows }));
}
const poll = setInterval(observe, 5000);
const limit = setTimeout(() => { observe(); child.kill('SIGTERM'); }, 16000);
child.on('exit', (code, signal) => {
  clearInterval(poll); clearTimeout(limit);
  console.log(JSON.stringify({ event: 'exit', code, signal, elapsed_ms: Date.now() - started }));
  process.exitCode = code === 0 ? 0 : 1;
});
