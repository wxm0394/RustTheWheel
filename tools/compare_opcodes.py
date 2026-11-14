#!/usr/bin/env python3
import ast
import csv
import hashlib
import os
import re
import sys
import tempfile

# Constants for bitwise operations
NEG_FLAG = 0x80000000
THIS_OR_NEXT_FLAG = 0x40000000

# Cross-version name mapping for mission_cam_*_aperture opcodes
MISSION_CAM_APERTURE_MAPPING = {
    "mission_cam_set_aperture": "mission_cam_set_fov",
    "mission_cam_get_aperture": "mission_cam_get_fov",
    "mission_cam_animate_to_aperture": "mission_cam_animate_to_fov",
    "mission_cam_set_aperture_instant": "mission_cam_set_fov_instant",
}

def calculate_sha256(filepath):
    """Calculates the SHA256 hash of a file."""
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()

class ExpressionEvaluator(ast.NodeVisitor):
    """
    Evaluates a Python abstract syntax tree (AST) node to a constant value.
    Supports constants, names (variables), binary operations, and unary operations.
    Rejects unsupported node types with explicit errors.
    """
    def __init__(self, constants):
        self.constants = constants
        self.evaluated_value = None

    def evaluate(self, node):
        self.visit(node)
        return self.evaluated_value

    def _require_value(self, value, message):
        if value is None:
            raise ValueError(message)
        return value

    def visit_Constant(self, node):
        self.evaluated_value = node.value

    def visit_Name(self, node):
        if node.id in self.constants:
            self.evaluated_value = self.constants[node.id]
        else:
            raise NameError(f"Undefined constant: {node.id}")

    # Reject unsupported AST node types
    def visit_Call(self, node):
        raise TypeError(f"Unsupported AST node: function call ({node.func.id if hasattr(node.func, 'id') else node.func})")

    def visit_Attribute(self, node):
        raise TypeError(f"Unsupported AST node: attribute access ({node.attr})")

    def visit_Subscript(self, node):
        raise TypeError(f"Unsupported AST node: subscript ({node.slice})")

    def visit_IfExp(self, node):  # Ternary expression
        raise TypeError("Unsupported AST node: ternary expression")

    def generic_visit(self, node):
        raise TypeError(f"Unsupported AST node: {type(node).__name__}")

    def visit_BinOp(self, node):
        left_evaluator = ExpressionEvaluator(self.constants)
        left_value = left_evaluator.evaluate(node.left)
        left_value = self._require_value(left_value, "Left operand could not be evaluated")

        right_evaluator = ExpressionEvaluator(self.constants)
        right_value = right_evaluator.evaluate(node.right)
        right_value = self._require_value(right_value, "Right operand could not be evaluated")

        if isinstance(node.op, ast.Add):
            self.evaluated_value = left_value + right_value
        elif isinstance(node.op, ast.Sub):
            self.evaluated_value = left_value - right_value
        elif isinstance(node.op, ast.Mult):
            self.evaluated_value = left_value * right_value
        elif isinstance(node.op, ast.Div):
            self.evaluated_value = left_value / right_value
        elif isinstance(node.op, ast.Mod):
            self.evaluated_value = left_value % right_value
        elif isinstance(node.op, ast.LShift):
            self.evaluated_value = left_value << right_value
        elif isinstance(node.op, ast.RShift):
            self.evaluated_value = left_value >> right_value
        elif isinstance(node.op, ast.BitOr):
            self.evaluated_value = left_value | right_value
        elif isinstance(node.op, ast.BitAnd):
            self.evaluated_value = left_value & right_value
        elif isinstance(node.op, ast.BitXor):
            self.evaluated_value = left_value ^ right_value
        else:
            raise TypeError(f"Unsupported binary operator: {type(node.op).__name__}")

    def visit_UnaryOp(self, node):
        operand_evaluator = ExpressionEvaluator(self.constants)
        operand_value = operand_evaluator.evaluate(node.operand)
        operand_value = self._require_value(operand_value, "Operand could not be evaluated")

        if isinstance(node.op, ast.USub):
            self.evaluated_value = -operand_value
        elif isinstance(node.op, ast.UAdd):
            self.evaluated_value = +operand_value
        elif isinstance(node.op, ast.Invert): # Bitwise NOT (~)
            self.evaluated_value = ~operand_value
        else:
            raise TypeError(f"Unsupported unary operator: {type(node.op).__name__}")

def evaluate_expression(expression_str, known_constants, filepath, line_num):
    """Evaluates a Python expression string using AST."""
    try:
        node = ast.parse(expression_str, mode='eval')
        evaluator = ExpressionEvaluator(known_constants)
        return evaluator.evaluate(node.body)
    except (ValueError, TypeError, NameError) as e:
        return f"ERROR: {e} in {filepath}:{line_num} - '{expression_str}'"
    except Exception as e:
        return f"UNEXPECTED ERROR: {e} in {filepath}:{line_num} - '{expression_str}'"

def _strip_inline_comment(line):
    """Strips inline comments from a line of code."""
    comment_start = line.find("#")
    if comment_start != -1:
        return line[:comment_start].strip()
    return line.strip()

def _is_list_only_expression(expression_str):
    """
    Checks if an expression is likely a list definition, not an opcode assignment.
    This is a heuristic to distinguish `x = [1, 2, 3]` from `x = 1 | 2`.
    """
    return expression_str.strip().startswith('[') and expression_str.strip().endswith(']')

def parse_opcodes(filepath):
    """
    Parses opcode definitions from a header_operations.py file using AST.
    Extracts opcode names, values, and identifies list groupings.
    Tracks duplicates and categorizes definitions.
    """
    opcodes = {}
    list_groupings = {}
    known_constants = {
        "neg": NEG_FLAG,
        "this_or_next": THIS_OR_NEXT_FLAG,
        # Add other common constants if necessary, e.g., from header_common.py
    }
    
    # Track duplicates and categorize definitions
    duplicates = []
    categories = {
        "opcode": [],
        "constant": [],
        "list_grouping": [],
        "unparseable": [],
    }

    with open(filepath, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=filepath)

    for node in tree.body:
        if isinstance(node, ast.Assign):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                var_name = node.targets[0].id
                
                # Check if it's a list grouping
                if isinstance(node.value, (ast.List, ast.Tuple)):
                    members = _extract_list_members(node.value, known_constants)
                    list_groupings[var_name] = {
                        "name": var_name,
                        "members": members,
                        "line": node.lineno,
                        "raw_expression": ast.unparse(node.value).strip()
                    }
                    categories["list_grouping"].append(var_name)
                    continue # Skip to next node, as this is a list grouping

                # Otherwise, it's an opcode or constant assignment
                try:
                    # Attempt to evaluate the expression
                    evaluator = ExpressionEvaluator(known_constants)
                    value = evaluator.evaluate(node.value)
                    
                    if isinstance(value, (int, float)): # Only store numeric values as opcodes/constants
                        # Check for duplicate definition
                        if var_name in known_constants:
                            duplicates.append({
                                "name": var_name,
                                "old_value": known_constants[var_name],
                                "new_value": value,
                                "line": node.lineno,
                                "raw_expression": ast.unparse(node.value).strip()
                            })
                        
                        known_constants[var_name] = value
                        
                        # Categorize: if value is a known flag or used in bitwise ops, it's a constant
                        # Otherwise it's an opcode. Heuristic: if name starts with known opcode prefixes
                        is_opcode = var_name.startswith(("op_", "OP_", "store_", "assign_", "set_", "get_",
                                                          "try_", "call_", "eq_", "neq_", "lt_", "gt_", "le_", "ge_",
                                                          "add_", "sub_", "mul_", "div_", "mod_", "val_", "str_",
                                                          "troop_", "party_", "agent_", "item_", "scene_", "mission_",
                                                          "faction_", "quest_", "menu_", "dialog_", "presentation_",
                                                          "animation_", "sound_", "mesh_", "texture_", "material_",
                                                          "prop_", "trigger_", "script_", "global_", "local_",
                                                          "position_", "rotation_", "scale_", "color_", "overlay_",
                                                          "map_", "ai_", "formation_", "camera_", "cam_", "mission_cam_"))
                        # Also recognize bare condition/control-flow names (no prefix) that are opcodes
                        bare_opcode_names = {
                            "eq", "neq", "lt", "gt", "le", "ge", "is_between",
                            "else_try", "else_try_begin", "end_try", "try_end", "try_begin", "try_for_range", "try_for_range_backwards",
                            "try_for_parties", "try_for_agents", "try_for_prop_instances",
                            "call_script", "store_script_param", "store_script_param_1", "store_script_param_2",
                            "entering_town", "encountered_party_is_attacker", "conversation_screen_is_active",
                            "in_meta_mission", "key_is_down", "key_clicked", "game_key_is_down", "game_key_clicked",
                            "mouse_get_position", "hero_can_join", "hero_can_join_as_prisoner",
                            "troops_can_join", "troops_can_join_as_prisoner", "main_party_has_troop",
                            "player_has_item", "check_quest_active", "check_quest_finished", "check_quest_succeeded",
                            "check_quest_failed", "check_quest_concluded", "play_sound", "play_track",
                            "play_cue_track", "music_set_situation", "music_set_culture", "stop_all_sounds",
                            "copy_position", "init_position", "start_presentation", "start_background_presentation",
                            "create_text_overlay", "create_mesh_overlay", "create_button_overlay",
                            "create_image_button_overlay", "create_slider_overlay", "create_progress_overlay",
                            "create_combo_button_overlay", "create_text_box_overlay", "create_check_box_overlay",
                            "create_image_button_overlay_with_tableau_material", "create_mesh_overlay_with_tableau_material",
                            "create_game_button_overlay", "context_menu_add_item", "all_enemies_defeated",
                            "race_completed_by_player", "num_active_teams_le", "main_hero_fallen",
                            "start_map_conversation", "rest_for_hours", "rest_for_hours_interactive",
                            "spawn_around_party", "display_log_message", "display_message", "tutorial_box",
                            "question_box", "tutorial_message", "reset_price_rates", "remove_member_from_party",
                            "remove_regular_prisoners", "remove_troops_from_companions", "remove_troops_from_prisoners",
                            "heal_party", "disable_party", "enable_party", "remove_party", "remove_troop_from_site",
                            "modify_visitors_at_site", "reset_visitors",
                        }
                        if var_name in bare_opcode_names:
                            is_opcode = True
                        
                        if is_opcode:
                            categories["opcode"].append(var_name)
                        else:
                            categories["constant"].append(var_name)
                        
                        opcodes[var_name] = {
                            "name": var_name,
                            "value": value,
                            "line": node.lineno,
                            "raw_expression": ast.unparse(node.value).strip(),
                            "category": "opcode" if is_opcode else "constant"
                        }
                except (ValueError, TypeError, NameError) as e:
                    # Store unparseable expressions for reporting
                    opcodes[var_name] = {
                        "name": var_name,
                        "value": f"UNPARSEABLE: {e}",
                        "line": node.lineno,
                        "raw_expression": ast.unparse(node.value).strip(),
                        "category": "unparseable"
                    }
                    categories["unparseable"].append(var_name)
                except Exception as e:
                    opcodes[var_name] = {
                        "name": var_name,
                        "value": f"UNEXPECTED ERROR: {e}",
                        "line": node.lineno,
                        "raw_expression": ast.unparse(node.value).strip(),
                        "category": "unparseable"
                    }
                    categories["unparseable"].append(var_name)
    
    return opcodes, list_groupings, known_constants, duplicates, categories

def _extract_list_members(node, constants):
    """Recursively extracts members from AST List/Tuple nodes."""
    members = []
    for element in node.elts:
        if isinstance(element, (ast.List, ast.Tuple)):
            members.extend(_extract_list_members(element, constants))
        else:
            try:
                evaluator = ExpressionEvaluator(constants)
                value = evaluator.evaluate(element)
                members.append(value)
            except Exception as e:
                members.append(f"UNPARSEABLE_MEMBER: {ast.unparse(element).strip()} ({e})")
    return members

def compare_opcodes(old_opcodes_data, new_opcodes_data):
    """Compares two sets of opcode data and returns a detailed comparison."""
    comparison_results = {
        "added": [],
        "removed": [],
        "changed": [],
        "same": [],
        "aliases": [],
        "duplicates": [],
        "unparseable_old": [],
        "unparseable_new": [],
    }

    old_names = set(old_opcodes_data.keys())
    new_names = set(new_opcodes_data.keys())

    # Identify unparseable opcodes
    for name, data in old_opcodes_data.items():
        if isinstance(data["value"], str) and data["value"].startswith("UNPARSEABLE"):
            comparison_results["unparseable_old"].append(data)
    for name, data in new_opcodes_data.items():
        if isinstance(data["value"], str) and data["value"].startswith("UNPARSEABLE"):
            comparison_results["unparseable_new"].append(data)

    # Compare opcodes that exist in both versions
    for name in old_names.intersection(new_names):
        old_opcode = old_opcodes_data[name]
        new_opcode = new_opcodes_data[name]

        # Skip if either is unparseable
        if isinstance(old_opcode["value"], str) or isinstance(new_opcode["value"], str):
            continue

        if old_opcode["value"] == new_opcode["value"]:
            comparison_results["same"].append({
                "name": name,
                "value": old_opcode["value"],
                "old_line": old_opcode["line"],
                "new_line": new_opcode["line"],
            })
        else:
            comparison_results["changed"].append({
                "name": name,
                "old_value": old_opcode["value"],
                "new_value": new_opcode["value"],
                "old_line": old_opcode["line"],
                "new_line": new_opcode["line"],
                "old_raw": old_opcode["raw_expression"],
                "new_raw": new_opcode["raw_expression"],
            })

    # Identify added opcodes
    for name in new_names - old_names:
        new_opcode = new_opcodes_data[name]
        if not (isinstance(new_opcode["value"], str) and new_opcode["value"].startswith("UNPARSEABLE")):
            comparison_results["added"].append({
                "name": name,
                "value": new_opcode["value"],
                "new_line": new_opcode["line"],
                "new_raw": new_opcode["raw_expression"],
            })

    # Identify removed opcodes
    for name in old_names - new_names:
        old_opcode = old_opcodes_data[name]
        if not (isinstance(old_opcode["value"], str) and old_opcode["value"].startswith("UNPARSEABLE")):
            comparison_results["removed"].append({
                "name": name,
                "value": old_opcode["value"],
                "old_line": old_opcode["line"],
                "old_raw": old_opcode["raw_expression"],
            })

    # Identify aliases (same value, different name)
    new_value_to_names = {}
    for name, data in new_opcodes_data.items():
        if not (isinstance(data["value"], str) and data["value"].startswith("UNPARSEABLE")):
            new_value_to_names.setdefault(data["value"], []).append(name)

    for value, names in new_value_to_names.items():
        if len(names) > 1:
            comparison_results["aliases"].append({
                "value": value,
                "names": sorted(names)
            })

    # Identify duplicates (same name, different value - already covered by 'changed' if both exist)
    # This section would typically be for cases where a name might appear multiple times in a single file,
    # but our parsing extracts the last assignment, so this is less relevant here.
    # However, if we consider "duplicates" as names that exist in both but with different values,
    # then the "changed" category already covers this.

    return comparison_results

def generate_csv(comparison_results, output_path):
    """Generates a CSV report of the opcode comparison."""
    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["Category", "Name", "Old Value", "New Value", "Old Line", "New Line", "Old Raw", "New Raw", "Notes"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for item in comparison_results["changed"]:
            writer.writerow({
                "Category": "Changed",
                "Name": item["name"],
                "Old Value": item["old_value"],
                "New Value": item["new_value"],
                "Old Line": item["old_line"],
                "New Line": item["new_line"],
                "Old Raw": item["old_raw"],
                "New Raw": item["new_raw"],
                "Notes": "",
            })
        for item in comparison_results["added"]:
            writer.writerow({
                "Category": "Added",
                "Name": item["name"],
                "New Value": item["value"],
                "New Line": item["new_line"],
                "New Raw": item["new_raw"],
                "Notes": "",
            })
        for item in comparison_results["removed"]:
            writer.writerow({
                "Category": "Removed",
                "Name": item["name"],
                "Old Value": item["value"],
                "Old Line": item["old_line"],
                "Old Raw": item["old_raw"],
                "Notes": "",
            })
        for item in comparison_results["same"]:
            writer.writerow({
                "Category": "Same",
                "Name": item["name"],
                "Old Value": item["value"],
                "New Value": item["value"],
                "Old Line": item["old_line"],
                "New Line": item["new_line"],
                "Notes": "",
            })
        for item in comparison_results["unparseable_old"]:
            writer.writerow({
                "Category": "Unparseable (Old)",
                "Name": item["name"],
                "Old Value": item["value"],
                "Old Line": item["line"],
                "Old Raw": item["raw_expression"],
                "Notes": "Expression could not be parsed/evaluated",
            })
        for item in comparison_results["unparseable_new"]:
            writer.writerow({
                "Category": "Unparseable (New)",
                "Name": item["name"],
                "New Value": item["value"],
                "New Line": item["line"],
                "New Raw": item["raw_expression"],
                "Notes": "Expression could not be parsed/evaluated",
            })
        for item in comparison_results["aliases"]:
            writer.writerow({
                "Category": "Alias",
                "Name": ", ".join(item["names"]),
                "New Value": item["value"],
                "Notes": "Multiple names map to the same value in the new version",
            })

def generate_markdown_report(comparison_results, old_filepath, new_filepath, output_path, old_sha, new_sha, old_list_groupings, new_list_groupings, old_opcodes_data, new_opcodes_data):
    """Generates a Markdown report of the opcode comparison."""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# Mount & Blade Opcode Comparison Report\n\n")
        f.write("This report compares opcode definitions between two `header_operations.py` files.\n\n")

        f.write("## Input Files\n")
        f.write(f"- **Old File:** [`{old_filepath}`]({old_filepath})\n")
        f.write(f"  - SHA256: `{old_sha}`\n")
        f.write(f"- **New File:** [`{new_filepath}`]({new_filepath})\n")
        f.write(f"  - SHA256: `{new_sha}`\n\n")

        f.write("## Summary\n")
        f.write(f"- Total Opcodes (Old): {len(old_opcodes_data)}\n")
        f.write(f"- Total Opcodes (New): {len(new_opcodes_data)}\n")
        f.write(f"- Opcodes Added: {len(comparison_results['added'])}\n")
        f.write(f"- Opcodes Removed: {len(comparison_results['removed'])}\n")
        f.write(f"- Opcodes Changed: {len(comparison_results['changed'])}\n")
        f.write(f"- Opcodes Unchanged: {len(comparison_results['same'])}\n")
        f.write(f"- Aliases (same value, different name in new): {len(comparison_results['aliases'])}\n")
        f.write(f"- Unparseable Opcodes (Old): {len(comparison_results['unparseable_old'])}\n")
        f.write(f"- Unparseable Opcodes (New): {len(comparison_results['unparseable_new'])}\n\n")

        f.write("## Detailed Comparison\n\n")

        if comparison_results["changed"]:
            f.write("### Changed Opcodes\n")
            f.write("| Name | Old Value | New Value | Old Line | New Line | Old Raw Expression | New Raw Expression |\n")
            f.write("|---|---|---|---|---|---|---|\n")
            for item in comparison_results["changed"]:
                f.write(f"| {item['name']} | {item['old_value']} | {item['new_value']} | {item['old_line']} | {item['new_line']} | `{item['old_raw']}` | `{item['new_raw']}` |\n")
            f.write("\n")

        if comparison_results["added"]:
            f.write("### Added Opcodes\n")
            f.write("| Name | Value | Line | Raw Expression |\n")
            f.write("|---|---|---|---|\n")
            for item in comparison_results["added"]:
                f.write(f"| {item['name']} | {item['value']} | {item['new_line']} | `{item['new_raw']}` |\n")
            f.write("\n")

        if comparison_results["removed"]:
            f.write("### Removed Opcodes\n")
            f.write("| Name | Value | Line | Raw Expression |\n")
            f.write("|---|---|---|---|\n")
            for item in comparison_results["removed"]:
                f.write(f"| {item['name']} | {item['value']} | {item['old_line']} | `{item['old_raw']}` |\n")
            f.write("\n")

        if comparison_results["aliases"]:
            f.write("### Aliases (Same Value, Different Name in New Version)\n")
            f.write("| Value | Names |\n")
            f.write("|---|---|\n")
            for item in comparison_results["aliases"]:
                f.write(f"| {item['value']} | {', '.join(item['names'])} |\n")
            f.write("\n")

        if comparison_results["unparseable_old"]:
            f.write("### Unparseable Opcodes (Old File)\n")
            f.write("| Name | Raw Expression | Line | Error |\n")
            f.write("|---|---|---|---|\n")
            for item in comparison_results["unparseable_old"]:
                f.write(f"| {item['name']} | `{item['raw_expression']}` | {item['line']} | {item['value']} |\n")
            f.write("\n")

        if comparison_results["unparseable_new"]:
            f.write("### Unparseable Opcodes (New File)\n")
            f.write("| Name | Raw Expression | Line | Error |\n")
            f.write("|---|---|---|---|\n")
            for item in comparison_results["unparseable_new"]:
                f.write(f"| {item['name']} | `{item['raw_expression']}` | {item['line']} | {item['value']} |\n")
            f.write("\n")

        if old_list_groupings or new_list_groupings:
            f.write("## List Groupings Comparison\n\n")
            f.write("These are variables assigned to lists, often used for grouping related opcodes or flags.\n\n")

            all_list_grouping_names = sorted(list(set(old_list_groupings.keys()) | set(new_list_groupings.keys())))

            for name in all_list_grouping_names:
                old_group = old_list_groupings.get(name)
                new_group = new_list_groupings.get(name)

                f.write(f"### `{name}`\n")
                if old_group and new_group:
                    if old_group["members"] == new_group["members"]:
                        f.write(f"- Status: Unchanged\n")
                        f.write(f"  - Members: `{old_group['raw_expression']}`\n")
                    else:
                        f.write(f"- Status: Changed\n")
                        f.write(f"  - Old Members: `{old_group['raw_expression']}` (Line: {old_group['line']})\n")
                        f.write(f"  - New Members: `{new_group['raw_expression']}` (Line: {new_group['line']})\n")
                        # Detailed diff for members could be added here if needed
                elif old_group:
                    f.write(f"- Status: Removed\n")
                    f.write(f"  - Old Members: `{old_group['raw_expression']}` (Line: {old_group['line']})\n")
                elif new_group:
                    f.write(f"- Status: Added\n")
                    f.write(f"  - New Members: `{new_group['raw_expression']}` (Line: {new_group['line']})\n")
                f.write("\n")


def main():
    run_tests()  # Run tests before main logic
    if len(sys.argv) != 3:
        print("Usage: python3 compare_opcodes.py <old_header_operations.py> <new_header_operations.py>")
        sys.exit(1)

    old_filepath = sys.argv[1]
    new_filepath = sys.argv[2]

    if not os.path.exists(old_filepath):
        print(f"Error: Old file not found at {old_filepath}")
        sys.exit(1)
    if not os.path.exists(new_filepath):
        print(f"Error: New file not found at {new_filepath}")
        sys.exit(1)

    print(f"Parsing old opcodes from {old_filepath}...")
    old_opcodes_data, old_list_groupings, old_known_constants, old_duplicates, old_categories = parse_opcodes(old_filepath)
    print(f"Found {len(old_opcodes_data)} opcodes and {len(old_list_groupings)} list groupings in old file.")

    print(f"Parsing new opcodes from {new_filepath}...")
    new_opcodes_data, new_list_groupings, new_known_constants, new_duplicates, new_categories = parse_opcodes(new_filepath)
    print(f"Found {len(new_opcodes_data)} opcodes and {len(new_list_groupings)} list groupings in new file.")

    print("Comparing opcodes...")
    comparison_results = compare_opcodes(old_opcodes_data, new_opcodes_data)

    output_dir = "docs"
    os.makedirs(output_dir, exist_ok=True)

    csv_output_path = os.path.join(output_dir, "opcodes_comparison.csv")
    print(f"Generating CSV report to {csv_output_path}...")
    generate_csv(comparison_results, csv_output_path)

    markdown_output_path = os.path.join(output_dir, "opcodes_comparison_report.md")
    print(f"Generating Markdown report to {markdown_output_path}...")
    old_sha = calculate_sha256(old_filepath)
    new_sha = calculate_sha256(new_filepath)
    generate_markdown_report(comparison_results, old_filepath, new_filepath, markdown_output_path, old_sha, new_sha, old_list_groupings, new_list_groupings, old_opcodes_data, new_opcodes_data)

    print("Comparison complete.")

def run_tests():
    """
    Runs a series of tests to validate the ExpressionEvaluator and parse_opcodes functions.
    """
    print("Running AST parser validation tests...")

    # Test 1: Basic integer and hex parsing
    assert evaluate_expression("123", {}, "", 0) == 123, "Test 1 Failed: Basic integer"
    assert evaluate_expression("0xFF", {}, "", 0) == 255, "Test 1 Failed: Hex integer"
    assert evaluate_expression("0o77", {}, "", 0) == 63, "Test 1 Failed: Octal integer"
    assert evaluate_expression("0b101", {}, "", 0) == 5, "Test 1 Failed: Binary integer"

    # Test 2: Constant evaluation
    constants = {"MY_CONST": 100}
    assert evaluate_expression("MY_CONST", constants, "", 0) == 100, "Test 2 Failed: Custom constant"
    assert evaluate_expression("NEG_FLAG", {"NEG_FLAG": NEG_FLAG}, "", 0) == NEG_FLAG, "Test 2 Failed: NEG_FLAG"
    assert evaluate_expression("THIS_OR_NEXT_FLAG", {"THIS_OR_NEXT_FLAG": THIS_OR_NEXT_FLAG}, "", 0) == THIS_OR_NEXT_FLAG, "Test 2 Failed: THIS_OR_NEXT_FLAG"

    # Test 3: Binary operations
    assert evaluate_expression("10 + 5", {}, "", 0) == 15, "Test 3 Failed: Addition"
    assert evaluate_expression("10 - 5", {}, "", 0) == 5, "Test 3 Failed: Subtraction"
    assert evaluate_expression("10 * 5", {}, "", 0) == 50, "Test 3 Failed: Multiplication"
    assert evaluate_expression("10 / 5", {}, "", 0) == 2.0, "Test 3 Failed: Division"
    assert evaluate_expression("10 % 3", {}, "", 0) == 1, "Test 3 Failed: Modulo"
    assert evaluate_expression("1 << 2", {}, "", 0) == 4, "Test 3 Failed: Left Shift"
    assert evaluate_expression("4 >> 2", {}, "", 0) == 1, "Test 3 Failed: Right Shift"
    assert evaluate_expression("5 | 2", {}, "", 0) == 7, "Test 3 Failed: Bitwise OR" # 101 | 010 = 111
    assert evaluate_expression("5 & 3", {}, "", 0) == 1, "Test 3 Failed: Bitwise AND" # 101 & 011 = 001
    assert evaluate_expression("5 ^ 3", {}, "", 0) == 6, "Test 3 Failed: Bitwise XOR" # 101 ^ 011 = 110

    # Test 4: Unary operations
    assert evaluate_expression("-10", {}, "", 0) == -10, "Test 4 Failed: Unary Negation"
    assert evaluate_expression("~10", {}, "", 0) == -11, "Test 4 Failed: Bitwise NOT"

    # Test 5: Combined operations and constants
    constants_combined = {"A": 5, "B": 3, "NEG_FLAG": NEG_FLAG}
    assert evaluate_expression("A + B * 2", constants_combined, "", 0) == 11, "Test 5 Failed: Combined 1"
    assert evaluate_expression("NEG_FLAG | 100", constants_combined, "", 0) == (NEG_FLAG | 100), "Test 5 Failed: Combined 2"
    assert evaluate_expression("-(A + B)", constants_combined, "", 0) == -8, "Test 5 Failed: Combined 3"

    # Test 6: Unparseable expressions (should return error string)
    assert "ERROR" in evaluate_expression("10 + X", {}, "", 0), "Test 6 Failed: Undefined variable"
    assert "ERROR" in evaluate_expression("10 +", {}, "", 0), "Test 6 Failed: Syntax error"

    # Test 7: parse_opcodes - basic assignments
    test_content_basic = """
OP_A = 1
OP_B = 0x10
OP_C = OP_A + 5
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file_path = os.path.join(tmpdir, "test_header_operations_basic.py")
        with open(test_file_path, "w") as f:
            f.write(test_content_basic)
        opcodes, list_groupings, _, _, _ = parse_opcodes(test_file_path)
        assert opcodes["OP_A"]["value"] == 1, "Test 7 Failed: OP_A value"
        assert opcodes["OP_B"]["value"] == 16, "Test 7 Failed: OP_B value"
        assert opcodes["OP_C"]["value"] == 6, "Test 7 Failed: OP_C value"
        assert len(list_groupings) == 0, "Test 7 Failed: No list groupings expected"

        # Test 8: parse_opcodes - list groupings
        test_content_lists = """
OP_D = 10
MY_LIST = [1, 2, 3]
ANOTHER_LIST = [OP_D, 5]
"""
        test_file_path = os.path.join(tmpdir, "test_header_operations_lists.py")
        with open(test_file_path, "w") as f:
            f.write(test_content_lists)
        opcodes, list_groupings, _, _, _ = parse_opcodes(test_file_path)
        assert "MY_LIST" in list_groupings, "Test 8 Failed: MY_LIST not found"
        assert list_groupings["MY_LIST"]["members"] == [1, 2, 3], "Test 8 Failed: MY_LIST members"
        assert "ANOTHER_LIST" in list_groupings, "Test 8 Failed: ANOTHER_LIST not found"
        assert list_groupings["ANOTHER_LIST"]["members"] == [10, 5], "Test 8 Failed: ANOTHER_LIST members"
        assert opcodes["OP_D"]["value"] == 10, "Test 8 Failed: OP_D value"

        # Test 9: parse_opcodes - mixed content and unparseable
        test_content_mixed = f"""
CONST_A = 10
OP_X = CONST_A + 5
OP_Y = CONST_A | neg
UNPARSEABLE_OP = CONST_A + UNDEFINED_VAR
MY_GROUP = [OP_X, OP_Y]
"""
        test_file_path = os.path.join(tmpdir, "test_header_operations_mixed.py")
        with open(test_file_path, "w") as f:
            f.write(test_content_mixed)
        opcodes, list_groupings, _, _, _ = parse_opcodes(test_file_path)
        assert opcodes["OP_X"]["value"] == 15, "Test 9 Failed: OP_X value"
        assert opcodes["OP_Y"]["value"] == (10 | NEG_FLAG), "Test 9 Failed: OP_Y value"
        assert "UNPARSEABLE" in opcodes["UNPARSEABLE_OP"]["value"], "Test 9 Failed: Unparseable op"
        assert "MY_GROUP" in list_groupings, "Test 9 Failed: MY_GROUP not found"
        assert list_groupings["MY_GROUP"]["members"] == [15, (10 | NEG_FLAG)], "Test 9 Failed: MY_GROUP members"

        # Test 10: Nested lists and tuples in list groupings
        test_content_nested_lists = """
NESTED_LIST = [1, [2, 3], (4, 5)]
"""
        test_file_path = os.path.join(tmpdir, "test_header_operations_nested.py")
        with open(test_file_path, "w") as f:
            f.write(test_content_nested_lists)
        opcodes, list_groupings, _, _, _ = parse_opcodes(test_file_path)
        assert "NESTED_LIST" in list_groupings, "Test 10 Failed: NESTED_LIST not found"
        assert list_groupings["NESTED_LIST"]["members"] == [1, 2, 3, 4, 5], "Test 10 Failed: NESTED_LIST members"

    print("All AST parser validation tests passed!")

if __name__ == "__main__":
    main()

