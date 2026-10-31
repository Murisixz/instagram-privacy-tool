<div align="center">

```text
██████╗  ██████╗  ██╗ ██╗   ██╗  █████╗   ██████╗ ██╗   ██╗
██╔══██╗ ██╔══██╗ ██║ ██║   ██║ ██╔══██╗ ██╔════╝ ╚██╗ ██╔╝
██████╔╝ ██████╔╝ ██║ ██║   ██║ ███████║ ██║       ╚████╔╝
██╔═══╝  ██╔══██╗ ██║ ╚██╗ ██╔╝ ██╔══██║ ██║        ╚██╔╝
██║      ██║  ██║ ██║  ╚████╔╝  ██║  ██║ ╚██████╗    ██║
╚═╝      ╚═╝  ╚═╝ ╚═╝   ╚═══╝   ╚═╝  ╚═╝  ╚═════╝    ╚═╝

          I N S T A G R A M   P R I V A C Y   T O O L
```

**Hide or show the follower and following lists on your own Instagram account from the command line.**

[Install](#install) · [Usage](#usage) · [Saved session](#saved-session) · [Limitations](#limitations) · [Tests](#tests) · [License](#license)

</div>

---

## What it does

Two small Python scripts:

| Script | Purpose |
| --- | --- |
| `privacy_query.py` | Reads your account's privacy settings. It does not change anything. |
| `privacy_mutation.py` | Turns one setting on or off, then reads it back to check the result. |

Your username, password, and verification code are typed at hidden prompts. They are never passed as command-line arguments or written to disk.

> [!WARNING]
> This tool uses an **unofficial Instagram interface**. It is not affiliated with Instagram or Meta, and it may stop working at any time.

---

## Install

Requires **Python 3.11 or newer**. It has been tested on Linux. It has not been tested on macOS or on a real Windows device (see [Tests](#tests)).

### Linux

```bash
git clone https://github.com/Murisixz/instagram-privacy-tool.git
cd instagram-privacy-tool
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Debian or Ubuntu, if `venv` is missing, install it with `sudo apt install python3-venv`.

### macOS

```bash
git clone https://github.com/Murisixz/instagram-privacy-tool.git
cd instagram-privacy-tool
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

If `python3 --version` shows a version older than 3.11, install a newer one from [python.org](https://www.python.org/downloads/) or with `brew install python`.

### Windows (PowerShell)

```powershell
git clone https://github.com/Murisixz/instagram-privacy-tool.git
cd instagram-privacy-tool
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

In Command Prompt, activate with `.venv\Scripts\activate.bat` instead.

### Android (Termux) — experimental, untested

This has **not been tested**. The steps below may fail.

```bash
pkg update
pkg install python git
git clone https://github.com/Murisixz/instagram-privacy-tool.git
cd instagram-privacy-tool
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

- The only direct dependency is `instagrapi`. It pulls in `curl_cffi`, `Pillow`, `pydantic-core`, and `pycryptodomex`, which all contain compiled code. If pip finds no prebuilt package for Termux, it tries to compile them. That may need extra build tools (for example, `pkg install clang rust`) and can still fail.
- Keep the project in Termux's home directory, not in shared storage (`/sdcard`). The session file needs owner-only permissions, which shared storage cannot provide.

> [!TIP]
> Open a new terminal later? Go back to the project folder and activate the environment again (`source .venv/bin/activate`, or `.venv\Scripts\Activate.ps1` on Windows).

---

## Usage

Run every command from the project folder with the virtual environment active.

### 1. Log in and check your settings

Log in once and save a local session:

```bash
python privacy_query.py --save-session
```

Later checks can use the saved session without asking for your password:

```bash
python privacy_query.py --reuse-session
```

To log in without saving a session:

```bash
python privacy_query.py
```

The output shows two settings:

```text
hide_followers_following_list: false (server returned a boolean)
hide_self_from_others_lists: false (server returned a boolean)
```

Some logins ask for verification that only the official Instagram app can complete.

### 2. Hide your follower and following lists

```bash
python privacy_mutation.py --setting hide_followers_following_list --value true --execute --reuse-session
```

### 3. Show them again

```bash
python privacy_mutation.py --setting hide_followers_following_list --value false --execute --reuse-session
```

**Without a saved session:** replace `--reuse-session` with `--login` in the commands above.

If you leave out `--execute`, the script only prints the request it would send. Nothing is sent.

After each change, the script reads the setting back. Turning it on and off was tested on one account. A matching read-back does not prove what other people actually see.

---

## Saved session

`--save-session` stores your login session in `.session/session.json`. It is excluded from git. The file is **not encrypted**, so treat it like a password.

The tool limits access to your own account and refuses to save or load the session if it can't:

| | Linux, macOS, Termux | Windows |
| --- | --- | --- |
| Access limited by | Folder mode `700`, file mode `600` | The built-in `icacls` replaces the folder's and file's permissions with one entry for your Windows account. Inherited permissions are removed. |
| Links refused | Symbolic links | Symbolic links, junctions, and other reparse points |
| Owner checked | Yes. Must be your user ID. | No. Permissions are reset on every use instead. |
| Re-applied | Every time the session is loaded | Every time the session is loaded |

Administrators (root on Unix) can still read the file. On Windows, drives without NTFS permissions, such as FAT32 or exFAT USB drives, cannot be restricted, so the tool refuses to save a session there.

To delete it:

```bash
# Linux, macOS, Termux
rm -rf .session
```

```powershell
# Windows (PowerShell)
Remove-Item -Recurse -Force .session
```

Deleting the file does not log you out on Instagram's side. To end the session there too, go to **Accounts Center → Password and security → Where you're logged in** in the Instagram app.

---

## Limitations

- **Hiding your account from other people's lists is not verified.** The second setting, `hide_self_from_others_lists`, is shown by the query, and `privacy_mutation.py` accepts it. However, changing it has **not been verified** to work.
- **Unofficial interface.** Instagram can change or block it at any time, and the tool may then stop working.
- **Platforms.** Only Linux has been tested. Windows session handling is covered by simulated tests but has not been run on a real Windows device. macOS is untested. Android/Termux is experimental.

---

## Tests

The tests need no Instagram login and send no network requests:

```bash
python -m unittest
```

| What | How it is tested |
| --- | --- |
| Unix session storage (modes, owner checks, symlinks) | Real files on Linux |
| Windows session storage (`icacls` calls, junction checks, failure handling) | **Simulated** on any OS. Fakes stand in for `whoami.exe` and `icacls.exe`, and Unix-only functions are hidden. This checks the logic, not real Windows permissions. |
| Real Windows permissions | A test that runs only on Windows and checks the resulting permissions with `icacls`. **It has not been run yet.** It is skipped on other systems. |

---

## License

Project code: [MIT License](LICENSE) © 2026 Mohammed Al Murisi.

This license does not grant rights to Instagram, Meta, or other third-party materials. Dependency licenses and attribution are listed in [THIRD_PARTY.md](THIRD_PARTY.md).
