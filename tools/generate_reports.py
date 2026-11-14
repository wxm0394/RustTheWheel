#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate JSON and CSV reports from scan_rtw_opcodes.py

Accepts CLI arguments --input (scripts.txt path) and --output-dir (output directory).
All output is isolated in the specified output directory.
"""

import sys
import os
import hashlib
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scan_rtw_opcodes import scan_rtw_scripts, _generate_json_report, _generate_csv_report


def _calculate_sha256(filepath):
    """Calculate SHA-256 hash of a file."""
    try:
        with open(filepath, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"Error calculating SHA256 for {filepath}: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description='Generate JSON and CSV reports from scan_rtw_opcodes.py'
    )
    parser.add_argument(
        '--input', required=True,
        help='Path to the scripts.txt file to scan'
    )
    parser.add_argument(
        '--output-dir', required=True,
        help='Directory to save output reports'
    )
    args = parser.parse_args()

    scripts_filepath = args.input
    output_dir = args.output_dir

    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Verify input file exists
    if not os.path.exists(scripts_filepath):
        print(f"Error: {scripts_filepath} not found")
        return 1

    # Calculate SHA-256 of the input file
    file_sha256 = _calculate_sha256(scripts_filepath)
    if file_sha256 is None:
        print(f"Error: Could not calculate SHA256 for {scripts_filepath}")
        return 1

    print(f"Scanning {scripts_filepath}...")
    print(f"  SHA256: {file_sha256}")

    # Run the scanner with statement detail capture for opcodes 713, 715, 716
    result = scan_rtw_scripts(scripts_filepath, capture_statement_details=True)

    # Prepare metadata for reports
    report_metadata = {
        "source_path": os.path.abspath(scripts_filepath),
        "source_sha256": file_sha256,
        "scan_tool_version": "scan_rtw_opcodes.py",
        "scan_command": (
            f"generate_reports.py --input {scripts_filepath} --output-dir {output_dir}"
        ),
        "known_opcode_table_source": "not_checked",
        "known_opcode_table_hash": "not_checked",
        "known_opcode_table_count": "not_checked",
    }

    # Merge metadata with scan results
    result_with_meta = dict(result)
    result_with_meta.update(report_metadata)

    # Generate JSON report with metadata
    json_output_path = os.path.join(output_dir, "scan_results.json")
    _generate_json_report(result_with_meta, json_output_path)
    print(f"JSON report generated at {json_output_path}")

    # Generate CSV report with metadata
    csv_output_path = os.path.join(output_dir, "scan_results.csv")
    _generate_csv_report(result_with_meta, csv_output_path)
    print(f"CSV report generated at {csv_output_path}")

    # Print summary
    print(f"\nScan completed successfully!")
    print(f"  File success: {result['file_success']}")
    print(f"  Structure success: {result['structure_success']}")
    print(f"  Opcode identification status: {result['opcode_identification_status']}")
    print(f"  Semantic compatibility status: {result['semantic_compatibility_status']}")
    print(f"  Declared scripts: {result['declared_script_count']}")
    print(f"  Discovered scripts: {result['discovered_script_count']}")
    print(f"  Successful scripts: {result['successful_script_count']}")
    print(f"  Failed scripts: {result['failed_script_count']}")
    print(f"  Declared statements: {result['declared_statement_total']}")
    print(f"  Successful statements: {result['successful_statement_total']}")
    print(f"  SHA256: {result['sha256']}")

    # Exit with non-zero code on failures
    if not result["file_success"]:
        print("Error: File scan failed")
        return 1
    if not result["structure_success"]:
        print("Warning: Structural issues detected in scan")
        return 2
    if result["opcode_identification_status"] != "ok":
        print(f"Warning: Opcode identification status is {result['opcode_identification_status']}")
        return 3
    if result["semantic_compatibility_status"] != "ok":
        print(f"Warning: Semantic compatibility status is {result['semantic_compatibility_status']}")
        return 4

    return 0


if __name__ == '__main__':
    sys.exit(main())