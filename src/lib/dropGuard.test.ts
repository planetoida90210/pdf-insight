import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { refuseDropsOutsideZone } from './dropGuard';

// Testy działają bez DOM, więc okno zastępuje zwykły EventTarget.
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
  it('blokuje upuszczenie poza strefą, a po sprzątaniu przestaje', () => {
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

  it('nie rusza zdarzenia, które obsłużyła strefa', () => {
    target.addEventListener('dragover', (event) => event.preventDefault());
    const stop = refuseDropsOutsideZone();
    const over = dragEvent('dragover');
    target.dispatchEvent(over);
    expect(over.dataTransfer.dropEffect).toBe('copy');
    stop();
  });
});
