// Synthetic test storage only; native workerd checks validate real R2 behavior.
export function syntheticR2(objects = new Map()) {
  const metadata = new Map();
  return {
    async put(key, value, options = {}) {
      if (options.onlyIf?.get("if-none-match") === "*" && objects.has(key)) return null;
      const bytes = typeof value === "string" ? new TextEncoder().encode(value) : new Uint8Array(value);
      objects.set(key, bytes.slice());
      metadata.set(key, options.customMetadata || {});
      return { key, size: bytes.length };
    },
    async get(key) {
      if (!objects.has(key)) return null;
      const bytes = objects.get(key).slice();
      return { size: bytes.length, customMetadata: metadata.get(key) || {},
        async arrayBuffer() { return bytes.buffer; } };
    },
  };
}
