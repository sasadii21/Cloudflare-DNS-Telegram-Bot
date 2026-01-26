# Cloudflare DNS Telegram Bot

A lightweight Telegram bot to manage Cloudflare DNS records (A Records) quickly via Inline Buttons. Designed for ease of use without needing to log in to the Cloudflare dashboard.

## Features
- 🌐 List all Zones (Domains) in your Cloudflare account.
- 📂 View DNS records for a specific domain.
- ✏️ **Update IP** for existing subdomains instantly.
- ➕ **Add new A records** (Subdomains) directly from Telegram.
- 🛡 Preserves Proxy status (Orange/Grey cloud).
- 🔒 Secured by Admin ID (only you can control the bot).

## Installation on VPS (Ubuntu/Debian)

3.**🔑 How to Get Your Cloudflare API Token**
## 
To run this bot, you need a Cloudflare API Token with permission to edit DNS records.

1.  Log in to your **[Cloudflare Dashboard](https://dash.cloudflare.com/profile/api-tokens)**.
2.  Go to **My Profile** > **API Tokens**.
3.  Click on the **Create Token** button.
4.  Find the **Edit zone DNS** template and click **Use template**.
5.  Under **Zone Resources**, select:
    * `Include`
    * `All zones` (or select the specific specific domain you want to control).
6.  Click **Continue to summary**, review the permissions, and click **Create Token**.
7.  ⚠️ **Copy the token immediately.** Cloudflare will not show it to you again!




1. **Clone the repository:**
   ```bash
   git clone https://github.com/sasadii21/Cloudflare-DNS-Telegram-Bot.git
   cd Cloudflare-DNS-Telegram-Bot

2.**install:**
```bash
sudo bash install.sh
