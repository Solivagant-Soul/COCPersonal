/**
 * 测试环境补丁：jsdom 不提供 ResizeObserver / matchMedia，Element Plus 的
 * el-select / el-table / el-input 等会直接引用它们。
 */

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

if (!('ResizeObserver' in globalThis)) {
  ;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver =
    ResizeObserverStub
}

if (typeof window !== 'undefined' && !window.matchMedia) {
  const stub = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })
  ;(window as unknown as { matchMedia: unknown }).matchMedia = stub
}
