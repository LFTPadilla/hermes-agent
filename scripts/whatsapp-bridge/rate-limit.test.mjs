#!/usr/bin/env node
/**
 * Self-check for the per-sender WhatsApp rate limiter.
 * Run: node rate-limit.test.mjs
 * Proves: under-limit passes, over-limit drops, window resets, default-off,
 * per-sender isolation, and one-notice-per-window.
 */
import assert from 'node:assert/strict';
import { createRateLimiter } from './rate-limit.js';

// 1. DEFAULT-OFF: no env set → unlimited
{
  const rl = createRateLimiter({});
  assert.equal(rl.enabled, false, 'disabled when env unset');
  for (let i = 0; i < 1000; i += 1) {
    assert.equal(rl.check('alice').allowed, true, 'unlimited when disabled');
  }
}

// 2. MAX set but WINDOW unset/0 → still unlimited (both required)
{
  const rl = createRateLimiter({ WHATSAPP_RATE_LIMIT_MAX: '3' });
  assert.equal(rl.enabled, false, 'disabled when only MAX set');
  assert.equal(rl.check('alice').allowed, true);
}

// 3. Under the limit passes, over the limit drops
{
  const rl = createRateLimiter({
    WHATSAPP_RATE_LIMIT_MAX: '3',
    WHATSAPP_RATE_LIMIT_WINDOW_SEC: '10',
  });
  assert.equal(rl.enabled, true, 'enabled when both set');
  const t0 = 1_000_000;
  assert.equal(rl.check('alice', t0 + 0).allowed, true, 'msg 1 passes');
  assert.equal(rl.check('alice', t0 + 1).allowed, true, 'msg 2 passes');
  assert.equal(rl.check('alice', t0 + 2).allowed, true, 'msg 3 passes');
  const over = rl.check('alice', t0 + 3);
  assert.equal(over.allowed, false, 'msg 4 dropped (over limit)');
  assert.equal(over.notify, true, 'first drop emits notice');
  // 4th+ drops within window: notice NOT re-emitted
  assert.equal(rl.check('alice', t0 + 4).notify, false, 'notice rate-limited within window');
}

// 4. Window resets: after window passes, sender is allowed again
{
  const rl = createRateLimiter({
    WHATSAPP_RATE_LIMIT_MAX: '2',
    WHATSAPP_RATE_LIMIT_WINDOW_SEC: '10',
  });
  const t0 = 5_000_000;
  assert.equal(rl.check('bob', t0).allowed, true);
  assert.equal(rl.check('bob', t0 + 1000).allowed, true);
  assert.equal(rl.check('bob', t0 + 2000).allowed, false, 'dropped within window');
  // Advance far enough that BOTH earlier timestamps (t0, t0+1000) age out of
  // the 10s sliding window, so the sender is fully reset.
  const after = rl.check('bob', t0 + 11_001);
  assert.equal(after.allowed, true, 'allowed again after window reset');
  assert.equal(rl.check('bob', t0 + 11_002).allowed, true, '2nd in fresh window passes');
  assert.equal(rl.check('bob', t0 + 11_003).allowed, false, '3rd dropped in fresh window');
}

// 5. Per-sender isolation: one sender hitting the limit does not affect another
{
  const rl = createRateLimiter({
    WHATSAPP_RATE_LIMIT_MAX: '1',
    WHATSAPP_RATE_LIMIT_WINDOW_SEC: '60',
  });
  const t0 = 9_000_000;
  assert.equal(rl.check('carol', t0).allowed, true);
  assert.equal(rl.check('carol', t0 + 1).allowed, false, 'carol throttled');
  assert.equal(rl.check('dave', t0 + 2).allowed, true, 'dave unaffected');
}

console.log('PASS: all rate-limit self-checks passed');
