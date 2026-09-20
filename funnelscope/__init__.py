"""FunnelScope — GA4 event-data product analysis.

The analytical logic lives here, not in the notebook, the Streamlit app or the static
site, so the memo, both dashboards and the tests all compute from one implementation.
The moment two of them calculate the same rate independently they can disagree, and
then neither is worth quoting.
"""

__version__ = "3.0.0"

FUNNEL_STAGES = ("viewed", "added_to_cart", "began_checkout", "purchased")

STAGE_LABELS = {
    "viewed": "Viewed an item",
    "added_to_cart": "Added to cart",
    "began_checkout": "Began checkout",
    "purchased": "Purchased",
}
