# How 234 is doing: metrics

234 records how it runs in Workers Analytics Engine, in the dataset `ask234_metrics` (staging:
`ask234_staging_metrics`; `tools/deploy.sh names` shows it). Code: `host/src/turns/metrics.py` and
`host/src/turns/health.py`. There are no alerts: the numbers are read when someone asks.

## What is recorded

One data point per event, in three kinds. `index1` and `blob1` are the kind.

| Kind | When | blob2 | blob3 | blob4 | double1 | double2 | double3 | double4 |
|---|---|---|---|---|---|---|---|---|
| `turn` | a turn finishes | how it ended: `completed`, `input_required`, `failed`, `max_rounds`, `cancelled` | why it was given up (`no_progress`, `resumes_exhausted`) or empty | | duration (ms) | model rounds | prompt tokens | completion tokens |
| `tool` | a tool call of the model ends | connector | tool | `ok`, `error`, `slow`, `unknown`, `unreachable`, `refused`, `repeat` | duration (ms) | | | |
| `health` | every five minutes, for each part | `database`, `chats`, or a connector's name | `ok` or `failed` | | duration (ms) | | | |

**Never recorded:** who asked (no owner, account or visitor), which chat, what was said, or a tool's arguments
or result. `tests/test_metrics.py` sends a message with a name and an amount and checks that neither, nor the
chat id or the owner, is in any data point.

**The health check** runs on the host's cron (`*/5 * * * *`): a query on its database, a `ping` to the chats'
Durable Objects, and MCP's own `ping` to each connector after the handshake. It calls no model, so it costs
nothing and takes nothing from the day's model budget. Whether the model answers shows in the `turn` points.

**What it costs:** Analytics Engine is not billed yet. When it is, Workers Paid includes 10 million data points
and 1 million queries a month, then $0.25 per million points and $1 per million queries. At about five points
a turn that is 2 million turns a month before the first cent.

## Saved queries

Run in the dashboard (Workers & Pages → Analytics Engine) or with the SQL API:
`curl https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/analytics_engine/sql -H "Authorization: Bearer $TOKEN" -d "$QUERY"`
(a token with *Account Analytics: Read*). `_sample_interval` weights each row by Analytics Engine's sampling.

**Turns in the last hour, by how they ended:**

```sql
SELECT blob2 AS ended, SUM(_sample_interval) AS turns
FROM ask234_metrics
WHERE index1 = 'turn' AND timestamp > NOW() - INTERVAL '1' HOUR
GROUP BY ended ORDER BY turns DESC
```

**How long turns take (median and p95, last day):**

```sql
SELECT quantileWeighted(0.5)(double1, _sample_interval) AS median_ms,
       quantileWeighted(0.95)(double1, _sample_interval) AS p95_ms
FROM ask234_metrics
WHERE index1 = 'turn' AND blob2 = 'completed' AND timestamp > NOW() - INTERVAL '1' DAY
```

**Tools that fail (last day):**

```sql
SELECT blob2 AS connector, blob3 AS tool, blob4 AS outcome, SUM(_sample_interval) AS calls,
       AVG(double1) AS avg_ms
FROM ask234_metrics
WHERE index1 = 'tool' AND blob4 != 'ok' AND timestamp > NOW() - INTERVAL '1' DAY
GROUP BY connector, tool, outcome ORDER BY calls DESC
```

**Health checks that failed (last day):**

```sql
SELECT blob2 AS part, COUNT() AS failed, MAX(timestamp) AS last
FROM ask234_metrics
WHERE index1 = 'health' AND blob3 = 'failed' AND timestamp > NOW() - INTERVAL '1' DAY
GROUP BY part
```

**Model tokens per day (last week):**

```sql
SELECT toStartOfDay(timestamp) AS day, SUM(double3 * _sample_interval) AS prompt,
       SUM(double4 * _sample_interval) AS completion
FROM ask234_metrics
WHERE index1 = 'turn' AND timestamp > NOW() - INTERVAL '7' DAY
GROUP BY day ORDER BY day
```

## Not done

Alerts (email when a service level is missed) are not set up: the owner chose metrics only. Local development
writes to a local dataset that is not kept; the queries above read only what a deployment recorded.
