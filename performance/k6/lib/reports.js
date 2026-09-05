export function writeAtlasSummary(data) {
  const path = __ENV.ATLAS_K6_RAW_SUMMARY || 'k6-summary.json';
  const compact = {
    run_id: __ENV.ATLAS_K6_RUN_ID || 'unknown',
    mode: __ENV.ATLAS_K6_MODE || 'unknown',
    requests: data.metrics.http_reqs ? data.metrics.http_reqs.values.count : 0,
    failed_rate: data.metrics.http_req_failed ? data.metrics.http_req_failed.values.rate : 0,
  };
  return {
    [path]: JSON.stringify(data, null, 2),
    stdout: `${JSON.stringify(compact, null, 2)}\n`,
  };
}
