#!/usr/bin/env python3
"""Generate independent conversion candidates for changed opcodes."""

import json
import sys
import os

# Add the project root to path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)


def generate_conversion_candidates(
    scan_results_path,
    identification_table_path,
    target_scan_path,
    output_path
):
    """Generate conversion candidates from scan results and identification table."""
    
    # Load scan results (RTW original)
    with open(scan_results_path, 'r', encoding='utf-8') as f:
        scan_results = json.load(f)
    
    # Load identification table
    with open(identification_table_path, 'r', encoding='utf-8') as f:
        identification_table = json.load(f)
    
    # Load target scan (Warband 1.174)
    with open(target_scan_path, 'r', encoding='utf-8') as f:
        target_scan = json.load(f)
    
    # Extract base usage from scan results
    base_usage = scan_results.get('base_usage', {})
    target_base_usage = target_scan.get('base_usage', {})
    
    # Extract mappings from identification table
    mappings = identification_table.get('mappings', {})
    
    # Create conversion candidates
    candidates = {
        "metadata": {
            "source_scan": scan_results_path,
            "target_scan": target_scan_path,
            "identification_table": identification_table_path,
            "description": "Independent conversion candidates for changed opcodes used in RTW"
        },
        "candidates": []
    }
    
    # Process each opcode in base usage that has a "changed" mapping
    for opcode_str, count in base_usage.items():
        opcode = int(opcode_str)
        
        # Find mapping in identification table
        if str(opcode) in mappings:
            mapping = mappings[str(opcode)]
            status = mapping['status']
            
            if status == "changed":
                new_value = mapping['new_value']
                old_name = mapping['old_names'][0] if mapping['old_names'] else f"opcode_{opcode}"
                new_name = mapping['new_names'][0] if mapping['new_names'] else f"opcode_{new_value}"
                
                # Check if target opcode exists in target scan
                target_count = target_base_usage.get(str(new_value), 0)
                
                candidate = {
                    "old_opcode": opcode,
                    "new_opcode": new_value,
                    "old_name": old_name,
                    "new_name": new_name,
                    "rtw_occurrences": count,
                    "target_occurrences": target_count,
                    "status": "needs_conversion"
                }
                candidates["candidates"].append(candidate)
                print(f"Candidate: {opcode} ({old_name}) -> {new_value} ({new_name})")
                print(f"  RTW occurrences: {count}")
                print(f"  Target occurrences: {target_count}")
    
    # Save conversion candidates
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(candidates, f, indent=2, ensure_ascii=False)
    
    print(f"\nConversion candidates generated: {len(candidates['candidates'])}")
    print(f"Output saved to: {output_path}")
    
    return candidates


def verify_candidates(candidates_path, scan_results_path, target_scan_path):
    """Verify conversion candidates."""
    
    with open(candidates_path, 'r', encoding='utf-8') as f:
        candidates = json.load(f)
    
    with open(scan_results_path, 'r', encoding='utf-8') as f:
        scan_results = json.load(f)
    
    with open(target_scan_path, 'r', encoding='utf-8') as f:
        target_scan = json.load(f)
    
    base_usage = scan_results.get('base_usage', {})
    target_base_usage = target_scan.get('base_usage', {})
    
    print("\n=== VERIFICATION ===")
    all_passed = True
    
    for candidate in candidates["candidates"]:
        old_opcode = candidate["old_opcode"]
        new_opcode = candidate["new_opcode"]
        rtw_count = candidate["rtw_occurrences"]
        target_count = candidate["target_occurrences"]
        
        # Verify 1: Change list - old opcode exists in RTW scan
        actual_rtw_count = base_usage.get(str(old_opcode), 0)
        if actual_rtw_count != rtw_count:
            print(f"FAIL: {old_opcode} count mismatch - expected {rtw_count}, got {actual_rtw_count}")
            all_passed = False
        else:
            print(f"PASS: {old_opcode} count verified ({rtw_count})")
        
        # Verify 2: Round-trip - new opcode exists in target scan
        actual_target_count = target_base_usage.get(str(new_opcode), 0)
        if actual_target_count != target_count:
            print(f"FAIL: {new_opcode} target count mismatch - expected {target_count}, got {actual_target_count}")
            all_passed = False
        else:
            print(f"PASS: {new_opcode} target count verified ({target_count})")
        
        # Verify 3: Target scan - new opcode is actually used in Warband
        if actual_target_count == 0:
            print(f"WARN: {new_opcode} not used in target (Warband 1.174) - may be unused in native but needed for RTW")
        else:
            print(f"PASS: {new_opcode} is used in target ({actual_target_count} times)")
    
    print(f"\nVerification {'PASSED' if all_passed else 'FAILED'}")
    return all_passed


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("Usage: python tools/generate_conversion_candidates.py <scan_results.json> <identification_table.json> <target_scan.json> <output_candidates.json>")
        sys.exit(1)
    
    scan_results_path = sys.argv[1]
    identification_table_path = sys.argv[2]
    target_scan_path = sys.argv[3]
    output_path = sys.argv[4]
    
    candidates = generate_conversion_candidates(
        scan_results_path,
        identification_table_path,
        target_scan_path,
        output_path
    )
    
    verify_candidates(output_path, scan_results_path, target_scan_path)