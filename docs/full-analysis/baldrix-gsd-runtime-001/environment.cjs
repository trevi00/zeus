'use strict';
const fs = require('node:fs');
const os = require('node:os');
const { spawnSync } = require('node:child_process');
fs.mkdirSync('/tmp/home', { recursive: true });
const commands = [['git', ['--version']], ['apk', ['info', '-v']]];
const results = commands.map(([command, argv]) => {
  const result = spawnSync(command, argv, { encoding: 'utf8', timeout: 5000 });
  return { command, argv, status: result.status, stdout: result.stdout, stderr: result.stderr, error: result.error?.message || null };
});
console.log(JSON.stringify({ node: process.version, platform: process.platform, architecture: process.arch, uid: process.getuid(), homedir: os.homedir(), tmpdir: os.tmpdir(), results }));
if (process.getuid() === 0 || results.some(r => r.status !== 0)) process.exitCode = 1;
