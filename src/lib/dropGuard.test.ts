import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { refuseDropsOutsideZone } from './dropGuard';

// Tests run without a DOM, so a plain EventTarget stands in for window.
const dragEvent = (type: string) =>
  Object.assign(new Event(type, { cancelable: true }), { dataTransfer: { dropEffect: 'copy' } });

let target: EventTarget;

beforeEach(() => {
  target = new EventTarget();
  vi.stubGlobal('window', target);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('refuseDropsOutsideZone', () => {
  it('refuses drops outside the zone until cleaned up', () => {
    const stop = refuseDropsOutsideZone();
    const over = dragEvent('dragover');
    const drop = dragEvent('drop');
    target.dispatchEvent(over);
    target.dispatchEvent(drop);
    expect(over.defaultPrevented).toBe(true);
    expect(over.dataTransfer.dropEffect).toBe('none');
    expect(drop.defaultPrevented).toBe(true);

    stop();
    const later = dragEvent('drop');
    target.dispatchEvent(later);
    expect(later.defaultPrevented).toBe(false);
  });

  it('leaves events the zone handled alone', () => {
    target.addEventListener('dragover', (event) => event.preventDefault());
    const stop = refuseDropsOutsideZone();
    const over = dragEvent('dragover');
    target.dispatchEvent(over);
    expect(over.dataTransfer.dropEffect).toBe('copy');
    stop();
  });
});
