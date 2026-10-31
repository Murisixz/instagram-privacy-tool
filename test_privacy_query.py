import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
import types
from unittest import mock
import warnings

spec = importlib.util.spec_from_file_location("privacy_query", Path(__file__).with_name("privacy_query.py"))
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)

class QueryTests(unittest.TestCase):
    def test_prompt_opens_terminal_for_writing_only(self):
        with mock.patch("builtins.open", mock.mock_open()) as opened, mock.patch.object(q.getpass, "getpass", return_value="sample") as prompt:
            self.assertEqual(q.prompt_private("Hidden: "), "sample")
            opened.assert_called_once_with("/dev/tty", "w", encoding="utf-8", buffering=1)
            prompt.assert_called_once()

    def test_prompt_refuses_input_when_echo_cannot_be_disabled(self):
        def unsafe_fallback(*args, **kwargs):
            warnings.warn("input may echo", q.getpass.GetPassWarning)
        with mock.patch("builtins.open", mock.mock_open()), mock.patch.object(q.getpass, "getpass", side_effect=unsafe_fallback):
            with self.assertRaises(q.TerminalError):
                q.prompt_private("Hidden: ")

    def test_exact_read_only_query_for_both_settings(self):
        class Fake:
            def __init__(self): self.calls = []
            def private_graphql_query_request(self, **kwargs):
                self.calls.append(kwargs)
                return {"data": {q.ROOT_FIELD: {"value": len(self.calls) == 1}}}
        client = Fake()
        result = q.run_queries(client)
        self.assertEqual([x[2] for x in result], [True, False])
        self.assertEqual([x["variables"] for x in client.calls], [{"setting_id": x} for x in q.SETTINGS])
        self.assertTrue(all(x["friendly_name"] == "IGSettingsBooleanQuery" and x["client_doc_id"] == q.QUERY_ID and x["root_field_name"] == q.ROOT_FIELD for x in client.calls))

    def test_unexpected_or_error_payload_is_not_a_boolean(self):
        for response in ({"data": {q.ROOT_FIELD: {"value": "false"}}}, {"data": {}}, {"errors": [{"message": "secret"}]}, None):
            self.assertNotEqual(q.parse_result(response)[0], "accepted")
        self.assertEqual(q.parse_result({"data": {q.ROOT_FIELD + "(setting_id:$setting_id)": {"value": False}}}), ("accepted", False))

    def test_only_exact_ipa_field_names_are_accepted(self):
        for key in q.QUERY_FIELD_KEYS:
            for value in (True, False):
                with self.subTest(key=key, value=value):
                    response = {"data": {key: {"value": value, "error_name_value": None, "fallback_message": None}}}
                    self.assertEqual(q.parse_result(response), ("accepted", value))
        unrelated = ["not_the_settings_field", q.ROOT_FIELD + "_other", q.ROOT_FIELD + "(wrong:$arg)"]
        for key in unrelated:
            self.assertEqual(q.parse_result({"data": {key: {"value": False, "error_name_value": None, "fallback_message": None}}})[0], "unknown response format")

    def test_ambiguous_or_failed_field_is_not_reported_as_setting(self):
        ambiguous = {"data": {q.QUERY_FIELD_KEYS[0]: {"value": False}, q.QUERY_FIELD_KEYS[2]: {"value": True}}}
        self.assertEqual(q.parse_result(ambiguous)[0], "unknown response format")
        for error_key in ("error_name_value", "errorNameValue", "fallback_message", "fallbackMessage"):
            response = {"data": {q.ROOT_FIELD: {"value": False, error_key: "private error"}}}
            self.assertEqual(q.parse_result(response)[0], "setting-level error reported; details redacted")

    def test_case_and_underscore_variants_preserve_full_field_identity(self):
        for key in ("xdt_api_v1_settings_get_bool", "xdtApiV1SettingsGetBool", "XDT_API__V1__SETTINGS__GET_BOOL"):
            response = {"data": {key: {"value": False}}}
            self.assertEqual(q.parse_result(response), ("accepted", False))
        for key in ("get_bool", "settings_get_bool", "xdt_api_v1_settings_get_boolean", "xdt_api_v1_settings_get_bool_other"):
            self.assertEqual(q.parse_result({"data": {key: {"value": False}}})[0], "unknown response format")
        self.assertEqual(q.parse_result({"data": {q.ROOT_FIELD: {"value": False}, "xdtApiV1SettingsGetBool": {"value": False}}})[0], "unknown response format")

    def test_serialized_argument_must_match_requested_setting_exactly(self):
        first, second = q.SETTINGS
        key = q.ROOT_FIELD + '(setting_id:"' + first + '")'
        response = {"data": {key: {"value": True}}}
        self.assertEqual(q.parse_result(response, expected_setting=first), ("accepted", True))
        self.assertEqual(q.parse_result(response, expected_setting=second)[0], "unknown response format")
        self.assertEqual(q.parse_result(response)[0], "unknown response format")

    def test_observed_prefixed_query_invocation_is_bound_to_each_request(self):
        key = "opaque_prefix$" + q.ROOT_FIELD + "(setting_id:$setting_id)"
        for setting, value in zip(q.SETTINGS, (False, True)):
            response = {"data": {key: {"value": value, "error_name_value": None, "fallback_message": None}}}
            self.assertEqual(q.parse_result(response, expected_setting=setting), ("accepted", value))
        self.assertEqual(q.parse_result({"data": {key: {"value": False}}})[0], "unknown response format")
        self.assertEqual(q.parse_result({"data": {key: {"value": False}}}, expected_setting="unrelated")[0], "unknown response format")

    def test_prefixed_invocation_rejects_unrelated_and_ambiguous_fields(self):
        key = "opaque_prefix$" + q.ROOT_FIELD + "(setting_id:$setting_id)"
        for other in ("opaque_prefix$" + q.ROOT_FIELD + "(setting_id:$different)",
                      "opaque_prefix$" + q.ROOT_FIELD + "_other(setting_id:$setting_id)",
                      key + "_other", "$" + q.ROOT_FIELD + "(setting_id:$setting_id)"):
            with self.subTest(key=other):
                self.assertEqual(q.parse_result({"data": {other: {"value": False}}}, expected_setting=q.SETTINGS[0])[0], "unknown response format")
        ambiguous = {"data": {key: {"value": False}, q.ROOT_FIELD: {"value": True}}}
        self.assertEqual(q.parse_result(ambiguous, expected_setting=q.SETTINGS[0])[0], "unknown response format")
        error = {"data": {key: {"value": False, "error_name_value": "unsupported"}}}
        self.assertEqual(q.parse_result(error, expected_setting=q.SETTINGS[0])[0], "setting-level error reported; details redacted")

    def test_candidate_comparisons_and_field_name_are_redacted(self):
        secret = "privateperson123"
        key = q.ROOT_FIELD + "_" + secret
        response = {"data": {key: {"value": False, "error_name_value": None, "fallback_message": None}}}
        result = q.safe_diagnostic(response, expected_setting=q.SETTINGS[0])
        candidate = result["candidate_fields"][0]
        self.assertTrue(candidate["contains_ipa_root_name"])
        self.assertFalse(candidate["ipa_graphql_field"])
        self.assertFalse(candidate["case_underscore_variant"])
        self.assertIn("<redacted>", candidate["sanitized_name"])
        self.assertNotIn(secret, json.dumps(result))
        self.assertEqual(q.parse_result(response, expected_setting=q.SETTINGS[0])[0], "unknown response format")

    def test_field_key_template_keeps_only_fixed_markers_and_syntax(self):
        key = "private_person:" + q.ROOT_FIELD + "(setting_id:$setting_id)"
        template = q.field_key_template(key, q.SETTINGS[0])
        self.assertEqual(template, "<REDACTED>:<IPA_FIELD>(<SETTING_ARGUMENT>:<SETTING_VARIABLE>)")
        self.assertNotIn("private_person", template)
        self.assertEqual(q.parse_result({"data": {key: {"value": False}}}, expected_setting=q.SETTINGS[0])[0], "unknown response format")

    def test_field_key_template_redacts_arbitrary_values_and_wrong_setting(self):
        key = "abc_secret:" + q.ROOT_FIELD + '(setting_id:"' + q.SETTINGS[1] + '",extra:"email@example.com")'
        template = q.field_key_template(key, q.SETTINGS[0])
        for forbidden in ("abc_secret", "email", "example", ".com", q.SETTINGS[1]):
            self.assertNotIn(forbidden, template)
        self.assertIn("<OTHER_SETTING>", template)
        self.assertEqual(q.parse_result({"data": {key: {"value": False}}}, expected_setting=q.SETTINGS[0])[0], "unknown response format")

    def test_rejection_is_not_asserted_to_be_unsupported(self):
        exc = type("ClientBadRequestError", (Exception,), {})("secret")
        self.assertIn("unconfirmed", q.classify_exception(exc, "query"))
        self.assertNotIn("secret", q.classify_exception(exc, "query"))
        self.assertIn("Authentication", q.classify_exception(type("ClientUnauthorizedError", (Exception,), {})(), "query"))
        self.assertIn("verification", q.classify_exception(type("TwoFactorRequired", (Exception,), {})(), "login"))

    def test_query_stops_after_an_error(self):
        class Fake:
            calls = 0
            def private_graphql_query_request(self, **kwargs):
                self.calls += 1
                raise type("ClientBadRequestError", (Exception,), {})("private")
        client = Fake()
        result = q.run_queries(client)
        self.assertEqual(client.calls, 1)
        self.assertNotIn("private", result[0][1])

    def test_unrecognized_success_is_diagnosed_and_second_query_runs(self):
        class Fake:
            calls = 0
            def private_graphql_query_request(self, **kwargs):
                self.calls += 1
                return {"data": {"unexpected_private_key": {"value": False}}}
        client = Fake()
        diagnostics = []
        result = q.run_queries(client, diagnostics)
        self.assertEqual(client.calls, 2)
        self.assertEqual([row[1] for row in result], ["unknown response format"] * 2)
        self.assertEqual(len(diagnostics), 2)
        self.assertNotIn("unexpected_private_key", str(diagnostics))

    def test_stream_response_single_row(self):
        self.assertEqual(q.parse_result({"stream_rows": [{"data": {q.ROOT_FIELD: {"value": True}}}]}), ("accepted", True))
        self.assertEqual(q.parse_result({"stream_rows": [{}, {}]})[0], "unknown response format")

    def test_safe_diagnostic_never_emits_untrusted_values(self):
        response = {"data": {q.ROOT_FIELD + "(secret-token)": {"value": False, "email": "secret@example.com", "status": "secret-token"}},
                    "errors": [{"message": "private-person@example.com", "extensions": {"code": "NOT_SUPPORTED", "secret": "secret-token"}}],
                    "secret-token": "secret-token"}
        diagnostic = q.safe_diagnostic(response)
        serialized = json.dumps(diagnostic)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("example.com", serialized)
        self.assertIn('"value": false', serialized)
        self.assertIn('"code": "NOT_SUPPORTED"', serialized)
        self.assertIn("other message redacted", serialized)

    def test_error_message_is_reduced_to_known_category(self):
        diagnostic = q.safe_diagnostic({"errors": [{"code": 123, "message": "not supported; secret personal details"}]})
        self.assertEqual(diagnostic["graphql_errors"], [{"code": 123}, {"message_category": "unsupported reported"}])
        self.assertNotIn("secret", json.dumps(diagnostic))

    def test_reuse_session_skips_login_and_terminal_prompts(self):
        class FakeClient:
            def set_settings(self, settings): self.settings = settings
            def login(self, *args, **kwargs): raise AssertionError("login must not run")
            def private_graphql_query_request(self, **kwargs):
                return {"data": {q.ROOT_FIELD: {"value": False}}}
        module = types.SimpleNamespace(Client=FakeClient)
        with mock.patch.dict("sys.modules", {"instagrapi": module}), mock.patch.object(q, "read_session", return_value={"state": "sample"}), mock.patch.object(q, "prompt_private", side_effect=AssertionError("must not prompt")), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(q.main(["--reuse-session"]), 0)
            self.assertIn("Saved session loaded", output.getvalue())
        q.logging.disable(q.logging.NOTSET)

    def test_session_is_private_and_password_not_written(self):
        with tempfile.TemporaryDirectory() as directory:
            old_dir, old_file = q.SESSION_DIR, q.SESSION_FILE
            try:
                q.SESSION_DIR = Path(directory) / "session"
                q.SESSION_FILE = q.SESSION_DIR / "session.json"
                q.save_session({"password": "secret", "nested": {"verification_code": "secret"}, "cookies": {"example": "private"}})
                self.assertEqual(stat.S_IMODE(q.SESSION_DIR.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(q.SESSION_FILE.stat().st_mode), 0o600)
                self.assertNotIn("secret", q.SESSION_FILE.read_text())
                self.assertEqual(q.read_session()["cookies"], {"example": "private"})
            finally:
                q.SESSION_DIR, q.SESSION_FILE = old_dir, old_file

    def test_session_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            old_dir, old_file = q.SESSION_DIR, q.SESSION_FILE
            try:
                q.SESSION_DIR = Path(directory) / "session"
                q.SESSION_DIR.mkdir()
                q.SESSION_FILE = q.SESSION_DIR / "session.json"
                q.SESSION_FILE.symlink_to(Path(directory) / "other")
                with self.assertRaises(q.SessionStorageError): q.read_session()
            finally:
                q.SESSION_DIR, q.SESSION_FILE = old_dir, old_file

if __name__ == "__main__": unittest.main()
