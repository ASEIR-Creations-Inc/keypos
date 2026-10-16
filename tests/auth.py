"""Signs the API suites in as the test admin that `testenv.sh up` sets on the test copy."""
import json
import urllib.request

TEST_USER = "admin"
TEST_PASSWORD = "test-admin-pass"
_token = None


def token(api="http://127.0.0.1:8095/api"):
    global _token
    if _token is None:
        body = json.dumps({"username": TEST_USER, "password": TEST_PASSWORD}).encode()
        req = urllib.request.Request(api + "/auth/login", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            _token = json.load(r)["access_token"]
    return _token


def auth_headers(content_type="application/json"):
    return {"Content-Type": content_type, "Authorization": "Bearer " + token()}
