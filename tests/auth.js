/* Signs the browser suites in as the test admin that `testenv.sh up` sets (see auth.py).
 * POS_USER / POS_PASSWORD override it, e.g. to run test-tour.js against the live site. */
const USER = process.env.POS_USER || 'admin';
const PASSWORD = process.env.POS_PASSWORD || 'test-admin-pass';
const BASE = process.env.BASE || 'http://127.0.0.1:8095';

let session = null;

async function login() {
  if (session) return session;
  const r = await fetch(BASE + '/api/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: USER, password: PASSWORD }),
  });
  if (r.status !== 200) throw new Error('test sign-in failed: ' + r.status);
  session = await r.json();
  return session;
}

async function authFetch(url, options) {
  const { access_token: token } = await login();
  const opts = Object.assign({}, options);
  opts.headers = Object.assign({}, opts.headers, { Authorization: 'Bearer ' + token });
  return fetch(url, opts);
}

/* Store the login in the page's origin the way index.html does; then open pos.html. */
async function signIn(page, origin) {
  const data = await login();
  await page.goto((origin || BASE) + '/index.html');
  await page.evaluate((d) => saveSession(d), data);
}

module.exports = { authFetch, signIn, login };
