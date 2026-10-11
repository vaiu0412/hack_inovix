# Order offers and the AI call

Goal: no urgent order is silently missed. Every assigned (or reassigned) order is an **offer** the partner must
answer, and it escalates until someone does.

| Time after assigning | Offer status | What happens |
|---|---|---|
| 0 min | **Sent** → **Seen** | In-app card with **Accept** / **Can't take** (urgent orders fill the screen). Seen when the partner's app shows it. |
| 1 min | **Ringing** | Loud alarm (`assets/alert.wav`, loops every 15 s) + vibration on Android. |
| 3 min | **Calling** | AI voice call. Twilio when configured, otherwise a simulated call screen in the app (Demo mode). Not for low-priority orders. |
| 5 min | **No response** | Red alert for the Branch Admin with the next-best partner and **Reassign**. |

- **Accept** (app, or key **1** / "yes" on the call): the order is the partner's; the escalation stops.
- **Can't take** (app with a reason, or key **2** / "no"): the order goes back to the queue and the admin gets the
  red alert at once. The suggestion never picks a partner who declined or didn't answer that order.
- The partner can still accept after the 5-minute alert, until the admin reassigns.
- Times and "no call for" priorities: Super Admin → **Overview → Order escalation** (saved in the `settings` table).
- Who moves offers along: admin pages every 20 s, the partner's own app every 15 s, and the API every 20 s when no
  page is open (`ESCALATION_SCHEDULER=off` disables it). Each step is claimed with one database update, so running
  them together never rings or calls twice.
- Every step is logged in the `escalations` table and shown as a timeline in **Deliveries** (select an order).

## Demo mode (no keys)
Nothing to set up. At 3 minutes the partner's screen shows **DEPORT is calling · Demo mode** with the spoken
message and the same choices (**1 · Accept**, **2 · Can't take**).

Quick demo with short times: Super Admin → Overview → set ring 1, call 2, alert 3 → assign a *medical* order to
`DP102` → open the partner's app on a phone and wait.

## Real calls with Twilio
1. Create a Twilio account and buy (or use the trial) phone number with Voice. On a trial account, verify the
   partner phone numbers you will call (Twilio only calls verified numbers on trial).
2. Use real partner phone numbers: add the partner in **Partners → Add partner** with their number (the demo
   partners' numbers are not real; for them edit `data/partners.csv` before a reset).
3. Run the API and make it reachable from the internet:
   ```bash
   uvicorn api.main:app --port 8000
   ngrok http 8000                      # copy the https forwarding URL
   ```
4. Set the keys (environment, `.env` for Docker, or `.streamlit/secrets.toml`) – for **both** the app and the API:
   ```
   TWILIO_ACCOUNT_SID=AC...
   TWILIO_AUTH_TOKEN=...
   TWILIO_FROM_NUMBER=+1...
   PUBLIC_BASE_URL=https://<your-ngrok-id>.ngrok-free.app
   CALL_LANGUAGE=en-IN                  # optional; CALL_VOICE=Polly.Aditi for an Indian English voice
   ```
5. Restart. Super Admin → Overview shows **AI calls: Twilio**.

How a call works: DEPORT asks Twilio to call the partner with `Url = PUBLIC_BASE_URL/twilio/voice?...`. Twilio
fetches the script (TwiML `<Say>` + `<Gather>` for one key or a spoken yes/no) and posts the answer to
`/twilio/gather`, which updates the order in one transaction. Both webhooks reject requests without a valid
`X-Twilio-Signature` (checked against `PUBLIC_BASE_URL` + path + query and your auth token).

Message: *"Hello {name}, this is DEPORT. New urgent delivery: {category} to {customer} by {deadline}. Press 1 to
accept. Press 2 if you cannot."*

## Exotel / Plivo
`services/voice_call.py` has adapter slots for Exotel and Plivo (common for Indian numbers). They are stubs: with
their keys set, calls fall back to Demo mode and the timeline says so.

## Limits
- Browsers only play sound after the partner has tapped the page once (signing in counts). iPhones can't vibrate
  from a web page.
- The escalation clock is the real clock; delivery ETAs use the demo's 09:00 clock.
- The SQLite file must be shared by the app and the API (same `DB_PATH`, same machine or volume).
