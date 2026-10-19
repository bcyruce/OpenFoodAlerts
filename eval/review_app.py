"""Local review page for AI classifications (spec §6.5, ticket 20).

    cd pipeline && uv run --group eval streamlit run ../eval/review_app.py

Reads the `review_queue` view of DATABASE_URL (default: the local `ofa` database): current
AI results that are abstained or below the task's confidence threshold and unreviewed.
For each one: approve (the model is right), correct (pick or type the right value; it is
checked like a model output), "cannot tell" (a reviewer abstain), or skip (this session
only). Reviews are written to ai_classifications (review_status, reviewed_value,
reviewed_at) and the AI rows derived from them are rewritten at once.
Logic: openfoodalerts.classify.review / review_queue / effective.

Keyboard: A approve, N cannot tell, S skip, Ctrl+Enter save the correction.
"""

import html
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import streamlit as st

from openfoodalerts.classify.review import ReviewError, approve, choices, correct, value_fields
from openfoodalerts.classify.review_queue import highlight, queue_items, review_stats
from openfoodalerts.classify.tasks import Task, make_task
from openfoodalerts.db.connection import Connection, connect, database_url
from openfoodalerts.eval.labelset import default_taxonomy_path, load_taxonomy

st.set_page_config(page_title="OpenFoodAlerts review", layout="wide")


@st.cache_resource
def connection() -> Connection:
    return connect()


@st.cache_resource
def task_for(name: str) -> Task | None:
    try:
        return make_task(name, load_taxonomy(default_taxonomy_path()))
    except ValueError:
        return None


conn = connection()
conn.rollback()  # a fresh snapshot on every rerun
skipped: set[int] = st.session_state.setdefault("skipped", set())
stats = review_stats(conn)

st.sidebar.caption(database_url().split("@")[-1])
task_name = st.sidebar.selectbox("Task", ["all", *(s.task for s in stats)])
source = st.sidebar.radio("Source", ["all", "nvwa", "openfda"], horizontal=True)
for s in stats:
    st.sidebar.caption(
        f"{s.task}: {s.queued_abstained} abstained, {s.queued_low_confidence} below"
        f" {s.min_confidence}; {s.approved + s.corrected} reviewed"
    )
if skipped and st.sidebar.button("Show skipped again"):
    skipped.clear()
    st.rerun()

items = queue_items(
    conn,
    task=None if task_name == "all" else task_name,
    source=None if source == "all" else source,
)
todo = [i for i in items if i["classification_id"] not in skipped]
if message := st.session_state.pop("message", None):
    st.toast(message)
st.progress(1.0 if not items else 1 - len(todo) / len(items), text=f"{len(todo)} to review")
if not todo:
    st.success("Nothing left to review for this filter.")
    st.stop()

item: dict[str, Any] = todo[0]
cid: int = item["classification_id"]
task = task_for(item["task"])
st.subheader(f"{item['task']} · {item['source']} · {item['source_key']}")
st.caption(
    f"{item['reason'].replace('_', ' ')} · {item['model']} {item['prompt_version']}"
    f" · taxonomy {item['taxonomy_version']} · classification {cid}"
)
if task is None:
    st.warning(f"Task {item['task']} is not implemented in this checkout; skip it.")
    if st.button("Skip", shortcut="S"):
        skipped.add(cid)
        st.rerun()
    st.stop()

left, right = st.columns([3, 2])
with left:
    for field, text in task.build_input(item["source"], item).items():
        st.markdown(f"**{field}**")
        marked = highlight(text or "—", item["evidence_span"])
        st.markdown(f"<div>{marked}</div>", unsafe_allow_html=True)
    st.markdown(f"[Official source page]({item['source_url']})")

value = item["value"]
with right:
    if item["abstained"]:
        st.markdown(f"**AI: abstained** ({value.get('abstain_reason')})")
        if value.get("model_output") is not None:
            st.code(json.dumps(value["model_output"], ensure_ascii=False, indent=1), "json")
    else:
        shown = ", ".join(str(value.get(k)) for k in value_fields(task))
        st.markdown(f"**AI: {shown}** · confidence **{item['confidence']}**")
        evidence = html.escape(item["evidence_span"] or "", quote=False)
        st.markdown(f"Evidence: <mark>{evidence}</mark>", unsafe_allow_html=True)

    def act(review: Callable[[], object], text: str) -> None:
        """Apply a review; on success go to the next item, otherwise show why not."""
        try:
            review()
        except ReviewError as exc:
            conn.rollback()
            st.error(str(exc))
            return
        st.session_state["message"] = text
        st.rerun()

    buttons = st.columns(3)
    if buttons[0].button("Approve", shortcut="A", type="primary"):
        act(lambda: approve(conn, task, cid, now=datetime.now(UTC)), f"approved {cid}")
    if buttons[1].button("Cannot tell", shortcut="N", help="The text does not say (abstain)"):
        act(lambda: correct(conn, task, cid, None, now=datetime.now(UTC)), f"{cid}: cannot tell")
    if buttons[2].button("Skip", shortcut="S"):
        skipped.add(cid)
        st.rerun()

    with st.form(f"correct-{cid}"):
        st.markdown("**Correct it**")
        corrected: dict[str, Any] = {}
        for field in value_fields(task):
            options = choices(task, field)
            current = value.get(field)
            if options is None:
                corrected[field] = st.text_input(
                    f"{field} (copy it verbatim from the text)", value=current or ""
                )
            else:
                index = options.index(current) if current in options else None
                corrected[field] = st.selectbox(field, options, index=index)
        if st.form_submit_button("Save correction", shortcut="Ctrl+Enter"):
            if any(v in (None, "") for v in corrected.values()):
                st.error("Pick or type a value first.")
            else:
                act(
                    lambda: correct(conn, task, cid, corrected, now=datetime.now(UTC)),
                    f"corrected {cid}",
                )
