"""Local labelling page for the eval set (spec §7.1). Logic: openfoodalerts.eval.labeling.

    cd pipeline && uv run --group eval streamlit run ../eval/label_app.py

Shows one item's frozen model input at a time; Labels are appended to eval/labels.csv.
Stop whenever you like: the next start resumes at the first item you have not labelled.
"""

from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

from openfoodalerts.eval.files import read_items
from openfoodalerts.eval.labeling import LabelSession, default_options, validate
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy

EVAL_DIR = Path(__file__).resolve().parent

st.set_page_config(page_title="OpenFoodAlerts labelling", layout="wide")
annotator = st.sidebar.radio("Annotator", ["A", "B"], horizontal=True)
guideline = st.sidebar.text_input("Guideline version", "v1")
taxonomy = load_taxonomy(default_taxonomy_path())
st.sidebar.caption(f"Taxonomy {taxonomy.version}")
options = default_options(taxonomy.labels)
session = LabelSession(
    read_items(EVAL_DIR / "items.csv"), EVAL_DIR / "labels.csv", annotator, guideline
)

item = session.next_item()
done, total = session.progress()
st.progress(done / total if total else 1.0, text=f"{done} / {total} labelled by {annotator}")
if item is None:
    st.success("Every item is labelled. Run `ofa eval-exclude --from-labels` for non-food ones.")
    st.stop()

st.subheader(f"{item.item_id} · {item.source} · {item.split}")
for field, text in item.input.items():
    st.markdown(f"**{field}**")
    st.text(text or "—")
with st.expander("Source page"):
    st.markdown(f"[{item.source_url}]({item.source_url})")


def pick(label: str, choices: tuple[str, ...], key: str) -> str:
    choice = st.selectbox(label, choices, index=None, key=f"{key}-{item.item_id}")
    return choice or ""


with st.form(f"labels-{item.item_id}"):
    values = {
        "hazard_category": pick("T1 Primary hazard category", options.hazard_categories, "t1"),
        "product_category": pick("T2 Product category", options.product_categories, "t2"),
        "hazard": st.text_input(
            "T3 Hazard: copy it verbatim from the text, or 'none'", key=f"t3-{item.item_id}"
        ),
        "origin_country": pick("T4 Origin country (only if stated)", options.countries, "t4"),
        "product_type": st.radio(
            "T5 Product type", options.product_types, horizontal=True, key=f"t5-{item.item_id}"
        ),
    }
    note = st.text_input("Note (optional)", key=f"note-{item.item_id}")
    submitted = st.form_submit_button("Save and next")

if submitted:
    errors = validate(item, values, options)
    for error in errors:
        st.error(error)
    if not errors:
        session.save(item, values, note=note, now=datetime.now(UTC))
        st.rerun()
