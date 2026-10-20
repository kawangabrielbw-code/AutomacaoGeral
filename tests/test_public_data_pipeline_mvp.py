import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from src.engine.public_data_pipeline import PublicDataPipeline


class PublicDataPipelineMvpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.catalog = self.root / "sources.json"
        self.catalog.write_text(json.dumps({
            "version": 1,
            "sources": [
                {"id": "sample", "name": "Sample", "url": "https://example.com",
                 "resource_url": None, "encoding": "utf-8-sig", "delimiter": ";"}
            ]
        }), encoding="utf-8")
        self.pipeline = PublicDataPipeline(self.catalog, self.root / "data")

    def tearDown(self):
        self.temp.cleanup()

    def test_semicolon_csv_is_normalized_and_leading_zero_is_preserved(self):
        raw_dir = self.root / "raw"
        out_dir = self.root / "processed"
        raw_dir.mkdir()
        out_dir.mkdir()
        raw = raw_dir / "sample.csv"
        raw.write_text("codigo;nome\n00123;Diadema\n", encoding="utf-8")
        outputs = self.pipeline._convert_resource(raw, out_dir, {"delimiter": ";", "encoding": "utf-8"})
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0].suffix, ".csv")
        self.assertEqual(outputs[0].read_text(encoding="utf-8"), "codigo,nome\n00123,Diadema\n")

    def test_zip_txt_resource_is_written_with_csv_extension(self):
        raw_dir = self.root / "raw"
        out_dir = self.root / "processed"
        raw_dir.mkdir()
        out_dir.mkdir()
        archive_path = raw_dir / "sample.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("dados.txt", "codigo;nome\n00123;Diadema\n")
        outputs = self.pipeline._convert_resource(
            archive_path, out_dir, {"delimiter": ";", "encoding": "utf-8"}
        )
        self.assertTrue(outputs, "ZIP deveria gerar ao menos um arquivo tabular")
        self.assertTrue(
            all(path.suffix.lower() == ".csv" for path in outputs),
            f"Todos os resultados devem ser CSV; extensões geradas: {[p.name for p in outputs]}",
        )
        self.assertEqual(outputs[0].read_text(encoding="utf-8"), "codigo,nome\n00123,Diadema\n")

    def test_catalog_rejects_duplicate_source_ids(self):
        self.catalog.write_text(json.dumps({
            "sources": [{"id": "duplicate"}, {"id": "duplicate"}]
        }), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "identificadores vazios ou duplicados"):
            self.pipeline.catalog()


if __name__ == "__main__":
    unittest.main()
