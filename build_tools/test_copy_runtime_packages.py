import tempfile
import unittest
from pathlib import Path

from build_tools.copy_runtime_packages import (
    _installed_distributions,
    copy_distributions,
    dependency_closure,
    validate_top_level_pth,
)


def _install_fake_distribution(
    root: Path, name: str, *, requires: tuple[str, ...] = ()
) -> None:
    normalized = name.replace("-", "_")
    package_dir = root / normalized
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")

    metadata_dir = root / f"{normalized}-1.0.dist-info"
    metadata_dir.mkdir()
    metadata = ["Metadata-Version: 2.1", f"Name: {name}", "Version: 1.0"]
    metadata.extend(f"Requires-Dist: {requirement}" for requirement in requires)
    (metadata_dir / "METADATA").write_text("\n".join(metadata) + "\n", encoding="utf-8")
    records = [
        f"{normalized}/__init__.py,,",
        f"{normalized}-1.0.dist-info/METADATA,,",
        f"{normalized}-1.0.dist-info/RECORD,,",
    ]
    (metadata_dir / "RECORD").write_text("\n".join(records) + "\n", encoding="utf-8")


class RuntimeCopyTests(unittest.TestCase):
    def test_copies_only_the_selected_dependency_closure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "site-packages"
            destination = root / "runtime"
            source.mkdir()
            _install_fake_distribution(
                source,
                "demo-app",
                requires=(
                    "demo-dep>=1",
                    "unrelated-large-package; extra == 'large'",
                ),
            )
            _install_fake_distribution(source, "demo-dep")
            _install_fake_distribution(source, "unrelated-large-package")

            selected = dependency_closure(
                _installed_distributions(source), ["demo-app"]
            )
            copy_distributions(source, destination, selected)

            self.assertTrue((destination / "demo_app" / "__init__.py").is_file())
            self.assertTrue((destination / "demo_dep" / "__init__.py").is_file())
            self.assertFalse((destination / "unrelated_large_package").exists())

    def test_rejects_unknown_top_level_pth(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            (source / "unexpected.pth").write_text("import payload\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "unexpected.pth"):
                validate_top_level_pth(source)


if __name__ == "__main__":
    unittest.main()
