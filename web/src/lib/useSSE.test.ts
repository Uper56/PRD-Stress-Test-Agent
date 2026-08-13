import { describe, expect, it } from 'vitest';
import { parseSSEBlock } from './useSSE';

describe('parseSSEBlock', () => {
  it('parses id / event / data into a typed event', () => {
    const ev = parseSSEBlock(
      'id: 7\nevent: thinking\ndata: {"delta":"hello"}',
    );
    expect(ev).toEqual({ id: 7, event: 'thinking', data: { delta: 'hello' } });
  });

  it('tolerates multi-line data payloads', () => {
    const ev = parseSSEBlock('event: x\ndata: {"a":\ndata: 1}');
    expect(ev?.data).toEqual({ a: 1 });
  });

  it('drops non-JSON data into a raw field instead of throwing', () => {
    const ev = parseSSEBlock('event: x\ndata: not json at all');
    expect(ev?.data).toEqual({ raw: 'not json at all' });
  });

  it('ignores blocks without an event name (keep-alives)', () => {
    expect(parseSSEBlock('data: {"ping":true}')).toBeNull();
    expect(parseSSEBlock('id: 3')).toBeNull();
  });

  it('ignores comment lines and trims id whitespace', () => {
    const ev = parseSSEBlock(': keepalive\nevent: phase\nid: 12\ndata: {"name":"graph"}');
    expect(ev?.id).toBe(12);
    expect(ev?.event).toBe('phase');
  });
});
