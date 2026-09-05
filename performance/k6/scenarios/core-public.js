import http from 'k6/http';
      import { check } from 'k6';
      import { atlasOptions } from '../lib/config.js';
      import { writeAtlasSummary } from '../lib/reports.js';


      export const options = atlasOptions();



      export default function () {
        const response = http.get(__ENV.TARGET_URL || 'http://localhost:8100/items', {
  tags: { operation: 'core-public-read' },
});
check(response, {
  'Core public query returned 200': (result) => result.status === 200,
});
      }

      export function handleSummary(data) {
        return writeAtlasSummary(data);
      }
