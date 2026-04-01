import subprocess
import sys


TEST_TARGETS = [
    "tests.test_invoice_payload",
    "tests.test_validation_explainability",
    "tests.test_revalidation_behavior",
    "tests.test_xml_import_helpers",
    "tests.test_legacy_mapping_payload",
    "tests.test_contract_consistency",
    "tests.test_invoice.TestValidation",
    "tests.test_invoice.TestXMLGeneration",
]


def main() -> int:
    cmd = [sys.executable, "-m", "unittest", *TEST_TARGETS, "-v"]
    completed = subprocess.run(cmd)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
