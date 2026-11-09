# SpringDev status card

The read-only card shows the Contact us pilot's reviewed candidate, eight observed checks, independent verdict, and separate presentation and landing decisions. [Pilot summary](https://github.com/spring-labs-inc/SpringDev/issues/5) · [Spring workflow rollout](https://github.com/spring-labs-inc/Spring/pull/455)

## View the card

From the SpringDev checkout, start the loopback-only server and keep its terminal open.

```sh
python3 -B status-card/serve.py --port 8766
```

Open the card in the Codex desktop browser. The browser can use a different local port when it forwards the route. The footer identifies the stages observed by the page. [Open the card](http://127.0.0.1:8766/)

If the forwarded tab reports `ERR_CONNECTION_RESET`, check the listener on the checkout host first. A task-managed preview process can stop when its session ends. Restart the loopback server, verify that `/` and `/status.json` respond, then reload the forwarded tab. If the tab still resets, reopen the original loopback URL from Codex to establish a fresh route.

| Stage | What to look for | If it fails |
| --- | --- | --- |
| Publication | The server prints its loopback URL. On the checkout host, a GET of `/status.json` returns the curated snapshot. | Check the server output and port. |
| Browser route | The card reports **Forwarded endpoint reached** when the browser-facing port differs from the publication port, or **Endpoint reached** when they match. | If publication works but the page will not open, reopen the server URL in the Codex desktop browser and check its forwarded route. |
| Rendering | The card reports **Snapshot rendered** and shows eight gate results and `APPROVE_WITH_NITS`. | If the shell opens but the snapshot is unavailable, check `/status.json` on the checkout host. If it reports **Shell only**, use issue #5 while diagnosing the card. |

A connection loss retains the last rendered snapshot and labels the route disconnected. A reachable endpoint with unusable data is labeled unavailable. Pending gates have their own section. A historical result is labeled stale for live use even while the route is connected.

## Observed airJoker verification

On November 9, 2026, the forwarded tab reported `ERR_CONNECTION_RESET` after the mac-mini preview listener stopped. After restarting the loopback server in a detached process, both `/` and `/status.json` returned HTTP 200 on mac-mini. The owner then confirmed that the Codex desktop browser on airJoker displayed **Snapshot rendered**. Codex browser control was unavailable, so the owner directly verified the browser route and render.

## Snapshot boundary

The card serves only the HTML, CSS, JavaScript, and the curated `status-card/pilot.json` snapshot. It exposes no raw evidence files and accepts only reads. It has no owner-response, issue mutation, delivery, or deployment controls.

The snapshot is maintained by editing the curated JSON from verified evidence. Its review time is the observed pilot verdict time, and its cutover time is the verified merge time. It does not poll GitHub, Spring, or FlightCheck. Update the snapshot only when a new recorded observation is available, then restart the loopback server. Owner decisions and the warning-capture follow-up stay on the tracker. [SpringDev #5](https://github.com/spring-labs-inc/SpringDev/issues/5) · [SpringDev #6](https://github.com/spring-labs-inc/SpringDev/issues/6)
