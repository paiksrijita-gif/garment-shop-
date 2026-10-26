# Google Sheet dashboard on Vercel

Your data lives in one Google Sheet that you edit by hand. The website on Vercel reads that sheet and shows the metrics. There is no other database, no login and nothing to install.

Google Sheet: **Garment Shop Database** (in your Google Drive)
GitHub repo: https://github.com/paiksrijita-gif/garment-shop-

---

## Step 1 — Let the website read the sheet

1. Open the **Garment Shop Database** sheet.
2. Click **Share**. Under **General access**, choose **Anyone with the link**, set the role to **Viewer**, and click **Done**.
3. *(Recommended)* Go to **File → Settings → Locale** and choose **India**, so dates show as DD/MM/YYYY.
4. Copy the sheet's address from the browser bar. It looks like `https://docs.google.com/spreadsheets/d/1UaY…/edit`.

"Viewer" means people who have the link can see the data but cannot change it. Only you can edit the sheet.

## Step 2 — Deploy on Vercel

1. Go to https://vercel.com/new and import the **`garment-shop-`** repository.
2. **Framework Preset:** `Other`. Leave the build settings as they are; `vercel.json` already sets them.
3. Under **Environment Variables**, add one:

   | Name | Value |
   |---|---|
   | `GOOGLE_SHEET_ID` | the sheet link you copied in Step 1 |

4. Click **Deploy**, then open the `https://….vercel.app` address when it finishes.

If the page says *Cannot load the Google Sheet*, check Step 1.2 (sharing) and the `GOOGLE_SHEET_ID` value. After changing the value, redeploy: Deployments → ⋯ → Redeploy.

## Step 3 — Keep the sheet up to date

Row 1 holds the column headers; don't rename or remove them. Each row below is one stock entry:

| Column | What to type |
|---|---|
| Date of Entry | Date the stock came in, e.g. `27/10/2026` |
| Product ID | Your code for the item, e.g. `KUR-001` (required) |
| Product Category | e.g. Women, Men, Kids |
| Product Type | e.g. Kurti, Saree, Jeans |
| Sizes | e.g. `S, M, L, XL` or `Free Size` |
| Seller | Who you bought it from |
| Cost | Cost **per unit** in ₹ (numbers only) |
| Total Units | Units received |
| Selling Price | Selling price **per unit** in ₹ |
| Units Sold | Update this as items sell |
| Units available, Revenue, Profit | Worked out automatically — leave them alone |

How the numbers are worked out:
- **Units available** = Total Units − Units Sold
- **Revenue** = Units Sold × Selling Price
- **Profit** = Units Sold × (Selling Price − Cost). Unsold stock is not counted as a loss; it stays as stock at cost.

The website always calculates these three columns itself, so they are right on the dashboard even if the sheet's own formula cells show an error.

After you edit the sheet, press **Refresh** on the dashboard. Without that, changes appear within about 15 seconds.

**Before you enter real data,** delete the 24 sample rows. Their seller names end in "(sample)".

**If a row is wrong** (missing Product ID, text in a number column, more units sold than stocked), the dashboard lists it under *rows in the sheet need attention* and leaves the rest working.

### Fixing the three formula columns in the sheet (optional)

When the sheet was created, cells K1, L1 and M1 came out as `#NAME?`. The dashboard doesn't need them. If you want the columns filled in the sheet as well:

1. Type the headers `Units available`, `Revenue` and `Profit` into K1, L1 and M1.
2. Type these formulas into row 2:
   - K2: `=IF(B2="","",H2-J2)`
   - L2: `=IF(B2="","",J2*I2)`
   - M2: `=IF(B2="","",J2*(I2-G2))`
3. Select K2:M2 and drag the small square at the corner down as far as you need.

## Good to know

- **Who can see it:** anyone who has the website address or the sheet link can see the shop's numbers. Share them only with people you trust.
- **Cost:** Vercel's free Hobby plan is enough for this personal project.
- **Trying it on your computer:** `python3 tools/dev_dashboard.py` opens the dashboard at http://127.0.0.1:8002 using the sample data. To read your real sheet instead, run `GOOGLE_SHEET_ID=<sheet link> python3 tools/dev_dashboard.py`.
- **The full shop app** (purchases, sales, returns, staff logins) still runs on your computer with `python3 server.py`. It keeps its own database and does not read the Google Sheet.
