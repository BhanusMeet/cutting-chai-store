# Showing Cutting Chai Co. to a client

## Start it
```powershell
python pitch.py
```
Leave the window open and go to http://localhost:8010/
Sign-ins are in `data\pitch\PITCH-LOGINS.txt`. Sign in to each screen **before** the meeting, in its own browser tab.

It is a separate pitch store with **made-up** sales (marked "Sample data" on staff screens). Your real store
is not touched. On a new day it adds that day's sample orders when started.
`python pitch.py --reset` makes a fresh one with new passwords.

## Five-minute walkthrough
1. **The guest.** Owner panel -> Tables & QR -> **Open as this table** (Table 5). Show the steaming glass,
   switch to Hindi, add two Cutting Chai and a Vada Pav, type "less spicy", place the order.
2. **The kitchen.** The kitchen tab: the order and the note are there. Press **Mark ready**, then **Served to table**.
3. **The counter.** Bills: take payment for that table by UPI. (This records the payment; it takes no money.)
4. **The owner.** Overview (today, low stock), then Money & Excel -> **This month**: sales and ingredient margin.
   Download the Excel sheet. Stock: ginger and lemon are low.
5. **Their own brand.** "Your restaurant gets its own guest website. Kitchen, counter and reports work the same."
   To show the standard menu design as a contrast, use your real store or a second test store.

## Showing it on a real phone
Start with `python pitch.py --lan`, put the laptop and phone on the same **private** network, then in
Tables & QR press **Use my Wi-Fi address** and scan a code. Test this before the meeting: some networks and
hotspots block devices from reaching each other, and Windows may ask to allow Python through the firewall.
This is only for the demo. Ordering on a guest's mobile data needs the online system, which is **not built**.
Use "Open as this table" if the phone will not connect.

## Say plainly
| Works today | Planned, not built yet |
|---|---|
| Table QR ordering on the restaurant's local network, English / Hindi / Marathi, special requests | Ordering on mobile data |
| Own guest website per restaurant (Cutting Chai is the example) | Tools to manage and publish designs for you |
| Kitchen, counter, unpaid bills | One bill per table, open/close table, split bill, waiter calls |
| Stock, ingredient margin (not profit), Excel sheets | GST bills |
| USB slip printing or No print | **Not yet tested on a real printer** |
| Sign-ins, activity log, backups | Independent security review |
| | Your client panel, subscriptions, auto-debit, menu from photo, reviews |

The menu prices, ingredient costs and sales figures here are examples. Do not present them as a real
restaurant's results.
