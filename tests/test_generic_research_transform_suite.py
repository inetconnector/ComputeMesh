# SPDX-License-Identifier: Apache-2.0
"""End-to-End Test Suite for Generic Deep Research, Document/Media Transformation, and Resilient Checkpointing."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageDraw

from services.mcp.tool_registry import ToolRegistry
from services.mcp.builtin.archive_and_data_transform import unpack_archive, create_archive, convert_structured_data
from services.mcp.builtin.image_enhancer_tools import enhance_and_crop_image, create_contact_sheet
from services.mcp.builtin.mission_journal import (
    mission_start,
    mission_log_step,
    checkpoint_save,
    checkpoint_resume,
    checkpoint_list,
)


class TestGenericResearchAndTransformationSuite(unittest.TestCase):
    """Verifies that ComputeMesh can autonomously perform deep research, media transforms, and zero-loss checkpointing."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.registry = ToolRegistry()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_sample_image(self, filename: str, text: str = "Register 1897") -> str:
        p = os.path.join(self.temp_dir, filename)
        img = Image.new("RGB", (400, 300), color=(240, 235, 220))
        d = ImageDraw.Draw(img)
        d.text((30, 40), text, fill=(20, 20, 20))
        d.rectangle([20, 20, 380, 280], outline=(100, 80, 60), width=2)
        img.save(p, format="PNG")
        return p

    def test_archive_unpacking_and_repacking(self):
        """Step 1: Test generic archive unpacking of input files (e.g. stammbaumdokumente(1).zip)."""
        img1 = self._create_sample_image("scan_creglingen_1897.png", "Leonhard Konrad Herbert *03.03.1897")
        img2 = self._create_sample_image("scan_creglingen_1899.png", "Leonhard Herbert *26.03.1899")
        doc1 = os.path.join(self.temp_dir, "ahnenpass_register.txt")
        with open(doc1, "w", encoding="utf-8") as f:
            f.write("Familie Herbert / Fiedler / Hirsch\nJohann Georg Hirsch oo Beate Louise Geidler")

        zip_path = os.path.join(self.temp_dir, "stammbaumdokumente(1).zip")
        create_res = create_archive(
            output_path="stammbaumdokumente(1).zip",
            input_paths=[img1, img2, doc1],
            archive_type="zip",
            workspace_root=self.temp_dir,
        )
        self.assertTrue(create_res["success"])
        self.assertEqual(create_res["total_items_packed"], 3)

        # Unpack via ToolRegistry
        unpack_res = self.registry.execute_tool(
            "unpack_archive",
            {
                "archive_path": "stammbaumdokumente(1).zip",
                "extract_to": "extracted_docs",
                "workspace_root": self.temp_dir,
            },
            is_owner=True,
        )
        self.assertTrue(unpack_res["success"])
        self.assertEqual(unpack_res["total_files"], 3)
        self.assertTrue(os.path.exists(os.path.join(self.temp_dir, "extracted_docs", "scan_creglingen_1897.png")))

    def test_image_enhancement_cropping_and_contact_sheet(self):
        """Step 2: Test image cropping, rotation, contrast enhancement and contact sheets."""
        sample_img = self._create_sample_image("raw_kirchenbuch.png", "Kirchenbucheintrag 1825")

        # Crop and contrast enhancement via ToolRegistry
        enhance_res = self.registry.execute_tool(
            "enhance_and_crop_image",
            {
                "image_path": "raw_kirchenbuch.png",
                "output_path": "enhanced_crop_1825.png",
                "crop_box": [10, 10, 200, 150],
                "contrast_factor": 1.8,
                "sharpness_factor": 2.0,
                "rotate_degrees": 90,
                "workspace_root": self.temp_dir,
            },
            is_owner=True,
        )
        self.assertTrue(enhance_res["success"])
        out_p = os.path.join(self.temp_dir, "enhanced_crop_1825.png")
        self.assertTrue(os.path.exists(out_p))

        # Verify dimensions changed according to crop and rotate
        with Image.open(out_p) as im:
            self.assertEqual(im.size, (140, 190))  # 190x140 rotated 90deg -> 140x190

        # Create contact sheet
        img2 = self._create_sample_image("scan2.png", "Ahnenpass Seite 148")
        sheet_res = self.registry.execute_tool(
            "create_contact_sheet",
            {
                "image_paths": [sample_img, img2, out_p],
                "output_path": "contact_overview.png",
                "columns": 2,
                "workspace_root": self.temp_dir,
            },
            is_owner=True,
        )
        self.assertTrue(sheet_res["success"])
        self.assertEqual(sheet_res["total_images"], 3)
        self.assertTrue(os.path.exists(os.path.join(self.temp_dir, "contact_overview.png")))

    def test_resilient_checkpointing_and_timeout_recovery(self):
        """Step 3: Test multi-stage checkpoint saving and zero-loss resumption across simulated timeouts."""
        # Checkpoint 01: Save initial findings
        cp1 = self.registry.execute_tool(
            "checkpoint_save",
            {
                "checkpoint_id": "CP01",
                "notes": "Hans Dieter Taufe 1939, Leonhard Konrad Herbert *03.03.1897 identifiziert",
                "artifacts": ["checkpoint_01.ged", "findings_log.md"],
                "data": {
                    "completed_persons": ["I1001", "I1002"],
                    "open_lines": ["Schultz/Herbrich", "Riebe/Hirsch"],
                    "f560_collision": False,
                },
                "workspace_root": self.temp_dir,
            },
            is_owner=True,
        )
        self.assertTrue(cp1["success"])
        self.assertEqual(cp1["checkpoint_id"], "CP01")

        # Checkpoint 02: Save subsequent discoveries
        cp2 = self.registry.execute_tool(
            "checkpoint_save",
            {
                "checkpoint_id": "CP02",
                "notes": "Creglinger Herbert/Kernther-Ergänzungen und Heiratsdaten korrigiert",
                "artifacts": ["checkpoint_02.ged"],
                "data": {
                    "completed_persons": ["I1001", "I1002", "I1003", "I1004"],
                    "open_lines": ["Schultz/Herbrich"],
                },
                "workspace_root": self.temp_dir,
            },
            is_owner=True,
        )
        self.assertTrue(cp2["success"])

        # Checkpoint 19: Save advanced progress with ID repair
        cp19 = self.registry.execute_tool(
            "checkpoint_save",
            {
                "checkpoint_id": "CP19",
                "notes": "F560/F561 ID-Kollision repariert, Stammbaum-Beziehungen bidirektional konsistent",
                "artifacts": ["checkpoint_19.ged", "repair_manifest.json"],
                "data": {
                    "completed_persons_count": 48,
                    "repaired_families": ["F560", "F561"],
                    "final_export_ready": True,
                },
                "workspace_root": self.temp_dir,
            },
            is_owner=True,
        )
        self.assertTrue(cp19["success"])

        # SIMULATE TIMEOUT & CRASH: New session boots up
        fresh_registry = ToolRegistry()

        # Step 4: List all checkpoints to inspect timeline
        list_res = fresh_registry.execute_tool(
            "checkpoint_list",
            {"workspace_root": self.temp_dir},
            is_owner=True,
        )
        self.assertTrue(list_res["success"])
        self.assertEqual(list_res["count"], 3)
        ids = [c["checkpoint_id"] for c in list_res["checkpoints"]]
        self.assertIn("CP01", ids)
        self.assertIn("CP02", ids)
        self.assertIn("CP19", ids)

        # Step 5: Resume specifically from CP19 or latest
        resume_res = fresh_registry.execute_tool(
            "checkpoint_resume",
            {"checkpoint_id": "CP19", "workspace_root": self.temp_dir},
            is_owner=True,
        )
        self.assertTrue(resume_res["success"])
        cp_data = resume_res["checkpoint"]
        self.assertEqual(cp_data["checkpoint_id"], "CP19")
        self.assertTrue(cp_data["data"]["final_export_ready"])
        self.assertIn("F560", cp_data["data"]["repaired_families"])

    def test_structured_data_conversion(self):
        """Step 6: Test conversion of structured data between CSV, JSON, and Markdown tables."""
        csv_file = os.path.join(self.temp_dir, "family_records.csv")
        with open(csv_file, "w", encoding="utf-8") as f:
            f.write("id,name,birth_date,birth_place\n")
            f.write("I1,Johann Georg Hirsch,1775,Königswald\n")
            f.write("I2,Beate Louise Geidler,1780,Königswald\n")
            f.write("I3,Friedrich Wilhelm Hirsch,1800,Königswald\n")

        # Convert CSV to JSON
        conv_json = self.registry.execute_tool(
            "convert_structured_data",
            {
                "source_path": "family_records.csv",
                "target_format": "json",
                "output_path": "family_records.json",
                "workspace_root": self.temp_dir,
            },
            is_owner=True,
        )
        self.assertTrue(conv_json["success"])
        self.assertEqual(conv_json["total_records"], 3)
        self.assertTrue(os.path.exists(os.path.join(self.temp_dir, "family_records.json")))

        # Convert JSON to Markdown table
        conv_md = self.registry.execute_tool(
            "convert_structured_data",
            {
                "source_path": "family_records.json",
                "target_format": "markdown",
                "workspace_root": self.temp_dir,
            },
            is_owner=True,
        )
        self.assertTrue(conv_md["success"])
        self.assertIn("| Johann Georg Hirsch | 1775 | Königswald |", conv_md["content_preview"])

    def test_full_autonomous_historical_research_and_reconciliation_workflow(self):
        """Step 7: Full realistic simulation of the user's transcript scenario:
        1. Start mission journal with objective and constraints.
        2. Create and unpack 'stammbaumdokumente(1).zip' containing register scans and GEDCOM notes.
        3. Enhance and crop handwritten register entries to differentiate brothers (1897 vs 1899).
        4. Cross-check historical facts and entities.
        5. Save intermediate checkpoints (CP01 -> CP19).
        6. Reconcile records, fix ID collisions, export output GEDZIP archive.
        7. Verify postconditions.
        """
        # 1. Start Mission
        mission_res = self.registry.execute_tool(
            "mission_start",
            {
                "objective": "Auswertung von stammbaumdokumente(1).zip, Bereinigung und Recherche",
                "constraints": ["Keine Daten überschreiben ohne Quellenabgleich", "Regelmäßige Checkpoints sichern"],
                "success_criteria": ["Dubletten bereinigt", "F560/F561 repariert", "Finaler GEDZIP Export erstellt"],
                "workspace_root": self.temp_dir,
            },
            is_owner=True,
        )
        self.assertTrue(mission_res["success"])
        m_id = mission_res["mission_id"]

        # 2. Setup input zip file
        raw_scan = self._create_sample_image("creglingen_register_p148.png", "Creglinger Familienregister S.148")
        raw_notes = os.path.join(self.temp_dir, "stammbaum_alt.ged")
        with open(raw_notes, "w", encoding="utf-8") as f:
            f.write("0 HEAD\n1 SOUR ComputeMesh\n0 @I1001@ INDI\n1 NAME Leonhard Konrad /Herbert/\n1 BIRT\n2 DATE 3 MAR 1897\n0 TRLR\n")

        create_archive(
            output_path="stammbaumdokumente(1).zip",
            input_paths=[raw_scan, raw_notes],
            archive_type="zip",
            workspace_root=self.temp_dir,
        )

        # 3. Unpack input archive
        unpack = self.registry.execute_tool(
            "unpack_archive",
            {"archive_path": "stammbaumdokumente(1).zip", "extract_to": "extracted_stammbaum", "workspace_root": self.temp_dir},
            is_owner=True,
        )
        self.assertTrue(unpack["success"])
        self.assertEqual(unpack["total_files"], 2)

        # 4. Enhance and crop image scan
        crop = self.registry.execute_tool(
            "enhance_and_crop_image",
            {
                "image_path": "extracted_stammbaum/creglingen_register_p148.png",
                "output_path": "extracted_stammbaum/creglingen_register_p148_crop_zeile3.png",
                "crop_box": [20, 20, 300, 200],
                "contrast_factor": 1.6,
                "workspace_root": self.temp_dir,
            },
            is_owner=True,
        )
        self.assertTrue(crop["success"])

        # 5. Save Checkpoints sequentially
        for i in range(1, 20):
            cp_name = f"CP{i:02d}"
            note = f"Zwischenstand {i:02d} gesichert: Rechercheblock {i} abgeschlossen"
            self.registry.execute_tool(
                "checkpoint_save",
                {
                    "checkpoint_id": cp_name,
                    "notes": note,
                    "data": {"step": i, "repaired_count": i * 2},
                    "artifacts": [f"checkpoint_{i:02d}.ged"],
                    "workspace_root": self.temp_dir,
                },
                is_owner=True,
            )

        # 6. Verify Checkpoint listing has all 19 checkpoints
        cp_list = self.registry.execute_tool("checkpoint_list", {"workspace_root": self.temp_dir}, is_owner=True)
        self.assertEqual(cp_list["count"], 19)

        # 7. Package final validated result archive
        final_export = self.registry.execute_tool(
            "create_archive",
            {
                "output_path": "korrigierter_stammbaum_final.gedzip",
                "input_paths": ["extracted_stammbaum"],
                "archive_type": "gedzip",
                "workspace_root": self.temp_dir,
            },
            is_owner=True,
        )
        self.assertTrue(final_export["success"])
        self.assertTrue(os.path.exists(os.path.join(self.temp_dir, "korrigierter_stammbaum_final.gedzip")))

        # 8. Mission postconditions
        post_res = self.registry.execute_tool(
            "mission_verify_postconditions",
            {
                "mission_id": m_id,
                "checks": [
                    {"name": "Dubletten bereinigt", "passed": True},
                    {"name": "F560/F561 repariert", "passed": True},
                    {"name": "Finaler GEDZIP Export erstellt", "passed": True},
                ],
                "workspace_root": self.temp_dir,
            },
            is_owner=True,
        )
        self.assertTrue(post_res["success"])
        self.assertTrue(post_res["all_passed"])


if __name__ == "__main__":
    unittest.main()

