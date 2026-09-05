function integer(name, fallback) {
  const value = Number.parseInt(__ENV[name] || `${fallback}`, 10);
  if (!Number.isInteger(value) || value < 1) {
    throw new Error(`${name} must be a positive integer`);
  }
  return value;
}

function number(name, fallback) {
  const value = Number.parseFloat(__ENV[name] || `${fallback}`);
  if (!Number.isFinite(value) || value < 0) {
    throw new Error(`${name} must be a non-negative number`);
  }
  return value;
}

export function atlasOptions() {
  const mode = __ENV.ATLAS_K6_MODE || 'smoke';
  const requests = integer('K6_REQUESTS', 500);
  const concurrency = integer('K6_CONCURRENCY', 10);
  const rate = integer('K6_RATE', 25);
  const duration = __ENV.K6_DURATION || '30s';
  const preAllocatedVUs = integer('K6_PREALLOCATED_VUS', 25);
  const maxVUs = integer('K6_MAX_VUS', 100);
  const maxErrorRate = number('K6_MAX_ERROR_RATE', 0.01);
  const p95Ms = integer('K6_P95_MS', 1000);
  const errorThreshold = maxErrorRate === 0
    ? 'rate==0'
    : `rate<=${maxErrorRate}`;
  const checksThreshold = `rate>=${1 - maxErrorRate}`;

  const scenarios = {
    smoke: {
      executor: 'shared-iterations',
      vus: Math.min(concurrency, requests),
      iterations: requests,
      maxDuration: duration,
    },
    load: {
      executor: 'constant-arrival-rate',
      rate,
      timeUnit: '1s',
      duration,
      preAllocatedVUs,
      maxVUs,
    },
    stress: {
      executor: 'ramping-arrival-rate',
      startRate: Math.max(1, Math.floor(rate / 4)),
      timeUnit: '1s',
      preAllocatedVUs,
      maxVUs,
      stages: [
        { target: Math.max(1, Math.floor(rate / 2)), duration: '15s' },
        { target: rate, duration },
        { target: Math.max(1, Math.floor(rate / 2)), duration: '15s' },
      ],
    },
    soak: {
      executor: 'constant-vus',
      vus: concurrency,
      duration,
    },
  };

  if (!scenarios[mode]) {
    throw new Error(`unsupported ATLAS_K6_MODE: ${mode}`);
  }

  return {
    discardResponseBodies: false,
    scenarios: { atlas: scenarios[mode] },
    thresholds: {
      http_req_failed: [errorThreshold],
      http_req_duration: [`p(95)<${p95Ms}`],
      checks: [checksThreshold],
      dropped_iterations: ['count==0'],
    },
    summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  };
}
