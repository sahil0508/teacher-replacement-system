# ============================================================
# Teacher Replacement System (Multi-Absent, Constraint-Based)
# + Timetable Viewer Tab (Class View / Teacher View)
# ============================================================

import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Teacher Replacement System",
    layout="wide"
)

st.title("🎓 Time Table Management")

# ============================================================
# CONSTANTS
# ============================================================

DATA_FILE = Path("processed/normalized_timetable.parquet")

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

MAX_SUBSTITUTIONS_PER_DAY = 2

# ============================================================
# LOAD DATA
# ============================================================

@st.cache_data
def load_df():
    if not DATA_FILE.exists():
        st.error(f"Processed data not found: {DATA_FILE.resolve()}")
        st.stop()

    df = pd.read_parquet(DATA_FILE)

    required_cols = {"teacher", "day", "period", "class", "subject"}
    missing = required_cols - set(df.columns)
    if missing:
        st.error(f"Missing required columns: {missing}")
        st.stop()

    return df


def normalize_teacher_name(name: str) -> str:
    if not isinstance(name, str):
        return name

    name = name.strip()
    name = " ".join(name.split())  # remove extra spaces
    return name.title()  # "Firstname Lastname"


df = load_df()
df["teacher"] = df["teacher"].apply(normalize_teacher_name)

ALL_TEACHERS = sorted(df["teacher"].dropna().unique())

st.caption(f"Loaded **{len(df):,}** timetable rows")

# ============================================================
# HELPERS
# ============================================================

def get_teacher_schedule(df, teacher, day):
    return (
        df[(df["teacher"] == teacher) & (df["day"] == day)]
        .sort_values("period")
        .reset_index(drop=True)
    )


def get_teacher_load(df, teacher, day):
    return len(df[(df["teacher"] == teacher) & (df["day"] == day)])


# ============================================================
# REPLACEMENT ENGINE
# ============================================================

def get_required_slots(df, absent_teachers, day):
    slots = []

    for teacher in absent_teachers:
        schedule = get_teacher_schedule(df, teacher, day)

        for _, row in schedule.iterrows():
            slots.append({
                "absent_teacher": teacher,
                "period": row["period"],
                "class": row["class"],
                "subject": row["subject"]
            })

    return slots


def generate_multi_replacement_plan(df, absent_teachers, day):

    required_slots = get_required_slots(df, absent_teachers, day)
    required_slots.sort(key=lambda x: x["period"])

    substitute_load = defaultdict(int)
    busy_substitutes = defaultdict(set)

    plans = []

    for slot in required_slots:
        period = slot["period"]
        subject = slot["subject"]

        candidates = []

        for teacher in ALL_TEACHERS:

            if teacher in absent_teachers:
                continue

            # Teacher must be free in that period (no class assigned)
            if not df[
                (df["teacher"] == teacher) &
                (df["day"] == day) &
                (df["period"] == period)
            ].empty:
                continue

            # Avoid assigning same substitute twice in same period
            if teacher in busy_substitutes[(day, period)]:
                continue

            # Cap substitutions per day
            if substitute_load[(teacher, day)] >= MAX_SUBSTITUTIONS_PER_DAY:
                continue

            # Same-subject preference (base on any appearance of subject)
            teaches_subject = not df[
                (df["teacher"] == teacher) &
                (df["subject"] == subject)
            ].empty

            daily_load = get_teacher_load(df, teacher, day)

            score = (100 if teaches_subject else 0) + (10 - daily_load)

            candidates.append({
                "teacher": teacher,
                "score": score,
                "is_same_subject": teaches_subject,
                "daily_load": daily_load,
                "subs_today": substitute_load[(teacher, day)],
                "reason": (
                    "Same subject, " if teaches_subject else "Different subject, "
                ) + f"daily load {daily_load}"
            })

        if candidates:
            best = max(candidates, key=lambda x: x["score"])

            selected = best["teacher"]
            substitute_load[(selected, day)] += 1
            busy_substitutes[(day, period)].add(selected)

            plans.append({
                "Absent Teacher": slot["absent_teacher"],
                "Day": day,
                "Period": period,
                "Substitute Teaching Class": slot["class"],
                "Subject": subject,
                "Substitute Teacher": selected,
                "Is Same Subject": best["is_same_subject"],
                "Teacher Daily Load": best["daily_load"],
                "Substitutions Today": best["subs_today"],
                "Selection Score": best["score"],
                "Why Selected": best["reason"]
            })
        else:
            plans.append({
                "Absent Teacher": slot["absent_teacher"],
                "Day": day,
                "Period": period,
                "Substitute Teaching Class": slot["class"],
                "Subject": subject,
                "Substitute Teacher": "—",
                "Is Same Subject": False,
                "Teacher Daily Load": None,
                "Substitutions Today": None,
                "Selection Score": None,
                "Why Selected": "No suitable substitute available"
            })

    return pd.DataFrame(plans)

# ============================================================
# UI (TABS)
# ============================================================

tab1, tab2 = st.tabs(["🔁 Replacement Plan", "📘 Timetable Viewer"])

# ---------------------------
# TAB 1: Replacement Plan
# ---------------------------
with tab1:
    col1, col2 = st.columns(2)

    with col1:
        absent_teachers = st.multiselect("Absent Teachers", ALL_TEACHERS)

    with col2:
        today = datetime.today().strftime("%A")
        day = st.selectbox("Day", DAYS, index=DAYS.index(today) if today in DAYS else 0)

    if st.button("🚀 Generate Replacement Plan"):
        if not absent_teachers:
            st.warning("Please select at least one absent teacher.")
        else:
            plan_df = generate_multi_replacement_plan(df, absent_teachers, day)
            st.subheader("🔁 Replacement Plan")
            st.dataframe(plan_df, use_container_width=True)

# ---------------------------
# TAB 2: Timetable Viewer
# ---------------------------
with tab2:
    st.subheader("📘 Timetable Viewer")

    view_mode = st.radio(
        "View timetable by:",
        ["Class View", "Teacher View"],
        horizontal=True
    )

    # Build helper columns safely (only if needed)
    base_df = df.copy()

    if view_mode == "Class View":
        base_df["class_number"] = base_df["class"].astype(str).str.extract(r"(\d+)")
        base_df["class_section"] = base_df["class"].astype(str).str.extract(r"([A-Za-z]+)")
        base_df["class_section"] = base_df["class_section"].str.upper()

        c1, c2 = st.columns(2)

        with c1:
            class_numbers = sorted(base_df["class_number"].dropna().unique(), key=lambda x: int(x))
            class_number = st.selectbox("Class Number", class_numbers)

        with c2:
            sections = sorted(
                base_df[base_df["class_number"] == class_number]["class_section"]
                .dropna()
                .unique()
            )
            section = st.selectbox("Section", sections)

        filtered = base_df[
            (base_df["class_number"] == class_number) &
            (base_df["class_section"] == section)
        ]

        st.caption(f"Showing timetable for **Class {class_number}{section}**")

    else:  # Teacher View
        teacher = st.selectbox("Select Teacher", ALL_TEACHERS)
        filtered = base_df[base_df["teacher"] == teacher]
        st.caption(f"Showing timetable for **{teacher}**")

    # Optional day filter for both views
    d1, d2 = st.columns([1, 3])
    with d1:
        day_filter = st.selectbox("Day Filter", ["All"] + DAYS, index=0)

    if day_filter != "All":
        filtered = filtered[filtered["day"] == day_filter]

    if filtered.empty:
        st.info("No timetable rows found for the selected filters.")
    else:
        filtered = filtered.sort_values(["day", "period"]).reset_index(drop=True)

        display_df = filtered.rename(columns={
            "day": "Day",
            "period": "Period",
            "class": "Class",
            "subject": "Subject",
            "teacher": "Teacher"
        })[["Day", "Period", "Class", "Subject", "Teacher"]]

        st.dataframe(display_df, use_container_width=True)
