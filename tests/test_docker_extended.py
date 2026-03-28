from __future__ import annotations

import unittest

from nexora_node_sdk.docker import estimate_docker_resources, generate_nginx_proxy_for_container


class DockerExtendedTests(unittest.TestCase):
    def test_estimate_docker_resources_returns_total(self):
        report = estimate_docker_resources(["redis", "postgres"])
        self.assertGreater(report["total_mem_mb"], 0)

    def test_generate_nginx_proxy_for_container_uses_local_proxy(self):
        config = generate_nginx_proxy_for_container("svc", "example.org", 8080)
        self.assertIn("proxy_pass http://127.0.0.1:8080", config)

    def test_estimate_docker_resources_keeps_timestamp(self):
        report = estimate_docker_resources(["redis"])
        self.assertIn("timestamp", report)


if __name__ == "__main__":
    unittest.main()
