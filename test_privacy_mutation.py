import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
spec = importlib.util.spec_from_file_location("privacy_mutation", Path(__file__).with_name("privacy_mutation.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class MutationTests(unittest.TestCase):
    def test_constructs_exact_ipa_mutation_with_boolean(self):
        request = m.build_mutation(m.query.SETTINGS[0], True)
        self.assertEqual(request, {
            "friendly_name": "IGSettingsBooleanMutation",
            "root_field_name": "xdt_api__v1__settings__set_bool",
            "client_doc_id": "2669261950526978627082629536",
            "variables": {"allow_error_codes": True, "callsite": "account_privacy", "setting_id": m.query.SETTINGS[0], "value": True},
        })
        self.assertIs(m.build_mutation(m.query.SETTINGS[1], False)["variables"]["value"], False)
        with self.assertRaises(ValueError): m.build_mutation("unrelated", True)
        with self.assertRaises(ValueError): m.build_mutation(m.query.SETTINGS[0], 1)

    def test_mutation_response_is_strict_and_detects_errors(self):
        setting = m.query.SETTINGS[0]
        for key in (m.MUTATION_ROOT, m.MUTATION_INVOCATION, "xdtApi_V1_Settings_SetBool", "opaque$" + m.MUTATION_INVOCATION):
            self.assertEqual(m.parse_mutation({"data": {key: {"value": True, "error_name_value": None}}}, setting), ("mutation returned a Boolean", True))
        self.assertIn("GraphQL error", m.parse_mutation({"errors": [{"message": "secret"}]}, setting)[0])
        self.assertIn("setting-level error", m.parse_mutation({"data": {m.MUTATION_ROOT: {"value": True, "error_name_value": "secret"}}}, setting)[0])
        self.assertIn("unrecognized", m.parse_mutation({"data": {"other": {"value": True}}}, setting)[0])
        self.assertIn("ambiguous", m.parse_mutation({"data": {m.MUTATION_ROOT: {"value": True}, "opaque$" + m.MUTATION_INVOCATION: {"value": True}}}, setting)[0])
        self.assertIn("unrecognized", m.parse_mutation({"data": {m.MUTATION_ROOT: {"value": "true"}}}, setting)[0])

    def test_one_mutation_then_one_readback_for_same_setting(self):
        class Fake:
            def __init__(self): self.calls = []
            def private_graphql_query_request(self, **kwargs):
                self.calls.append(kwargs)
                root = m.MUTATION_ROOT if len(self.calls) == 1 else m.query.ROOT_FIELD
                return {"data": {root: {"value": True}}}
        client = Fake()
        mutation, verification = m.run_mutation_and_verify(client, m.query.SETTINGS[0], True)
        self.assertEqual(mutation, ("mutation returned a Boolean", True))
        self.assertEqual(verification, ("accepted", True))
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[0], m.build_mutation(m.query.SETTINGS[0], True))
        self.assertEqual(client.calls[1]["friendly_name"], "IGSettingsBooleanQuery")
        self.assertEqual(client.calls[1]["variables"], {"setting_id": m.query.SETTINGS[0]})

    def test_failure_still_reads_back_and_never_exposes_exception(self):
        class Fake:
            def __init__(self): self.calls = 0
            def private_graphql_query_request(self, **kwargs):
                self.calls += 1
                if self.calls == 1: raise RuntimeError("secret token")
                return {"data": {m.query.ROOT_FIELD: {"value": False}}}
        client = Fake()
        result = m.run_mutation_and_verify(client, m.query.SETTINGS[0], True)
        self.assertEqual(client.calls, 2)
        self.assertIn("unknown", result[0][0])
        self.assertEqual(result[1], ("accepted", False))
        self.assertNotIn("secret", repr(result))

    def test_review_mode_never_loads_session_or_sends_request(self):
        output = io.StringIO()
        with mock.patch.object(m.query, "read_session", side_effect=AssertionError("must not load")), contextlib.redirect_stdout(output):
            self.assertEqual(m.main(["--setting", m.query.SETTINGS[0], "--value", "true"]), 0)
        self.assertIn("Review only", output.getvalue())
        self.assertIn(m.MUTATION_ID, output.getvalue())

    def test_execute_wiring_disables_retries_and_compares_readback(self):
        instances = []
        class FakeClient:
            def __init__(self): self.private = types.SimpleNamespace(max_redirects=30); self.calls=[]; instances.append(self)
            def set_settings(self, settings): pass
            def set_retry_config(self, **kwargs): self.retry=kwargs
            def private_graphql_query_request(self, **kwargs):
                self.calls.append(kwargs)
                field = m.MUTATION_ROOT if len(self.calls) == 1 else m.query.ROOT_FIELD
                return {"data": {field: {"value": True}}}
        module = types.SimpleNamespace(Client=FakeClient)
        output = io.StringIO()
        with mock.patch.dict("sys.modules", {"instagrapi": module}), mock.patch.object(m.query, "read_session", return_value={"state": "sample"}), contextlib.redirect_stdout(output):
            self.assertEqual(m.main(["--setting", m.query.SETTINGS[0], "--value", "true", "--execute"]), 0)
        m.logging.disable(m.logging.NOTSET)
        self.assertEqual(instances[0].retry, {"session_retry_total": 0, "session_retry_statuses": []})
        self.assertEqual(instances[0].private.max_redirects, 0)
        self.assertIn("Read-back matches", output.getvalue())
        self.assertEqual(len(instances[0].calls), 2)

    def test_private_login_executes_without_saving_or_reading_a_session(self):
        instances = []
        class FakeClient:
            def __init__(self): self.private = types.SimpleNamespace(max_redirects=30); self.calls=[]; instances.append(self)
            def login(self, username, password, verification_code): return True
            def set_retry_config(self, **kwargs): pass
            def private_graphql_query_request(self, **kwargs):
                self.calls.append(kwargs)
                field = m.MUTATION_ROOT if len(self.calls) == 1 else m.query.ROOT_FIELD
                return {"data": {field: {"value": True}}}
        module = types.SimpleNamespace(Client=FakeClient)
        output = io.StringIO()
        with mock.patch.dict("sys.modules", {"instagrapi": module}), mock.patch.object(m.query, "prompt_private", side_effect=["user", "password", ""]), mock.patch.object(m.query, "read_session", side_effect=AssertionError("must not read")), mock.patch.object(m.query, "save_session", side_effect=AssertionError("must not save")), contextlib.redirect_stdout(output):
            self.assertEqual(m.main(["--setting", m.query.SETTINGS[0], "--value", "true", "--login", "--execute"]), 0)
        m.logging.disable(m.logging.NOTSET)
        self.assertEqual(len(instances[0].calls), 2)
        self.assertNotIn("password", output.getvalue())

    def test_login_failure_stops_before_mutation(self):
        class FakeClient:
            def __init__(self): self.private = types.SimpleNamespace(max_redirects=30)
            def login(self, *args, **kwargs): raise RuntimeError("private error")
            def private_graphql_query_request(self, **kwargs): raise AssertionError("must not request")
        module = types.SimpleNamespace(Client=FakeClient)
        output = io.StringIO()
        with mock.patch.dict("sys.modules", {"instagrapi": module}), mock.patch.object(m.query, "prompt_private", side_effect=["user", "password", ""]), contextlib.redirect_stdout(output):
            self.assertEqual(m.main(["--setting", m.query.SETTINGS[0], "--value", "true", "--login", "--execute"]), 2)
        m.logging.disable(m.logging.NOTSET)
        self.assertIn("No mutation was sent", output.getvalue())
        self.assertNotIn("private error", output.getvalue())

if __name__ == "__main__": unittest.main()
