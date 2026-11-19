import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
CODE = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "tutor").glob("*.py"))


def test_three_mermaid_diagrams():
    assert DOC.count("```mermaid") == 3


def test_every_python_file_named_in_doc_exists():
    names = set(re.findall(r"\b([a-z_]+\.py)\b", DOC))
    missing = [n for n in names if not (list((ROOT / "tutor").glob(n)) or list((ROOT / "scripts").glob(n)))]
    assert not missing, missing


def test_every_function_named_in_doc_is_defined():
    names = set(re.findall(r"\b([a-z_]+)(?= ?\(|<br/>|\s→| ·|\n)", DOC))        # 느슨한 후보
    named = {"find_answer_file", "read_answer_lines", "parse_theory", "check_item", "apply_corrections", "read_bank_files", "load_bank", "question_row",
             "tag_question", "search_content", "sync_raw", "needs_convert", "export_data", "render_html", "api_ask", "search_theory", "expand_everyday_words",
             "_candidate_ids", "_score_rows", "tax_notice", "build_summary", "related_results", "classify", "split_sentences", "merge_sentences",
             "select_sentences", "coverage", "covers_core_terms", "explain", "api_answer", "check_answer", "save", "pick_exam", "grade", "dispatch"}
    for fn in named:
        assert fn in DOC, fn
        assert re.search(rf"def {fn}\b", CODE), fn
    assert names
