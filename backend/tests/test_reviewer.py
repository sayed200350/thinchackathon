"""HTTP regression checks using only newly constructed synthetic data."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.client import HTTPConnection
import json
import os
from pathlib import Path
from queue import Queue, Empty
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import unittest

from backend.store import connect
from engine import load_policy
from engine.tests.synthetic import BASE, candidate

ROOT=Path(__file__).resolve().parents[2]
CORRECTION=dict(recommendation="human_review",reviewer="Synthetic tester",reason="Synthetic reviewer evidence update",
                policy_version="v1",expected_revision=0,request_id="synthetic-review")


@contextmanager
def running_api(database):
    process=subprocess.Popen([sys.executable,"-m","backend","--db",str(database),"--port","0","--claims",str(ROOT/"engine/tests/fixtures/synthetic_claims.csv")],cwd=ROOT,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=dict(os.environ,POLICY_TWIN_OWNER_TOKEN="synthetic-test-credential"))
    try:
        lines=Queue()
        Thread(target=lambda:lines.put(process.stdout.readline()),daemon=True).start()
        try:
            banner=lines.get(timeout=15).strip()
        except Empty as error:
            raise RuntimeError("API startup timed out") from error
        if not banner:
            raise RuntimeError(process.stderr.read())
        yield int(banner.rsplit(":",1)[1])
    finally:
        process.terminate()
        try: process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.communicate()


def call(port,method,path,body=None,token=None):
    connection=HTTPConnection("127.0.0.1",port,timeout=8)
    try:
        headers={"Content-Type":"application/json"}
        if token: headers["X-Policy-Owner-Token"]=token
        connection.request(method,path,body=None if body is None else json.dumps(body),headers=headers)
        response=connection.getresponse()
        raw=response.read()
        return response.status,json.loads(raw) if raw else None,response.getheaders()
    finally: connection.close()


class ReviewerTests(unittest.TestCase):
    def test_override_survives_restart_preserves_machine_and_is_append_only(self):
        with TemporaryDirectory() as folder:
            database=Path(folder)/"synthetic.sqlite3"
            with running_api(database) as port:
                _,original,_=call(port,"GET","/api/claims/SYN-ROUTINE")
                status,updated,_=call(port,"POST","/api/claims/SYN-ROUTINE/corrections",CORRECTION)
                self.assertEqual(status,201)
                self.assertEqual(updated["decision"],original["decision"])
                entry=updated["history"][0]
                for field in ("reviewer","reason","policy_version"):
                    self.assertEqual(entry[field],CORRECTION[field])
                self.assertTrue(entry["created_at"].endswith("Z"))
                self.assertTrue(original["decision"]["created_at"])
                self.assertEqual(call(port,"POST","/api/claims/SYN-ROUTINE/corrections",CORRECTION)[0],200)
            with running_api(database) as port:
                self.assertEqual(call(port,"GET","/api/claims/SYN-ROUTINE")[1],updated)
            db=connect(database)
            try:
                for sql in ("UPDATE claims SET original_route='human_review'", "DELETE FROM corrections", "UPDATE corrections SET reason='changed'"):
                    with self.assertRaises(sqlite3.IntegrityError): db.execute(sql)
                    db.rollback()
            finally: db.close()

    def test_conflicting_review_and_closed_case_rejection(self):
        with TemporaryDirectory() as folder,running_api(Path(folder)/"synthetic.sqlite3") as port:
            requests=[dict(CORRECTION,request_id=f"request-{i}") for i in range(2)]
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses=list(pool.map(lambda body:call(port,"POST","/api/claims/SYN-ROUTINE/corrections",body),requests))
            self.assertEqual(sorted(r[0] for r in responses),[201,409])
            self.assertEqual(call(port,"POST","/api/claims/SYN-CLOSED/corrections",CORRECTION)[0],409)
            self.assertEqual(call(port,"POST","/api/claims/SYN-MISSING/corrections",dict(CORRECTION,reason=""))[0],400)

    def test_workbench_synthetic_startup_partial_rows_and_saved_history(self):
        with TemporaryDirectory() as folder,running_api(Path(folder)/"synthetic.sqlite3") as port:
            status,workspace,_=call(port,"GET","/api/workbench")
            self.assertEqual(status,200)
            self.assertEqual(len(workspace["claims"]),6)
            self.assertTrue(all(c["case_id"].startswith("SYN-") for c in workspace["claims"]))
            status,result,_=call(port,"POST","/api/workbench/run",dict(claims=workspace["claims"],candidate="threshold",use_saved=True))
            self.assertEqual(status,200)
            closed=next(c for c in result["audit_cases"] if c["case_id"]=="SYN-CLOSED")
            self.assertEqual(closed["retention_source"],"persisted_history")
            self.assertFalse(closed["needs_recheck"])
            status,result,_=call(port,"POST","/api/workbench/run",dict(csv="case_id,case_status,injury_reported\nSYN-1,open,true\nSYN-2,broken,false\n"))
            self.assertEqual(status,200)
            self.assertEqual(len(result["rows"]),2)
            self.assertEqual(len(result["errors"]),1)
            self.assertEqual(result["rows"][0]["recommendation_v1"],"human_review")
            self.assertEqual(result["rows"][1]["recommendation_v1"],"")
            _,again,_=call(port,"POST","/api/workbench/run",dict(claims=result["claims"],input_issues=result["input_issues"]))
            self.assertEqual(result["decisions"][0]["validation_warnings"],again["decisions"][0]["validation_warnings"])

    def test_custom_version_registration_and_owner_review(self):
        with TemporaryDirectory() as folder,running_api(Path(folder)/"synthetic.sqlite3") as port:
            config=candidate(load_policy(),"synthetic-owner-review-v2")
            body=dict(claims=[BASE],candidate="custom",policy=config)
            self.assertEqual(call(port,"POST","/api/workbench/run",body)[0],200)
            config["rules"][6]["if"]["value"]="1100"
            self.assertEqual(call(port,"POST","/api/workbench/run",body)[0],409)
            config["rules"][6]["if"]["value"]="1300"
            review=dict(policy=config,actor="Test policy owner",reason="Reviewed synthetic changes for test only")
            self.assertEqual(call(port,"POST","/api/policies/approve",review)[0],403)
            status,result,_=call(port,"POST","/api/policies/approve",review,"synthetic-test-credential")
            self.assertEqual(status,201,result)
            self.assertEqual(result["review"]["actor"],"Test policy owner")
            self.assertTrue(result["review"]["occurred_at"].endswith("Z"))
            self.assertEqual(result["independent_v2_quality"],"not measured")
            config["version"]="hypothetical-test-v2"
            self.assertEqual(call(port,"POST","/api/policies/approve",review,"synthetic-test-credential")[0],400)

    def test_browser_assets_and_invalid_policy_are_errors(self):
        with TemporaryDirectory() as folder,running_api(Path(folder)/"synthetic.sqlite3") as port:
            connection=HTTPConnection("127.0.0.1",port)
            connection.request("GET","/")
            response=connection.getresponse()
            self.assertEqual(response.status,200)
            self.assertIn(b"Why this decision?",response.read())
            connection.close()
            self.assertEqual(call(port,"POST","/api/workbench/run",dict(claims=[BASE],candidate=[]))[0],400)
            self.assertEqual(call(port,"POST","/api/workbench/run",dict(claims=[BASE],candidate="custom",policy={}))[0],400)


if __name__=="__main__": unittest.main()
