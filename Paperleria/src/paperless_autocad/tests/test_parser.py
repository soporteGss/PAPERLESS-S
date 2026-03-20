import subprocess
import tempfile
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from django.test import TestCase

from documents.parsers import ParseError
from paperless_autocad.parsers import AutocadDocumentParser


class TestAutocadDocumentParser(TestCase):
    """
    Tests for the AutoCAD document parser.

    The parser converts DWG/DXF files to PDF using dwg2pdf from QCAD,
    then generates a thumbnail from the resulting PDF.
    These tests mock the subprocess calls so no real dwg2pdf or xvfb is required.
    """

    def setUp(self) -> None:
        # Create a temporary directory for parser output
        self.tempdir_obj = tempfile.TemporaryDirectory(prefix="paperless-autocad-test-")
        self.tempdir = Path(self.tempdir_obj.name)

        # Build a minimal parser instance without calling __init__ via the signal
        # to avoid Django startup dependencies in isolated unit tests.
        with patch("documents.parsers.settings") as mock_settings:
            mock_settings.SCRATCH_DIR = self.tempdir
            self.parser = AutocadDocumentParser.__new__(AutocadDocumentParser)
            self.parser.tempdir = self.tempdir
            self.parser.archive_path = None
            self.parser.text = None
            self.parser.date = None
            self.parser.settings = self.parser.get_settings()
            self.parser.logging_group = "test-group"
            self.parser.log = MagicMock()

    def tearDown(self) -> None:
        self.tempdir_obj.cleanup()

    # ------------------------------------------------------------------
    # get_settings
    # ------------------------------------------------------------------
    def test_get_settings_default_binary(self) -> None:
        """When env variable is not set, the default binary is 'dwg2pdf'."""
        settings = self.parser.get_settings()
        self.assertEqual(settings["dwg2pdf_binary"], "dwg2pdf")

    def test_get_settings_custom_binary(self) -> None:
        """When PAPERLESS_AUTOCAD_DWG2PDF_BINARY is set, it is used."""
        with mock.patch.dict("os.environ", {"PAPERLESS_AUTOCAD_DWG2PDF_BINARY": "/usr/local/bin/dwg2pdf"}):
            settings = self.parser.get_settings()
        self.assertEqual(settings["dwg2pdf_binary"], "/usr/local/bin/dwg2pdf")

    # ------------------------------------------------------------------
    # parse — success path
    # ------------------------------------------------------------------
    @patch("paperless_autocad.parsers.run_subprocess")
    def test_parse_creates_archive_path(self, mock_run: MagicMock) -> None:
        """
        When dwg2pdf succeeds, archive_path is set to the converted PDF.
        We simulate success by creating the expected output file ourselves
        after the subprocess mock runs.
        """
        # Arrange
        dummy_dwg = self.tempdir / "test_drawing.dwg"
        dummy_dwg.write_bytes(b"AC1015")  # minimal DWG magic bytes

        pdf_path = self.tempdir / "converted.pdf"

        def fake_run_subprocess(args, **kwargs):
            # Simulate dwg2pdf producing the output PDF
            pdf_path.write_bytes(b"%PDF-1.4 fake")

        mock_run.side_effect = fake_run_subprocess

        # Act
        self.parser.parse(str(dummy_dwg), "image/vnd.dwg", "test_drawing.dwg")

        # Assert
        mock_run.assert_called_once()
        called_args = mock_run.call_args[0][0]
        self.assertIn("xvfb-run", called_args)
        self.assertIn("dwg2pdf", called_args)
        self.assertEqual(self.parser.archive_path, pdf_path)
        self.assertIsNone(self.parser.text)

    @patch("paperless_autocad.parsers.run_subprocess")
    def test_parse_uses_correct_output_path(self, mock_run: MagicMock) -> None:
        """The output PDF is placed inside the parser's tempdir."""
        dummy_dwg = self.tempdir / "plano.dwg"
        dummy_dwg.write_bytes(b"AC1015")

        pdf_path = self.tempdir / "converted.pdf"

        def fake_run(*args, **kwargs):
            pdf_path.write_bytes(b"%PDF-1.4 fake")

        mock_run.side_effect = fake_run

        self.parser.parse(str(dummy_dwg), "image/vnd.dwg", "plano.dwg")

        # The archive path must resolve to inside tempdir
        self.assertEqual(self.parser.archive_path.parent, self.tempdir)
        self.assertEqual(self.parser.archive_path.name, "converted.pdf")

    # ------------------------------------------------------------------
    # parse — failure paths
    # ------------------------------------------------------------------
    @patch("paperless_autocad.parsers.run_subprocess")
    def test_parse_raises_on_subprocess_error(self, mock_run: MagicMock) -> None:
        """A CalledProcessError from dwg2pdf must propagate as ParseError."""
        dummy_dwg = self.tempdir / "bad.dwg"
        dummy_dwg.write_bytes(b"BAD")

        mock_run.side_effect = subprocess.CalledProcessError(1, "dwg2pdf")

        with self.assertRaises(ParseError):
            self.parser.parse(str(dummy_dwg), "image/vnd.dwg", "bad.dwg")

    @patch("paperless_autocad.parsers.run_subprocess")
    def test_parse_raises_when_pdf_not_produced(self, mock_run: MagicMock) -> None:
        """If dwg2pdf exits 0 but no PDF is written, ParseError must be raised."""
        dummy_dwg = self.tempdir / "empty.dwg"
        dummy_dwg.write_bytes(b"AC1015")

        # Subprocess succeeds but produces no file
        mock_run.return_value = None

        with self.assertRaises(ParseError) as ctx:
            self.parser.parse(str(dummy_dwg), "image/vnd.dwg", "empty.dwg")

        self.assertIn("did not produce output", str(ctx.exception))

    @patch("paperless_autocad.parsers.run_subprocess")
    def test_parse_raises_on_generic_exception(self, mock_run: MagicMock) -> None:
        """Any unexpected exception from the subprocess must propagate as ParseError."""
        dummy_dwg = self.tempdir / "mystery.dwg"
        dummy_dwg.write_bytes(b"AC1015")

        mock_run.side_effect = OSError("Device not found")

        with self.assertRaises(ParseError):
            self.parser.parse(str(dummy_dwg), "image/vnd.dwg", "mystery.dwg")

    # ------------------------------------------------------------------
    # get_thumbnail
    # ------------------------------------------------------------------
    def test_get_thumbnail_returns_none_without_archive_path(self) -> None:
        """If parse() was never called (or failed), get_thumbnail returns None."""
        self.parser.archive_path = None
        result = self.parser.get_thumbnail(
            document_path="irrelevant.dwg",
            mime_type="image/vnd.dwg",
            file_name="irrelevant.dwg",
        )
        self.assertIsNone(result)

    @patch("paperless_autocad.parsers.make_thumbnail_from_pdf")
    def test_get_thumbnail_calls_make_thumbnail_with_pdf(
        self,
        mock_make_thumb: MagicMock,
    ) -> None:
        """
        When archive_path is set (after a successful parse),
        get_thumbnail delegates to make_thumbnail_from_pdf.
        """
        fake_pdf = self.tempdir / "converted.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")
        self.parser.archive_path = fake_pdf

        expected_thumb = self.tempdir / "thumbnail.webp"
        mock_make_thumb.return_value = expected_thumb

        result = self.parser.get_thumbnail(
            document_path="test.dwg",
            mime_type="image/vnd.dwg",
            file_name="test.dwg",
        )

        mock_make_thumb.assert_called_once_with(fake_pdf, self.tempdir, "test-group")
        self.assertEqual(result, expected_thumb)

    # ------------------------------------------------------------------
    # signals integration
    # ------------------------------------------------------------------
    def test_autocad_consumer_declaration_returns_correct_mime_types(self) -> None:
        """
        The consumer declaration must include all DWG and DXF MIME types
        so Paperless can route these files to AutocadDocumentParser.
        """
        from paperless_autocad.signals import autocad_consumer_declaration

        result = autocad_consumer_declaration(sender=None)

        self.assertIn("image/vnd.dwg", result["mime_types"])
        self.assertIn("application/acad", result["mime_types"])
        self.assertIn("image/x-dwg", result["mime_types"])
        self.assertIn("application/x-dwg", result["mime_types"])
        self.assertIn("image/vnd.dxf", result["mime_types"])
        self.assertIn("application/dxf", result["mime_types"])

        # All DWG types must map to .dwg extension
        for mime, ext in result["mime_types"].items():
            if "dwg" in mime:
                self.assertEqual(ext, ".dwg", f"{mime} should map to .dwg")
            elif "dxf" in mime:
                self.assertEqual(ext, ".dxf", f"{mime} should map to .dxf")

    def test_autocad_consumer_declaration_weight(self) -> None:
        """The parser weight must be positive so it takes precedence over fallbacks."""
        from paperless_autocad.signals import autocad_consumer_declaration

        result = autocad_consumer_declaration(sender=None)
        self.assertGreater(result["weight"], 0)
