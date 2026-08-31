"""FunnelScope — GA4 event-data product analysis.

The analytical logic lives here, not in the notebook or the Streamlit app, so that
the memo, the dashboard and the tests are all computing from one implementation.
"""

__version__ = "1.0.0"

FUNNEL_STAGES = ("viewed", "added_to_cart", "began_checkout", "purchased")

STAGE_LABELS = {
    "viewed": "Viewed an item",
    "added_to_cart": "Added to cart",
    "began_checkout": "Began checkout",
    "purchased": "Purchased",
}
