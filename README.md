```text
 ____  ____  ___ __   __  _    ____ __   __
|  _ \|  _ \|_ _|\ \ / / / \  / ___|\ \ / /
| |_) | |_) || |  \ V / / _ \| |     \ V /
|  __/|  _ < | |   \ / / ___ \ |___   | |
|_|   |_| \_\___|   V /_/   \_\____|  |_|

       I N S T A G R A M   P R I V A C Y   T O O L
```

<div align="center">

# Instagram Privacy Tool

**Control the visibility of your follower and following lists.**

A small command-line tool for checking and changing your own account's list privacy setting.

[Quick start](#quick-start) · [Change the setting](#change-the-setting) · [Session](#session) · [License](#license)

</div>

---

## Quick start

You need **Python 3.11 or newer**, an internet connection, and a terminal. The tested computer setup is Linux.

Download and extract the project. In a terminal, open its folder and install the dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

In a new terminal, return to the project folder and run `. .venv/bin/activate` again.

### Sign in and check

Sign in to your own account, save a local session, and check the settings:

```bash
python privacy_query.py --save-session
```

Your username, password, and any verification code are entered at hidden prompts. Some challenges may require the official Instagram app.

To check again using your saved session:

```bash
python privacy_query.py --reuse-session
```

The query also reports `hide_self_from_others_lists`. Changing that separate option has **not been verified**.

## Change the setting

**Hide** your follower and following lists:

```bash
python privacy_mutation.py --setting hide_followers_following_list --value true --execute --reuse-session
```

**Unhide** your follower and following lists:

```bash
python privacy_mutation.py --setting hide_followers_following_list --value false --execute --reuse-session
```

The tool reads the setting back after each change. Enabling and disabling it was tested on one account; the read-back does not independently confirm what other people see.

## Session

Saving a session is optional. To check without saving one, run `python privacy_query.py`. For a change without saving, replace `--reuse-session` with `--login` in the relevant command.

A saved session is stored locally in `.session/session.json` with owner-only permissions. Keep it private. To delete it, run this from the project folder:

```bash
rm -rf .session
```

---

This tool uses an **unofficial Instagram interface** that may change or stop working. It is not affiliated with Instagram or Meta.

## License

Project code: [MIT License](LICENSE) © 2026 Mohammed Al Murisi. This license does not grant rights to Instagram, Meta, or other third-party materials. Dependency licenses and attribution are in [THIRD_PARTY.md](THIRD_PARTY.md).
