```text
##### #   #  #### #####  ###   #### ####   ###  #   #
  #   ##  # #       #   #   # #     #   # #   # ## ##
  #   # # #  ###    #   ##### #  ## ####  ##### # # #
  #   #  ##     #   #   #   # #   # #  #  #   # #   #
##### #   # ####    #   #   #  #### #   # #   # #   #

####  ####  ##### #   #  ###   #### #   #     #####  ###   ###  #
#   # #   #   #   #   # #   # #      # #        #   #   # #   # #
####  ####    #   #   # ##### #       #         #   #   # #   # #
#     #  #    #    # #  #   # #       #         #   #   # #   # #
#     #   # #####   #   #   #  ####   #         #    ###   ###  #####
```

An unofficial command-line tool to hide or unhide your Instagram follower and following lists. The change was tested on one account; the read-back does not independently confirm what other people see.

## Install

You need a computer with Python 3.11 or newer, an internet connection, and a terminal. The tested setup is Linux. Download and extract the project, open a terminal in its folder, and run:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

In a new terminal, return to the project folder and run `. .venv/bin/activate` before using the commands below.

## Sign in and check

Sign in privately to your own account, save a local session, and check the settings:

```bash
python privacy_query.py --save-session
```

Enter your username, password, and any verification code at the hidden terminal prompts. Never share them or your session file. Some verification challenges may require the official Instagram app.

To check the settings again using the saved session:

```bash
python privacy_query.py --reuse-session
```

The query also reports `hide_self_from_others_lists`; changing that separate setting has not been verified.

## Hide or unhide your lists

Hide your follower and following lists:

```bash
python privacy_mutation.py --setting hide_followers_following_list --value true --execute --reuse-session
```

Unhide them:

```bash
python privacy_mutation.py --setting hide_followers_following_list --value false --execute --reuse-session
```

After each change, the tool reads the setting back. To sign in without saving a session, run `python privacy_query.py` to check the settings, or replace `--reuse-session` with `--login` in a change command.

## Delete your saved session

The optional session is stored locally in `.session/session.json` with owner-only permissions. From the project folder, delete it with:

```bash
rm -rf .session
```

This tool uses an unofficial Instagram interface that may change or stop working. It is not affiliated with Instagram or Meta.

## License

The project's own code is licensed under the [MIT License](LICENSE), copyright 2026 Mohammed Al Murisi. This does not grant rights to Instagram, Meta, or other third-party materials. See [THIRD_PARTY.md](THIRD_PARTY.md) for dependency licenses and attribution.
