# SPDX-License-Identifier: Apache-2.0
"""Test suite for ComputeMesh Office & Table Processing Suite."""

import json
import unittest
from services.mcp.builtin.office_suite import (
    convert_data_to_markdown_table,
    generate_office_document,
    parse_office_document,
)
from services.mcp.formatting.tool_formatter import format_tool_content_if_json
from services.mcp.builtin.weather import get_current_weather


class TestOfficeAndTableSuite(unittest.TestCase):
    def test_convert_data_to_markdown_table(self):
        data = [
            {"Stadt": "Berlin", "Temperatur": "20.0 °C", "Zustand": "Bedeckt"},
            {"Stadt": "München", "Temperatur": "17.8 °C", "Zustand": "Klar"},
            {"Stadt": "Zürich", "Temperatur": "20.7 °C", "Zustand": "Sonnig"},
        ]
        tbl = convert_data_to_markdown_table(data, title="Wettervergleich")
        self.assertIn("Wettervergleich", tbl)
        self.assertIn("| Stadt |", tbl)
        self.assertIn("| Berlin |", tbl)
        self.assertIn("| München |", tbl)
        self.assertIn("| Zürich |", tbl)

    def test_generate_office_document_csv_and_md(self):
        data = [
            {"Asset": "BTC", "Price_USD": 65000, "Change_24h": "+2.5%"},
            {"Asset": "ETH", "Price_USD": 3500, "Change_24h": "-1.2%"},
        ]
        res_csv = generate_office_document(file_format="csv", title="Krypto_Report", data=data)
        self.assertEqual(res_csv["status"], "success")
        self.assertEqual(res_csv["file_format"], "csv")
        self.assertTrue(res_csv["file_size_bytes"] > 0)
        self.assertIn("BTC", res_csv["markdown_table"])

        res_md = generate_office_document(file_format="md", title="Krypto_Report", data=data)
        self.assertEqual(res_md["status"], "success")
        self.assertEqual(res_md["file_format"], "md")

    def test_weather_formatter_multi_city_table(self):
        weather_data = {
            "multiple_locations": True,
            "locations": [
                {
                    "location": "Berlin",
                    "country": "Deutschland",
                    "temperature_celsius": 20.0,
                    "apparent_temperature_celsius": 20.4,
                    "condition": "Bedeckt / Bewölkt",
                    "humidity_percent": 70,
                    "wind_speed_kmh": 7.3,
                },
                {
                    "location": "München",
                    "country": "Deutschland",
                    "temperature_celsius": 17.8,
                    "apparent_temperature_celsius": 18.1,
                    "condition": "Hauptsächlich klar",
                    "humidity_percent": 74,
                    "wind_speed_kmh": 4.8,
                },
                {
                    "location": "Zürich",
                    "country": "Schweiz",
                    "temperature_celsius": 20.7,
                    "apparent_temperature_celsius": 22.1,
                    "condition": "Klarer Himmel / Sonnig",
                    "humidity_percent": 75,
                    "wind_speed_kmh": 5.2,
                },
            ],
            "count": 3,
        }
        formatted = format_tool_content_if_json(json.dumps(weather_data))
        self.assertIn("Wetter-Vergleich", formatted)
        self.assertIn("| 📍 Ort |", formatted)
        self.assertIn("Berlin", formatted)
        self.assertIn("München", formatted)
        self.assertIn("Zürich", formatted)
        self.assertIn("20.0 °C", formatted)


if __name__ == "__main__":
    unittest.main()
