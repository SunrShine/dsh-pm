#!/usr/bin/env node
// 批量判定 DSH 会话日志是否属于 subagent（子 agent）。
//
// 为什么只解第一帧：子 agent 的标记出现在 seq 0
//   {"type":"session", ..., "parentSession":"session-xxxx"}
//   {"type":"subagent/descriptor", ...}
// Node 的 zstdDecompressSync 默认**只解第一帧**，正好够用且便宜
// （实测一个 1.4MB / 5000+ 帧的日志，解第一帧即可判定）。
//
// 为什么批量：177 个会话逐个起 node 进程会慢几十倍；这里一次进程处理全部路径。
//
// 判定失败（读不了 / 不是 zstd 也读不出）→ unknown；
// 调用方必须保守地把它当作**非**子 agent（宁可多显示，不可漏掉真实工作）。
'use strict';

const fs = require('fs');
const zlib = require('zlib');

const MARKERS = ['parentSession', 'subagent/descriptor'];
const HEAD_LIMIT = 200000;
const ZSTD_MAGIC = [0x28, 0xb5, 0x2f, 0xfd];

function isZstd(buf) {
  return buf.length >= 4 && ZSTD_MAGIC.every((byte, i) => buf[i] === byte);
}

function headOf(buf) {
  // 未压缩的 .jsonl 日志：直接当文本读前 200KB
  if (!isZstd(buf)) return buf.subarray(0, HEAD_LIMIT).toString('utf8');
  // 拼接的多帧 zstd：只解第一帧（seq 0 就在这里）
  return zlib.zstdDecompressSync(buf).subarray(0, HEAD_LIMIT).toString('utf8');
}

function classify(file) {
  let head;
  try {
    head = headOf(fs.readFileSync(file));
  } catch (err) {
    return 'unknown';
  }
  return MARKERS.some((marker) => head.includes(marker)) ? 'SUBAGENT' : 'normal';
}

const args = process.argv.slice(2);
let files = args;
if (files.length === 0) {
  // 路径多时走 stdin，一行一个（避免命令行长度上限）
  let input = '';
  try {
    input = fs.readFileSync(0, 'utf8');
  } catch (err) {
    input = '';
  }
  files = input.split('\n');
}
files = files.map((line) => line.replace(/\r$/, '')).filter((line) => line.length > 0);

const out = [];
for (const file of files) out.push(classify(file) + '\t' + file);
if (out.length > 0) process.stdout.write(out.join('\n') + '\n');
