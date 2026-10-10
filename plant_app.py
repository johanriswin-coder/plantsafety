"""
plant_app.py - PlantGuard dashboard (Streamlit, pure Python).

Streamlit re-runs this file top to bottom on every interaction. The dashboard itself is a
"fragment" that re-runs by itself every couple of seconds, so the readings update live
without reloading the page. Each refresh = one simulation step in plantsim.py.

Run locally:   streamlit run plant_app.py
"""
import streamlit as st

import plantui as ui
from plantsim import (ACTION_LABELS, FAULT_RATES, FAULTS, ROSTER, SAMPLE_PHONE_EMPLOYEE, SCENARIOS,
                      SPEC_BY_ID, SPECS, Plant)

st.set_page_config(page_title="PlantGuard", page_icon="🏭", layout="wide", initial_sidebar_state="expanded")
st.markdown(ui.CSS, unsafe_allow_html=True)

if "plant" not in st.session_state:
    st.session_state["plant"] = Plant(seed=7)
plant: Plant = st.session_state["plant"]


# --------------------------------------------------------------------------- #
# Button callbacks (they run before the next refresh)
# --------------------------------------------------------------------------- #
def start_scenario() -> None:
    st.session_state["plant"].load_scenario(st.session_state["scenario_pick"])
    st.session_state["live"] = True


def do_inject() -> None:
    msg = st.session_state["plant"].inject(
        st.session_state["fault_machine"], st.session_state["fault_kind"], st.session_state["fault_speed"])
    st.session_state["flash"] = "" if msg == "ok" else msg


def do_act() -> None:
    msg = st.session_state["plant"].act(st.session_state["action_machine"], st.session_state["action_kind"])
    st.session_state["flash"] = "" if msg == "ok" else msg


def apply_advice(machine: str, action: str) -> None:
    msg = st.session_state["plant"].act(machine, action)
    st.session_state["flash"] = "" if msg == "ok" else msg


def step_once() -> None:
    st.session_state["plant"].step()


def reset_plant() -> None:
    st.session_state["plant"].reset()


# --------------------------------------------------------------------------- #
# Sidebar: controls for the demo
# --------------------------------------------------------------------------- #
machine_ids = [m.id for m in SPECS]
machine_label = lambda i: f"{i}  {SPEC_BY_ID[i].name}"          # noqa: E731

with st.sidebar:
    st.markdown("### Controls")
    live = st.toggle("Live monitoring", value=True, key="live", help="Refresh the readings automatically")
    every = st.select_slider("Update every (seconds)", options=[1, 2, 3, 5], value=2, key="every")
    if not live:
        st.button("Step once", on_click=step_once, use_container_width=True)
    st.divider()

    st.markdown("**Run a scripted scenario**")
    st.selectbox("Scenario", list(SCENARIOS), format_func=lambda k: SCENARIOS[k]["title"], key="scenario_pick")
    st.caption(SCENARIOS[st.session_state.get("scenario_pick", "normal")]["desc"])
    st.button("Start scenario", on_click=start_scenario, use_container_width=True)
    st.divider()

    st.markdown("**Simulate a fault**")
    fault_machine = st.selectbox("Machine", machine_ids, format_func=machine_label, key="fault_machine")
    st.selectbox("Fault", plant.applicable_faults(fault_machine), format_func=lambda k: FAULTS[k]["label"], key="fault_kind")
    st.select_slider("How fast it develops", options=list(FAULT_RATES), value="normal", key="fault_speed")
    st.button("Inject fault", on_click=do_inject, use_container_width=True)
    st.divider()

    st.markdown("**Operator actions**")
    st.selectbox("Machine ", machine_ids, format_func=machine_label, key="action_machine")
    st.selectbox("Action", list(ACTION_LABELS), format_func=lambda k: ACTION_LABELS[k], key="action_kind")
    st.button("Apply action", on_click=do_act, use_container_width=True)
    st.divider()

    st.selectbox("Show the phone of", [e[0] for e in ROSTER], index=[e[0] for e in ROSTER].index(SAMPLE_PHONE_EMPLOYEE),
                 format_func=lambda i: next(f"{e[1]} ({e[2]})" for e in ROSTER if e[0] == i), key="phone_emp")
    st.button("Reset plant", on_click=reset_plant, use_container_width=True)
    if st.session_state.get("flash"):
        st.warning(st.session_state["flash"])


# --------------------------------------------------------------------------- #
# The dashboard
# --------------------------------------------------------------------------- #
def render(s: dict) -> None:
    st.markdown(ui.mode_css(s["mode"]), unsafe_allow_html=True)
    st.markdown(ui.header_html(s), unsafe_allow_html=True)

    left, centre, right = st.columns([1, 3.1, 1.15], gap="medium")
    with left:
        st.markdown(ui.pie_html(s), unsafe_allow_html=True)
        st.markdown(ui.advice_html(s), unsafe_allow_html=True)
        seen = set()
        for a in [a for a in s["advice"] if a["action"]][:3]:                 # one-click fixes
            key = f"apply_{a['machine']}_{a['action']}"
            if key not in seen:
                seen.add(key)
                st.button(f"{ACTION_LABELS[a['action']]}: {a['machine']}", key=key, on_click=apply_advice,
                          args=(a["machine"], a["action"]), use_container_width=True)
    with centre:
        st.markdown(ui.plan_html(s), unsafe_allow_html=True)
        st.markdown(ui.tiles_html(s), unsafe_allow_html=True)
    with right:
        st.markdown(ui.feed_html(s), unsafe_allow_html=True)
        st.markdown(ui.phone_html(s), unsafe_allow_html=True)
        st.markdown(ui.log_html(s), unsafe_allow_html=True)
    st.markdown(ui.disclaimer_html(), unsafe_allow_html=True)


@st.fragment(run_every=every if live else None)
def dashboard() -> None:
    p: Plant = st.session_state["plant"]
    if live:
        p.step()                                    # one simulation step per refresh
    render(p.snapshot(phone_employee=st.session_state.get("phone_emp", SAMPLE_PHONE_EMPLOYEE)))


dashboard()
