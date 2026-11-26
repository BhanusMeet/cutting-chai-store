# QR table ordering for your store

Guests scan the QR code on their table and order in their own language. The kitchen
sees the order live, staff ring up takeaway at the counter, and the owner manages the
menu, prices, stock-outs, table QR codes, passwords and backups. It runs on the store
computer and needs only Python 3.11 or newer.

## Start it

```powershell
cd qr-order
python server.py --lan
```

Leave that window open. Use `python server.py` (without `--lan`) to allow this
computer only. `--port` changes the port (default 8000).

**First time:** the window prints a setup code. Open `http://localhost:8000/setup.html`,
enter the code, then your restaurant name, tables, owner password and staff PIN.
Setup can be done only once. The sample menu is optional and its prices are
placeholders: change every one before opening.

## Screens

| Screen | Address | Who | Sign-in |
|---|---|---|---|
| Staff home | `/` | Staff | none (links only) |
| Guest menu | `/r/<outlet>/<table>?k=<table code>` (inside the table's QR) | Guests | none |
| Kitchen | `/kitchen.html?outlet=<outlet>` | Kitchen tablet | Staff PIN |
| Counter | `/counter.html?outlet=<outlet>` | Cashier | Staff PIN |
| Token board | `/board.html?outlet=<outlet>` | Takeaway customers | none (numbers only) |
| Owner panel | `/admin.html?brand=<brand>` | Owner | Owner password |

## Before opening

1. Owner panel -> Menu: add your sections and dishes and check every price.
2. Owner panel -> Tables & QR: press **Use my Wi-Fi address**, print the sheet, stick one code on each table.
3. Place a test order from a phone, then check it on the kitchen screen.
4. Give the store computer a fixed Wi-Fi address (in the router), or the printed codes stop working when the address changes.
5. Keep guest Wi-Fi password protected.

## Printing

Printers plug into the **store computer** (Windows) by USB. Use a receipt printer that
understands ESC/POS (most 58 mm and 80 mm thermal printers do).

1. Plug it in, switch it on and install the maker's Windows driver, so it appears in
   Windows **Printers**. (Windows' "Generic / Text Only" driver on its USB port can also work.)
2. The kitchen screen asks **"Use this printer?"**. Choose the paper width and accept.
3. Press **Printer -> Print test slip**. Check that English, Hindi and Marathi are readable.

Do not want to print? Choose **No print**: orders show on screens only and you are not
asked again. It can be changed in Owner panel -> Settings or the kitchen's **Printer** button.

- Counter slips (tea and other ready items) print at once; kitchen slips follow your gap.
- **Unplugged, offline or paper-out reported:** slips wait and print by themselves once fixed.
- **Unsure whether it printed:** printing stops. Look at the paper, then press **Try again**
  (marked REPRINT) or **Clear failed slips**.
- "Printed" means Windows delivered the slip to the printer. **Many cheap printers do not report
  an empty roll**, so watch the paper and use **Reprint** when needed.
- Slips that waited over 2 hours are not printed by themselves.
- One store computer prints for the printers plugged into it. Network and Bluetooth printers are not supported.

## Money, stock and Excel sheets

**Bills.** Counter sales record how the customer paid. Guest table orders and "Pay later" orders
appear under **Bills** on the Counter screen: press Cash, UPI or Card when the money arrives. The list shows the last 31 days; older unpaid orders still show
in the reports for their dates.
If a paid order is rejected, Bills reminds staff to give the money back. Only the owner can undo
a payment marked by mistake (Money & Excel tab); it is logged.

**Stock and margins** (owner panel):

1. **Stock:** add ingredients (g, ml or pieces), set their cost, record purchases, and set a low-stock warning.
2. **Dish costs:** for each dish enter what one plate uses.
3. From then on each order takes its ingredients out of stock. Rejecting an order that was not made
   yet puts them back; rejecting a ready one counts as waste. Stock may go below zero (it is flagged);
   it never blocks a sale. Count the shelf regularly and press **I counted this much**.

A dish without a full ingredient list and costs has an **unknown** cost. Reports leave its sales out
of the margin and say how much was left out. Buying at a new price updates the cost as an average of
old and new stock. Changes affect new orders only.

**Gross margin is not profit:** rent, wages, gas, power and taxes are not taken out. These are not
GST invoices or accounts; ask your accountant.

**Order sheets** (Money & Excel tab): pick a day or month and download. Each finished day and month is
also saved to `data/reports` on the store computer (checked hourly while the server runs).

**Your own layout:** download the starting layout, change it in Excel, and upload the `.xlsx`
(up to 2 MB). Words like `{{sales}}` are filled in once; a row with words like `{{order.token}}` or
`{{line.item}}` repeats for every entry, and totals such as `=SUM(E4:E4)` grow with it. Use one list
per row. Sheets with repeating rows cannot contain Excel "tables", filled-down or array formulas.
Charts, pictures and print areas are not moved when rows are added; formulas that refer to a repeating
row from **another** sheet are not adjusted. Macros and links to other files are refused.

## Payments

The store does **not** take money. Guests pay at the counter; the counter screen only
records cash, UPI or card. Online payment stays switched off until you have your own
payment-gateway account and a developer connects and reviews it.

## Security, in plain words

- Only someone holding a table's QR code can order for that table. If a code is misused: Tables & QR -> **Make new QR codes** (then reprint all of them).
- Passwords and PINs are stored scrambled (hashed). Repeated wrong guesses are blocked for a while.
- Staff sign-ins end after 4 idle hours (12 hours at most), and when the server restarts.
- Owner panel -> **Activity** shows sign-ins, wrong guesses, price changes, counter sales and backups.
- Plain `--lan` uses unencrypted HTTP: anyone able to listen on your Wi-Fi could read a password.
  Keep staff devices off shared or public Wi-Fi. HTTPS works with `--cert` and `--key`.
- A backup is saved daily in `data/backups` (last 14). **Download a copy to another device regularly.**
  To restore: stop the server, replace `data/store.db` with the backup copy, and delete
  `data/store.db-wal` and `data/store.db-shm` if present.
- Do not share the `data` folder: it holds your sales and password hashes.
- These protections have been tested by this project's own tests, **not** by an independent
  security reviewer. Get one before taking online payments or putting the store on the internet.

## Test it

```powershell
python loadtest/blackbox_test.py
```

It starts its own empty store on a spare port (your real data is not touched), with a
simulated printer, and attacks it from outside like a user or an intruder. It takes a few
minutes. It cannot tell whether your real printer prints correctly: use the test slip for that.
The older load tests in `loadtest/` were written for the earlier demo build and do not
run against this version until they are updated.

## How it is built

`server.py` and `store.py` (API, live updates), `security.py`, `core.py`, `db.py`
(SQLite, file `data/store.db`), `printer.py` (slip pacing), `printing.py`, `print_routes.py` and
`winprint.py` (USB printing), `ledger.py`, `xlsx.py` and `business_routes.py` (money, stock,
Excel), `web/` (plain HTML,
CSS and JavaScript, no build step). Hindi and Marathi interface text are first drafts:
have a native speaker check them.

## Not built yet

- **Printing is untested on a real printer.** It has been tested with a simulated one only.
- Expenses other than ingredients (so no profit figure), supplier orders, expiry dates.
- **Online payment**, GST bills, connecting to an existing billing system.
- Per-person staff accounts, adding more outlets or brands from the screen.
- **Hosting on the internet.** Behind a proxy, the sign-in limits need changes first
  (they count by network address).
- The QR library and fonts load from the internet, so the QR sheet and themes need a connection.
