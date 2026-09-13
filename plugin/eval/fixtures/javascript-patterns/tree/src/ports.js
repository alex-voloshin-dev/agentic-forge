export function parsePort(text) {
  const value = Number(String(text).trim());
  if (!Number.isInteger(value)) {
    throw new RangeError(`not a port: ${text}`);
  }
  if (value < 1 || value > 65535) {
    throw new RangeError(`port out of range: ${value}`);
  }
  return value;
}
