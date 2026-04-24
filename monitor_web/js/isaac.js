/**
 * ISAAC-64 纯 JS 实现 (Standalone, 不依赖 WASM)
 * 产生与 WxIsaac64 WASM 模块相同的 131072 字节密钥流
 *
 * 移植自 reference ISAAC-64: http://burtleburtle.net/bob/rand/isaacafa.html
 * Public Domain, Bob Jenkins, 1996, 2001
 *
 * 关键：所有运算使用 BigInt (uint64) 而非 JavaScript 的 int32 | 0
 * 因为 C 源使用 uint64_t，WASM 保留 64 位行为
 */

'use strict';

/** @type {Map<string, Uint8Array>} 缓存: key=DecodeKey → keystream */
const _isaacCache = new Map();

const _RAND_SIZE = 256;
const _MASK64 = BigInt('0xFFFFFFFFFFFFFFFF');

/** indirection function */
function _ind(mm, x) {
  return mm[Number(BigInt(x) & BigInt(0xFF))];
}

/**
 * ISAAC-64 mix 函数（8 轮）- BigInt 版本
 */
function _mix(a, b, c, d, e, f, g, h) {
  a ^= (a << BigInt(13)); a = (a + b) & _MASK64; d ^= a; h ^= a;
  b ^= (b << BigInt(6));  b = (b + c) & _MASK64; e ^= b; a ^= b;
  c ^= (c << BigInt(5));  c = (c + d) & _MASK64; f ^= c; b ^= c;
  d ^= (d << BigInt(1));  d = (d + e) & _MASK64; g ^= d; c ^= d;
  e ^= (e << BigInt(8));  e = (e + f) & _MASK64; h ^= e; d ^= e;
  f ^= (f << BigInt(16)); f = (f + g) & _MASK64; a ^= f; e ^= f;
  g ^= (g << BigInt(31)); g = (g + h) & _MASK64; b ^= g; f ^= g;
  h ^= (h << BigInt(24)); h = (h + a) & _MASK64; c ^= h; g ^= h;
  return [a, b, c, d, e, f, g, h];
}

/**
 * ISAAC-64 内部状态
 * @constructor
 */
function _Isaac64(seed) {
  // All internal values are BigInt (uint64_t in C)
  var mm = new Array(_RAND_SIZE);
  var rr = new Array(_RAND_SIZE);
  var aa = BigInt(0), bb = BigInt(0), cc = BigInt(0);

  // seed: XOR each byte into lower 8 bits of mm[i] (as BigInt)
  var sb = new TextEncoder().encode(seed || '');
  for (var i = 0; i < _RAND_SIZE; i++) {
    mm[i] = BigInt(sb[i] || 0);
  }

  // golden ratio constants (uint64)
  var gold = [
    BigInt('0x9e3779b97f4a7c15'), BigInt('0x3c6ef372fe94f82b'), BigInt('0xa678fdd7d10c06bc'), BigInt('0x9e3779b97f4a7c15'),
    BigInt('0x3c6ef372fe94f82b'), BigInt('0xa678fdd7d10c06bc'), BigInt('0x717b8f70f4c54d3e'), BigInt('0x8e1c5a5d7b73a7fb'),
    BigInt('0x4e1ddb1f19c2b574'), BigInt('0x4f8b8e4fe35b30bf'), BigInt('0x1f6c4b3f5a9b3e7d'), BigInt('0x6d8d4c94a89fd7b5'),
    BigInt('0x6eaa9e30c7a7d3f4'), BigInt('0x1a8f1f2e0b3d3c7a'), BigInt('0x6c3fa2d8e5f1a4b3'), BigInt('0x6c5b9f7e4a3c2d1f')
  ];

  // save seed copy (BigInt array)
  var ss = mm.slice();
  // copy gold constants into mm
  for (var i = 0; i < _RAND_SIZE; i++) {
    mm[i] = gold[i % gold.length];
  }

  for (var k = 0; k < 4; k++) {
    for (var i = 0; i < _RAND_SIZE; i += 8) {
      var res = _mix(
        mm[i],     mm[i+1], mm[i+2], mm[i+3],
        mm[i+4],   mm[i+5], mm[i+6], mm[i+7]
      );
      mm[i]   = res[0]; mm[i+1] = res[1]; mm[i+2] = res[2]; mm[i+3] = res[3];
      mm[i+4] ^= res[4]; mm[i+5] ^= res[5]; mm[i+6] ^= res[6]; mm[i+7] ^= res[7];
    }
  }

  for (var i = 0; i < _RAND_SIZE; i++) mm[i] ^= ss[i];

  // extra init rounds (reference C)
  for (var i = 0; i < _RAND_SIZE; i++) {
    aa ^= (aa << BigInt(13)); aa = (aa + mm[i]) & _MASK64; bb = (bb + mm[(i + 1) & 0xFF]) & _MASK64;
    mm[i] = (mm[i] + aa + bb) & _MASK64;
    cc = mm[i];
    mm[(i + 1) & 0xFF] = (mm[(i + 1) & 0xFF] + bb + _ind(mm, mm[i] >> BigInt(2))) & _MASK64;
    rr[i] = _ind(mm, mm[i] >> BigInt(2));
    rr[(i + 1) & 0xFF] = _ind(mm, (mm[(i + 1) & 0xFF] >> BigInt(2)) & BigInt(0xFF));
  }
  for (var i = 0; i < _RAND_SIZE; i++) mm[i] ^= rr[i];

  this.mm = mm;
  this.rr = rr;
  this.a = aa;
  this.b = bb;
  this.c = cc;
}

/** ISAAC indirection function */
_Isaac64.prototype.ind = function (x) {
  return this.mm[Number(BigInt(x) & BigInt(0xFF))];
};

/**
 * ISAAC 生成函数
 */
_Isaac64.prototype.isaac = function () {
  var mm = this.mm, rr = this.rr;
  var a = this.a, b = this.b, c = this.c;

  for (var i = 0; i < _RAND_SIZE; i += 8) {
    var a2, b2, x;

    // block 0-1
    a2 = (a + mm[(i + 128) & 0xFF]) & _MASK64;
    b2 = (b + mm[(i + 64) & 0xFF]) & _MASK64;
    mm[i] = (mm[i] + a2 + b2) & _MASK64;
    x = mm[i];
    mm[i + 1] = (mm[i + 1] + b2 + this.ind(x >> BigInt(2))) & _MASK64;
    rr[i] = this.ind(x >> BigInt(2));
    mm[i] ^= mm[(i + 128) & 0xFF];
    mm[i + 1] ^= mm[(i + 65) & 0xFF];

    // block 2-3
    a2 = (a + mm[(i + 129) & 0xFF]) & _MASK64;
    b2 = (b + mm[(i + 65) & 0xFF]) & _MASK64;
    mm[i + 2] = (mm[i + 2] + a2 + b2) & _MASK64;
    x = mm[i + 2];
    mm[i + 3] = (mm[i + 3] + b2 + this.ind(x >> BigInt(2))) & _MASK64;
    rr[i + 2] = this.ind(x >> BigInt(2));
    mm[i + 2] ^= mm[(i + 130) & 0xFF];
    mm[i + 3] ^= mm[(i + 66) & 0xFF];

    // block 4-5
    a2 = (a + mm[(i + 130) & 0xFF]) & _MASK64;
    b2 = (b + mm[(i + 66) & 0xFF]) & _MASK64;
    mm[i + 4] = (mm[i + 4] + a2 + b2) & _MASK64;
    x = mm[i + 4];
    mm[i + 5] = (mm[i + 5] + b2 + this.ind(x >> BigInt(2))) & _MASK64;
    rr[i + 4] = this.ind(x >> BigInt(2));
    mm[i + 4] ^= mm[(i + 132) & 0xFF];
    mm[i + 5] ^= mm[(i + 67) & 0xFF];

    // block 6-7
    a2 = (a + mm[(i + 131) & 0xFF]) & _MASK64;
    b2 = (b + mm[(i + 67) & 0xFF]) & _MASK64;
    mm[i + 6] = (mm[i + 6] + a2 + b2) & _MASK64;
    x = mm[i + 6];
    mm[i + 7] = (mm[i + 7] + b2 + this.ind(x >> BigInt(2))) & _MASK64;
    rr[i + 6] = this.ind(x >> BigInt(2));
    mm[i + 6] ^= mm[(i + 134) & 0xFF];
    mm[i + 7] ^= mm[(i + 68) & 0xFF];

    a = a2; b = b2;
  }

  this.mm = mm; this.rr = rr; this.a = a; this.b = b; this.c = c;
};

/**
 * 生成 keystream
 * @param {number} count - 字节数
 * @returns {Uint8Array}
 */
_Isaac64.prototype.generate = function (count) {
  var out = new Uint8Array(count);
  while (count > 0) {
    this.isaac();
    var chunk = Math.min(1024, count);
    for (var i = 0; i < chunk; i++) {
      var v = this.rr[i >> 2];
      out[--count] = Number(v & BigInt(0xFF));
      if (count > 0) out[--count] = Number((v >> BigInt(8)) & BigInt(0xFF));
      if (count > 0) out[--count] = Number((v >> BigInt(16)) & BigInt(0xFF));
      if (count > 0) out[--count] = Number((v >> BigInt(24)) & BigInt(0xFF));
    }
  }
  return out;
};

/**
 * 生成解密密钥流（131072 字节）
 * @param {string} seed - DecodeKey
 * @returns {Uint8Array}
 */
function getDecryptionArray(seed) {
  var cached = _isaacCache.get(seed);
  if (cached) return cached;
  var rng = new _Isaac64(seed);
  var result = rng.generate(131072);
  _isaacCache.set(seed, result);
  return result;
}

/**
 * Uint8Array 转 base64
 * @param {Uint8Array} bytes
 * @returns {string}
 */
function uint8ArrayToBase64(bytes) {
  var len = bytes.byteLength || bytes.length;
  var binary = '';
  for (var i = 0; i < len; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

// Browser export
if (typeof window !== 'undefined') {
  window.getDecryptionArray = getDecryptionArray;
  window.uint8ArrayToBase64 = uint8ArrayToBase64;
}

// CommonJS export
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { getDecryptionArray, uint8ArrayToBase64 };
}

// ES Module export
export { getDecryptionArray, uint8ArrayToBase64 };
