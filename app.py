
import streamlit as st
import pandas as pd
import requests
import sqlite3
from datetime import datetime, timezone

# ==================================================
# 1. APP CONFIGURATION
# ==================================================

st.set_page_config(
    page_title="E-commerce Feedback Analyzer",
    page_icon="🛍️",
    layout="wide"
)

URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "openai/gpt-oss-20b"
DB_PATH = "feedback.db"

ALLOWED = [
    "Product Quality",
    "Delivery",
    "Customer Service",
    "Positive / No Issue",
    "Other / Unclear"
]

# Temporary API key check
if st.secrets.get("GROQ-API-KEY", ""):
    st.sidebar.success("Groq API key found")
else:
    st.sidebar.error("Groq API key missing")


COMPLAINT_LABELS = [
    "Product Quality",
    "Delivery",
    "Customer Service"
]

# ==================================================
# 2. LABELING GUIDE
# ==================================================

LABELING_GUIDE = """
You classify customer comments for an online store.

Assign exactly ONE of these labels:

Product Quality:
Product defects, damage, incorrect items,
or poor product performance.

Delivery:
Shipping delays, missing packages,
or delivery problems.

Customer Service:
Support communication, returns, or refunds.

Positive / No Issue:
Satisfaction without a substantive complaint.

Other / Unclear:
Ambiguous, unrelated, vague comments
or insufficient information.

Rules:
1. Return exactly one allowed label.
2. Prioritize substantive complaints over praise.
3. Select the dominant complaint.
4. If multiple complaints are equally important,
   choose Other / Unclear.
5. Recognize sarcasm.
6. Do not invent information.
7. Return only the exact label.
"""

# ==================================================
# 3. LABEL: GROQ API
# ==================================================

def label_comment(text):
    key = st.secrets.get("GROQ-API-KEY", "")

    if not key:
        raise RuntimeError("Groq API key is missing.")

    response = requests.post(
        URL,
        headers={
            "Authorization": f"Bearer {key}"
        },
        json={
            "model": MODEL,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": LABELING_GUIDE
                },
                {
                    "role": "user",
                    "content": f"Classify this comment:\n{text}"
                }
            ]
        },
        timeout=30
    )

    response.raise_for_status()

    result = response.json()["choices"][0]["message"]["content"]

    if not isinstance(result, str) or not result.strip():
        raise ValueError("LLM returned an empty label")

    result = result.strip()

    for label in ALLOWED:
        if result.casefold() == label.casefold():
            return label

    raise ValueError("LLM returned a label outside ALLOWED")

# ==================================================
# 4. CHECK: MANUAL REVIEW
# ==================================================

def check_review(comment, rating, label, error=False):
    reasons = []

    if error:
        reasons.append("LLM classification failed")

    if label == "Other / Unclear":
        reasons.append("Ambiguous or unclear feedback")

    safety_words = [
        "overheat", "smoke", "caught fire",
        "burn", "injur", "electric shock",
        "explod"
    ]

    if comment and any(
        word in comment.lower() for word in safety_words
    ):
        reasons.append("Possible safety concern")

    if rating is not None and comment:
        if rating <= 2 and label == "Positive / No Issue":
            reasons.append("Low rating with positive comment")

        if rating >= 4 and label in COMPLAINT_LABELS:
            reasons.append("High rating with complaint")

    if not comment and rating is not None and rating <= 2:
        reasons.append("Low rating without a comment")

    return bool(reasons), "; ".join(reasons)

# ==================================================
# 5. DATABASE: SAVE AND LOAD
# ==================================================

def initialize_database():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submitted_at TEXT NOT NULL,
                rating INTEGER,
                comment TEXT,
                label TEXT NOT NULL,
                needs_review INTEGER NOT NULL,
                review_reason TEXT,
                classification_error INTEGER NOT NULL
            )
        """)


def save_feedback(
    rating, comment, label,
    needs_review, review_reason,
    classification_error
):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO feedback (
                submitted_at, rating, comment, label,
                needs_review, review_reason,
                classification_error
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                rating,
                comment,
                label,
                int(needs_review),
                review_reason,
                int(classification_error)
            )
        )


def load_feedback():
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(
            "SELECT * FROM feedback ORDER BY id DESC",
            conn
        )


initialize_database()

# ==================================================
# 6. PAGE NAVIGATION
# ==================================================

st.sidebar.title("🛍️ Feedback Analyzer")

page = st.sidebar.radio(
    "Navigation",
    ["E-commerce Customer Feedback", "Owner Dashboard"]
)

# ==================================================
# 7. CUSTOMER SIDE
# ==================================================

if page == "E-commerce Customer Feedback":

    st.title("🛍️ E-commerce Customer Feedback")

    st.write(
        "We value your feedback! Please rate your "
        "shopping experience or share a written comment."
    )

    with st.form("feedback_form", clear_on_submit=True):

        rating = st.selectbox(
            "Star Rating (Optional)",
            [None, 1, 2, 3, 4, 5],
            format_func=lambda x: (
                "Select a rating" if x is None
                else f"{x} Star{'s' if x > 1 else ''}"
            )
        )

        comment = st.text_area(
            "Your Comment (Optional)",
            placeholder="Tell us about your experience...",
            max_chars=2000
        )

        submitted = st.form_submit_button(
            "Submit Feedback",
            type="primary"
        )

    if submitted:

        comment = comment.strip()

        if rating is None and not comment:
            st.warning(
                "Please provide a rating or a comment."
            )

        else:
            classification_error = False

            if comment:
                try:
                    with st.spinner("Analyzing feedback..."):
                        label = label_comment(comment)
                        
                except (
                    requests.RequestException,
                    RuntimeError,
                    ValueError,
                    KeyError,
                    IndexError,
                    TypeError
                ) as e:
                    label = "Other / Unclear"
                    classification_error = True

                    st.error(
                        "LLM classification failed: "
                        f"{type(e).__name__}"
                    )

                    if isinstance(e, requests.HTTPError):
                        st.warning(
                            "Groq HTTP status: "
                            f"{e.response.status_code}"
                        )


            else:
                label = "No Written Comment"

            needs_review, reason = check_review(
                comment, rating, label,
                error=classification_error
            )

            try:
                save_feedback(
                    rating,
                    comment,
                    label,
                    needs_review,
                    reason,
                    classification_error
                )

                st.success(
                    "Thank you! Your feedback has been saved."
                )

                if needs_review:
                    st.info(
                        "Your feedback has been flagged "
                        "for additional review."
                    )

            except sqlite3.Error:
                st.error("Feedback could not be saved.")

    st.caption(
        "Educational prototype. Do not submit "
        "sensitive or personal information."
    )

# ==================================================
# 8. BUSINESS OWNER SIDE
# ==================================================

else:

    st.title("📊 Business Owner Dashboard")

    st.write(
        "**Business Question:** Which operational issues "
        "generate the most customer complaints, and "
        "which feedback requires the owner's attention?"
    )


    df = load_feedback()

    if df.empty:
        st.info(
            "No feedback has been submitted yet. "
            "Submit sample feedback on the customer page."
        )
        st.stop()

    # TEMPORARY DIAGNOSTICS
    st.subheader("Classification Diagnostics")

    st.dataframe(
        df[
            [
                "id",
                "comment",
                "label",
                "classification_error",
                "review_reason"
            ]
        ],
        use_container_width=True
    )


    # ------------------------------------------
    # 8A. THREE KEY NUMBERS
    # ------------------------------------------

    total_feedback = len(df)

    complaint_count = df[
        df["label"].isin(COMPLAINT_LABELS)
    ].shape[0]

    manual_review_count = df[
        df["needs_review"] == 1
    ].shape[0]

    col1, col2, col3 = st.columns(3)

    col1.metric("Total Feedback", total_feedback)
    col2.metric("Categorized Complaints", complaint_count)
    col3.metric("Manual Review", manual_review_count)

    st.divider()

    # ------------------------------------------
    # 8B. GRAPH 1: FEEDBACK BY LABEL
    # ------------------------------------------

    st.subheader("1. Feedback by Category")

    label_counts = (
        df["label"]
        .value_counts()
        .rename_axis("Category")
        .reset_index(name="Comments")
    )

    st.bar_chart(
        label_counts.set_index("Category")["Comments"]
    )

    # ------------------------------------------
    # 8C. GRAPH 2: AVERAGE STAR RATING
    # ------------------------------------------

    st.subheader("2. Average Star Rating by Category")

    ratings_df = df.dropna(subset=["rating"])

    if not ratings_df.empty:

        average_ratings = (
            ratings_df
            .groupby("label")["rating"]
            .mean()
            .sort_values()
        )

        st.bar_chart(
            average_ratings,
            y_label="Average rating",
            x_label="Category"
        )

        st.caption(
            "Calculated only from feedback that "
            "includes a star rating."
        )

    else:
        st.info("No star ratings available yet.")

    # ------------------------------------------
    # 8D. FULL MANUAL REVIEW COMMENTS
    # ------------------------------------------

    st.divider()
    st.subheader("3. Comments Requiring Manual Review")

    review_df = df[df["needs_review"] == 1]

    if review_df.empty:
        st.success("No feedback currently requires review.")

    else:
        for _, record in review_df.iterrows():

            with st.container(border=True):
                st.write(
                    f"**Submission #{record['id']}**"
                )

                if pd.notna(record["rating"]):
                    st.write(
                        f"**Rating:** {int(record['rating'])}/5"
                    )
                else:
                    st.write("**Rating:** Not provided")

                st.write(f"**Label:** {record['label']}")

                st.write(
                    f"**Review reason:** "
                    f"{record['review_reason']}"
                )

                st.write("**Full comment:**")

                st.write(
                    record["comment"]
                    if record["comment"]
                    else "(No written comment)"
                )
