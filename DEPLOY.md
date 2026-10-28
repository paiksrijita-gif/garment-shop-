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
3. Open **Environment Variables**. Copy everything in the project's `.env` file and paste it into the **Key** box; Vercel splits the pasted lines into separate variables by itself. The file is on your computer only, not on GitHub. If you don't have it, copy `.env.example` to `.env` and put your sheet link after `GOOGLE_SHEET_ID=`. It holds one variable:

   | Name | Value |
   |---|---|
   | `GOOGLE_SHEET_ID` | the sheet's ID or the link you copied in Step 1 |

4. Click **Deploy**, then open the `https://….vercel.app` address when it finishes.

If the page says *Cannot load the Google Sheet*, check Step 1.2 (sharing) and the `GOOGLE_SHEET_ID` value. After changing the value, redeploy: Deployments → ⋯ → Redeploy.

## Step 3 — Keep the sheet up to date

Row 1 holds the column headers; don't rename or remove them. Each row below is one stock entry:

| Column | What to type |
|---|---|
| Date of Entry | Date the stock came in, e.g. `26/10/2026` |
| Product Category | e.g. Salwar Kameez, Co-ord Set |
| Product Type | Design or brand, e.g. Pratibha Dresses (can be left empty) |
| Sizes | e.g. `XXL` |
| Seller | Who you bought it from |
| CP | Cost price **per unit** in ₹ (numbers only) |
| Total Units | Units received |
| SP | Wholesale selling price per unit |
| Units Sold | Units sold **wholesale** |
| Units sold | Units sold **retail** (the second "Units sold" column, before Retail SP) |
| Retail SP | Retail selling price per unit |
| Total Cost, Units Available, Revenue/Profit columns | Your own formulas — the dashboard works these out itself |

Use `-` or leave a cell empty when there's nothing to enter.

How the dashboard works out the numbers:
- **Units Available** = Total Units − wholesale units sold − retail units sold
- **Wholesale revenue** = Units Sold × SP, and **wholesale profit** = Units Sold × (SP − CP)
- **Retail revenue** = Units sold × Retail SP, and **retail profit** = Units sold × (Retail SP − CP)
- Unsold stock is not counted as a loss; it stays as stock at cost.

Because the dashboard calculates these itself, its numbers are right even if a formula in the sheet is wrong. **One to fix:** the sheet's own Units Available formula only subtracts wholesale sales. For Pratibha Dresses XXL (Sachi-2) it shows 28, but 3 were also sold retail, so 25 are left. To match, change that column's formula to Total Units − Units Sold − Units sold: in K2, `=IF(G2="","",G2-N(J2)-N(N2))`, then drag it down.

After you edit the sheet, press **Refresh** on the dashboard. Without that, changes appear within about 15 seconds.

**If a row has a problem** (text in a number column, units sold without a price, more units sold than stocked), the dashboard lists it under *rows in the sheet need attention* and leaves the rest working.

The dashboard reads the **first tab** of the sheet. If you ever move the data to another tab, add `GOOGLE_SHEET_GID` in Vercel with that tab's number (the digits after `gid=` in its link).

## Good to know

- **Who can see it:** anyone who has the website address or the sheet link can see the shop's numbers. Share them only with people you trust.
- **Cost:** Vercel's free Hobby plan is enough for this personal project.
- **Trying it on your computer:** `python3 tools/dev_dashboard.py` opens the dashboard at http://127.0.0.1:8002. It reads your sheet using the ID in `.env`; without a `.env`, it shows the sample data.
- **The full shop app** (purchases, sales, returns, staff logins) still runs on your computer with `python3 server.py`. It keeps its own database and does not read the Google Sheet.
