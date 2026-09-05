import http from 'k6/http';
      import { check } from 'k6';
      import { atlasOptions } from '../lib/config.js';
      import { writeAtlasSummary } from '../lib/reports.js';


      export const options = atlasOptions();



      export default function () {
        const unique = `${__ENV.ATLAS_K6_RUN_ID}-${__VU}-${__ITER}`;
const response = http.post(
  __ENV.TARGET_URL || 'http://localhost:8103/messaging/email/messages',
  JSON.stringify({
    to: `benchmark+${unique}@example.invalid`,
    subject: 'Atlas local benchmark',
    body: 'This request must remain on the local provider boundary.',
    idempotency_key: unique,
    delivery_policy: { mode: 'transient' },
  }),
  {
    headers: { 'Content-Type': 'application/json' },
    tags: { operation: 'notification-local-email' },
  },
);
check(response, {
  'Notification accepted the local request': (result) => result.status === 202,
  'Notification stayed on local_ack': (result) => result.json('provider') === 'local_ack',
});
      }

      export function handleSummary(data) {
        return writeAtlasSummary(data);
      }
