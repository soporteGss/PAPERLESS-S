import os
import subprocess
from pathlib import Path

from django.conf import settings

from documents.parsers import DocumentParser, ParseError, make_thumbnail_from_pdf
from documents.utils import run_subprocess


class AutocadDocumentParser(DocumentParser):
    """
    Parser for AutoCAD files (.dwg, .dxf)
    Uses dwg2pdf (from QCAD) to convert the CAD file to PDF.
    Runs inside xvfb-run to ensure headless execution doesn't fail.
    """

    logging_name = "paperless.parsing.autocad"

    def get_settings(self):
        return {
            "dwg2pdf_binary": os.environ.get("PAPERLESS_AUTOCAD_DWG2PDF_BINARY", "dwg2pdf")
        }

    def parse(self, document_path, mime_type, file_name=None):
        self.log.info(f"Converting AutoCAD document {document_path} to PDF")
        
        # Determine paths
        document_path = Path(document_path)
        pdf_path = self.tempdir / "converted.pdf"
        
        dwg2pdf_binary = self.settings["dwg2pdf_binary"]
        
        # We wrap it in xvfb-run because dwg2pdf from qcad often requires an X server even if headless
        args = [
            "xvfb-run", "-a",
            dwg2pdf_binary,
            "-f", # Overwrite existing
            "-o", str(pdf_path),
            str(document_path)
        ]

        try:
            self.log.debug(f"Executing: {' '.join(args)}")
            run_subprocess(args, logger=self.log)
        except subprocess.CalledProcessError as e:
            raise ParseError(f"AutoCAD conversion failed at {args}") from e
        except Exception as e:
            raise ParseError(f"Unknown error while converting AutoCAD file: {e}") from e

        if not pdf_path.exists():
            raise ParseError("DWG to PDF conversion did not produce output file")

        self.archive_path = pdf_path
        
        # Let Paperless run OCR on the resulting PDF if needed.
        self.text = None
        self.log.info("Finished AutoCAD to PDF conversion")

    def get_thumbnail(self, document_path, mime_type, file_name=None):
        if not self.archive_path:
            self.log.warning("get_thumbnail called but archive_path is not set")
            return None
        
        self.log.debug(f"Generating thumbnail for AutoCAD document from {self.archive_path}")
        return make_thumbnail_from_pdf(self.archive_path, self.tempdir, self.logging_group)
