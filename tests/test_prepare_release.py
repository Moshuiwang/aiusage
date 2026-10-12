from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

class TestPrepareRelease(unittest.TestCase):
    def test_unchecked_commit_never_builds_or_creates_release(self):
        from scripts.prepare_release import check_release_source, ReleasePreparationError
        calls = []
        def run(command, cwd):
            calls.append(command)
            if command[:3] == ["git", "status", "--porcelain"]: return ""
            if command[:2] == ["git", "rev-parse"]: return "a" * 40
            if "pulls" in command[-1]: return "[]"
            raise AssertionError(command)
        with self.assertRaises(ReleasePreparationError):
            check_release_source(Path("."), run)
        self.assertFalse(any("release" in call or "build_signed_release.py" in " ".join(call) for call in calls))

    def test_dirty_or_unmerged_source_is_rejected_before_github_mutation(self):
        from scripts.prepare_release import check_release_source, ReleasePreparationError
        for dirty, head, main in [(" M source.py", "a"*40, "a"*40), ("", "b"*40, "a"*40)]:
            calls=[]
            def run(command,cwd):
                calls.append(command)
                if command[:3] == ["git", "status", "--porcelain"]: return dirty
                return head if command[-1]=="HEAD" else main
            with self.subTest(dirty=dirty,head=head):
                with self.assertRaises(ReleasePreparationError): check_release_source(Path("."),run)
                self.assertTrue(all(call[0]=="git" for call in calls))

    def test_all_four_required_checks_must_succeed_and_missing_is_rejected(self):
        from scripts.prepare_release import require_release_checks, ReleasePreparationError
        required=["Python","Cloudflare Worker","iOS Swift","macOS Swift"]
        valid=[{"name":name,"conclusion":"SUCCESS"} for name in required]
        require_release_checks(valid)
        for name in required:
            for failure in ["FAILURE","CANCELLED","PENDING",None]:
                with self.subTest(name=name,failure=failure):
                    rows=[dict(row,conclusion=failure) if row["name"]==name else row for row in valid]
                    with self.assertRaises(ReleasePreparationError):require_release_checks(rows)
            with self.assertRaises(ReleasePreparationError):require_release_checks([row for row in valid if row["name"]!=name])
        with self.assertRaises(ReleasePreparationError): require_release_checks(valid+[dict(valid[0],conclusion="FAILURE")])

    def test_mismatched_or_partial_remote_draft_never_passes_self_check(self):
        from scripts.prepare_release import require_draft_assets, ReleasePreparationError
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/"manifest.json").write_bytes(b"signed manifest");(root/"mac.tar.gz").write_bytes(b"app")
            import hashlib
            assets=[{"name":p.name,"size":p.stat().st_size,"digest":"sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()} for p in root.iterdir()]
            require_draft_assets(root,assets)
            for bad in [assets[:-1], [dict(row,size=row["size"]+1) for row in assets], [dict(row,digest="sha256:"+"0"*64) for row in assets]]:
                with self.assertRaises(ReleasePreparationError): require_draft_assets(root,bad)

    def test_creation_uses_only_draft_and_exact_verified_commit(self):
        from scripts.prepare_release import create_release_draft, GH
        calls=[]
        def run(command,cwd): calls.append(command);return ""
        create_release_draft(Path("."), "v2.2.0", "a"*40, [Path("app.tar.gz")], Path("notes.md"), run)
        self.assertEqual(len(calls),1)
        command=calls[0]
        self.assertEqual(command[:4],[GH,"release","create","v2.2.0"])
        self.assertIn("--draft",command)
        self.assertEqual(command[command.index("--target")+1],"a"*40)
        self.assertNotIn("--clobber",command)
