#!/usr/bin/env node
// 解码 DSH 会话日志并写到 stdout。
//
// 关键点：日志文件是**拼接的多个 zstd frame**（实测一个会话 5056 帧）。
// Node 的 zlib.zstdDecompressSync 只解第一帧就停，所以必须按 frame magic
// 切分后逐帧解。尾部可能有一帧写到一半（会话正在写），容忍并按帧报错。
'use strict';

const fs = require('fs');
const zlib = require('zlib');

const MAGIC = [0x28, 0xb5, 0x2f, 0xfd];

function frameStarts(buf) {
  const starts = [];
  for (let i = 0; i + 4 <= buf.length; i += 1) {
    if (buf[i] === MAGIC[0] && buf[i + 1] === MAGIC[1] && buf[i + 2] === MAGIC[2] && buf[i + 3] === MAGIC[3]) {
      starts.push(i);
    }
  }
  return starts;
}

function decode(buf) {
  const starts = frameStarts(buf);
  if (starts.length === 0) throw new Error('不是 zstd 文件（找不到 frame magic）');
  const parts = [];
  let failed = 0;
  for (let k = 0; k < starts.length; k += 1) {
    const end = k + 1 < starts.length ? starts[k + 1] : buf.length;
    try {
      parts.push(zlib.zstdDecompressSync(buf.subarray(starts[k], end)));
    } catch (err) {
      failed += 1;
      if (k < starts.length - 1) {
        process.stderr.write('frame ' + k + ' 解码失败: ' + err.message + '\n');
      }
    }
  }
  return { text: Buffer.concat(parts).toString('utf8'), frames: starts.length, failed };
}

const file = process.argv[2];
if (!file) {
  process.stderr.write('用法: zstd-decode.cjs <file>\n');
  process.exit(2);
}
try {
  const result = decode(fs.readFileSync(file));
  process.stdout.write(result.text);
  if (result.failed) {
    process.stderr.write('警告: ' + result.failed + '/' + result.frames + ' 帧解码失败（可能是尾部写了一半）\n');
  }
} catch (err) {
  process.stderr.write(err.message + '\n');
  process.exit(1);
}
