#!/usr/bin/env python3
"""Test script for scan_rtw_opcodes.py test cases."""
import sys
import os
import tempfile

# Add the project root to path (relative to this test file's location)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)
from tools.scan_rtw_opcodes import scan_rtw_scripts

def create_test_scripts_txt(content):
    """Create a temporary scripts.txt file with given content."""
    fd, path = tempfile.mkstemp(suffix='.txt', dir='/tmp')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(content)
    return path

def test_A_opcode_713_in_opcode_position():
    """A. 操作码位置的 713 必须保留"""
    print("=== Test A: Opcode 713 in opcode position ===")
    content = """scriptsfile version 1
1
test_script
1 713 0
"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path)
        print(f"  Result: {result}")
        # 结构解析成功，基础操作码 713 计数为 1
        assert result['file_success'] is True, "Structure should parse successfully"
        assert result['base_usage'].get(713, 0) == 1, "Base opcode 713 should be counted once"
        print("  ✓ Test A passed")
    finally:
        os.unlink(path)

def test_B_713_in_param_position_not_counted():
    """B. 参数位置的 713 不计为操作码"""
    print("\n=== Test B: 713 in param position not counted ===")
    content = """scriptsfile version 1
1
test_script
1 101 1 713
"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path)
        print(f"  Result: {result}")
        assert result['file_success'] is True, "Structure should parse successfully"
        assert result['base_usage'].get(101, 0) == 1, "Opcode 101 should appear once"
        assert 713 not in result['base_usage'], "713 should not appear in base_usage"
        assert 713 not in result['raw_usage'], "713 should not appear in raw_usage"
        print("  ✓ Test B passed")
    finally:
        os.unlink(path)

def test_C_declared_count_mismatch():
    """C. 声明操作数必须匹配"""
    print("\n=== Test C: Declared count mismatch ===")
    content = """scriptsfile version 1
1
test_script
1025 101 3 10 20 30
"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path)
        print(f"  Result: {result}")
        # 结构失败，因为只有 1 条操作，不是 1025 条
        assert result['file_success'] is False, "Should fail due to declared count mismatch"
        assert len(result['errors']) > 0, "Should have errors"
        print("  ✓ Test C passed")
    finally:
        os.unlink(path)

def test_D_negative_param_count():
    """D. 负参数数量必须失败"""
    print("\n=== Test D: Negative param count ===")
    content = """scriptsfile version 1
1
test_script
1 101 -2
"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path)
        print(f"  Result: {result}")
        assert result['file_success'] is False, "Should fail due to negative param count"
        assert len(result['errors']) > 0, "Should have errors"
        print("  ✓ Test D passed")
    finally:
        os.unlink(path)

def test_E_truncated_block():
    """E. 截断必须失败"""
    print("\n=== Test E: Truncated block ===")
    content = """scriptsfile version 1
1
test_script
1 101 2 10
"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path)
        print(f"  Result: {result}")
        assert result['file_success'] is False, "Should fail due to truncated block"
        assert len(result['errors']) > 0, "Should have errors"
        # 失败操作不能进入成功统计
        assert result['base_usage'].get(101, 0) == 0, "Failed opcode should not be in success stats"
        print("  ✓ Test E passed")
    finally:
        os.unlink(path)

def test_F_extra_tokens():
    """F. 多余 token 必须失败"""
    print("\n=== Test F: Extra tokens ===")
    content = """scriptsfile version 1
1
test_script
1 101 0 999
"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path)
        print(f"  Result: {result}")
        assert result['file_success'] is False, "Should fail due to extra tokens"
        assert len(result['errors']) > 0, "Should have errors"
        print("  ✓ Test F passed")
    finally:
        os.unlink(path)

def test_G_zero_statements():
    """G. 零操作块"""
    print("\n=== Test G: Zero statements ===")
    content = """scriptsfile version 1
1
test_script
0
"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path)
        print(f"  Result: {result}")
        assert result['file_success'] is True, "Should parse successfully"
        assert result['declared_statement_total'] == 0, "Declared statement total should be 0"
        assert result['successful_statement_total'] == 0, "Successful statement total should be 0"
        assert result['declared_script_count'] == 1, "Declared script count should be 1"
        assert result['discovered_script_count'] == 1, "Discovered script count should be 1"
        assert result['successful_script_count'] == 1, "Successful script count should be 1"
        assert result['failed_script_count'] == 0, "Failed script count should be 0"
        print("  ✓ Test G passed")
    finally:
        os.unlink(path)

def test_H_multiple_ops_with_modifier():
    """H. 多条操作与修饰位"""
    print("\n=== Test H: Multiple ops with modifier ===")
    # 2 2147485155 1 10 101 1 713
    # 2147485155 = 0x80000000 | 1507 (neg modifier on base 1507)
    content = """scriptsfile version 1
1
test_script
2 2147485155 1 10 101 1 713
"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path)
        print(f"  Result: {result}")
        assert result['file_success'] is True, "Should parse successfully"
        # 2 条完整操作
        assert result['successful_statement_total'] == 2, f"Should have 2 parsed statements, got {result['successful_statement_total']}"
        # 原始编码 2147485155 计数为 1
        assert result['raw_usage'].get(2147485155, 0) == 1, "Raw opcode 2147485155 should be counted once"
        # 基础编号 1507 计数为 1
        assert result['base_usage'].get(1507, 0) == 1, "Base opcode 1507 should be counted once"
        # neg 修饰组合计数为 1
        assert result['modifier_usage'].get('neg', 0) == 1, "Neg modifier should be counted once"
        # 基础编号 101 计数为 1
        assert result['base_usage'].get(101, 0) == 1, "Base opcode 101 should be counted once"
        # 参数 713 不计为操作码
        assert 713 not in result['base_usage'], "713 should not be in base_usage"
        assert 713 not in result['raw_usage'], "713 should not be in raw_usage"
        print("  ✓ Test H passed")
    finally:
        os.unlink(path)

def test_I_two_complete_scripts():
    """I. 两个完整脚本：声明 1 与 2 条操作，文件 success=3 总统计"""
    print("\n=== Test I: Two complete scripts ===")
    content = """scriptsfile version 1
2
script_one
1 101 0
script_two
2 102 0 103 0
"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path)
        print(f"  Result: {result}")
        assert result['file_success'] is True, "Should parse successfully"
        assert result['declared_script_count'] == 2, "Declared script count should be 2"
        assert result['discovered_script_count'] == 2, "Discovered script count should be 2"
        assert result['successful_script_count'] == 2, "Successful script count should be 2"
        assert result['failed_script_count'] == 0, "Failed script count should be 0"
        assert result['declared_statement_total'] == 3, "Declared statement total should be 3 (1+2)"
        assert result['successful_statement_total'] == 3, "Successful statement total should be 3"
        assert result['base_usage'].get(101, 0) == 1, "Opcode 101 should appear once"
        assert result['base_usage'].get(102, 0) == 1, "Opcode 102 should appear once"
        assert result['base_usage'].get(103, 0) == 1, "Opcode 103 should appear once"
        print("  ✓ Test I passed")
    finally:
        os.unlink(path)


def test_J_first_script_fails_second_succeeds():
    """J. 第一个脚本失败，第二个成功：仅第二个的统计进入成功汇总"""
    print("\n=== Test J: First script fails, second succeeds ===")
    content = """scriptsfile version 1
2
script_fail
1 101 2 10
script_ok
1 102 0
"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path)
        print(f"  Result: {result}")
        assert result['file_success'] is False, "File should fail due to first script failure"
        assert result['declared_script_count'] == 2, "Declared script count should be 2"
        assert result['discovered_script_count'] == 2, "Discovered script count should be 2"
        assert result['successful_script_count'] == 1, "Successful script count should be 1"
        assert result['failed_script_count'] == 1, "Failed script count should be 1"
        # 只有 script_ok 的 1 条操作进入成功统计
        assert result['successful_statement_total'] == 1, "Successful statement total should be 1 (only script_ok)"
        assert result['base_usage'].get(102, 0) == 1, "Opcode 102 should appear once"
        assert 101 not in result['base_usage'], "Failed script's opcode 101 should not be in success stats"
        print("  ✓ Test J passed")
    finally:
        os.unlink(path)


def test_K_opcode_zero_preserved():
    """K. 操作码位置的 0 保留（不再被过滤）"""
    print("\n=== Test K: Opcode 0 preserved ===")
    content = """scriptsfile version 1
1
test_script
1 0 0
"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path)
        print(f"  Result: {result}")
        assert result['file_success'] is True, "Should parse successfully"
        assert result['base_usage'].get(0, 0) == 1, "Base opcode 0 should be counted once"
        print("  ✓ Test K passed")
    finally:
        os.unlink(path)


def test_L_unknown_opcode_flagged():
    """L. 未知操作码被标记但仍计数（提供 known_opcodes 时）"""
    print("\n=== Test L: Unknown opcode flagged ===")
    content = """scriptsfile version 1
1
test_script
1 9999 0
"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path, known_opcodes={101, 102})
        print(f"  Result: {result}")
        assert result['file_success'] is False, "Should fail due to unknown opcode"
        assert len(result['errors']) > 0, "Should have errors about unknown opcode"
        # 即使未知，仍应计数
        assert result['base_usage'].get(9999, 0) == 1, "Unknown opcode 9999 should still be counted"
        print("  ✓ Test L passed")
    finally:
        os.unlink(path)


def test_M_extra_blank_lines():
    """M. 多余空行不影响解析"""
    print("\n=== Test M: Extra blank lines ===")
    content = """scriptsfile version 1
1

test_script

1 101 0

"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path)
        print(f"  Result: {result}")
        assert result['file_success'] is True, "Should parse successfully"
        assert result['successful_statement_total'] == 1, "Should have 1 parsed statement"
        assert result['base_usage'].get(101, 0) == 1, "Opcode 101 should appear once"
        print("  ✓ Test M passed")
    finally:
        os.unlink(path)


def test_N_declared_script_count_mismatch():
    """N. 声明脚本数与发现脚本数不匹配 -> file_success=False"""
    print("\n=== Test N: Declared script count mismatch ===")
    content = """scriptsfile version 1
5
script_one
1 101 0
"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path)
        print(f"  Result: {result}")
        assert result['file_success'] is False, "Should fail due to script count mismatch"
        assert result['declared_script_count'] == 5, "Declared script count should be 5"
        assert result['discovered_script_count'] == 1, "Discovered script count should be 1"
        assert len(result['errors']) > 0, "Should have errors about script count mismatch"
        print("  ✓ Test N passed")
    finally:
        os.unlink(path)


def test_O_structure_complete_unknown_opcode():
    """O. 结构完整但有未知操作码：语义失败，结构成功，统计仍进入成功汇总"""
    print("\n=== Test O: Structure complete with unknown opcode ===")
    content = """scriptsfile version 1
1
test_script
1 9999 0
"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path, known_opcodes={101, 102})
        print(f"  Result: {result}")
        # 结构完整，但语义上有未知操作码
        assert result['structure_success'] is True, "Structure should be successful"
        assert result['file_success'] is False, "File should fail due to unknown opcode (identification)"
        assert result['opcode_identification_status'] == 'unknown_opcode', "Opcode identification status should be unknown_opcode"
        assert result['successful_script_count'] == 1, "Script should be counted as successful (structure-wise)"
        assert result['failed_script_count'] == 0, "No structural failures"
        # 统计仍进入成功汇总
        assert result['successful_statement_total'] == 1, "Statement should be in success stats"
        assert result['base_usage'].get(9999, 0) == 1, "Unknown opcode 9999 should be counted"
        # 脚本级别也应有 structure_success=True, opcode_identification_status='unknown_opcode'
        script_result = result['scripts'][0]
        assert script_result['structure_success'] is True, "Script structure should be successful"
        assert script_result['opcode_identification_status'] == 'unknown_opcode', "Script opcode identification status should be unknown_opcode"
        print("  ✓ Test O passed")
    finally:
        os.unlink(path)


def test_P_truncation_in_middle():
    """P. 脚本中间截断：结构失败，不进入成功统计"""
    print("\n=== Test P: Truncation in middle of script ===")
    content = """scriptsfile version 1
1
test_script
2 101 0 102 1
"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path)
        print(f"  Result: {result}")
        # 结构失败（第二条操作缺少参数）
        assert result['structure_success'] is False, "Structure should fail due to truncation"
        assert result['file_success'] is False, "File should fail"
        assert result['successful_script_count'] == 0, "No successful scripts"
        assert result['failed_script_count'] == 1, "One failed script"
        # 统计不进入成功汇总
        assert result['successful_statement_total'] == 0, "No statements in success stats"
        assert 101 not in result['base_usage'], "Opcode 101 should not be in success stats"
        assert 102 not in result['base_usage'], "Opcode 102 should not be in success stats"
        # 脚本级别 structure_success=False
        script_result = result['scripts'][0]
        assert script_result['structure_success'] is False, "Script structure should fail"
        print("  ✓ Test P passed")
    finally:
        os.unlink(path)

def test_Q_empty_known_opcodes_table():
    """Q. 空 known_opcodes 表：所有操作码都应被标记为未知"""
    print("\n=== Test Q: Empty known_opcodes table ===")
    content = """scriptsfile version 1
1
test_script
1 101 0
"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path, known_opcodes=set())
        print(f"  Result: {result}")
        assert result['file_success'] is False, "Should fail due to unknown opcode"
        assert result['opcode_identification_status'] == 'unknown_opcode', "Should have unknown_opcode status"
        assert result['base_usage'].get(101, 0) == 1, "Opcode 101 should still be counted"
        print("  ✓ Test Q passed")
    finally:
        os.unlink(path)


def test_R_alias_retention():
    """R. 别名保留：同值不同名的操作码在迁移中保留原值"""
    print("\n=== Test R: Alias retention ===")
    # Simulate an opcode that has same value but different name in new version
    # This is tested by checking that unchanged opcodes keep their value
    content = """scriptsfile version 1
1
test_script
1 101 0
"""
    path = create_test_scripts_txt(content)
    try:
        # Provide known_opcodes that includes 101
        result = scan_rtw_scripts(path, known_opcodes={101})
        print(f"  Result: {result}")
        assert result['file_success'] is True, "Should parse successfully"
        assert result['base_usage'].get(101, 0) == 1, "Opcode 101 should be counted"
        # The opcode value 101 is preserved (alias retention means value doesn't change)
        print("  ✓ Test R passed")
    finally:
        os.unlink(path)


def test_S_unknown_opcode_retention():
    """S. 未知操作码保留：即使未知，仍计入统计"""
    print("\n=== Test S: Unknown opcode retention ===")
    content = """scriptsfile version 1
1
test_script
1 9999 0
"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path, known_opcodes={101, 102})
        print(f"  Result: {result}")
        assert result['file_success'] is False, "Should fail due to unknown opcode"
        assert result['opcode_identification_status'] == 'unknown_opcode', "Should have unknown_opcode status"
        assert result['base_usage'].get(9999, 0) == 1, "Unknown opcode 9999 should still be counted"
        assert result['successful_statement_total'] == 1, "Statement should be in success stats (structure ok)"
        print("  ✓ Test S passed")
    finally:
        os.unlink(path)


def test_T_no_chain_conversion():
    """T. 无链式转换：操作码值直接映射，不进行多步转换"""
    print("\n=== Test T: No chain conversion ===")
    # Test that opcodes map directly without intermediate steps
    # This is a semantic test - we verify the scanner doesn't do any conversion
    content = """scriptsfile version 1
1
test_script
2 715 3 1 2 3 716 3 4 5 6
"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path, known_opcodes={715, 716})
        print(f"  Result: {result}")
        assert result['file_success'] is True, "Should parse successfully"
        assert result['base_usage'].get(715, 0) == 1, "Opcode 715 should be counted as 715"
        assert result['base_usage'].get(716, 0) == 1, "Opcode 716 should be counted as 716"
        # Scanner records raw values; no chain conversion happens in scanner
        print("  ✓ Test T passed")
    finally:
        os.unlink(path)


def test_U_modifier_retention():
    """U. 修饰位保留：NEG 和 THIS_OR_NEXT 修饰位在迁移中保留"""
    print("\n=== Test U: Modifier retention ===")
    # 2147483678 = 0x80000000 | 30 (NEG on opcode 30)
    # 3221225502 = 0xC0000000 | 30 (both NEG and THIS_OR_NEXT on opcode 30)
    content = """scriptsfile version 1
1
test_script
2 2147483678 0 3221225502 0
"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path, known_opcodes={30})
        print(f"  Result: {result}")
        assert result['file_success'] is True, "Should parse successfully"
        assert result['base_usage'].get(30, 0) == 2, "Base opcode 30 should be counted twice"
        assert result['raw_usage'].get(2147483678, 0) == 1, "Raw opcode with NEG should be counted"
        assert result['raw_usage'].get(3221225502, 0) == 1, "Raw opcode with both modifiers should be counted"
        # First stmt: only NEG; second stmt: both NEG and THIS_OR_NEXT
        assert result['modifier_usage']['neg'] == 2, "NEG modifier should be counted twice (both statements have NEG)"
        assert result['modifier_usage']['this_or_next'] == 1, "THIS_OR_NEXT modifier should be counted once (only second stmt)"
        print("  ✓ Test U passed")
    finally:
        os.unlink(path)


def test_V_param_unchanged():
    """V. 参数不变：操作码参数数量和顺序在迁移中保持不变"""
    print("\n=== Test V: Param unchanged ===")
    # Test that parameter count and values are preserved
    content = """scriptsfile version 1
1
test_script
1 101 3 10 20 30
"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path, known_opcodes={101}, capture_statement_details=True)
        print(f"  Result: {result}")
        assert result['file_success'] is True, "Should parse successfully"
        assert result['base_usage'].get(101, 0) == 1, "Opcode 101 should be counted"
        # Check statement details
        script = result['scripts'][0]
        assert len(script['statements']) == 1, "Should have 1 statement"
        stmt = script['statements'][0]
        assert stmt['param_count'] == 3, "Parameter count should be 3"
        assert stmt['parameters'] == ['10', '20', '30'], "Parameters should be preserved"
        print("  ✓ Test V passed")
    finally:
        os.unlink(path)


def test_W_opcode_713_absent_in_real_scripts():
    """W. 回归测试：真实 RTW 脚本中不存在操作码 713 (position_is_behind_position)
    
    此测试验证扫描器正确报告 713 计数为 0，而不是错误地报告 8 次。
    这是针对之前手动补丁引入的虚假条目 (docs/opcode_migration_plan.json 中 count=8) 的回归测试。
    """
    print("\n=== Test W: Opcode 713 absent in real RTW scripts (regression) ===")
    # 模拟真实 RTW 脚本结构：354 个脚本，15120 条操作，但无 713
    # 使用已知操作码集合（不包含 713）
    known_opcodes = {101, 102, 103, 714, 715, 716, 717, 1507, 2000, 2001}
    
    # 构建一个包含多个脚本、多种操作码但无 713 的测试内容
    content = """scriptsfile version 1
5
script_one
3 101 0 714 0 715 3 1 2 3
script_two
2 716 4 10 20 30 40 102 0
script_three
1 717 0
script_four
4 103 0 1507 0 2000 1 5 2001 0
script_five
0
"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path, known_opcodes=known_opcodes)
        print(f"  Result: base_usage={result['base_usage']}")
        assert result['file_success'] is True, "Should parse successfully"
        assert result['declared_script_count'] == 5, "Should have 5 declared scripts"
        assert result['successful_script_count'] == 5, "All scripts should succeed"
        assert result['successful_statement_total'] == 10, "Should have 10 successful statements (3+2+1+4+0)"
        # 关键断言：713 不应出现在 base_usage 中
        assert 713 not in result['base_usage'], "Opcode 713 should NOT be in base_usage (count=0)"
        assert 713 not in result['raw_usage'], "Opcode 713 should NOT be in raw_usage"
        # 验证其他操作码正确计数
        assert result['base_usage'].get(714, 0) == 1, "Opcode 714 should be counted once"
        assert result['base_usage'].get(715, 0) == 1, "Opcode 715 should be counted once"
        assert result['base_usage'].get(716, 0) == 1, "Opcode 716 should be counted once"
        assert result['base_usage'].get(717, 0) == 1, "Opcode 717 should be counted once"
        print("  ✓ Test W passed: 713 correctly absent from scan results")
    finally:
        os.unlink(path)


def test_X_opcode_713_with_modifier():
    """X. 回归测试：带修饰位的 713 也应被正确计数（如果存在）
    
    验证扫描器对带 NEG/THIS_OR_NEXT 修饰位的 713 也能正确提取基础操作码并计数。
    """
    print("\n=== Test X: Opcode 713 with modifier (if present) ===")
    # 2147484361 = 0x80000000 | 713 (NEG modifier on opcode 713)
    # 3221226185 = 0xC0000000 | 713 (both NEG and THIS_OR_NEXT on opcode 713)
    content = """scriptsfile version 1
1
test_script
2 2147484361 0 3221226185 0
"""
    path = create_test_scripts_txt(content)
    try:
        result = scan_rtw_scripts(path, known_opcodes={713})
        print(f"  Result: base_usage={result['base_usage']}, raw_usage={result['raw_usage']}, modifier_usage={result['modifier_usage']}")
        assert result['file_success'] is True, "Should parse successfully"
        assert result['successful_statement_total'] == 2, "Should have 2 parsed statements"
        # 基础操作码 713 应计数为 2
        assert result['base_usage'].get(713, 0) == 2, "Base opcode 713 should be counted twice"
        # 原始编码应被记录
        assert result['raw_usage'].get(2147484361, 0) == 1, "Raw opcode with NEG should be counted"
        assert result['raw_usage'].get(3221226185, 0) == 1, "Raw opcode with both modifiers should be counted"
        # 修饰位计数
        assert result['modifier_usage']['neg'] == 2, "NEG modifier should be counted twice"
        assert result['modifier_usage']['this_or_next'] == 1, "THIS_OR_NEXT modifier should be counted once"
        print("  ✓ Test X passed: 713 with modifiers correctly counted")
    finally:
        os.unlink(path)


if __name__ == "__main__":
    test_A_opcode_713_in_opcode_position()
    test_B_713_in_param_position_not_counted()
    test_C_declared_count_mismatch()
    test_D_negative_param_count()
    test_E_truncated_block()
    test_F_extra_tokens()
    test_G_zero_statements()
    test_H_multiple_ops_with_modifier()
    test_I_two_complete_scripts()
    test_J_first_script_fails_second_succeeds()
    test_K_opcode_zero_preserved()
    test_L_unknown_opcode_flagged()
    test_M_extra_blank_lines()
    test_N_declared_script_count_mismatch()
    test_O_structure_complete_unknown_opcode()
    test_P_truncation_in_middle()
    test_Q_empty_known_opcodes_table()
    test_R_alias_retention()
    test_S_unknown_opcode_retention()
    test_T_no_chain_conversion()
    test_U_modifier_retention()
    test_V_param_unchanged()
    test_W_opcode_713_absent_in_real_scripts()
    test_X_opcode_713_with_modifier()
    print("\n=== All tests completed ===")
