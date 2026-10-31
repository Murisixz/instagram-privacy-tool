#!/usr/bin/env python3
"""Read the two Beegram privacy settings using an owner-authenticated client."""
import argparse
import contextlib
import csv
import getpass
import json
import logging
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import warnings

QUERY_ID = "3203310381321258553037549573"
QUERY_NAME = "IGSettingsBooleanQuery"
ROOT_FIELD = "xdt_api__v1__settings__get_bool"
QUERY_FIELD_KEYS = (
    ROOT_FIELD,
    ROOT_FIELD + "(setting_id:$setting_id)",
    "xdtApi_V1_Settings_GetBool",
)
SETTINGS = ("hide_followers_following_list", "hide_self_from_others_lists")
SESSION_DIR = Path(__file__).resolve().parent / ".session"
SESSION_FILE = SESSION_DIR / "session.json"
IS_WINDOWS = os.name == "nt"

class SessionStorageError(Exception):
    pass


class TerminalError(Exception):
    pass


def prompt_private(prompt):
    try:
        # getpass opens the controlling terminal for input itself.  Its stream
        # is only used for the prompt; read/write buffered mode needs seeking.
        tty = None
        if not IS_WINDOWS:
            try:
                tty = open("/dev/tty", "w", encoding="utf-8", buffering=1)
            except OSError:
                tty = None
        if tty is not None:
            output = tty
        elif sys.stdin.isatty() and sys.__stderr__ is not None and sys.__stderr__.isatty():
            output = sys.__stderr__
        else:
            raise TerminalError()
        try:
            with warnings.catch_warnings():
                # Refuse getpass's fallback if it cannot disable echo.
                warnings.simplefilter("error", getpass.GetPassWarning)
                return getpass.getpass(prompt, stream=output)
        finally:
            if tty is not None:
                tty.close()
    except (OSError, EOFError, getpass.GetPassWarning):
        raise TerminalError() from None


def is_link_or_reparse_point(info):
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def windows_tool(name):
    # Use absolute System32 paths: Windows searches the current directory for bare names.
    return os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32", name)


def windows_user_sid():
    try:
        result = subprocess.run(
            [windows_tool("whoami.exe"), "/user", "/fo", "csv", "/nh"],
            capture_output=True, text=True, errors="replace", check=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        raise SessionStorageError() from None
    rows = list(csv.reader(result.stdout.strip().splitlines()))
    sid = rows[0][-1].strip() if len(rows) == 1 and rows[0] else ""
    if not re.fullmatch(r"S-1-\d+(-\d+)+", sid):
        raise SessionStorageError()
    return sid


def windows_restrict(path, directory):
    """Replace the ACL with a single full-control entry for the current user."""
    sid = windows_user_sid()
    grant = f"*{sid}:(OI)(CI)F" if directory else f"*{sid}:F"
    icacls = windows_tool("icacls.exe")
    for command in ([icacls, str(path), "/reset", "/q"],
                    [icacls, str(path), "/inheritance:r", "/grant:r", grant, "/q"]):
        try:
            subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            raise SessionStorageError() from None


def secure_directory():
    try:
        SESSION_DIR.mkdir(mode=0o700, exist_ok=True)
        info = SESSION_DIR.lstat()
        if not stat.S_ISDIR(info.st_mode) or is_link_or_reparse_point(info):
            raise SessionStorageError()
        if IS_WINDOWS:
            windows_restrict(SESSION_DIR, directory=True)
        else:
            if info.st_uid != os.geteuid():
                raise SessionStorageError()
            os.chmod(SESSION_DIR, 0o700)
    except OSError:
        raise SessionStorageError() from None


def open_session_file():
    if not IS_WINDOWS:
        return os.open(SESSION_FILE, os.O_RDONLY | os.O_NOFOLLOW)
    # Windows has no O_NOFOLLOW: reject links and reparse points, then confirm
    # the opened handle is the same file that was checked.
    before = os.lstat(SESSION_FILE)
    if not stat.S_ISREG(before.st_mode) or is_link_or_reparse_point(before):
        raise SessionStorageError()
    fd = os.open(SESSION_FILE, os.O_RDONLY)
    try:
        if not os.path.samestat(before, os.fstat(fd)):
            raise SessionStorageError()
    except BaseException:
        os.close(fd)
        raise
    return fd


def restrict_session_file(fd, path, info):
    if IS_WINDOWS:
        windows_restrict(path, directory=False)
    else:
        if info.st_uid != os.geteuid():
            raise SessionStorageError()
        os.fchmod(fd, 0o600)


def read_session():
    secure_directory()
    try:
        fd = open_session_file()
    except FileNotFoundError:
        return None
    except OSError:
        raise SessionStorageError() from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise SessionStorageError()
        restrict_session_file(fd, SESSION_FILE, info)
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            obj = json.load(stream)
        if not isinstance(obj, dict):
            raise SessionStorageError()
        return obj
    except (OSError, ValueError):
        raise SessionStorageError() from None
    finally:
        if fd != -1:
            os.close(fd)


def strip_passwords(value):
    if isinstance(value, dict):
        return {k: strip_passwords(v) for k, v in value.items() if str(k).lower() not in {"password", "passwd", "verification_code"}}
    if isinstance(value, list):
        return [strip_passwords(v) for v in value]
    return value


def save_session(settings):
    secure_directory()
    name = None
    try:
        fd, name = tempfile.mkstemp(prefix=".session-", dir=SESSION_DIR)
        try:
            restrict_session_file(fd, name, os.fstat(fd))
        except BaseException:
            os.close(fd)
            raise
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(strip_passwords(settings), stream, separators=(",", ":"))
        os.replace(name, SESSION_FILE)
    except (OSError, TypeError, ValueError, SessionStorageError):
        if name:
            try:
                os.unlink(name)
            except OSError:
                pass
        raise SessionStorageError() from None


def classify_exception(exc, stage):
    # Do not stringify exceptions: they may contain response bodies or session data.
    names = {c.__name__ for c in type(exc).__mro__}
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if names & {"TwoFactorRequired", "ChallengeRequired", "ChallengeError", "CheckpointRequired"}:
        return "Authentication needs verification in the app or a supported code; no response details shown."
    if names & {"BadPassword", "LoginRequired", "ClientLoginRequired", "ClientUnauthorizedError", "ClientForbiddenError"} or status in (401, 403):
        return "Authentication or access denied (login, verification, or account eligibility)."
    if names & {"RateLimitError", "ClientThrottledError", "PleaseWaitFewMinutes"} or status == 429:
        return "Rate limited; stop and try later."
    if stage == "query" and (status in (400, 404) or names & {"ClientBadRequestError", "ClientNotFoundError"}):
        return "Request rejected or endpoint unavailable; the operation may be unsupported, but the cause is unconfirmed."
    if names & {"ClientConnectionError", "ConnectionError", "Timeout", "TimeoutError"}:
        return "Connection failed; no account result is available."
    return "Authentication failed; no details shown." if stage == "login" else "Query failed; unsupported operation, network, or response error could not be distinguished."


def field_match(key, expected_setting=None):
    """Match only names that preserve the IPA field identity."""
    if not isinstance(key, str):
        return None
    if key in QUERY_FIELD_KEYS:
        return "ipa_exact"
    if re.fullmatch(r"[A-Za-z0-9_]+", key) and key.replace("_", "").lower() == ROOT_FIELD.replace("_", "").lower():
        return "same_name_case_underscore_variant"
    if expected_setting in SETTINGS:
        # The observed response uses an opaque identifier, a dollar separator,
        # and the exact IPA field invocation.  The variable is bound to
        # expected_setting by run_queries; do not infer a value from the key.
        prefixed_invocation = (
            r"[A-Za-z0-9_]{1,128}\$"
            + re.escape(ROOT_FIELD)
            + r"\(setting_id:\$setting_id\)"
        )
        if re.fullmatch(prefixed_invocation, key):
            return "prefixed_ipa_invocation_bound_by_request"
        # Accept only a fully specified known setting, never arbitrary arguments.
        serialized = (
            ROOT_FIELD + '(setting_id:"' + expected_setting + '")',
            ROOT_FIELD + '(setting_id: "' + expected_setting + '")',
        )
        if key in serialized:
            return "ipa_field_with_matching_setting_argument"
    return None


def parse_result(response, expected_setting=None):
    if isinstance(response, dict) and isinstance(response.get("stream_rows"), list):
        rows = response["stream_rows"]
        if len(rows) == 1:
            response = rows[0]
    if not isinstance(response, dict):
        return "unknown response format", None
    if response.get("errors") or response.get("status") == "fail":
        return "GraphQL rejected or reported an error; unsupported operation is possible but unconfirmed", None
    data = response.get("data")
    if not isinstance(data, dict):
        return "unknown response format", None
    # Names are limited to the exact field, invocation, and typed selector
    # found in Beegram's parser and the packaged query metadata.
    matches = [value for key, value in data.items() if field_match(key, expected_setting)]
    if len(matches) != 1:
        return "unknown response format", None
    root = matches[0]
    if not isinstance(root, dict):
        return "unknown response format", None
    if any(root.get(key) not in (None, "") for key in ("error_name_value", "errorNameValue", "fallback_message", "fallbackMessage")):
        return "setting-level error reported; details redacted", None
    value = root.get("value")
    if type(value) is bool:
        return "accepted", value
    return "unknown response format", None


SAFE_STRUCTURE_KEYS = frozenset({"data", "errors", "extensions", "stream_rows", "value", "result", "payload", "response", "settings", "setting", "enabled", "is_enabled", "isEnabled", "bool_value", "boolValue", "has_value", "success", "status", "code", "error_code", "error_name_value", "errorNameValue", "message", "fallback_message", "fallbackMessage", *QUERY_FIELD_KEYS})
SAFE_BOOLEAN_KEYS = frozenset({"value", "enabled", "is_enabled", "isEnabled", "bool_value", "boolValue", "has_value", "success"})
SAFE_ERROR_CODES = frozenset({"UNAUTHORIZED", "FORBIDDEN", "NOT_FOUND", "NOT_SUPPORTED", "UNSUPPORTED", "INVALID_REQUEST", "RATE_LIMITED", "LOGIN_REQUIRED"})
SAFE_FIELD_WORDS = frozenset({"xdt", "api", "v1", "settings", "setting", "get", "bool", "boolean", "query", "result", "response", "value", "data"})


def field_key_template(key, expected_setting=None):
    """Describe syntax using fixed markers only, never arbitrary key text."""
    if not isinstance(key, str) or len(key) > 240:
        return "<redacted>"
    token_pattern = re.compile(
        re.escape(ROOT_FIELD)
        + r"|\$setting_id(?![A-Za-z0-9_])|setting_id(?![A-Za-z0-9_])"
        + r"|[A-Za-z0-9_]+|[():,$\"\[\]{}]|\s+|."
    )
    parts = []
    for match in token_pattern.finditer(key):
        token = match.group()
        if token == ROOT_FIELD:
            parts.append("<IPA_FIELD>")
        elif token == "$setting_id":
            parts.append("<SETTING_VARIABLE>")
        elif token == "setting_id":
            parts.append("<SETTING_ARGUMENT>")
        elif expected_setting in SETTINGS and token == expected_setting:
            parts.append("<REQUESTED_SETTING>")
        elif token in SETTINGS:
            parts.append("<OTHER_SETTING>")
        elif token in "():,$\"[]{}" and len(token) == 1:
            parts.append(token)
        elif token.isspace():
            parts.append(" ")
        else:
            parts.append("<REDACTED>")
    return "".join(parts)


def sanitized_field_name(key):
    """Expose fixed schema words only; all other tokens are placeholders."""
    if not isinstance(key, str) or len(key) > 240:
        return "<redacted>"
    split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    words = re.findall(r"[A-Za-z]+[0-9]*|[0-9]+", split)
    return "_".join(word.lower() if word.lower() in SAFE_FIELD_WORDS else "<redacted>" for word in words[:20]) or "<redacted>"


def safe_diagnostic(response, expected_setting=None):
    """Return only bounded, allow-listed structure and sanitized error metadata."""
    error_details = []

    def walk(obj, depth=0, in_data=False, in_errors=False):
        if depth > 6:
            return "<depth limit>"
        if isinstance(obj, dict):
            result = {}
            unknown = 0
            for key, value in list(obj.items())[:80]:
                if isinstance(key, str) and key == QUERY_FIELD_KEYS[1]:
                    label = ROOT_FIELD + "(<arguments redacted>)"
                elif isinstance(key, str) and key in SAFE_STRUCTURE_KEYS:
                    label = key
                else:
                    unknown += 1
                    if unknown > 8:
                        continue
                    label = f"<other key {unknown}>"
                child_errors = in_errors or key == "errors"
                child_data = in_data or key == "data"
                if child_errors and key in {"code", "error_code"}:
                    if type(value) is int and 0 <= value <= 9999999:
                        error_details.append({"code": value})
                    elif isinstance(value, str) and value in SAFE_ERROR_CODES:
                        error_details.append({"code": value})
                if child_errors and key == "message" and isinstance(value, str):
                    text = value.lower()
                    if "not supported" in text or "unsupported" in text:
                        error_details.append({"message_category": "unsupported reported"})
                    elif "unauthorized" in text or "permission" in text or "login required" in text:
                        error_details.append({"message_category": "authentication or permission reported"})
                    elif "rate limit" in text or "too many" in text:
                        error_details.append({"message_category": "rate limit reported"})
                    else:
                        error_details.append({"message_category": "other message redacted"})
                if child_data and not child_errors and key in SAFE_BOOLEAN_KEYS and type(value) is bool:
                    result[label] = value
                else:
                    result[label] = walk(value, depth + 1, child_data, child_errors)
            if unknown:
                result["<other keys>"] = "names redacted"
            if len(obj) > 80:
                result["<more keys>"] = "omitted"
            return result
        if isinstance(obj, list):
            return [walk(item, depth + 1, in_data, in_errors) for item in obj[:3]] + (["<more items omitted>"] if len(obj) > 3 else [])
        if obj is None:
            return "null"
        if type(obj) is bool:
            return "boolean"
        if isinstance(obj, (int, float)):
            return "number"
        if isinstance(obj, str):
            return "string"
        return "other type"

    structure = walk(response)
    body = response
    if isinstance(body, dict) and isinstance(body.get("stream_rows"), list) and len(body["stream_rows"]) == 1:
        body = body["stream_rows"][0]
    data = body.get("data") if isinstance(body, dict) else None
    candidates = []
    if isinstance(data, dict):
        for key, obj in list(data.items())[:80]:
            if not isinstance(key, str) or not isinstance(obj, dict) or type(obj.get("value")) is not bool:
                continue
            candidate = {
                "ipa_graphql_field": key == QUERY_FIELD_KEYS[0],
                "ipa_query_invocation": key == QUERY_FIELD_KEYS[1],
                "ipa_typed_selector": key == QUERY_FIELD_KEYS[2],
                "case_underscore_variant": field_match(key, expected_setting) == "same_name_case_underscore_variant",
                "matching_serialized_argument": field_match(key, expected_setting) == "ipa_field_with_matching_setting_argument",
                "matching_prefixed_invocation": field_match(key, expected_setting) == "prefixed_ipa_invocation_bound_by_request",
                "contains_ipa_root_name": ROOT_FIELD in key,
                "sanitized_name": sanitized_field_name(key),
                "syntax_template": field_key_template(key, expected_setting),
            }
            candidates.append(candidate)
            if len(candidates) == 8:
                break
    return {"structure": structure, "graphql_errors": error_details[:8], "candidate_fields": candidates}


def run_queries(client, diagnostics=None):
    results = []
    for setting in SETTINGS:
        try:
            response = client.private_graphql_query_request(
                friendly_name=QUERY_NAME,
                root_field_name=ROOT_FIELD,
                variables={"setting_id": setting},
                client_doc_id=QUERY_ID,
            )
            category, value = parse_result(response, expected_setting=setting)
            if diagnostics is not None and category != "accepted":
                diagnostics.append((setting, safe_diagnostic(response, expected_setting=setting)))
        except Exception as exc:
            category, value = classify_exception(exc, "query"), None
            if diagnostics is not None:
                try:
                    response_obj = getattr(exc, "response", None)
                    if response_obj is not None:
                        diagnostics.append((setting, safe_diagnostic(response_obj.json(), expected_setting=setting)))
                except Exception:
                    pass
        results.append((setting, category, value))
        if category not in {"accepted", "unknown response format"}:
            # An unfamiliar response is safe to compare; stop on actual failures.
            break
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read two privacy settings on your own account. No mutation is implemented.")
    session_options = parser.add_mutually_exclusive_group()
    session_options.add_argument("--save-session", action="store_true", help="Save local session state with owner-only permissions.")
    session_options.add_argument("--reuse-session", action="store_true", help="Use an existing local session without prompting for credentials.")
    args = parser.parse_args(argv)
    try:
        from instagrapi import Client
    except ImportError:
        print("Missing instagrapi. Install the project's requirements in a virtual environment first.")
        return 2
    if not callable(getattr(Client, "private_graphql_query_request", None)):
        print("Installed instagrapi lacks the required mobile GraphQL method; update the dependency.")
        return 2
    logging.disable(logging.CRITICAL)
    try:
        username = password = code = None
        if not args.reuse_session:
            username = prompt_private("Instagram username (hidden): ")
            password = prompt_private("Instagram password (hidden): ")
            code = prompt_private("Verification code if available, otherwise press Enter (hidden): ")
            if not username or not password:
                print("Username and password are required.")
                return 2
        print("Reading settings; this may take a moment.", flush=True)
        diagnostics = []
        with open(os.devnull, "w", encoding="utf-8") as quiet, contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            client = Client()
            client.challenge_code_handler = lambda _username, _choice: prompt_private("Verification code (hidden): ")
            if args.save_session or args.reuse_session:
                saved = read_session()
                if saved:
                    client.set_settings(saved)
            if args.reuse_session:
                authenticated = bool(saved)
                login_failure = "No saved local session exists; run once with --save-session."
            else:
                try:
                    authenticated = client.login(username, password, verification_code=code)
                except Exception as exc:
                    login_failure = classify_exception(exc, "login")
                    authenticated = False
                else:
                    login_failure = "Authentication failed; no details shown."
            username = password = code = None
            if authenticated and args.save_session:
                save_session(client.get_settings())
            results = run_queries(client, diagnostics) if authenticated else None
    except SessionStorageError:
        print("Could not safely read or save the local session; no query was sent.")
        return 2
    except TerminalError:
        print("A local interactive terminal with hidden input is required.")
        return 2
    except Exception:
        print("Client setup failed; no sensitive error details shown.")
        return 2
    if not authenticated:
        print(login_failure)
        return 1
    print("Saved session loaded; authentication is checked by the query." if args.reuse_session else "Authentication succeeded.")
    for setting, category, value in results:
        if category == "accepted":
            print(f"{setting}: {str(value).lower()} (server returned a boolean)")
        else:
            print(f"{setting}: {category}")
    for setting, diagnostic in diagnostics:
        print(f"{setting} sanitized diagnostic: {json.dumps(diagnostic, sort_keys=True)}")
    if len(results) != len(SETTINGS):
        print("Remaining query not sent after the first request failed.")
    return 0 if len(results) == len(SETTINGS) and all(r[1] == "accepted" for r in results) else 1

if __name__ == "__main__":
    sys.exit(main())
