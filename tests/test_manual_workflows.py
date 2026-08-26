import unittest
from pathlib import Path


class ManualWorkflowTests(unittest.TestCase):
    def read(self, name: str) -> str:
        return Path(".github/workflows", name).read_text(encoding="utf-8")

    def test_no_fetch_workflows_disable_external_fetch(self):
        for name in ("recalculate-indicators.yml", "regenerate-charts.yml", "rebuild-dashboard-no-fetch.yml"):
            with self.subTest(name=name):
                workflow = self.read(name)
                self.assertIn('EXTERNAL_FETCH_ENABLED: "false"', workflow)
                self.assertIn("pipeline_tasks", workflow)
                self.assertIn("publish:", workflow)

    def test_publication_concurrency_is_shared_only_when_publishing(self):
        for name in ("update-data.yml", "recalculate-indicators.yml", "regenerate-charts.yml", "rebuild-dashboard-no-fetch.yml"):
            with self.subTest(name=name):
                workflow = self.read(name)
                self.assertIn("ri-tracker-data-publication", workflow)
                self.assertIn("cancel-in-progress: false", workflow)

    def test_regenerate_charts_has_matplotlib_cache_and_artifacts(self):
        workflow = self.read("regenerate-charts.yml")
        self.assertIn("matplotlib-font-cache", workflow)
        self.assertNotIn("runner.temp", workflow)
        self.assertIn("actions/upload-artifact", workflow)

    def test_rebuild_dashboard_avoids_runner_context_in_job_env(self):
        workflow = self.read("rebuild-dashboard-no-fetch.yml")
        self.assertIn("MPLCONFIGDIR: .matplotlib-cache", workflow)
        self.assertNotIn("runner.temp", workflow)


if __name__ == "__main__":
    unittest.main()
