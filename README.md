# HireHub: job dashboard with UPI premium plans (Flask)

## Run locally
    python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
    pip install -r requirements.txt
    cp .env.example .env                                  # then edit the values
    python app.py                                         # http://127.0.0.1:5000

## Settings (.env locally, Environment tab on Render)
- UPI_ID, UPI_NAME: your UPI ID and payee name. Buyers see a QR code and a "Pay with UPI app" button built from them.
- ADMIN_EMAIL, ADMIN_PASSWORD: the admin account is created on first start. Log in at /login, then open /admin.
- SECRET_KEY: any long random string.
- DATABASE_URL: leave empty locally (SQLite). In production use a Postgres URL (Neon or Supabase free tier), otherwise data is lost on redeploy.

## How payments work
1. User picks a plan and gets an 8-minute window (timer is enforced on the server; the order expires after it).
2. User pays your UPI ID and enters the 12-digit UTR number.
3. You open /admin, Payments: match amount and UTR with your UPI app or bank statement, then press Approve. Premium starts automatically (a new plan adds to any remaining time). Press Reject for wrong or fake UTRs.
For automatic verification later, add a gateway such as Razorpay or Cashfree (needs business KYC).

## Managing users, jobs, reviews (/admin)
- Users: add premium days by hand, or revoke premium.
- Jobs: add manually, delete, or press Sync to import from Ashby's public API (Snowflake). Add more companies in sync_ashby() in app.py.
- Reviews: premium members submit reviews; they show on the home page only after you approve them.

## Jobs from the other sites
Most listed sites have no public API and many forbid scraping in their terms. Check each site's terms and robots.txt before automating, and add a fetcher like sync_ashby() only where allowed. Every job links to the original site. The six "Demo" jobs are placeholders: delete them in /admin before launch.

## Deploy on Render (recommended)
Push this folder to GitHub, then Render, New Web Service: Build `pip install -r requirements.txt`, Start `gunicorn app:app`, add the settings above. Vercel can run Flask too, but it needs a Postgres DATABASE_URL and static files placed in a public folder; I have not tested it there.

## Before you launch
Add Terms, Privacy and Refund pages, do not promise jobs or hiring speed in your marketing, and show only real customer reviews.
