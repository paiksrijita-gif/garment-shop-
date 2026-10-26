# Deploying to Vercel

On Vercel, the app runs online. Your data is kept in a free **Turso** database, because Vercel cannot keep files between requests. The app needs no packages; Vercel only runs `api/index.py` and serves the `static/` folder.

You need three free accounts: **GitHub**, **Turso** and **Vercel**. Sign in to all three with GitHub to keep things simple.

---

## Step 1 — Put the code on GitHub

1. Go to https://github.com/new.
2. **Repository name:** `garment-shop`. Select **Private**.
3. Leave "Add a README", ".gitignore" and "license" **unticked**. The project already has these files.
4. Click **Create repository**, then copy the HTTPS address. It looks like `https://github.com/<you>/garment-shop.git`.
5. Push the code. Either give the address to Claude, or run these two lines in Terminal:

   ```bash
   git -C ~/Documents/garment-shop remote add origin https://github.com/<you>/garment-shop.git
   git -C ~/Documents/garment-shop push -u origin main
   ```

   If Terminal asks for a password, GitHub needs a **personal access token**, not your password. Create one at GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate, with the `repo` scope. Paste it when asked for the password.

Your real data (`data/`) never goes to GitHub. It is listed in `.gitignore`.

## Step 2 — Create the database on Turso

1. Go to https://app.turso.tech and sign up with GitHub.
2. Click **Create Database**:
   - **Name:** `garment-shop`
   - **Location:** **Mumbai (aws-ap-south-1)**. This matches the Vercel region the app is set to (`bom1`), which keeps it fast.
3. Open the database and copy its **URL**. It looks like `libsql://garment-shop-<you>.turso.io`.
4. Click **Create Token**. Choose **Read & Write** and **no expiry**, then copy the token. Keep it secret; anyone with it can read your shop data.

You don't need to create any tables. The app creates them the first time it starts.

## Step 3 — Deploy on Vercel

1. Go to https://vercel.com/new and import the `garment-shop` repository. Allow Vercel to access it if asked.
2. **Framework Preset:** `Other`. Leave the build and output settings as they are; `vercel.json` already sets them.
3. Open **Environment Variables** and add three:

   | Name | Value |
   |---|---|
   | `TURSO_DATABASE_URL` | the `libsql://…` URL from Step 2 |
   | `TURSO_AUTH_TOKEN` | the token from Step 2 |
   | `GS_SETUP_KEY` | a long secret phrase you make up, e.g. `lakshmi-shop-setup-7291-blue` |

4. Click **Deploy**, then open the `https://….vercel.app` address when it finishes.
5. The first screen asks for the **Setup key**. Type your `GS_SETUP_KEY`, then create the owner account. Only someone who knows this key can create the owner account, so a stranger who finds the site can't take it over.
6. Go through the setup wizard: opening cash and bank, suppliers, opening stock and customers. Then add staff under **Settings → Staff & permissions**.

Staff open the same `https://….vercel.app` address on their phones and sign in with their own accounts.

## After it is live

- **Updates:** every `git push` to `main` redeploys automatically.
- **Backups:** use **Settings → Download backup** regularly. Turso also keeps a point-in-time history of the database.
- **Changing a variable:** after you edit an environment variable in Vercel, redeploy (Deployments → ⋯ → Redeploy) so the change takes effect.
- **If the site shows "Database not configured" or "Cannot open the database":** check the two `TURSO_…` variables, then redeploy.

## Good to know

- **Internet is required.** The online app can't record sales when the shop's internet is down. A phone hotspot is a good backup. The local version (`python3 server.py`) still works offline.
- **Vercel plan:** Vercel's free Hobby plan is for personal, non-commercial use. A business should use **Vercel Pro**. Turso's free plan is plenty for one shop.
- **Speed:** each screen makes several database calls. With Vercel and Turso both in Mumbai this stays quick. If you pick other regions, keep the two in the same place. The Vercel region is the `regions` setting in `vercel.json`.
- **Trying the demo data online:** make a second Turso database for testing. Never load demo data into your real one.

## Moving existing local data to Turso (optional)

If you already entered real data in the local app (`data/shop.db`), copy it into the new database **before** you open the Vercel site for the first time. Install the Turso CLI from https://docs.turso.tech/cli/installation, then run:

```bash
turso auth login
sqlite3 ~/Documents/garment-shop/data/shop.db .dump > shop-dump.sql
turso db shell garment-shop < shop-dump.sql
```

Then deploy. Your owner login, staff and every transaction come across as they are, so there is no setup key step.
