declare module "d3-force-3d" {
  interface Collide<N> { (alpha: number): void; radius(r: number | ((n: N) => number)): Collide<N>; strength(s: number): Collide<N>; iterations(i: number): Collide<N> }
  export function forceCollide<N = unknown>(radius?: number | ((n: N) => number)): Collide<N>;
}
