# Customers: track your orders, sign in with a code

Customers sign in on the same page as staff – **Customer? Track your orders** – with a 6-digit code sent to the
**mobile number or email on their order**, and land on **My orders**. The phone app does the same (*Code (SMS /
email)* on its sign-in screen). Staff can also sign in with a code, by email or SMS.

## What a customer sees (`views/customer/orders.py`, `modules/customers.py`)
- Every order that carries their mobile number or email, from any branch: open orders first with the live stage
  (*Order received → Partner assigned → Picked up → On the way → Delivered*), the ETA and promised time, the
  partner's first name and vehicle, a small map for the next one, and the tracking link to share. Delivered orders
  below, with *Proof* when a photo/code/signature was recorded. Refreshes every 30 s.
- Never phone numbers, other customers' stops or anything else of the branch.
- API (for the app): `GET /my/orders`, `GET /my/orders/{id}` – customers only (403 for everyone else, and
  customers get 403 on every other endpoint).

## Accounts – nothing to register
- The first code request for a number or email that is **on at least one order** creates the customer's account
  (role *customer*, no branch, no usable password). A number that is on no order gets *No orders found* and **no
  text is sent** – so strangers can't make the app send SMS (cost, spam).
- Admins add the customer's email in **Assign Work → New order** (or the `email` column of the CSV). The mobile
  number is the order's *Phone*. Signing in by email or by mobile gives the same account.
- Customers can't use a password or *Forgot password*; codes only.

## The codes
- 6 digits, valid 5 minutes, 3 tries, single use (even if two tries race), at most **3 codes per 10 minutes** per
  account. Only a salted hash is stored – with Twilio Verify not even that (Twilio holds and checks the code).
- Channel: a typed mobile number gets an **SMS**, an email or ID gets an **email**; staff can tick *Send by SMS*.
- **No codes on screen on a real site.** Without email/SMS set up, codes are shown (labelled DEMO) only when
  `DEMO_MODE` or `OTP_DEMO` is `true`. Otherwise code sign-in says *Sign-in codes aren't set up yet* – before
  this, a site without providers would have let anyone sign in as anyone by typing their ID.

## Make it real
### Email (any SMTP; Gmail shown)
1. Turn on 2-Step Verification for the Google account that will send the codes.
2. Google Account → Security → **App passwords** → create one (16 letters).
3. Set `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER=you@gmail.com`, `SMTP_PASSWORD=<app password>`,
   optionally `SMTP_FROM=DEPORT <you@gmail.com>`.

### SMS (Twilio)
1. Create a Twilio account (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` from the console). A **trial** account can
   only text numbers you verified in the console – upgrade to text any customer.
2. Recommended: Console → **Verify** → create a service → set `TWILIO_VERIFY_SID` (starts with `VA`). Twilio makes,
   sends and checks the code. For Indian numbers, SMS needs DLT-registered templates; Twilio Verify sends OTPs on
   its own registered templates in many countries – check Twilio's current India guidance before going live.
3. Or plain SMS: `TWILIO_SMS_FROM` (a Twilio number / approved sender id); DEPORT makes the code and Twilio
   delivers the text (for India your own DLT registration applies).
4. `SMS_DEFAULT_COUNTRY` (default `91`) completes 10-digit numbers.

Put the keys in `.env` / the host's environment, or in `.streamlit/secrets.toml` (Streamlit Cloud: App → Settings →
Secrets). Never commit them.

## Demo
With `DEMO_MODE=true` (or `OTP_DEMO=true`) and no providers: **Customer? Track your orders** → `90000 10007`
(Ukkadam Wholesale Traders, D07) → the DEMO code appears → **My orders** shows D07 on its way with Karthik.
To try a real email: create an order with your email in Assign Work, then sign in with that email.

## Limits
- Tamil for customers isn't there yet (the partner pages have it).
- One account per customer identity; a business with many phone numbers gets one account per number.
- WhatsApp as a code channel is possible with Twilio Verify (`Channel=whatsapp`) but not switched on.
