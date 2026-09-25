/** A small seeded random source: same seed, same sequence, every run. */
export interface Random {
  /** A float in [0, 1). */
  next(): number;
  /** An integer in [min, max], both included. */
  int(min: number, max: number): number;
  pick<T>(items: readonly T[]): T;
}

/** Mulberry32: tiny, fast and good enough for fixtures. */
export function createRandom(seed: number): Random {
  let state = seed >>> 0;
  function next(): number {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }
  function int(min: number, max: number): number {
    return min + Math.floor(next() * (max - min + 1));
  }
  function pick<T>(items: readonly T[]): T {
    const item = items[int(0, items.length - 1)];
    if (item === undefined) {
      throw new Error('pick() needs a non-empty list');
    }
    return item;
  }
  return {next, int, pick};
}

/** FNV-1a hash of the parts, used to derive a seed per date. */
export function hashSeed(...parts: Array<string | number>): number {
  let hash = 0x811c9dc5;
  for (const char of parts.join('|')) {
    hash ^= char.codePointAt(0) ?? 0;
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash;
}
