"""Automated server verification tests for Azure production readiness.

Runs against the FastAPI app with a SQLite test database to verify:
- Health endpoints
- Authentication (register, login, JWT, weak-secret detection)
- Resume upload and binary storage in DB
- Job queue lifecycle (enqueue → claim → report)
- Agent pairing and heartbeat
- CORS and static file mounting

Usage:
    python -m pytest tests/test_server_azure_ready.py -v
    # or:
    python -m unittest tests.test_server_azure_ready -v
"""
import os
import sys
import tempfile
import unittest

# Force a test SQLite database before any server imports.
_test_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_test_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_test_db.name}"
os.environ["JWT_SECRET"] = "test-secret-for-unit-tests-only-not-weak"

# Now import server modules — they will pick up the test DATABASE_URL.
from server.config import Settings, _WEAK_SECRETS  # noqa: E402
from server.db import init_db, check_db  # noqa: E402

# Explicitly create tables before tests (the lifespan runs in TestClient but
# some test ordering and parallel concerns make this safer).
init_db()

from fastapi.testclient import TestClient  # noqa: E402
from server.main import app  # noqa: E402

client = TestClient(app)


class TestHealth(unittest.TestCase):
    """Phase 8: Health endpoints."""

    def test_health(self):
        r = client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True})

    def test_health_db(self):
        r = client.get("/api/health/db")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["database"], "connected")

    def test_check_db_function(self):
        self.assertTrue(check_db())

    def test_platforms(self):
        r = client.get("/api/platforms")
        self.assertEqual(r.status_code, 200)
        names = [p["name"] for p in r.json()]
        self.assertIn("internshala", names)
        self.assertIn("unstop", names)


class TestFrontend(unittest.TestCase):
    """Phase 9–10: Frontend and static files."""

    def test_dashboard_loads(self):
        r = client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"InternHelper", r.content)

    def test_static_css(self):
        r = client.get("/static/style.css")
        self.assertEqual(r.status_code, 200)

    def test_static_auth_js(self):
        r = client.get("/static/auth.js")
        self.assertEqual(r.status_code, 200)

    def test_no_cache_header(self):
        r = client.get("/")
        self.assertEqual(r.headers.get("cache-control"), "no-store")


class TestAuth(unittest.TestCase):
    """Phase 12: Authentication flow."""

    def test_register_and_login(self):
        # Register
        r = client.post("/api/auth/register", json={
            "email": "test@example.com", "password": "StrongPass123!"
        })
        self.assertEqual(r.status_code, 200)
        token = r.json()["access_token"]
        self.assertTrue(len(token) > 20)

        # Duplicate register should fail
        r2 = client.post("/api/auth/register", json={
            "email": "test@example.com", "password": "Other456!"
        })
        self.assertEqual(r2.status_code, 409)

        # Login
        r3 = client.post("/api/auth/login", data={
            "username": "test@example.com", "password": "StrongPass123!"
        })
        self.assertEqual(r3.status_code, 200)
        login_token = r3.json()["access_token"]
        self.assertTrue(len(login_token) > 20)

        # /me
        r4 = client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {login_token}"
        })
        self.assertEqual(r4.status_code, 200)
        self.assertEqual(r4.json()["email"], "test@example.com")

    def test_wrong_password(self):
        # Register a user first
        client.post("/api/auth/register", json={
            "email": "wrong@example.com", "password": "CorrectPass123!"
        })
        r = client.post("/api/auth/login", data={
            "username": "wrong@example.com", "password": "WrongPass!"
        })
        self.assertEqual(r.status_code, 401)

    def test_invalid_token(self):
        r = client.get("/api/auth/me", headers={
            "Authorization": "Bearer invalid-token-here"
        })
        self.assertEqual(r.status_code, 401)


class TestWeakSecretDetection(unittest.TestCase):
    """Phase 12: Weak JWT secret detection."""

    def test_weak_secrets_list(self):
        for secret in ["dev-secret-change-me", "secret", "123456", "password"]:
            self.assertIn(secret, _WEAK_SECRETS)

    def test_validate_production_rejects_weak_with_postgres(self):
        """Simulate production DB URL + weak secret."""
        s = Settings(
            database_url="postgresql://user:pass@host:5432/db",
            jwt_secret="dev-secret-change-me",
        )
        with self.assertRaises(RuntimeError):
            s.validate_for_production()

    def test_validate_production_allows_strong_with_postgres(self):
        """Strong secret + PostgreSQL should not raise."""
        s = Settings(
            database_url="postgresql://user:pass@host:5432/db",
            jwt_secret="a-very-strong-random-secret-that-is-long-enough",
        )
        s.validate_for_production()  # should not raise

    def test_validate_allows_weak_with_sqlite(self):
        """Weak secret + SQLite (local dev) should not raise."""
        s = Settings(
            database_url="sqlite:///./data/app.db",
            jwt_secret="dev-secret-change-me",
        )
        s.validate_for_production()  # should not raise


def _get_token(email: str, password: str) -> str:
    """Register or login, return the token either way."""
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    if r.status_code == 200:
        return r.json()["access_token"]
    # Already registered — login instead.
    r2 = client.post("/api/auth/login", data={"username": email, "password": password})
    return r2.json()["access_token"]


class TestResumeUpload(unittest.TestCase):
    """Phase 13: Resume binary storage in DB."""

    def setUp(self):
        self.token = _get_token("resume-test@example.com", "ResumePass123!")
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_upload_and_download(self):
        # Upload a text file as a resume
        content = b"John Doe\nSoftware Engineer\nPython, FastAPI, PostgreSQL"
        r = client.post("/api/resumes", headers=self.headers,
                        data={"role": "backend"},
                        files={"file": ("resume.txt", content, "text/plain")})
        self.assertEqual(r.status_code, 200)
        resume_id = r.json()["id"]
        self.assertEqual(r.json()["role"], "backend")

        # List resumes
        r2 = client.get("/api/resumes", headers=self.headers)
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(len(r2.json()) >= 1)

        # Download resume file (binary from DB)
        r3 = client.get(f"/api/resumes/{resume_id}/file", headers=self.headers)
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(r3.content, content)

    def test_delete_resume(self):
        content = b"Delete me"
        r = client.post("/api/resumes", headers=self.headers,
                        data={"role": "delete-test"},
                        files={"file": ("del.txt", content, "text/plain")})
        resume_id = r.json()["id"]

        r2 = client.delete(f"/api/resumes/{resume_id}", headers=self.headers)
        self.assertEqual(r2.status_code, 200)


class TestJobQueue(unittest.TestCase):
    """Phase 15: Job queue lifecycle."""

    def setUp(self):
        self.token = _get_token("job-test@example.com", "JobPass123!")
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_enqueue_claim_report(self):
        # Enqueue a search job via the actions endpoint
        r = client.post("/api/search", headers=self.headers, json={
            "platforms": ["internshala"], "location": "work from home",
            "stipend_min": 0, "max_per_role": 5
        })
        self.assertEqual(r.status_code, 200)
        job_id = r.json()["id"]
        self.assertEqual(r.json()["status"], "queued")

        # Claim the job (as the same user/agent)
        r2 = client.post("/api/jobs/claim", headers=self.headers)
        self.assertEqual(r2.status_code, 200)
        claimed = r2.json()
        self.assertEqual(claimed["id"], job_id)
        self.assertEqual(claimed["status"], "running")

        # Report result
        r3 = client.post(f"/api/jobs/{job_id}/result", headers=self.headers, json={
            "status": "done", "result": {"listings": []}, "error": ""
        })
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(r3.json()["status"], "done")

        # No more jobs to claim
        r4 = client.post("/api/jobs/claim", headers=self.headers)
        self.assertEqual(r4.status_code, 200)
        # Should return null/empty when no jobs
        self.assertIsNone(r4.json())


class TestAgentPairing(unittest.TestCase):
    """Phase 14: Agent pairing flow."""

    def setUp(self):
        self.token = _get_token("agent-test@example.com", "AgentPass123!")
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_pair_token_and_exchange(self):
        # Get a pairing token
        r = client.post("/api/agent/pair-token", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        pair_data = r.json()
        self.assertIn("token", pair_data)
        self.assertIn("server_url", pair_data)
        self.assertIn("command", pair_data)

        # Exchange for device key
        r2 = client.post("/api/agent/pair", json={
            "token": pair_data["token"], "device_name": "test-machine"
        })
        self.assertEqual(r2.status_code, 200)
        self.assertIn("agent_key", r2.json())
        agent_key = r2.json()["agent_key"]

        # Use device key for heartbeat
        r3 = client.post("/api/agent/heartbeat", headers={
            "Authorization": f"Bearer {agent_key}"
        })
        self.assertEqual(r3.status_code, 200)

        # Check agent status
        r4 = client.get("/api/agent/status", headers=self.headers)
        self.assertEqual(r4.status_code, 200)
        self.assertTrue(r4.json()["connected"])
        self.assertEqual(r4.json()["device_name"], "test-machine")

    def test_invalid_pair_token(self):
        r = client.post("/api/agent/pair", json={
            "token": "invalid-token", "device_name": "bad"
        })
        self.assertEqual(r.status_code, 400)

    def test_pause_resume_stop(self):
        # Pause
        r = client.post("/api/agent/pause", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["paused"])

        # Claim should return None when paused
        r2 = client.post("/api/jobs/claim", headers=self.headers)
        self.assertIsNone(r2.json())

        # Resume
        r3 = client.post("/api/agent/resume", headers=self.headers)
        self.assertEqual(r3.status_code, 200)
        self.assertFalse(r3.json()["paused"])

        # Stop
        r4 = client.post("/api/agent/stop", headers=self.headers)
        self.assertEqual(r4.status_code, 200)
        self.assertIn("ok", r4.json())


class TestApplications(unittest.TestCase):
    """Applications CRUD."""

    def setUp(self):
        self.token = _get_token("apps-test@example.com", "AppsPass123!")
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_list_empty(self):
        r = client.get("/api/applications", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])


def tearDownModule():
    """Clean up the test database."""
    try:
        os.unlink(_test_db.name)
    except OSError:
        pass


if __name__ == "__main__":
    unittest.main()
