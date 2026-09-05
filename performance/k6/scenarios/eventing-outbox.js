import http from 'k6/http';
      import { check } from 'k6';
      import { atlasOptions } from '../lib/config.js';
      import { writeAtlasSummary } from '../lib/reports.js';


      export const options = atlasOptions();



      export default function () {
        const eventId = `${Date.now()}-${__VU}-${__ITER}`;
const response = http.post(
  __ENV.TARGET_URL || 'http://localhost:8102/events',
  JSON.stringify({
    event_id: eventId,
    event_type: 'core.item_created',
    source: 'core_api',
    version: 1,
    topic: 'atlas.benchmark.events',
    actor: { type: 'service', id: 'atlas-k6' },
    payload: { item_id: eventId, name: `Benchmark item ${eventId}` },
  }),
  {
    headers: { 'Content-Type': 'application/json' },
    tags: { operation: 'eventing-outbox-ingestion' },
  },
);
check(response, {
  'Eventing accepted the event': (result) => result.status === 202,
});
      }

      export function handleSummary(data) {
        return writeAtlasSummary(data);
      }
