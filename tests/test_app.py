"""Basic automated tests. Run with:  python -m unittest discover -s tests -v"""
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["GYM_DB"] = _tmp.name
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as gym  # noqa: E402
from db import query, scalar  # noqa: E402


class GymTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        gym.app.config["TESTING"] = True

    def setUp(self):
        self.c = gym.app.test_client()

    def login(self):
        return self.c.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)

    def test_login_required(self):
        r = self.c.get("/members")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_wrong_password(self):
        r = self.c.post("/login", data={"username": "admin", "password": "nope"})
        self.assertIn(b"Wrong username or password", r.data)

    def test_all_pages_load(self):
        self.login()
        for url in ["/", "/members", "/members?status=active", "/members?status=expired&q=a", "/attendance",
                    "/payments", "/payments?month=2026-11", "/plans", "/trainers", "/reports",
                    "/members/add", "/members/1", "/members/1/edit"]:
            self.assertEqual(self.c.get(url).status_code, 200, url)

    def test_seed_data_present(self):
        self.assertGreaterEqual(scalar("SELECT COUNT(*) FROM members"), 12)
        self.assertEqual(scalar("SELECT COUNT(*) FROM plans"), 4)

    def test_add_member_creates_payment(self):
        self.login()
        before = scalar("SELECT COUNT(*) FROM payments")
        r = self.c.post("/members/add", data={
            "name": "Test User", "phone": "9000000001", "email": "t@x.com", "gender": "Male",
            "plan_id": "1", "trainer_id": "", "start_date": date.today().isoformat(), "method": "UPI"},
            follow_redirects=True)
        self.assertIn(b"Member added", r.data)
        self.assertEqual(scalar("SELECT COUNT(*) FROM payments"), before + 1)
        m = query("SELECT * FROM members WHERE phone='9000000001'", one=True)
        self.assertEqual(m["plan_id"], 1)
        self.assertGreater(m["end_date"], m["start_date"])

    def test_duplicate_phone_rejected(self):
        self.login()
        r = self.c.post("/members/add", data={
            "name": "Dup", "phone": "9876500001", "gender": "Male", "plan_id": "1",
            "start_date": date.today().isoformat(), "method": "Cash"}, follow_redirects=True)
        self.assertIn(b"already exists", r.data)

    def test_invalid_phone_rejected(self):
        self.login()
        r = self.c.post("/members/add", data={
            "name": "Bad", "phone": "123", "gender": "Male", "plan_id": "1",
            "start_date": date.today().isoformat(), "method": "Cash"}, follow_redirects=True)
        self.assertIn(b"10 digits", r.data)

    def test_renew_extends_membership(self):
        self.login()
        # member 3 (Rohan) has a yearly plan that is still active
        old = query("SELECT * FROM members WHERE member_id=3", one=True)
        self.c.post("/members/3/renew", data={"plan_id": "1", "method": "Cash"}, follow_redirects=True)
        new = query("SELECT * FROM members WHERE member_id=3", one=True)
        self.assertEqual(new["start_date"], (date.fromisoformat(old["end_date"]) + timedelta(days=1)).isoformat())
        self.assertGreater(new["end_date"], old["end_date"])

    def test_attendance_rules(self):
        self.login()
        # member 8 (Ananya, yearly, started 200 days ago) is active and has no check-in today by default
        self.c.post("/attendance", data={"member_id": "8"}, follow_redirects=True)
        r = self.c.post("/attendance", data={"member_id": "8"}, follow_redirects=True)
        self.assertTrue(b"already checked in" in r.data)
        # expired member: member 7 (monthly, started 45 days ago) cannot check in
        r = self.c.post("/attendance", data={"member_id": "7"}, follow_redirects=True)
        self.assertIn(b"expired", r.data)

    def test_plan_in_use_cannot_be_deleted(self):
        self.login()
        r = self.c.post("/plans/1/delete", follow_redirects=True)
        self.assertIn(b"cannot be deleted", r.data)

    def test_trainer_delete_unassigns_members(self):
        self.login()
        self.c.post("/trainers", data={"name": "Temp Trainer", "phone": "9111111111", "speciality": "X"})
        tid = scalar("SELECT trainer_id FROM trainers WHERE phone='9111111111'")
        self.c.post("/members/add", data={
            "name": "With Trainer", "phone": "9000000002", "gender": "Female", "plan_id": "1",
            "trainer_id": str(tid), "start_date": date.today().isoformat(), "method": "Cash"})
        self.c.post(f"/trainers/{tid}/delete")
        m = query("SELECT * FROM members WHERE phone='9000000002'", one=True)
        self.assertIsNone(m["trainer_id"])

    def test_delete_member_cascades(self):
        self.login()
        mid = scalar("SELECT member_id FROM members WHERE phone='9876500012'")
        self.c.post(f"/members/{mid}/delete")
        self.assertEqual(scalar("SELECT COUNT(*) FROM payments WHERE member_id=?", (mid,)), 0)
        self.assertEqual(scalar("SELECT COUNT(*) FROM attendance WHERE member_id=?", (mid,)), 0)


if __name__ == "__main__":
    unittest.main()
