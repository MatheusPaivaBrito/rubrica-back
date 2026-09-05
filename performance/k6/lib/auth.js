import http from 'k6/http';
import { check } from 'k6';

export function login() {
  const authUrl = __ENV.AUTH_URL || 'http://localhost:8101';
  const email = __ENV.K6_AUTH_EMAIL;
  const password = __ENV.K6_AUTH_PASSWORD;
  if (!email || !password) {
    throw new Error(
      'K6_AUTH_EMAIL and K6_AUTH_PASSWORD are required for protected scenarios',
    );
  }
  const response = http.post(
    `${authUrl}/auth/login`,
    JSON.stringify({
      email,
      password,
    }),
    { headers: { 'Content-Type': 'application/json' }, tags: { operation: 'auth-login' } },
  );
  const valid = check(response, {
    'auth login returned 200': (result) => result.status === 200,
    'auth login returned an access token': (result) => Boolean(result.json('access_token')),
  });
  if (!valid) {
    throw new Error(`benchmark login failed with HTTP ${response.status}`);
  }
  return response.json('access_token');
}
