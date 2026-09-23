# typeless-switcher

**Reset the Typeless device ID on macOS, migrate your data to a new account, and optionally automate the whole switch end to end.**

English | [简体中文](README.zh-CN.md)

> The device reset, the reverse-engineered API client and the export/import tools are based on [estarpro1022/typeless-reset-device](https://github.com/estarpro1022/typeless-reset-device) by **Kartone** (MIT License). This project adds one-click migration, first-run sign-in, automated email sign-in and Gmail verification-code retrieval. See [Credits](#credits).

> [!IMPORTANT]
> **Supported platforms and mailboxes**
> - **macOS only.** The scripts rely on the macOS Keychain, `osascript`, the `open` command and Typeless's macOS file layout. Windows or Linux users will need to adapt the code themselves.
> - **Gmail only, over IMAP.** Automated verification-code retrieval reads the inbox through Gmail's IMAP server with an app password. Other providers are not supported out of the box. If you use a different mailbox, check whether it offers IMAP access and app passwords, then adapt `gmail_code.py` yourself.
> - The alias scheme depends on Gmail ignoring dots in the local part (`y.ou@gmail.com` is delivered to `you@gmail.com`). Most other providers do not do this.

## Disclaimer

This is an unofficial tool, built by reverse engineering. It is not affiliated with or endorsed by Typeless. It changes local application data and calls Typeless's private API. Future Typeless updates may break it, and using it may conflict with Typeless's Terms of Service. Use it at your own risk and responsibility. Back up anything you care about first.

## Background

> Tested with Typeless v2.0.0 on macOS.

Typeless sends a **Device ID** with every request and uses it to limit how many accounts can sign in on one machine. Once you pass the limit, sign-in fails with:

```
The number of users logged into this device has exceeded the limit.
```

This repository provides:

| Tool | What it does |
|------|--------------|
| `reset-device-macos.sh` | Clears the Device ID so the server sees this Mac as a new device |
| `export.py` / `import.py` | Moves your dictionary (cloud), history and recordings (local) from one account to another |
| `reset-and-migrate.sh` | One command that runs export → reset → sign in to a new account → import |
| `web_login.py` | Signs in to Typeless by email in a clean Chrome session, fills in the verification code, and hands the session back to the app |
| `gmail_code.py` | Reads Typeless verification codes from Gmail over IMAP (also usable on its own) |

## Requirements

- macOS, with Typeless installed at `/Applications/Typeless.app`
- [uv](https://docs.astral.sh/uv/) and Python 3.13+
- Google Chrome. `web_login.py` drives your installed Chrome through Playwright, using a fresh temporary profile. It does not touch your normal profile, and no extra browser download is needed.
- Node.js (used to edit `app-storage.json`)
- The `trash` command. It ships with recent macOS versions; on older systems run `brew install trash`. The one-click script moves files to the Trash instead of deleting them, so every change can be undone.
- For automated sign-in: a personal Gmail account with 2-Step Verification enabled

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # install uv
uv sync                                           # install Python dependencies
```

## Quick start

### Option A: one-click migration (recommended)

**One-time setup: store a Gmail app password in the Keychain**

1. Turn on 2-Step Verification for your Google account.
2. Create an app password at <https://myaccount.google.com/apppasswords>.
3. Save it in the macOS Keychain. The account must be your plain Gmail address, **without dots**:

   ```bash
   security add-generic-password -s "typeless-reset-gmail" -a "you@gmail.com" -w "<16-character app password>"
   ```

**First run (Typeless is not signed in yet)**

There is no account to export from, so the script skips export and dictionary import and signs straight in to your first alias (`y.o.u.rname@gmail.com`). It needs your Gmail address, which you can provide in either of two ways:

```bash
# Interactive: the script asks for your Gmail address
bash reset-and-migrate.sh

# Non-interactive, e.g. when run by a script or an AI agent: pass the address as an argument
bash reset-and-migrate.sh you@gmail.com
```

In a non-interactive shell with no address given, the script exits with a usage message instead of waiting for input.

**Each time you switch accounts**, make sure Typeless is signed in to the current account, then run:

```bash
bash reset-and-migrate.sh
```

What it does:

| Step | Action |
|------|--------|
| Preflight | Determines your Gmail inbox and checks that the Keychain entry exists. If anything is missing, it stops here, before any change is made. |
| 1 | Exports the dictionary, database, recordings and settings to `backup_<timestamp>/` (skipped on first run) |
| 2 | Quits Typeless |
| 3 | Resets the Device ID and clears the local sign-in state (moved to the Trash, so it can be restored) |
| 4 | Picks the next unused Gmail dot alias, signs in on the web in a clean Chrome session, reads the code from Gmail, enters it, and passes the `typeless://` callback to the app |
| 5 | Imports the dictionary into the new account (skipped on first run) and reassigns all local history to it |
| 6 | Restarts Typeless |

The Gmail address is taken from, in order: the command-line argument, the `GMAIL_USER` environment variable, the currently signed-in account, and finally an interactive prompt. Dots are removed automatically, so `y.ou@gmail.com` and `you@gmail.com` are treated as the same inbox.

### Option B: manual workflow

```bash
uv run python3 export.py                 # 1. while signed in to the old account
bash reset-device-macos.sh               # 2. reset the Device ID
                                         # 3. sign in to the new account in Typeless
uv run python3 import.py backup_<timestamp>/   # 4. import into the new account
```

If you only need to get past the device limit, step 2 alone is enough.

## Email aliases

Gmail ignores dots in the local part, so `you@gmail.com`, `y.ou@gmail.com` and `y.o.u@gmail.com` all reach the same inbox, while Typeless treats each one as a separate account.

`web_login.py` puts every possible dot placement in one fixed order and always takes the next unused one:

- It starts with 3 dots (`MIN_DOTS`) placed at the beginning: `y.o.u.rname@gmail.com`
- Within each dot count, placements are in lexicographic order. When those run out, it moves to 4 dots, then 5, and so on. 1- and 2-dot placements come last.
- Every alias that signs in successfully is recorded in `used_aliases.txt`, and aliases found there or in `backup_*/` are skipped. So a new user always starts at `y.o.u.rname`, and if an alias has been used before, the script moves on to the next one. It stops with an error once every alias has been used, instead of reusing one.

The number of aliases depends on the length of your Gmail username (the part before `@`, without dots). A name of *n* characters has *n − 1* gaps, so it has 2^(n−1) − 1 aliases in total. The script reads the length from your address automatically, so no configuration is needed:

| Username length | 3-dot aliases | All aliases |
|-----------------|---------------|-------------|
| 6 (Gmail's minimum) | 10 | 31 |
| 8 | 35 | 127 |
| 10 | 84 | 511 |
| 12 | 165 | 2,047 |
| 16 | 455 | 32,767 |

To start from a different number of dots, change `MIN_DOTS` at the top of the alias section in `web_login.py`. If your name is too short for that many dots, the script uses as many as fit.

## How it works (reverse-engineered)

### Device ID

The Device ID comes from the native library `libUtilHelper.dylib`, which looks it up in this order:

```
1. Keychain       → found: use it
2. Local cache    → found: use it and write it back to the Keychain
3. Neither        → generate a new UUID and write it to both
```

| Storage | Location |
|---------|----------|
| Keychain | service `now.typeless.desktop.deviceIdentifier`, account `now.typeless.desktop.security.auth_key` |
| Local cache | `~/Library/Application Support/now.typeless.desktop/device.cache` |

Clearing both makes Typeless generate a new Device ID on the next launch.

### Dictionary API

The dictionary exists only on Typeless's servers. `export.py` / `import.py` call the API directly:

1. Decrypt `user-data.json` (electron-store encryption: two rounds of PBKDF2 + AES-256-CBC)
2. Build the signed headers (HMAC-SHA1 signature, and an `X-Authorization` value encrypted with CryptoJS AES)
3. Call `/user/dictionary/list` (export) and `/user/dictionary/add` (import)

### Local database

Every row in the `history` and `history_v2` tables of `typeless.db` carries a `user_id`. Migration rewrites it to the new account's id. Recordings (`.ogg`) need no changes.

### Email sign-in

The app's "Sign in with email" button opens `https://www.typeless.com/login/email?registration_origin=desktop_app` in your browser. After verification, the page redirects to `typeless://auth/...`, and macOS hands that URL to the app, which completes sign-in. `web_login.py` catches the redirect through the Chrome DevTools Protocol (`Page.frameRequestedNavigation`) and opens it with `open`, so you never have to click the browser's "Open Typeless?" prompt. Because the browser profile is fresh each time, no earlier web session can interfere, and you don't have to sign out of the website first.

### Encryption details

```
key       = PBKDF2-SHA256(SHA256("darwin-{arch}").hex() + "Typeless", "typeless-user-service", 10000, 32)
value key = PBKDF2-SHA512(key, IV.toUtf8(), 10000, 32)
format    = [16-byte IV] + ':' + [AES-256-CBC ciphertext]
```

`arch` is `arm64` (Apple Silicon) or `x64` (Intel) and is detected automatically.

## Troubleshooting

- **Sign-in stops at step 4.** `web_login.py` saves a screenshot of the page at the moment of failure to `web_login_debug.png`. Typeless may have changed its login page.
- **`Keychain 里没有 ... 的 Gmail 应用专用密码`** means the Keychain entry is missing. Check that the `-a` account is your Gmail address without dots.
- **No verification code arrives.** Make sure IMAP is available for your Gmail account, and that the app password is still valid.

## Files

```
├── reset-and-migrate.sh    # one-click migration
├── web_login.py            # automated email sign-in + alias selection
├── gmail_code.py           # Gmail IMAP verification-code reader
├── reset-device-macos.sh   # Device ID reset
├── export.py               # export dictionary, database, recordings, settings
├── import.py               # import into a new account
├── crypto_utils.py         # decryption and API request signing
└── pyproject.toml
```

## Credits

- [estarpro1022/typeless-reset-device](https://github.com/estarpro1022/typeless-reset-device) by **Kartone** (MIT): the upstream project this fork is based on. It provides the device reset, the reverse-engineered API client and the export/import tools.
- Credited by the upstream project, whose implementations it drew on:
  - [mercy719/typeless-migrator](https://github.com/mercy719/typeless-migrator)
  - [schummiking/free-typeless](https://github.com/schummiking/free-typeless)

## License

[MIT](LICENSE). The upstream copyright notice is kept as the MIT License requires.
