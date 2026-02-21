"""
InstaBio Payments Module
Stripe integration for biography/journal/voice/legacy product purchases.

Environment Variables:
    STRIPE_SECRET_KEY:   Stripe secret key (required for payments).
    STRIPE_WEBHOOK_SECRET: Stripe webhook signing secret.
    INSTABIO_BASE_URL:   Base URL for success/cancel redirects.

When STRIPE_SECRET_KEY is not set, all endpoints return a clear
"payments not configured" message — no crashes.
"""

import os
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
BASE_URL = os.environ.get("INSTABIO_BASE_URL", "http://localhost:8000")

# Lazy-import stripe to avoid hard dependency when not configured
_stripe = None


def _get_stripe():
    """Lazy-load the stripe module and set the API key."""
    global _stripe
    if _stripe is None:
        try:
            import stripe
            stripe.api_key = STRIPE_SECRET_KEY
            _stripe = stripe
        except ImportError:
            logger.warning("Stripe package not installed — payments unavailable")
            return None
    return _stripe


def _payments_available() -> bool:
    return bool(STRIPE_SECRET_KEY) and _get_stripe() is not None


# ----- Product catalog aligned with DNA-MASTER-PLAN pricing -----

PRODUCTS = {
    "biography_digital": {
        "name": "Digital Biography",
        "description": "Your life story as a beautifully formatted digital book.",
        "price_cents": 4999,  # $49.99
        "currency": "usd",
    },
    "biography_print": {
        "name": "Printed Biography",
        "description": "A hardcover printed copy of your life story, mailed to you.",
        "price_cents": 7999,  # $79.99
        "currency": "usd",
    },
    "journal_collection": {
        "name": "Journal Collection",
        "description": "Retroactive journal entries from your life timeline.",
        "price_cents": 2999,  # $29.99
        "currency": "usd",
    },
    "voice_legacy": {
        "name": "Voice Legacy",
        "description": "A downloadable voice clone for family messages.",
        "price_cents": 9999,  # $99.99
        "currency": "usd",
    },
    "avatar_package": {
        "name": "Avatar Package",
        "description": "An animated avatar that speaks your stories.",
        "price_cents": 14999,  # $149.99
        "currency": "usd",
    },
    "soul_lifetime": {
        "name": "Soul — Lifetime Access",
        "description": "Interactive AI that family can talk to forever.",
        "price_cents": 29999,  # $299.99
        "currency": "usd",
    },
    "gift_biography": {
        "name": "Gift: Biography for a Loved One",
        "description": "Give the gift of a preserved life story.",
        "price_cents": 4999,
        "currency": "usd",
    },
    "gift_full": {
        "name": "Gift: Complete Legacy Package",
        "description": "Biography + Voice + Avatar + Soul. The ultimate gift.",
        "price_cents": 39999,  # $399.99
        "currency": "usd",
    },
}


async def create_checkout_session(
    user_id: int,
    product_id: str,
    email: Optional[str] = None,
) -> dict:
    """
    Create a Stripe Checkout session for a given product.

    Args:
        user_id:     The InstaBio user ID purchasing the product.
        product_id:  Key from ``PRODUCTS`` dict.
        email:       Optional customer email for Stripe receipt.

    Returns:
        dict with ``checkout_url`` and ``session_id`` on success.
    """
    if not _payments_available():
        return {
            "status": "unavailable",
            "message": (
                "Payments are not configured yet. "
                "Set the STRIPE_SECRET_KEY environment variable to enable purchases."
            ),
            "checkout_url": None,
        }

    product = PRODUCTS.get(product_id)
    if not product:
        return {
            "status": "error",
            "message": f"Unknown product: {product_id}",
            "checkout_url": None,
        }

    stripe = _get_stripe()
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": product["currency"],
                    "unit_amount": product["price_cents"],
                    "product_data": {
                        "name": product["name"],
                        "description": product["description"],
                    },
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"{BASE_URL}/progress?payment=success&product={product_id}",
            cancel_url=f"{BASE_URL}/progress?payment=cancelled",
            customer_email=email,
            metadata={
                "instabio_user_id": str(user_id),
                "product_id": product_id,
            },
        )

        logger.info("Stripe session created for user %d, product %s: %s",
                     user_id, product_id, session.id)

        return {
            "status": "created",
            "checkout_url": session.url,
            "session_id": session.id,
        }

    except Exception as exc:
        logger.error("Stripe checkout creation failed: %s", exc)
        return {
            "status": "error",
            "message": "Could not create checkout session. Please try again.",
            "checkout_url": None,
        }


async def handle_webhook(payload: bytes, sig_header: str) -> dict:
    """
    Handle an incoming Stripe webhook event.

    Verifies the signature, then processes the event.

    Args:
        payload:    Raw request body bytes.
        sig_header: Value of the ``Stripe-Signature`` header.

    Returns:
        dict with ``status`` and ``event_type``.
    """
    if not _payments_available():
        return {"status": "unavailable", "message": "Payments not configured"}

    stripe = _get_stripe()

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET,
        )
    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        logger.warning("Stripe webhook verification failed: %s", exc)
        return {"status": "error", "message": "Invalid webhook signature"}

    event_type = event["type"]
    logger.info("Stripe webhook received: %s", event_type)

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        user_id = session.get("metadata", {}).get("instabio_user_id")
        product_id = session.get("metadata", {}).get("product_id")
        amount = session.get("amount_total", 0)

        logger.info(
            "Payment completed: user=%s, product=%s, amount=%d",
            user_id, product_id, amount,
        )

        # Unlock the purchased feature in the database
        if user_id and product_id:
            await _unlock_product(int(user_id), product_id)

    return {"status": "ok", "event_type": event_type}


async def _unlock_product(user_id: int, product_id: str) -> None:
    """Mark a product as purchased for the user in the database."""
    from . import database as db

    logger.info("Unlocking product %s for user %d", product_id, user_id)

    # Store purchase record — uses the existing cache mechanism
    await db.save_cache_result(
        user_id,
        f"purchase_{product_id}",
        {"product_id": product_id, "purchased": True},
    )


def list_products() -> list:
    """Return the full product catalog."""
    return [
        {"id": pid, **info}
        for pid, info in PRODUCTS.items()
    ]
