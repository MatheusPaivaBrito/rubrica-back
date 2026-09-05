import http from 'k6/http';
      import { check } from 'k6';
      import { atlasOptions } from '../lib/config.js';
      import { writeAtlasSummary } from '../lib/reports.js';
      import { login } from '../lib/auth.js';

      export const options = atlasOptions();


        export function setup() {
          return { token: login() };
        }


      export default function (data) {
        const unique = `${__ENV.ATLAS_K6_RUN_ID}-${__VU}-${__ITER}`;
const response = http.post(
  __ENV.TARGET_URL || 'http://localhost:8100/items',
  JSON.stringify({ name: `Benchmark ${unique}`, description: 'k6 generated load' }),
  {
    headers: {
      Authorization: `Bearer ${data.token}`,
      'Content-Type': 'application/json',
    },
    tags: { operation: 'core-protected-create' },
  },
);
check(response, {
  'Core protected command returned 201': (result) => result.status === 201,
});
      }

      export function handleSummary(data) {
        return writeAtlasSummary(data);
      }
