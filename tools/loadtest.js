// k6 load test: 40-50 concurrent students doing login -> search -> submit.
// Per technical note section 9, this must ultimately run against the real
// VPS + real DRES, not just locally; this script just needs the base URL
// changed (BASE_URL env var).
//
// Usage (single shared test account, fine for a local sanity check):
//   k6 run tools/loadtest.js --env BASE_URL=http://127.0.0.1:5000 --env VUS=10 --env DURATION=1m
//
// Usage (one DRES account per virtual user, for the real 40-50 user test):
//   k6 run tools/loadtest.js --env BASE_URL=https://search.tenmien.edu.vn \
//       --env CREDS_FILE=./students.csv --env VUS=40 --env DURATION=10m
//   # students.csv: one "username,password" per line, no header

import http from "k6/http";
import { check, sleep } from "k6";
import { SharedArray } from "k6/data";

const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:5000";
const CREDS_FILE = __ENV.CREDS_FILE;

const credentials = new SharedArray("credentials", function () {
  if (!CREDS_FILE) {
    return [{ username: __ENV.DRES_USERNAME || "student", password: __ENV.DRES_PASSWORD || "student" }];
  }
  return open(CREDS_FILE)
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [username, password] = line.split(",");
      return { username, password };
    });
});

export const options = {
  scenarios: {
    students: {
      executor: "constant-vus",
      vus: Number(__ENV.VUS || 40),
      duration: __ENV.DURATION || "2m",
    },
  },
  thresholds: {
    "http_req_duration{endpoint:search}": ["p(95)<2000"],
    "http_req_duration{endpoint:submit}": ["p(95)<2000"],
    http_req_failed: ["rate<0.01"],
  },
};

const QUERIES = [
  "a stone castle wall",
  "a red bus near a river",
  "people walking in a square",
  "a church with a tower",
  "a bridge over water",
  "a narrow cobblestone street",
];

export default function () {
  const cred = credentials[(__VU - 1) % credentials.length];
  const jar = http.cookieJar();
  jar.set(BASE_URL, "ignored", "ignored"); // ensure jar is initialized per-VU

  const loginRes = http.post(
    `${BASE_URL}/api/login`,
    JSON.stringify({ username: cred.username, password: cred.password }),
    { headers: { "Content-Type": "application/json" }, tags: { endpoint: "login" } }
  );
  check(loginRes, { "login ok": (r) => r.status === 200 });
  if (loginRes.status !== 200) {
    sleep(5);
    return;
  }

  sleep(1 + Math.random() * 2);

  const query = QUERIES[Math.floor(Math.random() * QUERIES.length)];
  const searchRes = http.post(
    `${BASE_URL}/api/search`,
    JSON.stringify({ query, k: 50 }),
    { headers: { "Content-Type": "application/json" }, tags: { endpoint: "search" } }
  );
  check(searchRes, { "search ok": (r) => r.status === 200 });

  sleep(1 + Math.random() * 3);

  let results = [];
  try {
    results = JSON.parse(searchRes.body).results || [];
  } catch (e) {
    results = [];
  }

  if (results.length > 0) {
    const pick = results[Math.floor(Math.random() * results.length)];
    const submitRes = http.post(
      `${BASE_URL}/api/submit`,
      JSON.stringify({ id: pick.id }),
      { headers: { "Content-Type": "application/json" }, tags: { endpoint: "submit" } }
    );
    check(submitRes, { "submit ok or rejected": (r) => [200, 409, 429].includes(r.status) });
  }

  http.post(`${BASE_URL}/api/logout`, null, { tags: { endpoint: "logout" } });

  sleep(2 + Math.random() * 3);
}
