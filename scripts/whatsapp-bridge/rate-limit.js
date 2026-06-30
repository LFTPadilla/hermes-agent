/**
 * Per-sender inbound rate limiter for the WhatsApp bridge.
 *
 * ENV-GATED, DEFAULT-OFF. Other gateways/clients are unaffected unless they
 * opt in. The public "clientes" lane sets these to gate abuse (gate G7).
 *
 *   WHATSAPP_RATE_LIMIT_MAX        max inbound msgs per sender per window
 *   WHATSAPP_RATE_LIMIT_WINDOW_SEC sliding window length in seconds
 *
 * If MAX is unset/0 or WINDOW is unset/0 → unlimited (current behaviour).
 *
 * Sliding-window counter, in-memory only (no external store — ponytail).
 * CEILING: state lives in this process; a bridge restart resets all counters
 * (an attacker who can crash-loop the bridge could reset their window). The
 * window is short (seconds) so this is acceptable for anti-abuse throttling,
 * not a security boundary.
 */

function positiveIntFromEnv(env, name) {
  const raw = env[name];
  if (raw === undefined || raw === null || raw === '') return 0;
  const n = parseInt(raw, 10);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

export function createRateLimiter(env = process.env) {
  const max = positiveIntFromEnv(env, 'WHATSAPP_RATE_LIMIT_MAX');
  const windowMs = positiveIntFromEnv(env, 'WHATSAPP_RATE_LIMIT_WINDOW_SEC') * 1000;

  const enabled = max > 0 && windowMs > 0;

  // sender id -> { timestamps: number[], noticeSentAt: number }
  const buckets = new Map();

  function prune(entry, now) {
    const cutoff = now - windowMs;
    // timestamps are appended in order, so drop from the front
    let i = 0;
    while (i < entry.timestamps.length && entry.timestamps[i] <= cutoff) i += 1;
    if (i > 0) entry.timestamps.splice(0, i);
  }

  /**
   * Record an inbound message attempt from `senderId`.
   * Returns:
   *   { allowed: true }                          → process the message
   *   { allowed: false, notify: bool }           → drop; notify=true means
   *                                                 send ONE throttle notice
   *                                                 (notice itself rate-limited
   *                                                 to once per window).
   * When disabled, always { allowed: true }.
   */
  function check(senderId, now = Date.now()) {
    if (!enabled) return { allowed: true };
    const key = String(senderId || '');

    let entry = buckets.get(key);
    if (!entry) {
      entry = { timestamps: [], noticeSentAt: 0 };
      buckets.set(key, entry);
    }
    prune(entry, now);

    if (entry.timestamps.length < max) {
      entry.timestamps.push(now);
      return { allowed: true };
    }

    // Over the limit → drop. Decide whether to emit the one-per-window notice.
    let notify = false;
    if (now - entry.noticeSentAt >= windowMs) {
      notify = true;
      entry.noticeSentAt = now;
    }
    return { allowed: false, notify };
  }

  return {
    enabled,
    max,
    windowMs,
    check,
    // exposed for tests / introspection
    _buckets: buckets,
  };
}
