/**
 * decrypt.js — WeChat/QQ Video Decryption
 *
 * Loads the compiled WxIsaac64 WASM module and exposes getDecryptionArray().
 * Used to generate the XOR keystream for decrypting encrypted video files.
 *
 * Usage:
 *   <script src="/static/decrypt.js"></script>
 *   <script>
 *     const key = getDecryptionArray(decodeKey);  // Uint8Array
 *     const b64 = uint8ArrayToBase64(key);
 *   </script>
 */

(function () {
  'use strict';

  var wasmUrl = '/static/decrypt.wasm';
  var wasmModule = null;
  var wasmInstance = null;

  /**
   * Load and instantiate the WASM module.
   * @returns {Promise<WebAssembly.Instance>}
   */
  function loadWasm() {
    if (wasmInstance) return Promise.resolve(wasmInstance);

    return fetch(wasmUrl)
      .then(function (resp) {
        if (!resp.ok) throw new Error('Failed to load WASM: ' + resp.statusText);
        return resp.arrayBuffer();
      })
      .then(function (bytes) {
        return WebAssembly.instantiate(bytes);
      })
      .then(function (result) {
        wasmInstance = result.instance;
        return wasmInstance;
      });
  }

  /**
   * Synchronous wrapper — waits for WASM to load (call once at page init).
   * @param {string} seed
   * @param {number} count  - number of bytes to generate
   * @returns {Uint8Array}
   */
  function wasmGenerate(seed, count) {
    if (!wasmInstance) {
      throw new Error('WASM not loaded. Call window.initDecrypt() first.');
    }
    var mem = wasmInstance.exports.memory;

    // Write seed string into WASM linear memory
    var seedBytes = encodeUTF8(seed || '');
    var seedPtr = 0;
    var seedLen = seedBytes.length;

    // Grow memory if needed (seed + output buffer)
    var neededPages = Math.ceil((seedLen + count + 1024) / 65536);
    var currentPages = mem.buffer.byteLength / 65536;
    if (mem.buffer.byteLength < (seedLen + count + 1024)) {
      mem.grow(neededPages - currentPages + 1);
    }

    // Write seed bytes
    var heap = new Uint8Array(mem.buffer);
    seedPtr = 0;
    for (var i = 0; i < seedLen; i++) {
      heap[seedPtr + i] = seedBytes[i];
    }

    // Write args: seedPtr, seedLen, count
    var argPtr = seedPtr + seedLen + 16;  // alignment
    var view32 = new Uint32Array(mem.buffer);
    var view64 = new BigInt64Array(mem.buffer);
    view32[(argPtr >> 2) + 0] = seedPtr;       // seed ptr
    view32[(argPtr >> 2) + 1] = seedLen;       // seed len
    view32[(argPtr >> 2) + 2] = count;       // output count

    // Call WASM export (need to find the correct export name)
    // The WASM exports are: memory, generate, init
    var exports = wasmInstance.exports;
    var resultPtr = exports.generate(argPtr);

    // Read result: pointer to output bytes (stored by WASM)
    // The WASM stores result in decryptor_array at offset 0
    var resultSize = count;
    var resultBytes = heap.slice(resultPtr, resultPtr + resultSize);
    return new Uint8Array(resultBytes);
  }

  /**
   * Generate decryption keystream.
   * @param {string} seed - DecodeKey
   * @returns {Promise<Uint8Array>} - 131072-byte keystream
   */
  function getDecryptionArrayAsync(seed) {
    var _this = this;
    return loadWasm().then(function () {
      return wasmGenerate.call(_this, seed, 131072);
    });
  }

  /**
   * Synchronous getDecryptionArray — call after WASM is loaded.
   * @param {string} seed
   * @returns {Uint8Array}
   */
  function getDecryptionArray(seed) {
    if (!wasmInstance) {
      throw new Error('WASM not loaded. Call window.initDecrypt().then(() => ...) first.');
    }
    return wasmGenerate(seed, 131072);
  }

  /**
   * Initialize the WASM module. Call this once at page load.
   * @returns {Promise<void>}
   */
  function initDecrypt() {
    return loadWasm().then(function () {});
  }

  /**
   * Convert string to UTF-8 bytes.
   */
  function encodeUTF8(str) {
    return unescape(encodeURIComponent(str));
  }

  /**
   * Convert Uint8Array to base64 string.
   */
  function uint8ArrayToBase64(bytes) {
    var binary = '';
    var len = bytes.byteLength || bytes.length;
    for (var i = 0; i < len; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
  }

  // Expose to window
  window.initDecrypt = initDecrypt;
  window.getDecryptionArray = getDecryptionArray;
  window.getDecryptionArrayAsync = getDecryptionArrayAsync;
  window.uint8ArrayToBase64 = uint8ArrayToBase64;
})();
