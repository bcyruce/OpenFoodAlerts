"""Local fact-check page for T6 summaries (spec §7.2). Logic: openfoodalerts.eval.factcheck.

    cd pipeline && uv run ofa factcheck-sample --model claude-haiku-5-5   # once: the sample
    cd pipeline && uv run --group eval streamlit run ../eval/factcheck_app.py

Shows one sampled summary next to its frozen source text; your judgment is written to
eval/factcheck/t6.csv. "Consistent" means every statement of the summary is supported by
the source and nothing is added: no new facts, no severity judgement, no advice the
source does not give. Stop whenever you like: the next start resumes at the first row you
have not judged. `make eval` reports the result (latest.json `t6_factcheck`).
"""

from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

from openfoodalerts.eval.factcheck import (
    FACTCHECK_FILE,
    next_unjudged,
    read_factcheck,
    record_judgment,
)

PATH = Path(__file__).resolve().parent / FACTCHECK_FILE

st.set_page_config(page_title="OpenFoodAlerts T6 fact-check", layout="wide")
checker = st.sidebar.radio("Checker", ["A", "B"], horizontal=True)
rows = read_factcheck(PATH)
if not rows:
    st.warning(f"No sample in {PATH}: run `uv run ofa factcheck-sample` first.")
    st.stop()
done = sum(bool(r.consistent) for r in rows)
st.progress(done / len(rows), text=f"{done} / {len(rows)} judged")
row = next_unjudged(rows)
if row is None:
    st.success("Every sampled summary is judged. Run `make eval` and commit t6.csv.")
    st.stop()

st.subheader(f"{row.item_id} · {row.source} · {row.locale} · {row.model}/{row.prompt_version}")
left, right = st.columns(2)
with left:
    st.markdown("**Source text** (frozen eval input)")
    for field, text in row.input.items():
        st.markdown(f"*{field}*")
        st.text(text or "—")
with right:
    st.markdown(f"**AI summary ({row.locale})**")
    st.info(row.summary)

with st.form(f"judge-{row.item_id}-{row.task}"):
    verdict = st.radio(
        "Is every statement supported by the source, with nothing added?",
        ["yes", "no"],
        index=None,
        horizontal=True,
    )
    problem = st.text_input("If no: what is not supported (required)")
    submitted = st.form_submit_button("Save and next")

if submitted:
    try:
        record_judgment(
            PATH,
            row,
            consistent=verdict or "",
            problem=problem,
            checker=checker,
            now=datetime.now(UTC),
        )
    except ValueError as exc:
        st.error(str(exc))
    else:
        st.rerun()
