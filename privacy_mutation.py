#!/usr/bin/env python3
"""Review or explicitly apply one privacy setting, then read it back."""
import argparse
import contextlib
import json
import logging
import os
import re
import sys

import privacy_query as query

MUTATION_NAME = "IGSettingsBooleanMutation"
MUTATION_ID = "2669261950526978627082629536"
MUTATION_ROOT = "xdt_api__v1__settings__set_bool"
MUTATION_INVOCATION = (
    MUTATION_ROOT
    + '(data:{"allow_error_codes":$allow_error_codes,"callsite":$callsite,'
      '"setting_id":$setting_id,"value":$value})'
)


def build_mutation(setting, value):
    if setting not in query.SETTINGS or type(value) is not bool:
        raise ValueError("Invalid setting or value")
    return {
        "friendly_name": MUTATION_NAME,
        "root_field_name": MUTATION_ROOT,
        "client_doc_id": MUTATION_ID,
        "variables": {
            "allow_error_codes": True,
            "callsite": "account_privacy",
            "setting_id": setting,
            "value": value,
        },
    }


def mutation_field_match(key, setting):
    if not isinstance(key, str) or setting not in query.SETTINGS:
        return False
    if key in (MUTATION_ROOT, MUTATION_INVOCATION, "xdtApi_V1_Settings_SetBool"):
        return True
    return bool(re.fullmatch(r"[A-Za-z0-9_]{1,128}\$" + re.escape(MUTATION_INVOCATION), key))


def parse_mutation(response, setting):
    if isinstance(response, dict) and isinstance(response.get("stream_rows"), list):
        rows = response["stream_rows"]
        if len(rows) == 1:
            response = rows[0]
    if not isinstance(response, dict):
        return "unrecognized response", None
    if response.get("errors") or response.get("status") == "fail":
        return "GraphQL error or rejection; details redacted", None
    data = response.get("data")
    if not isinstance(data, dict):
        return "unrecognized response", None
    matches = [value for key, value in data.items() if mutation_field_match(key, setting)]
    if len(matches) != 1 or not isinstance(matches[0], dict):
        return "unrecognized or ambiguous response", None
    root = matches[0]
    if any(root.get(key) not in (None, "") for key in ("error_name_value", "errorNameValue", "fallback_message", "fallbackMessage")):
        return "setting-level error; details redacted", None
    value = root.get("value")
    if type(value) is not bool:
        return "unrecognized response", None
    return "mutation returned a Boolean", value


def run_mutation_and_verify(client, setting, value):
    request = build_mutation(setting, value)
    try:
        response = client.private_graphql_query_request(**request)
        mutation = parse_mutation(response, setting)
    except Exception:
        mutation = ("request failed or response unavailable; application is unknown", None)
        # A response is not proof that a request had no effect; always read back.
    try:
        response = client.private_graphql_query_request(
            friendly_name=query.QUERY_NAME,
            root_field_name=query.ROOT_FIELD,
            variables={"setting_id": setting},
            client_doc_id=query.QUERY_ID,
        )
        verification = query.parse_result(response, expected_setting=setting)
    except Exception as exc:
        verification = (query.classify_exception(exc, "query"), None)
    return mutation, verification


def main(argv=None):
    parser = argparse.ArgumentParser(description="Review or apply one setting using the existing saved session.")
    parser.add_argument("--setting", required=True, choices=query.SETTINGS)
    parser.add_argument("--value", required=True, choices=("true", "false"))
    parser.add_argument("--execute", action="store_true", help="Actually send the mutation and a read-only verification query.")
    auth_options = parser.add_mutually_exclusive_group()
    auth_options.add_argument("--login", action="store_true", help="Log in privately for this run without saving the session.")
    auth_options.add_argument("--save-session", action="store_true", help="Log in privately and save a local session for later use.")
    auth_options.add_argument("--reuse-session", action="store_true", help="Use a previously saved local session (the default).")
    args = parser.parse_args(argv)
    target = args.value == "true"
    request = build_mutation(args.setting, target)
    if not args.execute:
        print("Review only; no session loaded and no requests sent.")
        print(json.dumps(request, indent=2, sort_keys=True))
        print("Add --execute to send the mutation and verify the selected setting.")
        return 0
    try:
        from instagrapi import Client
    except ImportError:
        print("Missing instagrapi; install the project's requirements first.")
        return 2
    if not callable(getattr(Client, "private_graphql_query_request", None)):
        print("Installed instagrapi lacks the required mobile GraphQL method.")
        return 2
    logging.disable(logging.CRITICAL)
    try:
        username = password = code = None
        if args.login or args.save_session:
            username = query.prompt_private("Instagram username (hidden): ")
            password = query.prompt_private("Instagram password (hidden): ")
            code = query.prompt_private("Verification code if available, otherwise press Enter (hidden): ")
            if not username or not password:
                print("Username and password are required; no mutation was sent.")
                return 2
        login_failure = None
        with open(os.devnull, "w", encoding="utf-8") as quiet, contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            client = Client()
            client.challenge_code_handler = lambda _username, _choice: query.prompt_private("Verification code (hidden): ")
            if args.login or args.save_session:
                try:
                    authenticated = client.login(username, password, verification_code=code)
                except Exception as exc:
                    authenticated = False
                    login_failure = query.classify_exception(exc, "login")
                username = password = code = None
                if authenticated and args.save_session:
                    query.save_session(client.get_settings())
            else:
                saved = query.read_session()
                authenticated = bool(saved)
                if authenticated:
                    client.set_settings(saved)
                else:
                    login_failure = "No saved session exists; use --login or --save-session."
            if authenticated:
                # Do not automatically retry a state-changing request.
                client.set_retry_config(session_retry_total=0, session_retry_statuses=[])
                client.private.max_redirects = 0
                result = run_mutation_and_verify(client, args.setting, target)
            else:
                result = None
    except query.SessionStorageError:
        print("Could not safely read or save the session; no mutation was sent.")
        return 2
    except query.TerminalError:
        print("A local interactive terminal with hidden input is required; no mutation was sent.")
        return 2
    except Exception:
        print("Client setup failed; no sensitive details shown. Do not assume the setting changed.")
        return 2
    if result is None:
        print((login_failure or "Authentication failed.") + " No mutation was sent.")
        return 2
    mutation, verification = result
    mutation_msg, mutation_value = mutation
    print("Mutation: " + mutation_msg + (f" ({str(mutation_value).lower()})" if mutation_value is not None else ""))
    verification_msg, verification_value = verification
    if verification_msg == "accepted":
        print(f"Read-back: {args.setting} = {str(verification_value).lower()}")
        if verification_value == target:
            print("Read-back matches the requested value; visibility enforcement was not independently tested.")
        else:
            print("Read-back does not match the requested value.")
    else:
        print("Read-back: " + verification_msg + "; current setting is unverified.")
    return 0 if mutation[0] == "mutation returned a Boolean" and mutation_value == target and verification_msg == "accepted" and verification_value == target else 1


if __name__ == "__main__":
    sys.exit(main())
